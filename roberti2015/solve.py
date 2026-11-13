#!/usr/bin/env python3
"""MV2's solver for FrontierOR task roberti2015: the fixed charge transportation problem (FCTP).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python solve.py --problem roberti2015 --instance in.json --output out.json --time-limit 60

Standard library only. The FCTP cost is concave in the flows, so an optimal answer sits at a vertex of the
transportation polytope, that is a basic solution whose m + n - 1 basic arcs form a spanning tree of the bipartite
graph. The search therefore moves from tree to tree:
  * construction: a least-cost greedy on c_ij + f_ij / q_ij (q_ij = what the arc can still carry), which crosses out
    one source or sink per step and so always yields a spanning tree (randomised with noise on restarts);
  * local search: network-simplex pivots. For an arc (i, j) outside the tree the cycle it closes is found by
    climbing the tree; theta = the smallest flow on the cycle's minus arcs; the exact change in total cost
    (variable costs, fixed costs of arcs that open or close) is computed before any move, and only improving pivots
    are made (first improvement, random order) until no pivot improves;
  * perturbation (iterated local search): either a few random non-degenerate pivots, or a local search on randomly
    perturbed fixed costs; then the local search on the true costs. A result no worse than the current one is
    accepted; after 40 failures the search goes back to the best tree and after 200 it restarts from a noisy greedy.
With two CPUs a forked child runs the same search with another seed; the parent keeps the better answer.
Every answer is checked by verify() (the official checker's rules) before it is written, and the file is replaced
atomically. The run stops at min(0.9 T, T - 3) seconds after start-up.
Environment: MV2_FCTP_WORKERS (default 2; 1 = no child), MV2_FCTP_SEED (default 1), MV2_FCTP_LOG (write
<output>.log.json).
"""
import argparse
import json
import os
import random
import sys
import tempfile
import time

T_START = time.time()
VERSION = "0.1.0"
EPS = 1e-6
INF = float("inf")
TOL = 1e-5  # the official checker's tolerance on flows


def _num(v, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("%s must be a number, got %r" % (what, v))
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v


class Problem:
    def __init__(self, inst):
        m = int(inst["num_sources"])
        n = int(inst["num_sinks"])
        if m < 1 or n < 1:
            raise ValueError("need at least one source and one sink")
        a = [_num(v, "supply") for v in inst["supply"]]
        b = [_num(v, "demand") for v in inst["demand"]]
        if len(a) != m or len(b) != n:
            raise ValueError("supply/demand lengths %d/%d differ from %d/%d" % (len(a), len(b), m, n))
        if any(v < 0 for v in a) or any(v < 0 for v in b):
            raise ValueError("negative supply or demand")
        if abs(sum(a) - sum(b)) > 1e-9:
            raise ValueError("total supply %r differs from total demand %r" % (sum(a), sum(b)))
        C = [[float(v) for v in row] for row in inst["variable_cost"]]
        F = [[float(v) for v in row] for row in inst["fixed_cost"]]
        if len(C) != m or len(F) != m or any(len(r) != n for r in C) or any(len(r) != n for r in F):
            raise ValueError("cost matrices must be %d x %d" % (m, n))
        cap = inst.get("capacity")
        if cap is None:
            cap = [[min(a[i], b[j]) for j in range(n)] for i in range(m)]
        if len(cap) != m or any(len(r) != n for r in cap):
            raise ValueError("capacity must be %d x %d" % (m, n))
        self.m, self.n, self.a, self.b, self.C, self.F = m, n, a, b, C, F
        self.cap = [[float(v) for v in row] for row in cap]

    def objective(self, X):
        """sum_ij c_ij x_ij + f_ij [x_ij > 0], summed in the official checker's order."""
        s = 0.0
        C, F = self.C, self.F
        for i in range(self.m):
            Ci, Fi, Xi = C[i], F[i], X[i]
            for j in range(self.n):
                x = Xi[j]
                if x != 0:
                    s += Ci[j] * x + (Fi[j] if x > TOL else 0.0)
        return s


def solution_dict(pb, X):
    flow = [[X[i][j] for j in range(pb.n)] for i in range(pb.m)]
    used = [[1 if X[i][j] > TOL else 0 for j in range(pb.n)] for i in range(pb.m)]
    obj = 0.0
    for i in range(pb.m):
        for j in range(pb.n):
            obj += pb.C[i][j] * float(flow[i][j]) + pb.F[i][j] * float(used[i][j])
    return {"objective_value": float(obj), "flow": flow, "arcs_used": used}


def verify(pb, sol):
    """(ok, reason, cost): the official feasibility_check.py's rules, applied to a solution dict."""
    if not isinstance(sol, dict):
        return False, "solution is not a JSON object", None
    for k in ("arcs_used", "flow", "objective_value"):
        if sol.get(k) is None:
            return False, "missing " + k, None
    ov = sol["objective_value"]
    if isinstance(ov, bool) or not isinstance(ov, (int, float)) or ov != ov or ov in (INF, -INF):
        return False, "objective_value must be a finite number", None
    m, n = pb.m, pb.n
    sw = bool(sol.get("swapped", False))
    outer, inner = (n, m) if sw else (m, n)
    for key in ("flow", "arcs_used"):
        v = sol[key]
        if not isinstance(v, list) or len(v) != outer or any(not isinstance(r, list) or len(r) != inner for r in v):
            return False, "%s must be a %d x %d list" % (key, outer, inner), None
    try:
        if sw:
            x = [[float(sol["flow"][j][i]) for j in range(n)] for i in range(m)]
            y = [[float(sol["arcs_used"][j][i]) for j in range(n)] for i in range(m)]
        else:
            x = [[float(sol["flow"][i][j]) for j in range(n)] for i in range(m)]
            y = [[float(sol["arcs_used"][i][j]) for j in range(n)] for i in range(m)]
    except (TypeError, ValueError):
        return False, "non-numeric flow or arcs_used entry", None
    for i in range(m):
        if abs(sum(x[i]) - pb.a[i]) > TOL:
            return False, "supply of source %d not shipped exactly" % i, None
    for j in range(n):
        if abs(sum(x[i][j] for i in range(m)) - pb.b[j]) > TOL:
            return False, "demand of sink %d not met exactly" % j, None
    true = 0.0
    for i in range(m):
        for j in range(n):
            if x[i][j] - pb.cap[i][j] * y[i][j] > TOL:
                return False, "flow on (%d,%d) exceeds capacity times arcs_used" % (i, j), None
            if -x[i][j] > TOL:
                return False, "negative flow on (%d,%d)" % (i, j), None
            if min(abs(y[i][j]), abs(y[i][j] - 1.0)) > TOL:
                return False, "arcs_used (%d,%d) not 0/1" % (i, j), None
            true += pb.C[i][j] * x[i][j] + pb.F[i][j] * y[i][j]
    if abs(float(ov) - true) > max(1e-3, 1e-3 * abs(true)):
        return False, "objective_value %r differs from the recomputed cost %r" % (ov, true), None
    return True, "", true


class Search:
    def __init__(self, pb, seed, deadline):
        self.pb = pb
        self.rng = random.Random(seed)
        self.deadline = deadline
        m, n = pb.m, pb.n
        self.m, self.n, self.N = m, n, m + n
        self.X = [[0] * n for _ in range(m)]
        self.inB = [[False] * n for _ in range(m)]
        self.basis = []
        self.bpos = {}
        self.parent = [-1] * self.N
        self.depth = [0] * self.N
        self.as_ = [-1] * self.N
        self.at = [-1] * self.N
        self.cells = list(range(m * n))
        self.stats = {"seed": seed, "iterations": 0, "restarts": 0, "ls_calls": 0, "pivots": 0, "kicks": 0,
                      "noise_runs": 0}

    def late(self):
        return time.time() >= self.deadline

    # ------------------------------------------------------------------ basis handling
    def greedy(self, noise=0.0):
        """Least-cost rule on c + f / q. Returns m + n - 1 cells (i, j, q) forming a spanning tree."""
        pb, rng = self.pb, self.rng
        C, F = pb.C, pb.F
        ra, rb = list(pb.a), list(pb.b)
        rows, cols = list(range(self.m)), list(range(self.n))
        cells = []
        while True:
            bk, bi, bj = INF, -1, -1
            for i in rows:
                Ci, Fi, ai = C[i], F[i], ra[i]
                for j in cols:
                    q = ai if ai < rb[j] else rb[j]
                    key = Ci[j] + (Fi[j] / q if q > 0 else 0.0)
                    if noise:
                        key *= 1.0 + noise * rng.random()
                    if key < bk:
                        bk, bi, bj = key, i, j
            q = ra[bi] if ra[bi] < rb[bj] else rb[bj]
            cells.append((bi, bj, q))
            ra[bi] -= q
            rb[bj] -= q
            if len(rows) == 1 and len(cols) == 1:
                break
            if ra[bi] == 0 and len(rows) > 1:
                rows.remove(bi)
            else:
                cols.remove(bj)
        return cells

    def load(self, cells):
        """Install a basis given as (i, j, flow) triples."""
        X, inB = self.X, self.inB
        for (i, j) in self.basis:
            X[i][j] = 0
            inB[i][j] = False
        self.basis = []
        self.bpos = {}
        for (i, j, q) in cells:
            X[i][j] = q
            inB[i][j] = True
            self.bpos[(i, j)] = len(self.basis)
            self.basis.append((i, j))
        self.build()

    def snapshot(self):
        return [(i, j, self.X[i][j]) for (i, j) in self.basis]

    def build(self):
        m, N = self.m, self.N
        if len(self.basis) != N - 1:
            raise RuntimeError("basis has %d arcs, expected %d" % (len(self.basis), N - 1))
        adj = [[] for _ in range(N)]
        for (i, j) in self.basis:
            adj[i].append(m + j)
            adj[m + j].append(i)
        parent, depth = self.parent, self.depth
        seen = [False] * N
        seen[0] = True
        parent[0] = -1
        depth[0] = 0
        stack = [0]
        cnt = 1
        while stack:
            u = stack.pop()
            du = depth[u] + 1
            for w in adj[u]:
                if not seen[w]:
                    seen[w] = True
                    parent[w] = u
                    depth[w] = du
                    stack.append(w)
                    cnt += 1
        if cnt != N:
            raise RuntimeError("basis is not a spanning tree (%d of %d nodes reached)" % (cnt, N))
        as_, at = self.as_, self.at
        for w in range(1, N):
            p = parent[w]
            if w < m:
                as_[w], at[w] = w, p - m
            else:
                as_[w], at[w] = p, w - m

    def cost(self):
        C, F, X = self.pb.C, self.pb.F, self.X
        s = 0.0
        for (i, j) in self.basis:
            x = X[i][j]
            if x > 0:
                s += C[i][j] * x + F[i][j]
        return s

    # ------------------------------------------------------------------ pivots
    def path(self, i, j):
        """Tree path between source i and sink j, as two lists of nodes (each node = its arc to its parent)."""
        par, dep = self.parent, self.depth
        u, w = i, self.m + j
        du, dw = dep[u], dep[w]
        su, sw = [], []
        while du > dw:
            su.append(u)
            u = par[u]
            du -= 1
        while dw > du:
            sw.append(w)
            w = par[w]
            dw -= 1
        while u != w:
            su.append(u)
            u = par[u]
            sw.append(w)
            w = par[w]
        return su, sw

    def evaluate(self, i, j, C, F):
        """(delta, theta, su, sw) of pivoting arc (i, j) into the tree, under costs C, F.

        On the cycle, the arcs at an even distance from i (on i's side) or from sink j (on j's side) lose theta, the
        others gain theta. delta is the exact change of sum c x + f [x > 0]."""
        su, sw = self.path(i, j)
        X, as_, at = self.X, self.as_, self.at
        theta = INF
        for side in (su, sw):
            for k in range(0, len(side), 2):
                v = side[k]
                x = X[as_[v]][at[v]]
                if x < theta:
                    theta = x
        if not theta > 0:
            return 0.0, 0, su, sw
        d = C[i][j] * theta + F[i][j]
        for side in (su, sw):
            k = 0
            for v in side:
                s, t = as_[v], at[v]
                x = X[s][t]
                if k & 1:
                    d += C[s][t] * theta
                    if x == 0:
                        d += F[s][t]
                else:
                    d -= C[s][t] * theta
                    if x == theta:
                        d -= F[s][t]
                k += 1
        return d, theta, su, sw

    def apply(self, i, j, theta, su, sw):
        X, as_, at = self.X, self.as_, self.at
        leave = None
        for side in (su, sw):
            k = 0
            for v in side:
                s, t = as_[v], at[v]
                if k & 1:
                    X[s][t] += theta
                else:
                    X[s][t] -= theta
                    if leave is None and X[s][t] == 0:
                        leave = (s, t)
                k += 1
        if leave is None:
            raise RuntimeError("pivot found no leaving arc")
        X[i][j] = theta
        ls, lt = leave
        self.inB[ls][lt] = False
        self.inB[i][j] = True
        p = self.bpos.pop(leave)
        self.basis[p] = (i, j)
        self.bpos[(i, j)] = p
        self.build()
        self.stats["pivots"] += 1

    def local_search(self, C=None, F=None):
        """First-improvement pivots under costs C, F (default: the true costs) until none improves."""
        if C is None:
            C = self.pb.C
        if F is None:
            F = self.pb.F
        self.stats["ls_calls"] += 1
        n, inB, cells, rng = self.n, self.inB, self.cells, self.rng
        moves = 0
        improved = True
        while improved:
            improved = False
            rng.shuffle(cells)
            cnt = 0
            for idx in cells:
                i, j = divmod(idx, n)
                if inB[i][j]:
                    continue
                cnt += 1
                if cnt & 63 == 0 and self.late():
                    return moves
                d, theta, su, sw = self.evaluate(i, j, C, F)
                if d < -EPS:
                    self.apply(i, j, theta, su, sw)
                    moves += 1
                    improved = True
        return moves

    def kick(self, k):
        """k random non-degenerate pivots, improving or not."""
        m, n, rng, inB = self.m, self.n, self.rng, self.inB
        C, F = self.pb.C, self.pb.F
        done = tries = 0
        while done < k and tries < 50 * k:
            tries += 1
            i, j = rng.randrange(m), rng.randrange(n)
            if inB[i][j]:
                continue
            d, theta, su, sw = self.evaluate(i, j, C, F)
            if theta > 0:
                self.apply(i, j, theta, su, sw)
                done += 1
        self.stats["kicks"] += 1
        return done

    def noisy_fixed(self, sigma):
        rng = self.rng
        return [[f * (1.0 + sigma * (2.0 * rng.random() - 1.0)) for f in row] for row in self.pb.F]

    # ------------------------------------------------------------------ driver
    def run(self, on_improve=None):
        self.load(self.greedy())
        self.stats["construction"] = self.cost()
        self.local_search()
        cur = self.snapshot()
        cc = self.cost()
        best, bc = list(cur), cc
        self.stats["first_local_search"] = bc
        self.stats["events"] = [[round(time.time() - T_START, 3), bc]]
        if on_improve:
            on_improve(best, bc)
        since = 0
        rng = self.rng
        while not self.late():
            self.stats["iterations"] += 1
            if rng.random() < 0.5:
                self.kick(rng.randint(2, 6))
            else:
                self.stats["noise_runs"] += 1
                self.local_search(F=self.noisy_fixed(rng.choice((0.2, 0.4, 0.6))))
            self.local_search()
            nc = self.cost()
            if nc < bc - EPS:
                best, bc = self.snapshot(), nc
                since = 0
                self.stats["events"].append([round(time.time() - T_START, 3), bc])
                if on_improve:
                    on_improve(best, bc)
            else:
                since += 1
            if nc <= cc + EPS:
                cur, cc = self.snapshot(), nc
            else:
                self.load(cur)
            if since and since % 200 == 0 and not self.late():
                self.stats["restarts"] += 1
                self.load(self.greedy(noise=0.3))
                self.local_search()
                cur, cc = self.snapshot(), self.cost()
                if cc < bc - EPS:
                    best, bc = list(cur), cc
                    since = 0
                    self.stats["events"].append([round(time.time() - T_START, 3), bc])
                    if on_improve:
                        on_improve(best, bc)
            elif since and since % 40 == 0:
                self.load(best)
                cur, cc = list(best), bc
        self.stats["best"] = bc
        self.stats["events"] = self.stats["events"][:5] + self.stats["events"][-15:]
        return best, bc


def matrix(pb, cells):
    X = [[0] * pb.n for _ in range(pb.m)]
    for (i, j, q) in cells:
        X[int(i)][int(j)] = q
    return X


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="roberti2015")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    a = ap.parse_args(argv)
    T = float(a.time_limit)
    deadline = T_START + min(0.9 * T, T - 3.0)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    pb = Problem(inst)
    seed = int(os.environ.get("MV2_FCTP_SEED", "1"))
    workers = int(os.environ.get("MV2_FCTP_WORKERS", "2"))
    log = {"version": VERSION, "m": pb.m, "n": pb.n, "T": T, "load_s": round(time.time() - T_START, 3),
           "workers": workers}
    child_pid, child_path = None, None
    if workers >= 2 and hasattr(os, "fork") and pb.m * pb.n > pb.m + pb.n - 1:
        child_path = os.path.join(tempfile.gettempdir(), "mv2_fctp_child_%d.json" % os.getpid())
        try:
            pid = os.fork()
        except OSError:
            pid = None
        if pid == 0:
            code = 0
            try:
                s = Search(pb, seed + 1000, deadline - 0.25)
                bt, bcost = s.run()
                write_atomic(child_path, {"cells": bt, "cost": bcost, "stats": s.stats})
            except BaseException:  # noqa: BLE001 - the child must never outlive its parent's budget
                code = 1
            os._exit(code)
        child_pid = pid
    state = {"last_write": 0.0, "written": None}

    def on_improve(cells, cost, force=False):
        now = time.time()
        if not force and now - state["last_write"] < 0.5 and state["written"] is not None:
            return
        sol = solution_dict(pb, matrix(pb, cells))
        ok, why, real = verify(pb, sol)
        if ok:
            write_atomic(a.output, sol)
            state["last_write"] = now
            state["written"] = real
        else:
            log.setdefault("verify_failures", []).append(why)

    s = Search(pb, seed, deadline)
    best, bc = s.run(on_improve)
    log["parent"] = s.stats
    log["best_source"] = "parent"
    if child_pid:
        limit = deadline + 0.5
        done = False
        while time.time() < limit:
            try:
                r, _ = os.waitpid(child_pid, os.WNOHANG)
            except ChildProcessError:
                r = child_pid
            if r == child_pid:
                done = True
                break
            time.sleep(0.02)
        if not done:
            try:
                os.kill(child_pid, 9)
                os.waitpid(child_pid, 0)
            except Exception:  # noqa: BLE001
                pass
            log["child_killed"] = True
        try:
            with open(child_path, encoding="utf-8") as f:
                ch = json.load(f)
            os.remove(child_path)
            log["child"] = ch.get("stats")
            ccells, ccost = ch["cells"], ch["cost"]
            if ccost < bc - EPS:
                ok, _, real = verify(pb, solution_dict(pb, matrix(pb, ccells)))
                if ok:
                    best, bc = ccells, real
                    log["best_source"] = "child"
        except Exception as e:  # noqa: BLE001
            log["child_error"] = repr(e)[:200]
    if state["written"] is None or bc < state["written"] - EPS:
        on_improve(best, bc, force=True)
    log["best"] = state["written"]
    log["wall_s"] = round(time.time() - T_START, 3)
    if os.environ.get("MV2_FCTP_LOG"):
        try:
            write_atomic(a.output + ".log.json", log)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

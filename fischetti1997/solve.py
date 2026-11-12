#!/usr/bin/env python3
"""MV2's solver for FrontierOR task fischetti1997: the symmetric generalized TSP (E-GTSP, one node per cluster).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python solve.py --problem fischetti1997 --instance in.json --output out.json --time-limit 60

Standard library only. Method (iterated local search, in the spirit of Karapetyan & Gutin's GTSP local searches):
  * construction: nearest neighbour over nodes, never entering a cluster twice, from a random start;
  * local search, repeated until nothing improves:
      - 2-opt on the tour of selected nodes;
      - cluster relocation: take one cluster out and put it back between any two neighbours, choosing its best node
        for that spot (this also re-selects a cluster's node in place);
      - cluster optimisation: for the current cyclic order of clusters, the best node in every cluster at once, by
        an exact shortest-path dynamic programme (tried from every node of the smallest cluster);
  * perturbation: a local double bridge (two short neighbouring segments swapped), accepting a result no worse than
    the current one, going back to the best tour after 50 failures and restarting from a new construction after 300.
With two CPUs a forked child runs the same search with another seed; the parent keeps the better tour.
Every answer is checked by verify() (the official checker's rules) before it is written, and the file is replaced
atomically. The run stops at min(0.9 T, T - 3) seconds after start-up.
Environment: MV2_GTSP_WORKERS (default 2; 1 = no child), MV2_GTSP_SEED (default 1), MV2_GTSP_LOG (write
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
EPS = 1e-9
INF = float("inf")


class Problem:
    def __init__(self, inst):
        ps = inst["problem_size"]
        n = int(ps["n"])
        self.n = n
        self.m = int(ps["m"])
        vals = inst["distance_matrix_upper_triangular"]["values"]
        if len(vals) != n * (n - 1) // 2:
            raise ValueError("distance list has %d values, expected %d" % (len(vals), n * (n - 1) // 2))
        D = [[0] * n for _ in range(n)]
        k = 0
        for i in range(n):
            Di = D[i]
            for j in range(i + 1, n):
                v = vals[k]
                k += 1
                Di[j] = v
                D[j][i] = v
        self.D = D
        self.members = []
        self.cl = [-1] * n
        for idx, c in enumerate(inst["clusters"]):
            nodes = [int(v) for v in c["node_ids"]]
            for v in nodes:
                if not 0 <= v < n:
                    raise ValueError("node id %r outside 0..%d" % (v, n - 1))
                self.cl[v] = idx
            self.members.append(nodes)
        if len(self.members) != self.m or any(not mem for mem in self.members):
            raise ValueError("expected %d non-empty clusters, got %d" % (self.m, len(self.members)))
        self.nodes = [v for v in range(n) if self.cl[v] >= 0]

    def cost(self, t):
        D = self.D
        s = 0
        prev = t[-1]
        for v in t:
            s += D[prev][v]
            prev = v
        return s


def verify(pb, sol):
    """(ok, reason, cost): the official checker's rules, applied to a solution dict."""
    if not isinstance(sol, dict):
        return False, "solution is not a JSON object", None
    for k in ("objective_value", "tour", "visited_nodes"):
        if sol.get(k) is None:
            return False, "missing " + k, None
    tour = sol["tour"]
    if not isinstance(tour, list) or len(tour) != pb.m:
        return False, "tour must list exactly m = %d nodes" % pb.m, None
    if not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v < pb.n for v in tour):
        return False, "tour has an invalid node id", None
    if len(set(tour)) != len(tour):
        return False, "tour repeats a node", None
    cls = [pb.cl[v] for v in tour]
    if any(c < 0 for c in cls) or len(set(cls)) != pb.m:
        return False, "tour does not take exactly one node from every cluster", None
    vn = sol["visited_nodes"]
    if not isinstance(vn, list) or set(vn) != set(tour):
        return False, "visited_nodes differs from the tour's nodes", None
    if pb.m < 3:
        return False, "m < 3: a closed tour would use an edge twice", None
    cost = pb.cost(tour)
    ov = sol["objective_value"]
    if isinstance(ov, bool) or not isinstance(ov, (int, float)) or ov != ov or ov in (INF, -INF):
        return False, "objective_value must be a finite number", None
    if abs(ov - cost) > max(0.5, 1e-6 * abs(cost)):
        return False, "objective_value %r differs from the tour cost %r" % (ov, cost), None
    return True, "", cost


def solution_dict(tour, cost):
    return {"objective_value": float(cost), "tour": [int(v) for v in tour], "visited_nodes": [int(v) for v in tour]}


class Search:
    def __init__(self, pb, seed, deadline):
        self.pb = pb
        self.rng = random.Random(seed)
        self.deadline = deadline
        self.stats = {"seed": seed, "iterations": 0, "restarts": 0, "ls_calls": 0, "moves_2opt": 0,
                      "moves_relocate": 0, "moves_co": 0}

    def late(self):
        return time.time() >= self.deadline

    # ------------------------------------------------------------------ construction
    def nn_tour(self):
        pb, D, cl = self.pb, self.pb.D, self.pb.cl
        c0 = self.rng.randrange(pb.m)
        v = self.rng.choice(pb.members[c0])
        used = [False] * pb.m
        used[c0] = True
        t = [v]
        for _ in range(pb.m - 1):
            Dv = D[v]
            best, bd = -1, INF
            for u in pb.nodes:
                if not used[cl[u]]:
                    d = Dv[u]
                    if d < bd:
                        bd, best = d, u
            v = best
            used[cl[v]] = True
            t.append(v)
        return t

    # ------------------------------------------------------------------ moves
    def two_opt(self, t):
        m = len(t)
        if m < 4:
            return False
        D = self.pb.D
        any_imp = False
        improved = True
        while improved:
            improved = False
            for i in range(m - 2):
                if self.late():
                    return any_imp
                a, b = t[i], t[i + 1]
                Da, Db = D[a], D[b]
                dab = Da[b]
                jmax = m if i > 0 else m - 1
                j = i + 2
                while j < jmax:
                    c = t[j]
                    d = t[j + 1] if j + 1 < m else t[0]
                    delta = Da[c] + Db[d] - dab - D[c][d]
                    if delta < -EPS:
                        t[i + 1:j + 1] = t[i + 1:j + 1][::-1]
                        self.stats["moves_2opt"] += 1
                        improved = any_imp = True
                        b = t[i + 1]
                        Db = D[b]
                        dab = Da[b]
                    j += 1
        return any_imp

    def relocate(self, t):
        m = len(t)
        if m < 3:
            return False
        pb, D, cl = self.pb, self.pb.D, self.pb.cl
        any_imp = False
        improved = True
        while improved:
            improved = False
            i = 0
            while i < len(t):
                if self.late():
                    return any_imp
                m = len(t)
                p, u, q = t[i - 1], t[i], t[(i + 1) % m]
                Dp = D[p]
                dpq = Dp[q]
                gain = Dp[u] + D[u][q] - dpq
                mem = pb.members[cl[u]]
                best, ba, bw = gain - EPS, None, None
                for j in range(m):
                    a = t[j]
                    if a == u:
                        continue
                    b = t[j + 1] if j + 1 < m else t[0]
                    if b == u:
                        a, b, dab = p, q, dpq
                    else:
                        dab = D[a][b]
                    Da, Db = D[a], D[b]
                    for w in mem:
                        ins = Da[w] + Db[w] - dab
                        if ins < best:
                            best, ba, bw = ins, a, w
                if bw is not None:
                    t.pop(i)
                    k = t.index(ba)
                    t.insert(k + 1, bw)
                    self.stats["moves_relocate"] += 1
                    improved = any_imp = True
                else:
                    i += 1
        return any_imp

    def cluster_opt(self, t):
        """Best node per cluster for the cyclic cluster order of t (exact). Returns (tour, cost)."""
        pb, D, cl = self.pb, self.pb.D, self.pb.cl
        m = len(t)
        order = [cl[v] for v in t]
        k = min(range(m), key=lambda i: len(pb.members[order[i]]))
        order = order[k:] + order[:k]
        best_total, best_path = INF, None
        for s in pb.members[order[0]]:
            prev_nodes, prev_cost = [s], [0]
            back = []
            for idx in range(1, m):
                mem = pb.members[order[idx]]
                cur_cost, cur_arg = [], []
                for w in mem:
                    Dw = D[w]
                    bc, ba = INF, -1
                    for pi in range(len(prev_nodes)):
                        cc = prev_cost[pi] + Dw[prev_nodes[pi]]
                        if cc < bc:
                            bc, ba = cc, pi
                    cur_cost.append(bc)
                    cur_arg.append(ba)
                back.append(cur_arg)
                prev_nodes, prev_cost = mem, cur_cost
            Ds = D[s]
            for pi in range(len(prev_nodes)):
                total = prev_cost[pi] + Ds[prev_nodes[pi]]
                if total < best_total:
                    path = [0] * m
                    path[0] = s
                    j = pi
                    for idx in range(m - 1, 0, -1):
                        path[idx] = pb.members[order[idx]][j]
                        j = back[idx - 1][j]
                    best_total, best_path = total, path
        return best_path, best_total

    def local_search(self, t):
        self.stats["ls_calls"] += 1
        c = self.pb.cost(t)
        while True:
            imp = self.two_opt(t)
            imp = self.relocate(t) or imp
            if self.late():
                return t
            nt, nc = self.cluster_opt(t)
            c = self.pb.cost(t)
            if nt is not None and nc < c - EPS:
                t = nt
                c = nc
                self.stats["moves_co"] += 1
                imp = True
            if not imp or self.late():
                return t

    def perturb(self, t):
        m = len(t)
        if m < 4:
            return list(t)
        rng = self.rng
        L = max(2, min(50, m // 3))
        p1 = rng.randint(1, m - 3)
        p2 = p1 + rng.randint(1, min(L, m - p1 - 2))
        p3 = p2 + rng.randint(1, min(L, m - p2 - 1))
        return t[:p1] + t[p2:p3] + t[p1:p2] + t[p3:]

    # ------------------------------------------------------------------ driver
    def run(self, on_improve=None):
        pb = self.pb
        t = self.nn_tour()
        self.stats["construction"] = pb.cost(t)
        t = self.local_search(t)
        best, bc = list(t), pb.cost(t)
        self.stats["first_local_search"] = bc
        self.stats["events"] = [[round(time.time() - T_START, 3), bc]]
        if on_improve:
            on_improve(best, bc)
        cur, cc = list(best), bc
        since = 0
        while not self.late():
            self.stats["iterations"] += 1
            nt = self.local_search(self.perturb(cur))
            nc = pb.cost(nt)
            if nc <= cc:
                cur, cc = nt, nc
            if nc < bc - EPS:
                best, bc = list(nt), nc
                since = 0
                self.stats["events"].append([round(time.time() - T_START, 3), bc])
                if on_improve:
                    on_improve(best, bc)
            else:
                since += 1
                if since % 300 == 0:
                    self.stats["restarts"] += 1
                    cur = self.local_search(self.nn_tour())
                    cc = pb.cost(cur)
                elif since % 50 == 0:
                    cur, cc = list(best), bc
        self.stats["best"] = bc
        self.stats["events"] = self.stats["events"][:5] + self.stats["events"][-15:]
        return best, bc


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="fischetti1997")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    a = ap.parse_args(argv)
    T = float(a.time_limit)
    deadline = T_START + min(0.9 * T, T - 3.0)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    pb = Problem(inst)
    seed = int(os.environ.get("MV2_GTSP_SEED", "1"))
    workers = int(os.environ.get("MV2_GTSP_WORKERS", "2"))
    log = {"version": VERSION, "n": pb.n, "m": pb.m, "T": T, "load_s": round(time.time() - T_START, 3),
           "workers": workers}
    child_pid, child_path = None, None
    if workers >= 2 and hasattr(os, "fork") and pb.m >= 4:
        child_path = os.path.join(tempfile.gettempdir(), "mv2_gtsp_child_%d.json" % os.getpid())
        try:
            pid = os.fork()
        except OSError:
            pid = None
        if pid == 0:
            code = 0
            try:
                s = Search(pb, seed + 1000, deadline - 0.25)
                bt, bcost = s.run()
                write_atomic(child_path, {"tour": bt, "cost": bcost, "stats": s.stats})
            except BaseException:  # noqa: BLE001 - the child must never outlive its parent's budget
                code = 1
            os._exit(code)
        child_pid = pid
    state = {"last_write": 0.0, "written": None}

    def on_improve(tour, cost, force=False):
        now = time.time()
        if not force and now - state["last_write"] < 0.5 and state["written"] is not None:
            return
        sol = solution_dict(tour, cost)
        ok, why, _ = verify(pb, sol)
        if ok:
            write_atomic(a.output, sol)
            state["last_write"] = now
            state["written"] = cost
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
            ct, ccost = ch["tour"], ch["cost"]
            if ccost < bc - EPS:
                ok, _, real = verify(pb, solution_dict(ct, ccost))
                if ok:
                    best, bc = ct, real
                    log["best_source"] = "child"
        except Exception as e:  # noqa: BLE001
            log["child_error"] = repr(e)[:200]
    if state["written"] is None or bc < state["written"] - EPS:
        on_improve(best, bc, force=True)
    log["best"] = bc
    log["wall_s"] = round(time.time() - T_START, 3)
    if os.environ.get("MV2_GTSP_LOG"):
        try:
            write_atomic(a.output + ".log.json", log)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

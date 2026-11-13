#!/usr/bin/env python3
"""MV2's solver for FrontierOR task pessoa2021: the robust capacitated vehicle routing problem (cardinality budget).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python solve.py --problem pessoa2021 --instance in.json --output out.json --time-limit 60

Standard library only. Exactly num_vehicles routes, each starting and ending at the depot (node 0); every customer
(ids 1..n) on exactly one route. A route is robust-feasible when its worst-case demand, the sum of its nominal demands
plus the Gamma largest deviations among its customers (the official checker's rule), is at most the capacity.

Search: slack induction by string removals (SISR, Christiaens & Vanden Berghe 2020), written from the paper's
description: remove a few strings of consecutive customers from routes near a random seed customer, reinsert the
removed customers one by one at their cheapest position (each position skipped with a 1% "blink" chance), and accept
the result by simulated annealing on a schedule tied to the clock. Capacity is kept exact and incremental: for each
route we hold the nominal sum, the sum of its Gamma largest deviations and the Gamma-th largest deviation, so the
worst-case demand after inserting customer c is nominal + d_c + top + max(0, dev_c - threshold). An over-capacity
unit and an empty route are both penalised far above any travel cost, so the search only keeps them when nothing
else fits (when n < m some routes must stay empty; the checker allows that, and the penalty is then off).
Every new best is polished route by route (exact 2-opt / relocation, recomputed in full, so asymmetric costs are
fine), checked by verify() (the official checker's rules) and written atomically.
With two CPUs a forked child runs the same search with another seed; the parent keeps the better answer.
The run stops at min(0.9 T, T - 3) seconds after start-up.
Environment: MV2_RCVRP_WORKERS (default 2; 1 = no child), MV2_RCVRP_SEED (default 1), MV2_RCVRP_LOG (write
<output>.log.json).
"""
import argparse
import json
import math
import os
import random
import sys
import tempfile
import time

T_START = time.time()
VERSION = "0.1.0"
EPS = 1e-9
TOL = 1e-5  # the official checker's capacity tolerance
INF = float("inf")


class Problem:
    def __init__(self, inst):
        n = int(inst["num_customers"])
        self.n = n
        self.m = int(inst["num_vehicles"])
        self.C = inst["vehicle_capacity"]
        g = inst["uncertainty_set"]["Gamma"]
        self.G = int(g)
        D = [list(row) for row in inst["distance_matrix"]]
        if len(D) < n + 1 or any(len(row) < n + 1 for row in D[:n + 1]):
            raise ValueError("distance_matrix smaller than (n+1) x (n+1)")
        self.D = D
        bar = [0] * (n + 1)
        hat = [0] * (n + 1)
        for c in inst["customers"]:
            i = int(c["id"])
            if 1 <= i <= n:
                bar[i] = c["nominal_demand"]
                hat[i] = c["demand_deviation"]
        self.bar, self.hat = bar, hat
        self.custs = list(range(1, n + 1))
        self.sym = all(D[i][j] == D[j][i] for i in range(n + 1) for j in range(i + 1, n + 1))
        maxd = max(max(row[:n + 1]) for row in D[:n + 1]) if n >= 0 else 1
        self.maxd = max(1.0, float(maxd))
        unit = max(1.0, float(min([v for v in bar[1:] + hat[1:] if v > 0] or [1])))
        # one unit of excess, or one empty route, costs more than any change in travel cost can buy back
        self.LAM = 4.0 * (n + 2) * self.maxd / unit
        self.EPEN = 4.0 * (n + 2) * self.maxd if n >= self.m else 0.0
        self.weight = [bar[i] + hat[i] for i in range(n + 1)]
        # neighbours by symmetrised distance (for the ruin step)
        self.near = [[] for _ in range(n + 1)]
        for i in range(1, n + 1):
            Di = D[i]
            self.near[i] = sorted((j for j in range(1, n + 1) if j != i), key=lambda j: (Di[j] + D[j][i], j))

    def worst_case(self, custs):
        """The official checker's worst-case demand of a set of customers."""
        devs = sorted((self.hat[i] for i in custs), reverse=True)
        return sum(self.bar[i] for i in custs) + sum(devs[:min(self.G, len(devs))])

    def route_cost(self, seq):
        D = self.D
        prev = 0
        c = 0
        for v in seq:
            c += D[prev][v]
            prev = v
        return c + D[prev][0]


class Sol:
    """Routes plus per-route caches: cost, nominal sum, top-Gamma deviation sum, Gamma-th deviation, excess."""
    __slots__ = ("pb", "routes", "rcost", "nom", "top", "gth", "exc", "where")

    def __init__(self, pb, routes=None):
        self.pb = pb
        m = pb.m
        self.routes = [list(r) for r in routes] if routes is not None else [[] for _ in range(m)]
        self.rcost = [0] * m
        self.nom = [0] * m
        self.top = [0] * m
        self.gth = [0] * m
        self.exc = [0] * m
        self.where = [-1] * (pb.n + 1)
        for r in range(m):
            self.refresh(r)

    def copy(self):
        s = Sol.__new__(Sol)
        s.pb = self.pb
        s.routes = [list(r) for r in self.routes]
        s.rcost = list(self.rcost)
        s.nom = list(self.nom)
        s.top = list(self.top)
        s.gth = list(self.gth)
        s.exc = list(self.exc)
        s.where = list(self.where)
        return s

    def refresh(self, r):
        pb = self.pb
        seq = self.routes[r]
        hat = pb.hat
        G = pb.G
        devs = sorted((hat[i] for i in seq), reverse=True)
        self.nom[r] = sum(pb.bar[i] for i in seq)
        self.top[r] = sum(devs[:G]) if G > 0 else 0
        if G <= 0:
            self.gth[r] = INF
        elif len(devs) >= G:
            self.gth[r] = devs[G - 1]
        else:
            self.gth[r] = 0
        self.exc[r] = max(0, self.nom[r] + self.top[r] - pb.C)
        self.rcost[r] = pb.route_cost(seq)
        for v in seq:
            self.where[v] = r

    def load(self, r):
        return self.nom[r] + self.top[r]

    def distance(self):
        return sum(self.rcost)

    def excess(self):
        return sum(self.exc)

    def empties(self):
        return sum(1 for r in self.routes if not r)

    def penalised(self):
        pb = self.pb
        return sum(self.rcost) + pb.LAM * sum(self.exc) + pb.EPEN * sum(1 for r in self.routes if not r)

    def feasible(self):
        if any(e > TOL for e in self.exc):
            return False
        if self.pb.n >= self.pb.m and any(not r for r in self.routes):
            return False
        return True


def initial(pb, rng, order="weight"):
    s = Sol(pb)
    custs = list(pb.custs)
    if order == "weight":
        custs.sort(key=lambda i: (-pb.weight[i], i))
    else:
        rng.shuffle(custs)
    insert_all(s, custs, rng, blink=0.0)
    return s


def insert_all(s, custs, rng, blink=0.01):
    """Cheapest (penalised) insertion of each customer in turn."""
    pb = s.pb
    D = pb.D
    bar, hat = pb.bar, pb.hat
    C, LAM, EPEN = pb.C, pb.LAM, pb.EPEN
    routes = s.routes
    m = pb.m
    for c in custs:
        Dc = D[c]
        bc, hc = bar[c], hat[c]
        best, br, bp = INF, -1, 0
        for r in range(m):
            seq = routes[r]
            g = s.gth[r]
            add = hc - g if hc > g else 0
            nexc = s.nom[r] + bc + s.top[r] + add - C
            if nexc < 0:
                nexc = 0
            base = LAM * (nexc - s.exc[r])
            if not seq:
                d = base + D[0][c] + Dc[0] - EPEN
                if d < best:
                    best, br, bp = d, r, 0
                continue
            if base >= best:
                continue
            prev = 0
            Dp = D[0]
            L = len(seq)
            for p in range(L + 1):
                nxt = seq[p] if p < L else 0
                if blink and rng.random() < blink:
                    prev = nxt
                    Dp = D[prev]
                    continue
                d = base + Dp[c] + Dc[nxt] - Dp[nxt]
                if d < best:
                    best, br, bp = d, r, p
                prev = nxt
                Dp = D[prev]
        if br < 0:  # every position blinked: take the first route's end
            br, bp = 0, len(routes[0])
        routes[br].insert(bp, c)
        s.refresh(br)


def ruin(s, rng, cbar, lmax):
    pb = s.pb
    routes = s.routes
    nonempty = [r for r in routes if r]
    if not nonempty:
        return []
    avg = sum(len(r) for r in nonempty) / float(len(nonempty))
    ls_max = min(float(lmax), avg)
    ks_max = 4.0 * cbar / (1.0 + ls_max) - 1.0
    ks = int(rng.uniform(1.0, ks_max + 1.0))
    if ks < 1:
        ks = 1
    seed = rng.randint(1, pb.n)
    removed = []
    gone = set()
    ruined = set()
    for c in [seed] + pb.near[seed]:
        if len(ruined) >= ks:
            break
        if c in gone:
            continue
        r = s.where[c]
        if r < 0 or r in ruined:
            continue
        seq = routes[r]
        L = len(seq)
        lmt = min(float(L), ls_max)
        ln = int(rng.uniform(1.0, lmt + 1.0))
        ln = max(1, min(L, ln))
        pos = seq.index(c)
        if ln < L and rng.random() < 0.5:
            # split string: a window of ln + keep customers holding c; the keep in the middle stay
            keep = 1
            while ln + keep < L and rng.random() < 0.5:
                keep += 1
            w = ln + keep
            lo = max(0, pos - w + 1)
            hi = min(pos, L - w)
            st = rng.randint(lo, hi)
            ks0 = rng.randint(st, st + w - keep)
            idx = [st + k for k in range(w) if not (ks0 <= st + k < ks0 + keep)]
        else:
            lo = max(0, pos - ln + 1)
            hi = min(pos, L - ln)
            st = rng.randint(lo, hi)
            idx = list(range(st, st + ln))
        take = [seq[k] for k in idx]
        ids = set(idx)
        routes[r] = [v for k, v in enumerate(seq) if k not in ids]
        for v in take:
            s.where[v] = -1
            gone.add(v)
        removed.extend(take)
        ruined.add(r)
        s.refresh(r)
    return removed


def sort_removed(pb, removed, rng):
    x = rng.random() * 11.0
    if x < 4.0:
        rng.shuffle(removed)
    elif x < 8.0:
        removed.sort(key=lambda i: -pb.weight[i])
    elif x < 10.0:
        removed.sort(key=lambda i: -(pb.D[0][i] + pb.D[i][0]))
    else:
        removed.sort(key=lambda i: pb.D[0][i] + pb.D[i][0])
    return removed


def polish_route(pb, seq):
    """Exact intra-route improvement (2-opt reversal and single-customer relocation), full recomputation."""
    best = list(seq)
    bc = pb.route_cost(best)
    L = len(best)
    if L < 3:
        if L == 2:
            alt = [best[1], best[0]]
            ac = pb.route_cost(alt)
            if ac < bc - EPS:
                return alt, ac
        return best, bc
    improved = True
    rounds = 0
    while improved and rounds < 50:
        improved = False
        rounds += 1
        for i in range(L - 1):
            for j in range(i + 1, L):
                cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                cc = pb.route_cost(cand)
                if cc < bc - EPS:
                    best, bc, improved = cand, cc, True
        for i in range(L):
            u = best[i]
            rest = best[:i] + best[i + 1:]
            for p in range(L):
                if p == i:
                    continue
                cand = rest[:p] + [u] + rest[p:]
                cc = pb.route_cost(cand)
                if cc < bc - EPS:
                    best, bc, improved = cand, cc, True
                    break
            if improved:
                break
    return best, bc


def polish(s):
    for r in range(s.pb.m):
        if 2 <= len(s.routes[r]) <= 40:  # O(L^3) per pass; longer routes are left to the main search
            seq, _ = polish_route(s.pb, s.routes[r])
            s.routes[r] = seq
            s.refresh(r)
    return s


class Search:
    def __init__(self, pb, seed, deadline, cbar=10.0, lmax=10.0):
        self.pb = pb
        self.rng = random.Random(seed)
        self.deadline = deadline
        self.cbar, self.lmax = cbar, lmax
        self.stats = {"seed": seed, "iterations": 0, "accepted": 0, "improved": 0}

    def run(self, on_improve=None):
        pb, rng = self.pb, self.rng
        t0 = time.time()
        span = max(1e-3, self.deadline - t0)
        cur = initial(pb, rng, "weight")
        alt = initial(pb, rng, "random")
        if alt.penalised() < cur.penalised():
            cur = alt
        self.stats["construction"] = cur.distance()
        self.stats["construction_feasible"] = cur.feasible()
        fc = cur.penalised()
        best = polish(cur.copy())
        bf = best.penalised()
        events = [[round(time.time() - T_START, 3), best.distance(), best.feasible()]]
        if on_improve and best.feasible():
            on_improve(best)
        n_edges = pb.n + pb.m
        avg_edge = cur.distance() / float(max(1, n_edges))
        T0 = max(1e-6, 0.5 * avg_edge)
        Tf = max(1e-9, 0.005 * avg_edge)
        self.stats["T0"], self.stats["Tf"] = T0, Tf
        ratio = Tf / T0
        T = T0
        it = 0
        last_polish = 0.0
        best_polished = True
        while True:
            it += 1
            if (it & 15) == 0 or it < 16:
                now = time.time()
                if now >= self.deadline:
                    break
                frac = (now - t0) / span
                T = T0 * (ratio ** frac)
            nw = cur.copy()
            removed = ruin(nw, rng, self.cbar, self.lmax)
            if not removed:
                continue
            insert_all(nw, sort_removed(pb, removed, rng), rng)
            fn = nw.penalised()
            if fn < fc - T * math.log(1.0 - rng.random() + 1e-300):
                cur, fc = nw, fn
                self.stats["accepted"] += 1
                if fn < bf - EPS:
                    now = time.time()
                    if now - last_polish >= 0.25:
                        best = polish(nw.copy())
                        last_polish = now
                        best_polished = True
                    else:
                        best = nw.copy()
                        best_polished = False
                    bf = best.penalised()
                    self.stats["improved"] += 1
                    if len(events) < 400:
                        events.append([round(time.time() - T_START, 3), best.distance(), best.feasible()])
                    if on_improve and best.feasible():
                        on_improve(best)
        if not best_polished:
            best = polish(best)
            bf = best.penalised()
            if on_improve and best.feasible():
                on_improve(best, True)
        self.stats["iterations"] = it
        self.stats["best"] = best.distance()
        self.stats["best_feasible"] = best.feasible()
        self.stats["events"] = events[:5] + events[-15:]
        return best


def build_solution(pb, s):
    routes = []
    total = 0
    for seq in s.routes:
        c = pb.route_cost(seq)
        total += c
        routes.append({"customers": [int(v) for v in seq], "cost": c, "worst_case_demand": pb.worst_case(seq)})
    return {"objective_value": float(total), "status": "feasible", "routes": routes}


def _finite_number(v):
    return not isinstance(v, bool) and isinstance(v, (int, float)) and v == v and v not in (INF, -INF)


def verify(pb, sol):
    """(ok, reason, objective): the official checker's rules (contract, constraints 1-7), applied to a dict."""
    if not isinstance(sol, dict):
        return False, "solution is not a JSON object", None
    for f in ("objective_value", "routes"):
        if sol.get(f) is None:
            return False, "missing " + f, None
    ov = sol["objective_value"]
    if not _finite_number(ov):
        return False, "objective_value must be a finite number", None
    st = sol.get("status", "")
    if isinstance(st, str) and st.lower() in ("infeasible", "no_solution"):
        return False, "status says no solution", None
    try:
        routes = sol["routes"]
        n = pb.n
        cnt = {}
        for rt in routes:
            for c in rt["customers"]:
                cnt[c] = cnt.get(c, 0) + 1
        for i in range(1, n + 1):
            if cnt.get(i, 0) != 1:
                return False, "customer %d visited %d times" % (i, cnt.get(i, 0)), None
        if len(routes) != pb.m:
            return False, "%d routes, expected %d" % (len(routes), pb.m), None
        for rt in routes:
            for c in rt["customers"]:
                if not isinstance(c, int) or isinstance(c, bool) or c < 1 or c > n:
                    return False, "invalid customer id %r" % (c,), None
        for rt in routes:
            cs = rt["customers"]
            if cs and pb.worst_case(cs) - pb.C > TOL:
                return False, "worst-case demand %r over capacity %r" % (pb.worst_case(cs), pb.C), None
        true = 0.0
        D = pb.D
        for rt in routes:
            prev = 0
            for c in rt["customers"]:
                true += float(D[prev][c])
                prev = c
            true += float(D[prev][0])
        if abs(float(ov) - true) > max(1e-3, 1e-3 * abs(true)):
            return False, "objective_value %r differs from the recomputed %r" % (ov, true), None
        return True, "", true
    except (TypeError, ValueError, KeyError, IndexError, AttributeError) as e:
        return False, "malformed solution: %r" % (e,), None


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="pessoa2021")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    a = ap.parse_args(argv)
    T = float(a.time_limit)
    deadline = T_START + min(0.9 * T, T - 3.0)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    pb = Problem(inst)
    seed = int(os.environ.get("MV2_RCVRP_SEED", "1"))
    workers = int(os.environ.get("MV2_RCVRP_WORKERS", "2"))
    log = {"version": VERSION, "n": pb.n, "m": pb.m, "C": pb.C, "Gamma": pb.G, "symmetric": pb.sym, "T": T,
           "load_s": round(time.time() - T_START, 3), "workers": workers}
    child_pid, child_path = None, None
    if workers >= 2 and hasattr(os, "fork"):
        child_path = os.path.join(tempfile.gettempdir(), "mv2_rcvrp_child_%d.json" % os.getpid())
        try:
            pid = os.fork()
        except OSError:
            pid = None
        if pid == 0:
            code = 0
            try:
                s = Search(pb, seed + 1000, deadline - 0.25)
                b = s.run()
                write_atomic(child_path, {"routes": b.routes, "stats": s.stats})
            except BaseException:  # noqa: BLE001 - the child must never outlive its parent's budget
                code = 1
            os._exit(code)
        child_pid = pid
    state = {"last_write": 0.0, "written": None}

    def on_improve(sol_obj, force=False):
        now = time.time()
        if not force and now - state["last_write"] < 0.5 and state["written"] is not None:
            return
        out = build_solution(pb, sol_obj)
        ok, why, real = verify(pb, out)
        if ok:
            if state["written"] is None or real < state["written"] - EPS:
                write_atomic(a.output, out)
                state["last_write"] = now
                state["written"] = real
        else:
            log.setdefault("verify_failures", []).append(why[:200])

    s = Search(pb, seed, deadline)
    best = s.run(on_improve)
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
            cs = Sol(pb, ch["routes"])
            if cs.feasible() and (not best.feasible() or cs.distance() < best.distance() - EPS):
                best = cs
                log["best_source"] = "child"
        except Exception as e:  # noqa: BLE001
            log["child_error"] = repr(e)[:200]
    if best.feasible():
        out = build_solution(pb, best)
        ok, why, real = verify(pb, out)
        if ok and (state["written"] is None or real < state["written"] - EPS):
            write_atomic(a.output, out)
            state["written"] = real
        elif not ok:
            log.setdefault("verify_failures", []).append(why[:200])
    log["best"] = state["written"]
    log["wall_s"] = round(time.time() - T_START, 3)
    if os.environ.get("MV2_RCVRP_LOG"):
        try:
            write_atomic(a.output + ".log.json", log)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

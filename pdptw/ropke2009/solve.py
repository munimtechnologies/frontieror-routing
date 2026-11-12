"""ropke2009 (PDPTW: pickup and delivery with time windows) solver for the FrontierOR Challenge, v0.1.0.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Contest CLI:  python solve.py --problem ropke2009 --instance IN.json --output OUT.json --time-limit T

The contract is read from the official FrontierOR feasibility_check.py of task ropke2009 (Hugging Face
frontieror/FrontierOR, CC BY 4.0), not only from the problem page:
- request r has pickup node r and delivery node n + r; depots are 0 and 2n + 1 (same coordinates);
- cost(i, j) = Euclidean distance from the node coordinates (unrounded); travel time t(i, j) = cost(i, j) + service
  time of i; service starts at max(arrival, earliest) and must be <= latest; the clock starts at the depot's earliest
  time; the load after each node must stay in [0, Q];
- at most num_vehicles routes; empty vehicles may be left out (the checker pads them);
- objective_value must equal the checker's recomputation (sum of the arc costs, route by route) within 0.1%; we
  write exactly that recomputation.

Method: adaptive large neighbourhood search in the style of Ropke & Pisinger (2006): removal by random, worst-cost,
relatedness (Shaw) and whole-route; reinsertion by greedy and regret-2/3/4 with optional noise; simulated-annealing
acceptance on a time-based schedule; adaptive operator weights. Insertion feasibility is tested in O(1) per position
with forward start times and backward latest-start slacks. The second CPU runs the same search with another seed in
a forked process. A feasible incumbent is written as soon as one exists and refreshed while searching (anytime). The
search stops at min(0.85 T, T - 4) s after start.
"""
import argparse
import json
import math
import os
import random
import sys
import time

T_START = time.monotonic()
VERSION = "0.1.0"
INF = float("inf")


# ----------------------------------------------------------------------------------------------------- the problem
class Problem:
    def __init__(self, inst):
        n = int(inst["num_requests"])
        self.n = n
        self.Q = inst["vehicle_capacity"]
        self.K = int(inst["num_vehicles"])
        N = 2 * n + 2
        self.N = N
        self.o, self.e = 0, 2 * n + 1
        nodes = {int(nd["id"]): nd for nd in inst["nodes"]}
        missing = [i for i in range(N) if i not in nodes]
        if missing:
            raise ValueError("instance lacks nodes %r" % missing[:5])
        self.x = [nodes[i]["x"] for i in range(N)]
        self.y = [nodes[i]["y"] for i in range(N)]
        self.dem = [nodes[i]["demand"] for i in range(N)]
        self.svc = [nodes[i].get("service_time", 0) for i in range(N)]
        self.a = [nodes[i]["time_window"][0] for i in range(N)]
        self.b = [nodes[i]["time_window"][1] for i in range(N)]
        x, y, svc = self.x, self.y, self.svc
        # identical expressions to the official checker: sqrt((x1-x2)**2 + (y1-y2)**2) and dist + service_time[i]
        self.dist = [[(math.sqrt((x[i] - x[j]) ** 2 + (y[i] - y[j]) ** 2) if i != j else 0.0) for j in range(N)]
                     for i in range(N)]
        self.tt = [[(self.dist[i][j] + svc[i] if i != j else 0.0) for j in range(N)] for i in range(N)]
        self.load = [0] * (n + 1)
        for r in range(1, n + 1):
            self.load[r] = self.dem[r]
        self.maxd = max(1e-9, max(max(row) for row in self.dist))
        self.horizon = max(1e-9, self.b[self.e] - self.a[self.o])
        # cost and feasibility of a request alone on an empty vehicle (constant)
        self.solo = [INF] * (n + 1)
        for r in range(1, n + 1):
            if self.route_feasible([self.o, r, n + r, self.e]):
                self.solo[r] = self.dist[self.o][r] + self.dist[r][n + r] + self.dist[n + r][self.e] - \
                    self.dist[self.o][self.e]

    def route_feasible(self, s):
        """Checker semantics for one route (node list from 0 to 2n+1): times, windows, loads, pairing."""
        n, a, b, tt, dem, Q = self.n, self.a, self.b, self.tt, self.dem, self.Q
        if len(s) < 2 or s[0] != self.o or s[-1] != self.e:
            return False
        t = a[s[0]]
        ld = 0
        seen = set()
        for k in range(1, len(s)):
            v = s[k]
            t = t + tt[s[k - 1]][v]
            if t < a[v]:
                t = a[v]
            if t > b[v]:
                return False
            ld += dem[v]
            if ld > Q or ld < 0:
                return False
            if 1 <= v <= n:
                seen.add(v)
            elif n < v <= 2 * n:
                if v - n not in seen:
                    return False
                seen.discard(v - n)
        return not seen


class Route:
    __slots__ = ("s", "B", "LT", "L", "cost")

    def __init__(self, pb, s):
        self.s = s
        self.update(pb)

    def update(self, pb):
        s = self.s
        m = len(s)
        a, b, tt, dem, dist = pb.a, pb.b, pb.tt, pb.dem, pb.dist
        B = [0.0] * m
        L = [0] * m
        t = a[s[0]]
        B[0] = t
        ld = 0
        c = 0.0
        for k in range(1, m):
            t = t + tt[s[k - 1]][s[k]]
            if t < a[s[k]]:
                t = a[s[k]]
            B[k] = t
            ld += dem[s[k]]
            L[k] = ld
            c += dist[s[k - 1]][s[k]]
        LT = [0.0] * m
        LT[m - 1] = b[s[m - 1]]
        for k in range(m - 2, -1, -1):
            v = LT[k + 1] - tt[s[k]][s[k + 1]]
            LT[k] = b[s[k]] if b[s[k]] < v else v
        self.B, self.L, self.LT, self.cost = B, L, LT, c

    def requests(self, n):
        return [v for v in self.s if 1 <= v <= n]


def best_insertion(pb, R, r, best=INF):
    """Cheapest feasible insertion of request r into route R: (delta cost, i, j) or (INF, -1, -1).
    Pickup goes right after position i, delivery right after position j >= i (j == i: directly after the pickup)."""
    s, B, LT, L = R.s, R.B, R.LT, R.L
    m = len(s)
    a, b, tt, dist = pb.a, pb.b, pb.tt, pb.dist
    p = r
    d = pb.n + r
    l = pb.load[r]
    Q = pb.Q
    ap, bp, ad, bd = a[p], b[p], a[d], b[d]
    ttp, ttd, dp_row, dd_row = tt[p], tt[d], dist[p], dist[d]
    bi, bj = -1, -1
    for i in range(m - 1):
        si = s[i]
        tP = B[i] + tt[si][p]
        if tP > bp:
            break                      # later positions only start later (waiting + triangle inequality)
        if tP < ap:
            tP = ap
        if L[i] + l > Q:
            continue
        si1 = s[i + 1]
        dsi = dist[si]
        dpk = dsi[p] + dp_row[si1] - dsi[si1]
        if dpk >= best:
            continue
        # delivery directly after the pickup
        tD = tP + ttp[d]
        if tD < ad:
            tD = ad
        if tD <= bd and tD + ttd[si1] <= LT[i + 1]:
            c = dsi[p] + dp_row[d] + dd_row[si1] - dsi[si1]
            if c < best:
                best, bi, bj = c, i, i
        # delivery later: walk the shifted start times from position i+1
        t = tP + ttp[si1]
        if t < a[si1]:
            t = a[si1]
        k = i + 1
        while k < m - 1:
            sk = s[k]
            if t > b[sk] or L[k] + l > Q:
                break
            tD = t + tt[sk][d]
            if tD > bd:
                break
            if tD < ad:
                tD = ad
            sk1 = s[k + 1]
            if tD + ttd[sk1] <= LT[k + 1]:
                c = dpk + dist[sk][d] + dd_row[sk1] - dist[sk][sk1]
                if c < best:
                    best, bi, bj = c, i, k
            t = t + tt[sk][sk1]
            if t < a[sk1]:
                t = a[sk1]
            k += 1
    if bi < 0:
        return (INF, -1, -1)
    return (best, bi, bj)


def apply_insertion(pb, R, r, i, j):
    R.s.insert(j + 1, pb.n + r)
    R.s.insert(i + 1, r)
    R.update(pb)


def remove_request(pb, R, r):
    R.s.remove(r)
    R.s.remove(pb.n + r)
    R.update(pb)


# ------------------------------------------------------------------------------------------------------- the state
class State:
    def __init__(self, pb, routes=None):
        self.pb = pb
        self.routes = [Route(pb, list(s)) for s in (routes or [])]
        while len(self.routes) < pb.K:
            self.routes.append(Route(pb, [pb.o, pb.e]))
        self.where = [-1] * (pb.n + 1)
        for k, R in enumerate(self.routes):
            for v in R.s:
                if 1 <= v <= pb.n:
                    self.where[v] = k
        self.unassigned = set(r for r in range(1, pb.n + 1) if self.where[r] < 0)

    def copy_routes(self):
        return [list(R.s) for R in self.routes]

    def cost(self):
        return sum(R.cost for R in self.routes)

    def penalised(self):
        return self.cost() + len(self.unassigned) * 10.0 * self.pb.maxd * 4.0


# ------------------------------------------------------------------------------------------------- insertion ops
def insert_requests(pb, st, reqs, rng, regret_k=1, noise=0.0):
    """Insert the requests in reqs (a list) into st; regret_k=1 is greedy. Leaves failures in st.unassigned."""
    pending = list(reqs)
    if not pending:
        return
    routes = st.routes
    # cache[r][k] = (cost, i, j) for non-empty route k; empty routes share pb.solo
    cache = {}
    empty_idx = [k for k, R in enumerate(routes) if len(R.s) == 2]
    busy = [k for k, R in enumerate(routes) if len(R.s) > 2]
    for r in pending:
        cache[r] = {k: best_insertion(pb, routes[k], r) for k in busy}
    while pending:
        best_r, best_key, best_val = None, None, None
        for r in pending:
            opts = []
            cr = cache[r]
            for k in busy:
                c = cr[k][0]
                if c < INF:
                    if noise:
                        c = max(0.0, c + noise * pb.maxd * (2.0 * rng.random() - 1.0))
                    opts.append((c, k))
            if empty_idx and pb.solo[r] < INF:
                c = pb.solo[r]
                if noise:
                    c = max(0.0, c + noise * pb.maxd * (2.0 * rng.random() - 1.0))
                opts.append((c, empty_idx[0]))
            if not opts:
                continue
            opts.sort()
            if regret_k <= 1:
                key = (-opts[0][0],)
            else:
                reg = 0.0
                for h in range(1, regret_k):
                    reg += (opts[h][0] if h < len(opts) else 1e3 * pb.maxd) - opts[0][0]
                key = (reg, -opts[0][0])
            if best_key is None or key > best_key:
                best_r, best_key, best_val = r, key, opts[0]
        if best_r is None:
            break                          # nothing left can be inserted anywhere
        r = best_r
        k = best_val[1]
        R = routes[k]
        if len(R.s) == 2:
            i, j = 0, 0
            empty_idx.remove(k)
            busy.append(k)
        else:
            _, i, j = cache[r][k]
        apply_insertion(pb, R, r, i, j)
        st.where[r] = k
        st.unassigned.discard(r)
        pending.remove(r)
        for q in pending:
            cache[q][k] = best_insertion(pb, R, q)


# --------------------------------------------------------------------------------------------------- removal ops
def assigned(st):
    return [r for r in range(1, st.pb.n + 1) if st.where[r] >= 0]


def take_out(pb, st, reqs):
    by_route = {}
    for r in reqs:
        k = st.where[r]
        if k < 0:
            continue
        by_route.setdefault(k, []).append(r)
    for k, rs in by_route.items():
        R = st.routes[k]
        drop = set(rs) | set(pb.n + r for r in rs)
        R.s = [v for v in R.s if v not in drop]
        R.update(pb)
        for r in rs:
            st.where[r] = -1
            st.unassigned.add(r)


def remove_random(pb, st, q, rng):
    cand = assigned(st)
    rng.shuffle(cand)
    return cand[:q]


def remove_worst(pb, st, q, rng, power=3.0):
    dist = pb.dist
    sav = []
    for R in st.routes:
        s = R.s
        if len(s) <= 2:
            continue
        pos = {v: k for k, v in enumerate(s)}
        for v in s:
            if 1 <= v <= pb.n:
                ip, idd = pos[v], pos[v + pb.n]
                if idd == ip + 1:
                    g = dist[s[ip - 1]][v] + dist[v][s[idd]] + dist[s[idd]][s[idd + 1]] - dist[s[ip - 1]][s[idd + 1]]
                else:
                    g = (dist[s[ip - 1]][v] + dist[v][s[ip + 1]] - dist[s[ip - 1]][s[ip + 1]] +
                         dist[s[idd - 1]][s[idd]] + dist[s[idd]][s[idd + 1]] - dist[s[idd - 1]][s[idd + 1]])
                sav.append((g, v))
    sav.sort(reverse=True)
    out = []
    while sav and len(out) < q:
        idx = int((rng.random() ** power) * len(sav))
        out.append(sav.pop(idx)[1])
    return out


def remove_shaw(pb, st, q, rng, power=6.0):
    cand = assigned(st)
    if not cand:
        return []
    n, dist = pb.n, pb.dist
    tB = {}
    for R in st.routes:
        for k, v in enumerate(R.s):
            tB[v] = R.B[k]
    md, hz, Q = pb.maxd, pb.horizon, max(1, pb.Q)

    def rel(i, j):
        return (9.0 * (dist[i][j] + dist[n + i][n + j]) / md +
                3.0 * (abs(tB[i] - tB[j]) + abs(tB[n + i] - tB[n + j])) / hz +
                2.0 * abs(pb.load[i] - pb.load[j]) / Q + (0.0 if st.where[i] == st.where[j] else 1.0))
    first = rng.choice(cand)
    out = [first]
    rest = [r for r in cand if r != first]
    while len(out) < q and rest:
        ref = rng.choice(out)
        rest.sort(key=lambda j: rel(ref, j))
        idx = int((rng.random() ** power) * len(rest))
        out.append(rest.pop(idx))
    return out


def remove_route(pb, st, q, rng):
    busy = [R for R in st.routes if len(R.s) > 2]
    if not busy:
        return []
    busy.sort(key=lambda R: len(R.s))
    R = busy[int((rng.random() ** 2.0) * len(busy))]
    out = R.requests(pb.n)
    if len(out) < q:
        extra = [r for r in remove_shaw(pb, st, q, rng) if r not in out]
        out += extra[:q - len(out)]
    return out


REMOVALS = [("random", remove_random), ("worst", remove_worst), ("shaw", remove_shaw), ("route", remove_route)]
INSERTS = [("greedy", 1, 0.0), ("regret2", 2, 0.0), ("regret3", 3, 0.0), ("regret4", 4, 0.0),
           ("greedy_noise", 1, 0.025), ("regret2_noise", 2, 0.025)]


# ---------------------------------------------------------------------------------------------- construction + ALNS
def construct(pb, rng):
    best = None
    for kind in (2, 1, 3):
        st = State(pb)
        order = sorted(range(1, pb.n + 1), key=lambda r: (pb.b[r], pb.a[r]))
        insert_requests(pb, st, order, rng, regret_k=kind)
        if best is None or st.penalised() < best.penalised():
            best = st
        if not best.unassigned and time.monotonic() - T_START > 2.0:
            break
    return best


def alns(pb, st, seed, deadline, report=None, stats=None):
    rng = random.Random(seed)
    cur = st.penalised()
    best_cost = cur
    best_routes = st.copy_routes()
    best_complete = not st.unassigned
    if best_complete and report:
        report(best_routes, st.cost())
    t_begin = time.monotonic()
    span = max(1e-3, deadline - t_begin)
    T0 = max(1e-6, 0.05 * st.cost() / math.log(2.0)) if st.cost() > 0 else 1.0
    T_end_ratio = 0.002
    w_rem = [1.0] * len(REMOVALS)
    w_ins = [1.0] * len(INSERTS)
    sc_rem = [0.0] * len(REMOVALS)
    sc_ins = [0.0] * len(INSERTS)
    n_rem = [0] * len(REMOVALS)
    n_ins = [0] * len(INSERTS)
    seen = set()
    n = pb.n
    qmin = max(1, min(4, n // 2))
    qmax = max(qmin, min(n, max(int(0.4 * n), qmin + 1), 30))
    it = 0
    accepted = 0
    while True:
        now = time.monotonic()
        if now >= deadline:
            break
        it += 1
        frac = min(1.0, (now - t_begin) / span)
        temp = T0 * (T_end_ratio ** frac)
        ri = _roulette(w_rem, rng)
        ii = _roulette(w_ins, rng)
        q = rng.randint(qmin, qmax)
        saved = st.copy_routes()
        reqs = REMOVALS[ri][1](pb, st, q, rng)
        take_out(pb, st, reqs)
        pend = list(st.unassigned)
        rng.shuffle(pend)
        _, kreg, noise = INSERTS[ii]
        insert_requests(pb, st, pend, rng, regret_k=kreg, noise=noise)
        new = st.penalised()
        score = 0.0
        key = round(new, 6)
        if new < best_cost - 1e-9:
            best_cost = new
            if not st.unassigned:
                best_routes = st.copy_routes()
                best_complete = True
                if report:
                    report(best_routes, st.cost())
            score = 33.0
        elif new < cur - 1e-9 and key not in seen:
            score = 9.0
        accept = new <= cur or rng.random() < math.exp(-(new - cur) / max(1e-12, temp))
        if accept:
            if score == 0.0 and key not in seen:
                score = 13.0
            cur = new
            accepted += 1
        else:
            st.__init__(pb, saved)
        seen.add(key)
        sc_rem[ri] += score
        sc_ins[ii] += score
        n_rem[ri] += 1
        n_ins[ii] += 1
        if it % 100 == 0:
            for w, sc, cnt in ((w_rem, sc_rem, n_rem), (w_ins, sc_ins, n_ins)):
                for h in range(len(w)):
                    if cnt[h]:
                        w[h] = max(0.05, 0.9 * w[h] + 0.1 * sc[h] / cnt[h])
                    sc[h] = 0.0
                    cnt[h] = 0
            if len(seen) > 200000:
                seen.clear()
    if stats is not None:
        stats.update(iterations=it, accepted=accepted, best=best_cost if best_complete else None,
                     w_rem={REMOVALS[h][0]: round(w_rem[h], 3) for h in range(len(REMOVALS))},
                     w_ins={INSERTS[h][0]: round(w_ins[h], 3) for h in range(len(INSERTS))})
    return (best_cost if best_complete else None), (best_routes if best_complete else None)


def _roulette(w, rng):
    tot = sum(w)
    x = rng.random() * tot
    acc = 0.0
    for h, v in enumerate(w):
        acc += v
        if x <= acc:
            return h
    return len(w) - 1


# --------------------------------------------------------------------------------------------- output + verify
def checker_objective(pb, routes):
    """The official checker's recomputation: sum over the written routes, arc by arc, in order."""
    tot = 0.0
    for s in routes:
        for k in range(len(s) - 1):
            i, j = s[k], s[k + 1]
            if i != j:
                tot += pb.dist[i][j]
    return tot


def verify(pb, routes):
    """Full check with the checker's rules (no tolerance on our side). Returns (ok, reason)."""
    used = [s for s in routes if len(s) > 2]
    if len(used) > pb.K:
        return False, "too many routes"
    count = [0] * (2 * pb.n + 2)
    for s in used:
        if not pb.route_feasible(s):
            return False, "route infeasible %r" % (s[:6],)
        for v in s[1:-1]:
            if v in (pb.o, pb.e):
                return False, "depot inside route"
            count[v] += 1
        n = pb.n
        t = pb.a[s[0]]
        bt = {s[0]: t}
        for k in range(1, len(s)):
            t = t + pb.tt[s[k - 1]][s[k]]
            if t < pb.a[s[k]]:
                t = pb.a[s[k]]
            bt[s[k]] = t
        for v in s:
            if 1 <= v <= n and bt[v] + pb.tt[v][n + v] > bt[n + v] + 1e-7:
                return False, "precedence time"
    for v in range(1, 2 * pb.n + 1):
        if count[v] != 1:
            return False, "node %d visited %d times" % (v, count[v])
    return True, ""


def solution_json(pb, routes):
    used = [list(s) for s in routes if len(s) > 2]
    return {"objective_value": checker_objective(pb, used),
            "routes": [{"vehicle": k, "nodes": s} for k, s in enumerate(used)],
            "solver": "MV2 ropke2009 ALNS v%s (made with AI agents working in MV2's name)" % VERSION}


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def solve(inst, out_path, time_limit, seed=1, workers=2):
    pb = Problem(inst)
    search_end = T_START + max(0.5, min(0.85 * time_limit, time_limit - 4.0))
    log = {"version": VERSION, "n": pb.n, "K": pb.K, "Q": pb.Q, "events": []}
    rng = random.Random(seed)
    st = construct(pb, rng)
    log["init"] = st.cost() if not st.unassigned else None
    log["init_unassigned"] = len(st.unassigned)
    written = [None]
    last_write = [0.0]

    def write_if_valid(routes, force=False):
        ok, why = verify(pb, routes)
        if not ok:
            log.setdefault("verify_fail", []).append(why)
            return False
        sol = solution_json(pb, routes)
        if written[0] is None or sol["objective_value"] < written[0] - 1e-9 or force:
            write_json(out_path, sol)
            written[0] = sol["objective_value"]
            last_write[0] = time.monotonic()
        return True

    if not st.unassigned:
        write_if_valid(st.copy_routes())
    log["events"].append([round(time.monotonic() - T_START, 2), log["init"]])
    pending = [None]

    def report(routes, cost):
        log["events"].append([round(time.monotonic() - T_START, 2), cost])
        pending[0] = routes
        now = time.monotonic()
        if written[0] is None or (now - last_write[0] >= 2.0 and now < search_end):
            write_if_valid(routes)
            pending[0] = None

    child, conn = None, None
    if workers >= 2 and hasattr(os, "fork") and pb.n > 1:
        try:
            import multiprocessing as mp
            ctx = mp.get_context("fork")
            conn, child_conn = ctx.Pipe(duplex=False)
            start_routes = st.copy_routes()

            def run_child():
                try:
                    cst = State(pb, start_routes)
                    cs = {}
                    b, bl = alns(pb, cst, seed + 7919, search_end, None, cs)
                    child_conn.send((b, bl, cs))
                except Exception as e:  # noqa: BLE001
                    child_conn.send((None, None, {"error": repr(e)[:300]}))
                finally:
                    child_conn.close()

            child = ctx.Process(target=run_child, daemon=True)
            child.start()
        except Exception as e:  # noqa: BLE001 - one process is fine
            log["fork_error"] = repr(e)[:300]
            child = None
    stats = {}
    best, best_routes = alns(pb, st, seed, search_end, report, stats)
    log["main"] = stats
    cands = []
    if best_routes is not None:
        cands.append(best_routes)
    if pending[0] is not None:
        cands.append(pending[0])
    if child is not None:
        try:
            wait = max(0.2, min(2.0, T_START + time_limit - 3.0 - time.monotonic()))
            if conn.poll(wait):
                cb, cl, cstats = conn.recv()
                log["child"] = cstats
                if cl is not None:
                    cands.append(cl)
            else:
                log["child"] = "no answer in time"
        except Exception as e:  # noqa: BLE001
            log["child_error"] = repr(e)[:300]
        try:
            child.terminate()
        except Exception:  # noqa: BLE001
            pass
    final = None
    for routes in cands:
        ok, _ = verify(pb, routes)
        if ok:
            obj = checker_objective(pb, [s for s in routes if len(s) > 2])
            if final is None or obj < final[0] - 1e-9:
                final = (obj, routes)
    if final is not None and (written[0] is None or final[0] < written[0] - 1e-9):
        write_if_valid(final[1], force=True)
    log["final_objective"] = written[0]
    log["wall_s"] = round(time.monotonic() - T_START, 3)
    return written[0], log


def main(argv=None):
    ap = argparse.ArgumentParser(description="ropke2009 (PDPTW) solver, MV2 of Munim, Inc.")
    ap.add_argument("--problem", default="ropke2009")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    obj, log = solve(inst, a.output, a.time_limit, a.seed, a.workers)
    if os.environ.get("MV2_ROPKE_LOG") == "1":
        try:
            write_json(a.output + ".log.json", log)
        except Exception:  # noqa: BLE001
            pass
    sys.stderr.write(json.dumps({k: log.get(k) for k in ("version", "n", "K", "init", "init_unassigned",
                                                         "final_objective", "wall_s")}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

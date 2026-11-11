"""he2020 (VRPTW with convex node costs, "VRPTW-CNC") solver for the FrontierOR Challenge, v0.1.0.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Rules, as read on 2026-11-11 in the public FrontierOR benchmark's he2020 files (Hugging Face frontieror/FrontierOR,
CC BY 4.0: problem_description.txt, mathematical_formulation.md, gurobi_code.py, feasibility_check.py):
- vertices 0 (start depot), customers 1..n, n+1 (end depot, instance["depot_end"]["id"]); distance_matrix is both
  travel time and routing cost (Euclidean, rounded to one decimal);
- a route is [0, c_1, ..., c_m, n+1]; at most num_vehicles routes; total demand <= vehicle_capacity;
- schedule[c] = service start: t_c in [e_c, l_c], t_next >= t_c + service_c + d(c, next); the first customer can be
  reached no earlier than e_0 + d(0, c_1); the end depot must be reached by l_{n+1};
- objective = sum of d over every arc of every route + sum_c rho * (t_c - preferred_time_c)^2.
rho is read from instance["inconvenience_cost_function"]["rho"] (as gurobi_code.py does), else from a top-level
"inconvenience_cost_factor_rho" (the key the official checker reads, with default 0), else 0.

Method:
- route schedule: for a fixed customer order the best service times solve a separable convex QP on a chain. With
  u_k = t_k - c_k (c_k = the fixed travel + service offset from the first customer) it is isotonic regression of
  y_k = preferred_k - c_k under box bounds [e_k - c_k, l_k - c_k], solved exactly by the pool-adjacent-violators
  algorithm with each block's value = clip(mean, max lower, min upper) (PAVA is exact for separable convex costs,
  Ahuja and Orlin 2001), then verified (and, if rounding ever needs it, repaired forward);
- start: PyVRP (pip package pyvrp, MIT), if installed, on an exact integer copy (all times x10) for distance with the
  fleet limit, plus our own parallel cheapest insertion on the full cost;
- improvement: granular local search on the full cost (relocate, swap, two 2-opt* variants, open a route while
  fewer than num_vehicles are used), then ruin-and-recreate (related removal, cheapest full-cost reinsertion) with a
  shrinking threshold acceptance until the time limit.
Every candidate is re-checked exactly (cover, fleet, capacity, windows, precedence, objective) before it is written.
"""
import json
import math
import os
import random
import sys
import tempfile
import time

import frontier_runtime as R

__version__ = "0.1.0"
FEAS = 1e-9
SCALE = 10


def log(**kw):
    sys.stderr.write("he2020 log " + json.dumps(kw, default=str) + "\n")


def rho_of(data):
    f = data.get("inconvenience_cost_function")
    if isinstance(f, dict) and f.get("rho") is not None:
        return float(f["rho"]), "inconvenience_cost_function.rho"
    if data.get("inconvenience_cost_factor_rho") is not None:
        return float(data["inconvenience_cost_factor_rho"]), "inconvenience_cost_factor_rho"
    return 0.0, "none"


class Inst:
    def __init__(self, data):
        self.n = int(data["num_customers"])
        self.K = int(data["num_vehicles"])
        self.Q = float(data["vehicle_capacity"])
        self.d = [[float(v) for v in row] for row in data["distance_matrix"]]
        self.E = int(data["depot_end"]["id"])
        N = max(self.n + 2, self.E + 1, len(self.d))
        self.N = N
        self.e = [0.0] * N
        self.l = [0.0] * N
        self.q = [0.0] * N
        self.s = [0.0] * N
        self.p = [0.0] * N
        self.e[0], self.l[0] = float(data["depot"]["time_window"][0]), float(data["depot"]["time_window"][1])
        tw = data["depot_end"]["time_window"]
        self.e[self.E], self.l[self.E] = float(tw[0]), float(tw[1])
        default_s = data.get("service_time", 0.0)
        cust = []
        for c in data["customers"]:
            i = int(c["id"])
            self.e[i], self.l[i] = float(c["time_window"][0]), float(c["time_window"][1])
            self.q[i] = float(c["demand"])
            self.s[i] = float(c.get("service_time", default_s))
            pt = c.get("preferred_time")
            self.p[i] = float(pt) if pt is not None else (self.e[i] + self.l[i]) / 2.0
            cust.append(i)
        self.cust = sorted(cust)
        self.rho, self.rho_source = rho_of(data)

    # ---- one route ----------------------------------------------------------------------------------------------
    def _forward(self, r):
        """(dist, offsets, earliest) or None if capacity, a window or the depot return fails."""
        d, e, l, s, q = self.d, self.e, self.l, self.s, self.q
        load = 0.0
        for j in r:
            load += q[j]
        if load > self.Q + FEAS:
            return None
        m = len(r)
        j0 = r[0]
        t = e[0] + d[0][j0]
        if t < e[j0]:
            t = e[j0]
        if t > l[j0] + FEAS:
            return None
        dist = d[0][j0]
        cs = [0.0] * m
        et = [0.0] * m
        et[0] = t
        c = 0.0
        prev = j0
        for k in range(1, m):
            j = r[k]
            dij = d[prev][j]
            step = s[prev] + dij
            dist += dij
            c += step
            cs[k] = c
            t += step
            if t < e[j]:
                t = e[j]
            if t > l[j] + FEAS:
                return None
            et[k] = t
            prev = j
        dE = d[prev][self.E]
        if t + s[prev] + dE > l[self.E] + FEAS:
            return None
        return dist + dE, cs, et

    def _pava(self, r, cs):
        """Best service times for the order r (see module doc), before verification."""
        d, e, l, s, p, E = self.d, self.e, self.l, self.s, self.p, self.E
        m = len(r)
        bs = []
        for k in range(m):
            j = r[k]
            ck = cs[k]
            lo = e[j] - ck
            hi = l[j] - ck
            if k == 0:
                a0 = e[0] + d[0][j]
                if a0 > lo:
                    lo = a0
            if k == m - 1:
                b = l[E] - s[j] - d[j][E] - ck
                if b < hi:
                    hi = b
            sy = p[j] - ck
            cnt = 1
            v = sy
            if v < lo:
                v = lo
            elif v > hi:
                v = hi
            while bs and bs[-1][4] > v:
                bsy, bcnt, blo, bhi, _ = bs.pop()
                sy += bsy
                cnt += bcnt
                if blo > lo:
                    lo = blo
                if bhi < hi:
                    hi = bhi
                v = sy / cnt
                if v < lo:
                    v = lo
                elif v > hi:
                    v = hi
            bs.append((sy, cnt, lo, hi, v))
        t = [0.0] * m
        k = 0
        for b in bs:
            for _ in range(b[1]):
                t[k] = b[4] + cs[k]
                k += 1
        return t

    def _verify_times(self, r, t):
        d, e, l, s, E = self.d, self.e, self.l, self.s, self.E
        m = len(r)
        for k in range(m):
            j = r[k]
            a = e[0] + d[0][j] if k == 0 else t[k - 1] + s[r[k - 1]] + d[r[k - 1]][j]
            lo = e[j] if e[j] > a else a
            if t[k] < lo:
                t[k] = lo
            if t[k] > l[j] + FEAS:
                return False
        j = r[m - 1]
        return t[m - 1] + s[j] + d[j][E] <= l[E] + FEAS

    def eval(self, r, want=False):
        """(dist, inconvenience) or with want (dist, inconvenience, times); None if infeasible; [] costs 0."""
        if not r:
            return (0.0, 0.0, []) if want else (0.0, 0.0)
        f = self._forward(r)
        if f is None:
            return None
        dist, cs, et = f
        rho = self.rho
        if rho <= 0.0:
            return (dist, 0.0, et) if want else (dist, 0.0)
        t = self._pava(r, cs)
        if not self._verify_times(r, t):
            t = et
        p = self.p
        inc = 0.0
        for k in range(len(r)):
            dv = t[k] - p[r[k]]
            inc += dv * dv
        inc *= rho
        return (dist, inc, t) if want else (dist, inc)

    def cost(self, r):
        v = self.eval(r)
        return None if v is None else v[0] + v[1]

    # ---- whole solution -----------------------------------------------------------------------------------------
    def build(self, routes):
        """(solution dict, objective) or (None, reason)."""
        routes = [list(r) for r in routes if r]
        if len(routes) > self.K:
            return None, "fleet %d > %d" % (len(routes), self.K)
        seen = {}
        for r in routes:
            for j in r:
                seen[j] = seen.get(j, 0) + 1
        if sorted(seen) != self.cust or any(v != 1 for v in seen.values()):
            return None, "cover"
        times = {}
        for r in routes:
            ev = self.eval(r, want=True)
            if ev is None:
                return None, "route %s" % (r[:6],)
            for j, tj in zip(r, ev[2]):
                times[j] = float(tj)
        full = [[0] + r + [self.E] for r in routes]
        routing = 0.0
        for route in full:
            for k in range(1, len(route)):
                routing += self.d[route[k - 1]][route[k]]
        sched = {}
        for j in self.cust:
            sched[str(j)] = times[j]
        inconv = 0.0
        for j in self.cust:
            inconv += self.rho * (times[j] - self.p[j]) ** 2
        obj = routing + inconv
        why = self.validate(full, sched)
        if why:
            return None, why
        return {"objective_value": obj, "routes": full, "schedule": sched}, obj

    def validate(self, full, sched):
        d, e, l, s, E = self.d, self.e, self.l, self.s, self.E
        for route in full:
            if route[0] != 0 or route[-1] != E:
                return "ends"
            cs = route[1:-1]
            if sum(self.q[j] for j in cs) > self.Q + FEAS:
                return "capacity"
            t0 = max(e[0], min(l[0], sched[str(cs[0])] - d[0][cs[0]]))
            prev_t, prev = t0, 0
            for j in cs:
                tj = sched[str(j)]
                if tj < e[j] - 1e-7 or tj > l[j] + 1e-7:
                    return "window %d" % j
                if prev_t + s[prev] + d[prev][j] > tj + 1e-7:
                    return "precedence %d" % j
                prev_t, prev = tj, j
            if max(e[E], prev_t + s[prev] + d[prev][E]) > l[E] + 1e-7:
                return "return"
        return None


# ---- neighbourhoods ---------------------------------------------------------------------------------------------------
def neighbours(I, g=15):
    nb = {}
    for i in I.cust:
        others = [j for j in I.cust if j != i]
        others.sort(key=lambda j: I.d[i][j] + I.d[j][i])
        nb[i] = others[:g]
    return nb


def positions(routes):
    where = {}
    for ri, r in enumerate(routes):
        for k, j in enumerate(r):
            where[j] = (ri, k)
    return where


def local_search(I, routes, deadline, rng, nb, stats):
    routes = [list(r) for r in routes if r]
    rc = [I.cost(r) for r in routes]
    if any(c is None for c in rc):
        return None
    improved = True
    while improved:
        improved = False
        order = list(I.cust)
        rng.shuffle(order)
        where = positions(routes)
        for cnt, x in enumerate(order):
            if (cnt & 15) == 0 and time.monotonic() > deadline:
                return routes
            a, ia = where[x]
            A = routes[a]
            A_rem = A[:ia] + A[ia + 1:]
            cA_rem = I.cost(A_rem)
            best = None
            if cA_rem is not None and len(routes) < I.K and len(A) > 1:
                c = I.cost([x])
                if c is not None:
                    delta = cA_rem + c - rc[a]
                    if delta < -1e-9:
                        best = (delta, [(a, A_rem), (None, [x])])
            for y in nb[x]:
                b, ib = where[y]
                if cA_rem is not None:
                    if b == a:
                        iy = A_rem.index(y)
                        for pos in (iy, iy + 1):
                            cand = A_rem[:pos] + [x] + A_rem[pos:]
                            if cand == A:
                                continue
                            c = I.cost(cand)
                            if c is not None:
                                delta = c - rc[a]
                                if delta < -1e-9 and (best is None or delta < best[0]):
                                    best = (delta, [(a, cand)])
                    else:
                        B = routes[b]
                        for pos in (ib, ib + 1):
                            cand = B[:pos] + [x] + B[pos:]
                            c = I.cost(cand)
                            if c is not None:
                                delta = cA_rem + c - rc[a] - rc[b]
                                if delta < -1e-9 and (best is None or delta < best[0]):
                                    best = (delta, [(a, A_rem), (b, cand)])
                if b == a:
                    continue
                B = routes[b]
                A2 = A[:ia] + [y] + A[ia + 1:]
                B2 = B[:ib] + [x] + B[ib + 1:]
                c1 = I.cost(A2)
                if c1 is not None:
                    c2 = I.cost(B2)
                    if c2 is not None:
                        delta = c1 + c2 - rc[a] - rc[b]
                        if delta < -1e-9 and (best is None or delta < best[0]):
                            best = (delta, [(a, A2), (b, B2)])
                for A3, B3 in ((A[:ia + 1] + B[ib:], B[:ib] + A[ia + 1:]),
                               (A[:ia] + B[ib + 1:], B[:ib + 1] + A[ia:])):
                    c1 = I.cost(A3)
                    if c1 is None:
                        continue
                    c2 = I.cost(B3)
                    if c2 is None:
                        continue
                    delta = c1 + c2 - rc[a] - rc[b]
                    if delta < -1e-9 and (best is None or delta < best[0]):
                        best = (delta, [(a, A3), (b, B3)])
            if best is None:
                continue
            for idx, newr in best[1]:
                if idx is None:
                    routes.append(newr)
                    rc.append(I.cost(newr))
                else:
                    routes[idx] = newr
                    rc[idx] = I.cost(newr)
            keep = [k for k in range(len(routes)) if routes[k]]
            routes = [routes[k] for k in keep]
            rc = [rc[k] for k in keep]
            stats["ls_moves"] += 1
            improved = True
            where = positions(routes)
    return routes


def insert_all(I, routes, todo, rng, noise=0.0):
    """Cheapest full-cost insertion of every customer in todo (in order); may open routes up to K. None on failure."""
    routes = [list(r) for r in routes if r]
    rc = [I.cost(r) for r in routes]
    if any(c is None for c in rc):
        return None
    for x in todo:
        best = None
        for ri, r in enumerate(routes):
            base = rc[ri]
            for pos in range(len(r) + 1):
                cand = r[:pos] + [x] + r[pos:]
                c = I.cost(cand)
                if c is None:
                    continue
                delta = c - base
                if noise:
                    delta *= 1.0 + noise * (rng.random() - 0.5)
                if best is None or delta < best[0]:
                    best = (delta, ri, cand, c)
        if len(routes) < I.K:
            c = I.cost([x])
            if c is not None:
                delta = c * (1.0 + noise * (rng.random() - 0.5)) if noise else c
                if best is None or delta < best[0]:
                    best = (delta, None, [x], c)
        if best is None:
            return None
        _, ri, cand, c = best
        if ri is None:
            routes.append(cand)
            rc.append(c)
        else:
            routes[ri] = cand
            rc[ri] = c
    return routes


def construct(I, rng, deadline, tries=20):
    orders = [sorted(I.cust, key=lambda j: (I.l[j] - I.e[j], j)),
              sorted(I.cust, key=lambda j: (-(I.d[0][j] + I.d[j][I.E]), j)),
              sorted(I.cust, key=lambda j: (I.l[j], j))]
    for k in range(tries):
        if time.monotonic() > deadline:
            return None
        if k < len(orders):
            order = orders[k]
        else:
            order = list(I.cust)
            rng.shuffle(order)
        out = insert_all(I, [], order, rng, noise=0.0 if k < len(orders) else 0.2)
        if out is not None:
            return out
    return None


def ruin_recreate(I, routes, rng, nb, kmin, kmax):
    k = rng.randint(kmin, kmax)
    seed = rng.choice(I.cust)
    removed = [seed]
    pool = list(nb[seed])
    while len(removed) < k and pool:
        idx = min(len(pool) - 1, int(rng.random() ** 2 * len(pool)))
        removed.append(pool.pop(idx))
    if rng.random() < 0.3:
        while len(removed) < k:
            x = rng.choice(I.cust)
            if x not in removed:
                removed.append(x)
    rem = set(removed)
    new = [[c for c in r if c not in rem] for r in routes]
    new = [r for r in new if r]
    if any(I.cost(r) is None for r in new):
        return None
    mode = rng.random()
    if mode < 0.4:
        rng.shuffle(removed)
    elif mode < 0.7:
        removed.sort(key=lambda j: I.l[j] - I.e[j])
    else:
        removed.sort(key=lambda j: -(I.d[0][j] + I.d[j][I.E]))
    return insert_all(I, new, removed, rng, noise=0.1 if rng.random() < 0.5 else 0.0)


def total(I, routes):
    s = 0.0
    for r in routes:
        c = I.cost(r)
        if c is None:
            return None
        s += c
    return s


# ---- PyVRP (optional) ---------------------------------------------------------------------------------------------
def _int10(v, up):
    x = v * SCALE
    rx = round(x)
    if abs(x - rx) < 1e-6:
        return int(rx)
    return int(math.ceil(x - 1e-9)) if up else int(math.floor(x + 1e-9))


def vrplib_text(I):
    """Integer VRPLIB copy (times x10; exact when distances have one decimal and windows are integers). Node 0 = start
    depot for departures and the end depot (index n+1) for returns."""
    cust = I.cust
    nodes = [0] + cust
    N = len(nodes)
    lines = ["NAME: frontieror-he2020", "TYPE: VRPTW", "DIMENSION: %d" % N,
             "CAPACITY: %d" % int(math.floor(I.Q + FEAS)), "VEHICLES: %d" % max(1, I.K),
             "EDGE_WEIGHT_TYPE: EXPLICIT", "EDGE_WEIGHT_FORMAT: FULL_MATRIX", "NODE_COORD_SECTION"]
    for i in range(N):
        lines.append("%d 0 0" % (i + 1))
    lines.append("EDGE_WEIGHT_SECTION")
    for a in nodes:
        row = []
        for b in nodes:
            if a == b:
                row.append("0")
            elif b == 0:
                row.append(str(_int10(I.d[a][I.E], True)))
            else:
                row.append(str(_int10(I.d[a][b], True)))
        lines.append(" ".join(row))
    lines.append("DEMAND_SECTION")
    for k, a in enumerate(nodes):
        lines.append("%d %d" % (k + 1, 0 if a == 0 else int(math.ceil(I.q[a] - FEAS))))
    lines.append("SERVICE_TIME_SECTION")
    for k, a in enumerate(nodes):
        lines.append("%d %d" % (k + 1, 0 if a == 0 else _int10(I.s[a], True)))
    lines.append("TIME_WINDOW_SECTION")
    for k, a in enumerate(nodes):
        if a == 0:
            e, l_ = _int10(I.e[0], True), _int10(I.l[I.E], False)
        else:
            e, l_ = _int10(I.e[a], True), _int10(I.l[a], False)
        lines.append("%d %d %d" % (k + 1, e, max(e, l_)))
    lines += ["DEPOT_SECTION", "1", "-1", "EOF"]
    return "\n".join(lines) + "\n"


def pyvrp_routes(I, seconds, seed):
    import pyvrp
    from pyvrp import solve as pv_solve
    from pyvrp.stop import MaxRuntime

    fd, path = tempfile.mkstemp(suffix=".vrp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(vrplib_text(I))
        data = pyvrp.read(path, round_func="none")
    finally:
        os.remove(path)
    res = pv_solve(data, stop=MaxRuntime(max(0.1, seconds)), seed=int(seed) % (2 ** 31), collect_stats=False,
                   display=False)
    if not res.best.is_feasible():
        return None
    raw = [[int(v) for v in r.visits()] for r in res.best.routes()]
    idx_map = [0] + I.cust
    for k in (0, 1):
        try:
            out = [[idx_map[v + k] for v in r] for r in raw]
        except IndexError:
            continue
        flat = sorted(v for r in out for v in r)
        if flat == I.cust:
            return out
    return None


# ---- driver -------------------------------------------------------------------------------------------------------
def solve(inst, clock, inc, args):
    t0 = time.monotonic()
    I = Inst(inst)
    rng = random.Random(getattr(args, "seed", 0) or 0)
    stats = {"offers": 0, "rejected": 0, "ls_moves": 0, "rr_iters": 0, "rr_accept": 0, "rr_fail": 0,
             "pyvrp": None}
    best = {"routes": None, "cost": None}

    def offer(routes, source):
        stats["offers"] += 1
        sol, obj = I.build(routes)
        if sol is None:
            stats["rejected"] += 1
            log(event="invalid-candidate", source=source, why=obj)
            return False
        took = inc.offer(obj, sol, source)
        if took:
            best["routes"], best["cost"] = [list(r) for r in routes if r], obj
            log(event="incumbent", source=source, obj=round(obj, 4), routes=len(sol["routes"]),
                t=round(time.monotonic() - t0, 2))
        return took

    def deadline_in(frac):
        return time.monotonic() + clock.share(frac)

    info = {"version": __version__, "n": I.n, "K": I.K, "Q": I.Q, "rho": I.rho, "rho_source": I.rho_source}
    log(event="start", **info)
    nb = neighbours(I)
    if I.n <= I.K:
        offer([[c] for c in I.cust], "singletons")
    starts = []
    own = construct(I, rng, deadline_in(0.1))
    if own is not None:
        offer(own, "insertion")
        starts.append(("insertion", own))
    try:
        import pyvrp  # noqa: F401
        have_pyvrp = True
    except Exception:  # noqa: BLE001
        have_pyvrp = False
    if have_pyvrp:
        try:
            pv = pyvrp_routes(I, clock.share(0.25), rng.randrange(1 << 30))
            stats["pyvrp"] = "ok" if pv is not None else "no-feasible"
            if pv is not None:
                offer(pv, "pyvrp")
                starts.append(("pyvrp", pv))
        except Exception as e:  # noqa: BLE001
            stats["pyvrp"] = "error " + repr(e)[:200]
    else:
        stats["pyvrp"] = "missing"
    if not starts:
        log(event="no-start", **stats)
        return
    cur = None
    for name, routes in starts:
        ls = local_search(I, routes, deadline_in(0.2), rng, nb, stats)
        if ls is not None:
            offer(ls, name + "+ls")
            c = total(I, ls)
            if c is not None and (cur is None or c < cur[0]):
                cur = (c, ls)
    if cur is None:
        cur = (total(I, starts[0][1]), starts[0][1])
    end = time.monotonic() + clock.remaining()
    begin = time.monotonic()
    kmin = max(2, I.n // 25)
    kmax = max(kmin + 1, min(40, I.n // 6))
    while time.monotonic() < end - 0.05:
        stats["rr_iters"] += 1
        cand = ruin_recreate(I, cur[1], rng, nb, kmin, kmax)
        if cand is None:
            stats["rr_fail"] += 1
            continue
        cand = local_search(I, cand, end, rng, nb, stats)
        if cand is None:
            stats["rr_fail"] += 1
            continue
        c = total(I, cand)
        if c is None:
            stats["rr_fail"] += 1
            continue
        frac = (time.monotonic() - begin) / max(1e-6, end - begin)
        thr = 0.01 * max(0.0, 1.0 - frac) * abs(best["cost"] if best["cost"] is not None else c)
        if c < cur[0] - 1e-9 or c < cur[0] + thr * rng.random():
            cur = (c, cand)
            stats["rr_accept"] += 1
        if best["cost"] is None or c < best["cost"] - 1e-9:
            offer(cand, "ruin-recreate")
        if best["routes"] is not None and rng.random() < 0.02:
            cur = (best["cost"], [list(r) for r in best["routes"]])
    info.update(stats, best=best["cost"], time=round(time.monotonic() - t0, 2))
    log(event="final", **info)


if __name__ == "__main__":
    R.main(solve, "min")

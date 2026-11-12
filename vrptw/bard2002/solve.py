"""bard2002 (VRPTW, minimise the number of vehicles) solver for the FrontierOR Challenge, v0.1.0.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Rules, as read on 2026-11-11 in the public FrontierOR benchmark's bard2002 files (Hugging Face frontieror/FrontierOR,
CC BY 4.0: problem_description.txt, mathematical_formulation.md, gurobi_code.py, feasibility_check.py):
- node 0 = depot, customers 1..n in list order; raw distance = instance distance_matrix if given, else the Euclidean
  distance truncated to one decimal;
- travel time tau_ij = raw_ij (+ service_i unless travel_time_includes_service_time is true); if a_j - b_i > tau_ij
  then tau_ij = a_j - b_i;
- t_i in [a_i, b_i] for customers and t_j >= t_i + tau_ij on every customer-customer arc; so t behaves like a
  service start time;
- loads y_i in [q_i, Q], y_j >= y_i + q_j on every customer-customer arc, AND (constraint (5) with x_ij = 0, as the
  checker implements it) y_j >= y_i + 2 q_j - Q for EVERY other ordered pair of customers. That second family is a
  big-M of Q - q_j instead of Q, and it is binding: a route r = (c_1..c_k) only admits loads if
  max_m (q_{c_m} + q_{c_m} + ... + q_{c_k}) <= Q for m < k (a positive cycle otherwise), which is stricter than
  plain capacity. The solver enforces this rule (conservatively, also for m = k when no demand exceeds Q / 2) and
  writes the least load witness y found by longest-path relaxation;
- objective = number of routes leaving the depot; num_vehicles = len(routes); total_distance = raw distance of the
  routes rounded to 0.1.
The checker does not test the time to reach the first customer from the depot or to get back to it. This solver
does not use that gap: every route also leaves the depot no earlier than its ready time and returns by its due date.

Pipeline: lower bound (capacity, and a greedy clique of customers that cannot share a route); cheapest insertion;
route elimination with an ejection pool (after Nagata and Braysy 2009, simplified: insert, else eject one or two
customers chosen by visit-failure counters, plus random relocations); optionally PyVRP (pip package pyvrp, MIT) asked
for one vehicle fewer than the incumbent on a conservatively rounded integer copy, every result re-checked exactly.
Stops early only when the capacity bound is reached (the clique bound is reported, not trusted).
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
TOL = 1e-7
SCALE = 100


def log(**kw):
    sys.stderr.write("bard log " + json.dumps(kw, default=str) + "\n")


class Inst:
    def __init__(self, data, strict=True):
        depot = data["depot"]
        nodes = [depot] + list(data["customers"])
        self.N = len(nodes)
        self.n = self.N - 1
        self.Q = float(data["vehicle_capacity"])
        self.a = [float(v["ready_time"]) for v in nodes]
        self.b = [float(v["due_date"]) for v in nodes]
        self.q = [float(v["demand"]) for v in nodes]
        self.s = [float(v["service_time"]) for v in nodes]
        N = self.N
        dm = data.get("distance_matrix")
        if dm:
            raw = [[float(v) for v in row] for row in dm]
        else:
            xs = [float(v["x"]) for v in nodes]
            ys = [float(v["y"]) for v in nodes]
            raw = [[0.0] * N for _ in range(N)]
            for i in range(N):
                for j in range(N):
                    if i != j:
                        d = math.sqrt((xs[i] - xs[j]) ** 2 + (ys[i] - ys[j]) ** 2)
                        raw[i][j] = math.floor(d * 10) / 10.0
        self.raw = raw
        fold = data.get("travel_time_includes_service_time", False)
        self.fold = bool(fold)
        tau = [[0.0] * N for _ in range(N)]
        for i in range(N):
            for j in range(N):
                if i == j:
                    continue
                t = raw[i][j]
                if not fold:
                    t += self.s[i]
                if (self.a[j] - self.b[i]) > t:
                    t = self.a[j] - self.b[i]
                tau[i][j] = t
        self.tau = tau
        self.strict = strict
        self.cust = list(range(1, N))
        self.big = any(2.0 * self.q[j] > self.Q + TOL for j in self.cust)

    # ---- single-route tests -------------------------------------------------------------------------------------
    def sched(self, r):
        """Earliest start times along r, or None if a window (or the depot return, when strict) is missed."""
        tau, a, b = self.tau, self.a, self.b
        t = a[0]
        prev = 0
        out = []
        for k, j in enumerate(r):
            if k == 0 and not self.strict:
                t = a[j]
            else:
                t = t + tau[prev][j]
                if t < a[j]:
                    t = a[j]
            if t > b[j] + TOL:
                return None
            out.append(t)
            prev = j
        if self.strict and r and t + tau[prev][0] > b[0] + TOL:
            return None
        return out

    def cap_ok(self, r):
        """Exact single-route load rule (see module doc): load <= Q and q_m + suffix_m <= Q for every m < k."""
        q = self.q
        s = 0.0
        h = 0.0
        last = len(r) - 1
        for idx in range(last, -1, -1):
            j = r[idx]
            s += q[j]
            if (idx < last or not self.big) and s + q[j] > h:
                h = s + q[j]
        return s <= self.Q + TOL and h <= self.Q + TOL

    def route_ok(self, r):
        return self.cap_ok(r) and self.sched(r) is not None

    def dist(self, r):
        raw = self.raw
        seq = [0] + list(r) + [0]
        return sum(float(raw[seq[p]][seq[p + 1]]) for p in range(len(seq) - 1))

    # ---- whole solution ----------------------------------------------------------------------------------------
    def witness(self, routes):
        """Least loads y satisfying every load constraint the checker tests, or None (positive cycle / y > Q)."""
        q, Q = self.q, self.Q
        y = [0.0] * self.N
        for r in routes:
            acc = 0.0
            for j in r:
                acc += q[j]
                y[j] = acc
        for _ in range(2 * self.N + 5):
            m1, m1i, m2 = -1e300, -1, -1e300
            for j in self.cust:
                if y[j] > m1:
                    m2, m1, m1i = m1, y[j], j
                elif y[j] > m2:
                    m2 = y[j]
            changed = False
            for r in routes:
                prev = None
                for j in r:
                    other = m2 if j == m1i else m1
                    v = q[j]
                    w = other + 2.0 * q[j] - Q
                    if w > v:
                        v = w
                    if prev is not None and y[prev] + q[j] > v:
                        v = y[prev] + q[j]
                    if v > y[j] + 1e-9:
                        y[j] = v
                        changed = True
                    prev = j
            if not changed:
                break
        else:
            return None
        for j in self.cust:
            if y[j] > Q + 1e-9:
                return None
        return y

    def validate(self, routes, t, y):
        """The checker's constraints (2)-(7) on our own witnesses, with a tighter tolerance than its 1e-5."""
        seen = [0] * self.N
        for r in routes:
            for j in r:
                seen[j] += 1
        if any(seen[j] != 1 for j in self.cust):
            return "cover"
        q, Q, a, b, tau = self.q, self.Q, self.a, self.b, self.tau
        for j in self.cust:
            if t[j] < a[j] - 1e-9 or t[j] > b[j] + 1e-9:
                return "window %d" % j
            if y[j] < q[j] - 1e-9 or y[j] > Q + 1e-9:
                return "load bounds %d" % j
        for r in routes:
            for i, j in zip(r, r[1:]):
                if t[j] < t[i] + tau[i][j] - 1e-9:
                    return "time link %d-%d" % (i, j)
                if y[j] < y[i] + q[j] - 1e-9:
                    return "load link %d-%d" % (i, j)
        m1, m1i, m2 = -1e300, -1, -1e300
        for j in self.cust:
            if y[j] > m1:
                m2, m1, m1i = m1, y[j], j
            elif y[j] > m2:
                m2 = y[j]
        for j in self.cust:
            other = m2 if j == m1i else m1
            if y[j] < other + 2.0 * q[j] - Q - 1e-9:
                return "load pair %d" % j
        return None

    def build(self, routes):
        routes = [list(r) for r in routes if r]
        t = [0.0] * self.N
        for r in routes:
            st = self.sched(r)
            if st is None:
                return None, "schedule"
            for j, v in zip(r, st):
                t[j] = v
        y = self.witness(routes)
        if y is None:
            return None, "loads"
        why = self.validate(routes, t, y)
        if why:
            return None, why
        full = [[0] + r + [0] for r in routes]
        raw = self.raw
        dist = round(sum(float(raw[route[p]][route[p + 1]]) for route in full for p in range(len(route) - 1)), 1)
        nv = len(full)
        sol = {"objective_value": nv, "num_vehicles": nv, "routes": full, "total_distance": dist,
               "departure_times": {str(j): t[j] for r in routes for j in r},
               "loads": {str(j): y[j] for r in routes for j in r}}
        return sol, dist


class Route:
    """A route with cached earliest/latest start times and load-rule terms for O(1) insertion tests."""
    __slots__ = ("I", "c", "E", "L", "suf", "pre", "post")

    def __init__(self, I, c):
        self.I = I
        self.c = list(c)
        self.refresh()

    def refresh(self):
        I, c = self.I, self.c
        k = len(c)
        tau, a, b, q = I.tau, I.a, I.b, I.q
        E = [0.0] * k
        t = a[0]
        prev = 0
        for m, j in enumerate(c):
            if m == 0 and not I.strict:
                t = a[j]
            else:
                t = t + tau[prev][j]
                if t < a[j]:
                    t = a[j]
            E[m] = t
            prev = j
        L = [0.0] * k
        nxt = None
        for m in range(k - 1, -1, -1):
            j = c[m]
            if nxt is None:
                lim = b[0] - tau[j][0] if I.strict else b[j]
            else:
                lim = L[m + 1] - tau[j][nxt]
            L[m] = min(b[j], lim)
            nxt = j
        suf = [0.0] * (k + 1)
        for m in range(k - 1, -1, -1):
            suf[m] = suf[m + 1] + q[c[m]]
        g = [q[c[m]] + suf[m] for m in range(k)]
        pre = [-1e300] * (k + 1)
        for m in range(k):
            pre[m + 1] = max(pre[m], g[m])
        post = [-1e300] * (k + 1)
        for m in range(k - 1, -1, -1):
            post[m] = max(post[m + 1], g[m])
        self.E, self.L, self.suf, self.pre, self.post = E, L, suf, pre, post

    def ok(self):
        """Feasible as it stands? (Removing a customer can break a window: truncated distances are not exactly
        triangular.)"""
        if any(self.E[m] > self.L[m] + TOL for m in range(len(self.c))):
            return False
        return self.I.cap_ok(self.c)

    def can_insert(self, x, p):
        """Can customer x go at position p (0..k)? Conservative load rule; exact when the instance has no big demand."""
        I = self.I
        q, Q = I.q, I.Q
        qx = q[x]
        if I.big:
            cand = self.c[:p] + [x] + self.c[p:]
            return I.route_ok(cand)
        if self.pre[p] + qx > Q + TOL or 2.0 * qx + self.suf[p] > Q + TOL or self.post[p] > Q + TOL:
            return False
        tau, a, b = I.tau, I.a, I.b
        c = self.c
        k = len(c)
        if p == 0:
            if I.strict:
                ex = a[0] + tau[0][x]
                if ex < a[x]:
                    ex = a[x]
            else:
                ex = a[x]
        else:
            ex = self.E[p - 1] + tau[c[p - 1]][x]
            if ex < a[x]:
                ex = a[x]
        if ex > b[x] + TOL:
            return False
        if p == k:
            return (not I.strict) or ex + tau[x][0] <= b[0] + TOL
        return ex + tau[x][c[p]] <= self.L[p] + TOL

    def insert_cost(self, x, p):
        raw = self.I.raw
        c = self.c
        u = c[p - 1] if p > 0 else 0
        v = c[p] if p < len(c) else 0
        return raw[u][x] + raw[x][v] - raw[u][v]


def best_insert(routes, x, rng=None):
    best = None
    for ri, r in enumerate(routes):
        for p in range(len(r.c) + 1):
            if r.can_insert(x, p):
                cst = r.insert_cost(x, p)
                if rng is not None:
                    cst += rng.random() * 1e-6
                if best is None or cst < best[0]:
                    best = (cst, ri, p)
    return best


def best_eject(I, routes, x, pen, rng, deadline, allow_two=True):
    """Insert x into some route while ejecting one (or two) customers; minimise the ejected penalty sum."""
    best = None
    for ri, r in enumerate(routes):
        c = r.c
        k = len(c)
        order = sorted(range(k), key=lambda m: (pen[c[m]], rng.random()))
        for m in order:
            if best is not None and pen[c[m]] >= best[0]:
                break
            rest = Route(I, c[:m] + c[m + 1:])
            if not rest.ok():
                continue
            for p in range(len(rest.c) + 1):
                if rest.can_insert(x, p):
                    best = (pen[c[m]], rng.random(), ri, rest.c[:p] + [x] + rest.c[p:], [c[m]])
                    break
        if time.monotonic() > deadline:
            return best
    if best is not None or not allow_two:
        return best
    for ri, r in enumerate(routes):
        c = r.c
        k = len(c)
        if k < 2 or k > 25:
            continue
        for m1 in range(k):
            for m2 in range(m1 + 1, k):
                sc = pen[c[m1]] + pen[c[m2]]
                if best is not None and sc >= best[0]:
                    continue
                rest = Route(I, [c[j] for j in range(k) if j != m1 and j != m2])
                if not rest.ok():
                    continue
                for p in range(len(rest.c) + 1):
                    if rest.can_insert(x, p):
                        best = (sc, rng.random(), ri, rest.c[:p] + [x] + rest.c[p:], [c[m1], c[m2]])
                        break
            if time.monotonic() > deadline:
                return best
    return best


def perturb(I, routes, rng, moves):
    """Random feasible relocations; a route emptied on the way is dropped."""
    for _ in range(moves):
        if len(routes) < 2:
            return
        ri = rng.randrange(len(routes))
        r = routes[ri]
        if not r.c:
            continue
        m = rng.randrange(len(r.c))
        x = r.c[m]
        rem = r.c[:m] + r.c[m + 1:]
        if rem and I.sched(rem) is None:
            continue
        best = None
        for rj, other in enumerate(routes):
            if rj == ri:
                continue
            for p in range(len(other.c) + 1):
                if other.can_insert(x, p):
                    cst = other.insert_cost(x, p) + rng.random()
                    if best is None or cst < best[0]:
                        best = (cst, rj, p)
        if best is None:
            continue
        _, rj, p = best
        routes[rj].c.insert(p, x)
        routes[rj].refresh()
        del r.c[m]
        if r.c:
            r.refresh()
        else:
            del routes[ri]


def ep_loop(I, routes, ep, deadline, rng, stats, max_iter=100000):
    """Empty the ejection pool ep into routes (list of Route) without opening a route. True on success."""
    pen = [0] * I.N
    it = 0
    while ep:
        it += 1
        if it > max_iter or time.monotonic() > deadline:
            return False
        x = ep.pop()
        ins = best_insert(routes, x, rng)
        if ins is not None:
            _, ri, p = ins
            routes[ri].c.insert(p, x)
            routes[ri].refresh()
            continue
        pen[x] += 1
        ej = best_eject(I, routes, x, pen, rng, deadline)
        stats["ejections"] += 1
        if ej is None:
            return False
        _, _, ri, newc, out = ej
        routes[ri].c = newc
        routes[ri].refresh()
        ep.extend(out)
        perturb(I, routes, rng, max(2, I.n // 20))
    return True


def eliminate(I, cur, deadline, rng, stats):
    """Try to remove one route from cur (list of lists). Returns the new list of lists or None."""
    sizes = sorted(range(len(cur)), key=lambda i: (len(cur[i]), rng.random()))
    pick = sizes[rng.randrange(min(3, len(sizes)))]
    routes = [Route(I, r) for i, r in enumerate(cur) if i != pick]
    ep = sorted(cur[pick], key=lambda j: (I.b[j] - I.a[j], rng.random()), reverse=True)
    ok = ep_loop(I, routes, ep, deadline, rng, stats)
    if not ok:
        return None
    return [r.c[:] for r in routes if r.c]


def repair(I, cur, deadline, rng, stats):
    """Make a solution with the same number of routes valid under the exact rules, or None."""
    routes = []
    ep = []
    for r in cur:
        r = list(r)
        while r and not I.route_ok(r):
            m = max(range(len(r)), key=lambda k: (I.q[r[k]], rng.random()))
            ep.append(r.pop(m))
        routes.append(Route(I, r))
    if not ep:
        return [x.c[:] for x in routes if x.c]
    if not ep_loop(I, routes, ep, deadline, rng, stats):
        return None
    return [x.c[:] for x in routes if x.c]


def insertion(I, deadline):
    left = set(I.cust)
    out = []
    while left:
        if time.monotonic() > deadline:
            out.extend([c] for c in sorted(left))
            break
        seed = max(left, key=lambda c: (I.tau[0][c], -I.b[c], c))
        r = Route(I, [seed])
        left.discard(seed)
        while left:
            best = None
            for x in left:
                for p in range(len(r.c) + 1):
                    if r.can_insert(x, p):
                        cst = r.insert_cost(x, p)
                        if best is None or cst < best[0]:
                            best = (cst, x, p)
            if best is None:
                break
            _, x, p = best
            r.c.insert(p, x)
            r.refresh()
            left.discard(x)
        out.append(r.c[:])
    return out


def lower_bound(I, deadline, rng):
    lb_cap = int(math.ceil(sum(I.q[j] for j in I.cust) / I.Q - 1e-9)) if I.Q > 0 else 1
    cust = I.cust
    inc = {j: set() for j in cust}
    for ii, i in enumerate(cust):
        for j in cust[ii + 1:]:
            if not (I.route_ok([i, j]) or I.route_ok([j, i])):
                inc[i].add(j)
                inc[j].add(i)
        if time.monotonic() > deadline:
            return {"lb": max(1, lb_cap), "lb_cap": lb_cap, "lb_clique": None}
    best = 1 if cust else 0
    tries = 0
    while tries < 200 and time.monotonic() < deadline:
        tries += 1
        order = sorted(cust, key=lambda j: (-len(inc[j]) + (rng.random() * 3 if tries > 1 else 0)))
        clique = []
        for j in order:
            if all(j in inc[k] for k in clique):
                clique.append(j)
        best = max(best, len(clique))
    return {"lb": max(lb_cap, best, 1 if cust else 0), "lb_cap": lb_cap, "lb_clique": best}


# ---- PyVRP (optional) ---------------------------------------------------------------------------------------------
def vrplib_text(I, vehicles):
    """Integer VRPLIB copy: tau (service already inside) rounded up, windows rounded inwards, service 0."""
    N = I.N
    lines = ["NAME: frontieror-bard2002", "TYPE: VRPTW", "DIMENSION: %d" % N,
             "CAPACITY: %d" % int(math.floor(I.Q + TOL)), "VEHICLES: %d" % max(1, vehicles),
             "EDGE_WEIGHT_TYPE: EXPLICIT", "EDGE_WEIGHT_FORMAT: FULL_MATRIX", "NODE_COORD_SECTION"]
    for i in range(N):
        lines.append("%d 0 0" % (i + 1))
    lines.append("EDGE_WEIGHT_SECTION")
    for i in range(N):
        lines.append(" ".join("0" if i == j else str(int(math.ceil(I.tau[i][j] * SCALE - 1e-6))) for j in range(N)))
    lines.append("DEMAND_SECTION")
    for i in range(N):
        lines.append("%d %d" % (i + 1, 0 if i == 0 else int(math.ceil(I.q[i] - TOL))))
    lines.append("SERVICE_TIME_SECTION")
    for i in range(N):
        lines.append("%d 0" % (i + 1))
    lines.append("TIME_WINDOW_SECTION")
    for i in range(N):
        e = int(math.ceil(I.a[i] * SCALE - 1e-6))
        l_ = int(math.floor(I.b[i] * SCALE + 1e-6))
        lines.append("%d %d %d" % (i + 1, e, max(e, l_)))
    lines += ["DEPOT_SECTION", "1", "-1", "EOF"]
    return "\n".join(lines) + "\n"


def pyvrp_try(I, vehicles, seconds, seed):
    import pyvrp
    from pyvrp import solve as pv_solve
    from pyvrp.stop import MaxRuntime

    fd, path = tempfile.mkstemp(suffix=".vrp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(vrplib_text(I, vehicles))
        data = pyvrp.read(path, round_func="none")
    finally:
        os.remove(path)
    res = pv_solve(data, stop=MaxRuntime(max(0.1, seconds)), seed=int(seed) % (2 ** 31), collect_stats=False,
                   display=False)
    if not res.best.is_feasible():
        return None
    raw = [[int(v) for v in r.visits()] for r in res.best.routes()]
    for k in (0, 1):
        out = [[v + k for v in r] for r in raw]
        flat = sorted(v for r in out for v in r)
        if flat == I.cust:
            return out
    return None


# ---- driver ---------------------------------------------------------------------------------------------------------
def solve(inst, clock, inc, args):
    t0 = time.monotonic()
    I = Inst(inst, strict=True)
    rng = random.Random(getattr(args, "seed", 0) or 0)
    stats = {"offers": 0, "rejected": 0, "ejections": 0, "elim_ok": 0, "elim_fail": 0, "pyvrp_ok": 0,
             "pyvrp_fail": 0, "repairs": 0}
    best = {"routes": None, "n": None}

    def offer(routes, source):
        stats["offers"] += 1
        routes = [list(r) for r in routes if r]
        sol, dist = I.build(routes)
        if sol is None:
            stats["rejected"] += 1
            log(event="invalid-candidate", source=source, why=dist)
            return False
        took = inc.offer(len(routes) + dist * 1e-7, sol, source)
        if took:
            best["routes"], best["n"] = routes, len(routes)
            log(event="incumbent", source=source, routes=len(routes), dist=dist, t=round(time.monotonic() - t0, 2))
        return took

    info = {"version": __version__, "n_customers": I.n, "Q": I.Q, "fold": I.fold, "big_demand": I.big}
    singles = [[c] for c in I.cust if I.route_ok([c])]
    if len(singles) != I.n:
        bad = [c for c in I.cust if not I.route_ok([c])]
        info["unservable_alone"] = bad[:20]
        I.strict = False
        log(event="strict-off", unservable=len(bad))
        singles = [[c] for c in I.cust]
    offer(singles, "singletons")
    lbi = lower_bound(I, time.monotonic() + clock.share(0.05), rng)
    info.update(lbi)
    # Only the capacity bound is certain; the clique bound uses pairwise tests on truncated distances, so it is
    # reported but never used to stop.
    stop_at = max(1, lbi["lb_cap"])
    offer(insertion(I, time.monotonic() + clock.share(0.15)), "insertion")

    def elim_until(deadline):
        while best["n"] is not None and best["n"] > stop_at and time.monotonic() < deadline - 0.05:
            left = deadline - time.monotonic()
            slot = time.monotonic() + max(0.5, min(left, max(2.0, left / 3.0)))
            new = eliminate(I, best["routes"], min(deadline, slot), rng, stats)
            if new is None:
                stats["elim_fail"] += 1
                continue
            stats["elim_ok"] += 1
            offer(new, "eliminate")

    try:
        import pyvrp  # noqa: F401
        have_pyvrp = True
    except Exception:  # noqa: BLE001
        have_pyvrp = False
    info["pyvrp"] = have_pyvrp
    if have_pyvrp:
        elim_until(time.monotonic() + clock.share(0.45))
        stop_pv = time.monotonic() + clock.share(0.6)
        while best["n"] > stop_at and time.monotonic() < stop_pv - 0.5:
            left = stop_pv - time.monotonic()
            try:
                out = pyvrp_try(I, best["n"] - 1, left * 0.6, rng.randrange(1 << 30))
            except Exception as e:  # noqa: BLE001
                info["pyvrp_error"] = repr(e)[:300]
                break
            if out is None:
                stats["pyvrp_fail"] += 1
                break
            if not offer(out, "pyvrp"):
                stats["repairs"] += 1
                fixed = repair(I, out, time.monotonic() + max(0.5, left * 0.3), rng, stats)
                if fixed is None or not offer(fixed, "pyvrp-repair"):
                    stats["pyvrp_fail"] += 1
                    break
            stats["pyvrp_ok"] += 1
    elim_until(time.monotonic() + clock.remaining())
    info.update(stats, best_routes=best["n"], strict=I.strict, time=round(time.monotonic() - t0, 2))
    log(event="final", **info)


if __name__ == "__main__":
    R.main(solve, "min")

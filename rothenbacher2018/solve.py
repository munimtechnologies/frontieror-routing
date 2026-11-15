"""MV2 truck-and-trailer engine v0.1.1 for FrontierOR task rothenbacher2018 (standard library only).

The truck-and-trailer routing problem with time windows (Rothenbaecher, Drexl and Irnich, Transportation Science
2018): a heterogeneous fleet of trucks, each used solo or with a trailer (a "complete vehicle"), collects supply from
truck customers (reachable only by a truck without its trailer) and trailer customers. A complete vehicle may park
its trailer at a trailer customer or a transshipment location, serve a subtour with the truck alone, and come back
to couple. Minimise fixed truck costs + distance costs (towing surcharge while the trailer is attached) + handling.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python solve.py --problem rothenbacher2018 --instance in.json --output out.json --time-limit 60 [--seed 1]

Rules, read on 2026-11-14/15 in the public FrontierOR rothenbacher2018 files (Hugging Face frontieror/FrontierOR,
CC BY 4.0: problem_description.txt, gurobi_code.py, feasibility_check.py):
- the answer is written in the benchmark's own ("gurobi") format: route_sequence uses expanded node ids, where the
  decouple copy of parking location P[i] is n_orig + i and the couple copy is n_orig + len(P) + i, P = sorted(trailer
  customers + transshipment locations), n_orig = len(distance_matrix); route_sequence_physical maps them back;
- the official checker reads service start times from arrival_times (keys = route_sequence ids) and checks customer
  time windows (customers' optional "time_window", not in the published schema) and the planning horizon;
- loading as the checker simulates it: with the trailer attached, supply goes to the trailer first and the overflow
  to the truck; with the trailer parked, everything goes to the truck; coupling moves as much as fits into the
  trailer; truck <= truck capacity and trailer <= trailer capacity at every step;
- cost exactly as the checker recomputes it: an arc (i, j) of route_sequence is charged cost_factor + towing
  multiplier when the class has a trailer, i is the depot, a trailer customer or a couple copy, and j is the depot, a
  trailer customer or a decouple copy; otherwise cost_factor. Plus the truck's fixed cost and one decoupling and one
  coupling cost per parking. (So a trailer-customer to trailer-customer arc inside a subtour is charged the towing
  surcharge, as in the benchmark's own model.)
Conservative choices, so every answer is also a feasible point of the benchmark's own MIP (gurobi_code.py): at most
one parking per route, no class used more often than its num_available, and at a decouple/couple copy of a trailer
customer the customer's time window and service time apply as they do in that model (STRICT = True).

Method: a route is (class, main tour, optional parking p at main position pos, subtour). The search keeps every
route's expanded node list with earliest departures, latest feasible arrivals and load prefixes, so inserting a
customer (into the main tour, into the subtour, or as a new subtour with its own parking) is tested and priced in
O(1). Slack induction by string removals (SISR) with simulated annealing, plus route removal, vehicle class changes
and re-parking moves. Every written solution passes verify(), a mirror of the official checker.

v0.1.1 (2026-11-15): v0.1.0 could not turn two solo trucks into one complete vehicle. Greedy reinsertion always
opened the class with the cheapest one-customer route (a small solo truck), and a class change to a complete vehicle
was only tried for routes holding trailer customers alone. On the tiny public instance it never improved on its
first construction (0 improvements in 777,512 iterations; 15% above Gurobi's optimum). New: a "pair" move empties
two nearby routes and rebuilds them, and reinsertion can run in "big" mode, where a new route is always opened with
the largest-capacity class that is still available. Half of the constructions also use big mode.
"""
import argparse
import json
import math
import os
import random
import sys
import time

VERSION = "0.1.1"
INF = float("inf")
EPS = 1e-7
STRICT = True
NEAR_PARK = 5
D_, NH_, NL_, DC_, CP_ = 0, 1, 2, 3, 4
TOW_SRC = (D_, NH_, CP_)
TOW_TGT = (D_, NH_, DC_)


class VClass:
    __slots__ = ("cid", "truck", "trailer", "cv", "QL", "QH", "fixed", "cf", "tw", "avail", "fac")


class Problem:
    def __init__(self, inst, strict=STRICT, near_park=NEAR_PARK):
        par = inst["parameters"]
        hz = par.get("planning_horizon") or [0.0, INF]
        self.H0, self.H1 = float(hz[0]), float(hz[1])
        md = par.get("max_route_duration")
        self.end_lim = self.H1
        if md is not None and self.H0 + float(md) < self.end_lim:
            self.end_lim = self.H0 + float(md)
        self.dc_t = float(par.get("decoupling_time", 0) or 0)
        self.cp_t = float(par.get("coupling_time", 0) or 0)
        self.dc_c = float(par.get("decoupling_cost", 0) or 0)
        self.cp_c = float(par.get("coupling_cost", 0) or 0)
        svc0 = float(par.get("service_time", 0) or 0)
        self.d = [[float(v) for v in row] for row in inst["distance_matrix"]]
        self.tt = [[float(v) for v in row] for row in inst["travel_time_matrix"]]
        n0 = self.n_orig = len(self.d)
        self.depot = int(inst["depot"]["id"])
        self.is_nh = [False] * n0
        self.is_cust = [False] * n0
        self.q = [0.0] * n0
        self.svc = [0.0] * n0
        self.e = [-INF] * n0
        self.l = [INF] * n0
        self.NL, self.NH = [], []
        for grp, nh in ((inst.get("truck_customers") or [], False), (inst.get("trailer_customers") or [], True)):
            for c in grp:
                i = int(c["id"])
                self.is_cust[i] = True
                self.is_nh[i] = nh
                (self.NH if nh else self.NL).append(i)
                self.q[i] = float(c.get("supply", 0) or 0)
                self.svc[i] = float(c.get("service_time", svc0))
                tw = c.get("time_window")
                if tw is not None and len(tw) == 2:
                    self.e[i], self.l[i] = float(tw[0]), float(tw[1])
        self.cust = sorted(self.NL + self.NH)
        self.T = [int(t["id"]) for t in inst.get("transshipment_locations") or []]
        self.park = sorted(set(self.NH) | set(self.T))
        npk = len(self.park)
        self.dp_id = {p: n0 + i for i, p in enumerate(self.park)}
        self.cp_id = {p: n0 + npk + i for i, p in enumerate(self.park)}
        self.strict = strict
        # time window and handling time of the decouple / couple copies of each parking location
        self.dce, self.dcl, self.dch, self.cpe, self.cpl, self.cph = {}, {}, {}, {}, {}, {}
        for p in self.park:
            if strict and self.is_cust[p]:
                self.dce[p], self.dcl[p], self.dch[p] = self.e[p], self.l[p], self.dc_t + self.svc[p]
                self.cpe[p], self.cpl[p], self.cph[p] = self.e[p], self.l[p], self.cp_t + self.svc[p]
            else:
                self.dce[p], self.dcl[p], self.dch[p] = -INF, INF, self.dc_t
                self.cpe[p], self.cpl[p], self.cph[p] = -INF, INF, self.cp_t
        fleet = inst["fleet"]
        self.truck_avail = {t["id"]: int(t.get("num_available", 0)) for t in fleet.get("truck_types") or []}
        self.trailer_avail = {t["id"]: int(t.get("num_available", 0)) for t in fleet.get("trailer_types") or []}
        self.classes = []
        for vc in fleet["vehicle_classes"]:
            c = VClass()
            c.cid = vc["class_id"]
            c.truck = vc["truck_type_id"]
            c.trailer = vc.get("trailer_type_id", 0) or 0
            c.cv = c.trailer != 0
            c.QL = float(vc["truck_capacity"])
            c.QH = float(vc.get("trailer_capacity", 0) or 0) if c.cv else 0.0
            c.fixed = float(vc.get("truck_fixed_cost", 0) or 0)
            c.cf = float(vc.get("truck_cost_factor", 0) or 0)
            c.tw = float(vc.get("trailer_towing_cost_multiplier", 0) or 0) if c.cv else 0.0
            na = vc.get("num_available")
            c.avail = int(na) if na is not None else 10 ** 9
            c.fac = [[c.cf + (c.tw if (c.cv and a in TOW_SRC and b in TOW_TGT) else 0.0) for b in range(5)]
                     for a in range(5)]
            self.classes.append(c)
        k = len(self.park) if near_park is None else min(len(self.park), near_park)
        self.near_park = {}
        self.nbr = {}
        for u in self.cust:
            ps = sorted(self.park, key=lambda p: (self.d[u][p] + self.d[p][u], p))
            self.near_park[u] = ps[:k]
            o = [v for v in self.cust if v != u]
            o.sort(key=lambda v: self.d[u][v] + self.d[v][u])
            self.nbr[u] = o
        dep = self.depot
        n = max(1, len(self.cust))
        cfs = [c.cf for c in self.classes] or [1.0]
        self.scale = max(1e-6, (sum(self.d[dep][u] for u in self.cust) / n) * (sum(cfs) / len(cfs)))
        self._new = {}

    def ehl(self, kind, ph):
        if kind == NH_ or kind == NL_:
            return self.e[ph], self.l[ph], self.svc[ph]
        if kind == DC_:
            return self.dce[ph], self.dcl[ph], self.dch[ph]
        if kind == CP_:
            return self.cpe[ph], self.cpl[ph], self.cph[ph]
        return -INF, INF, 0.0

    def new_routes(self, u):
        """Best one-customer route of every class for customer u (cached): list of (class index, Route)."""
        if u in self._new:
            return self._new[u]
        out = []
        for ci, cl in enumerate(self.classes):
            best = None
            if not cl.cv or self.is_nh[u]:
                best = make_route(self, ci, [u])
            if cl.cv:
                for p in self.near_park[u]:
                    r = make_route(self, ci, [], [u], p, 0)
                    if r is not None and (best is None or r.cost < best.cost):
                        best = r
            if best is not None:
                out.append((ci, best))
        self._new[u] = out
        return out


# ---- one route ---------------------------------------------------------------------------------------------------
class Route:
    """Immutable. main: customers served with the trailer attached (any customers for a solo truck); p: parking
    location or None; pos: main index before which the trailer is parked; sub: the truck-alone subtour."""
    __slots__ = ("c", "main", "sub", "p", "pos", "net", "ph", "kd", "dep", "LA", "pre", "cost", "idc", "icp")

    def custs(self):
        return [self.net[k] for k in range(len(self.net)) if self.kd[k] == NH_ or self.kd[k] == NL_]


def make_route(P, c, main, sub=(), p=None, pos=0):
    """Build and check a route; None if it breaks a rule (time, load, access, structure)."""
    cl = P.classes[c]
    main = list(main)
    sub = list(sub)
    if not sub:
        p = None
    if p is None:
        sub = []
        pos = 0
    if p is not None and (not cl.cv or not (0 <= pos <= len(main)) or p not in P.dp_id):
        return None
    if not main and not sub:
        return None
    dep = P.depot
    is_nh = P.is_nh
    net, ph, kd = [dep], [dep], [D_]
    idc = icp = -1
    if p is None:
        seq = main
    else:
        seq = main[:pos]
    for x in seq:
        net.append(x)
        ph.append(x)
        kd.append(NH_ if is_nh[x] else NL_)
    if p is not None:
        idc = len(net)
        net.append(P.dp_id[p])
        ph.append(p)
        kd.append(DC_)
        for x in sub:
            net.append(x)
            ph.append(x)
            kd.append(NH_ if is_nh[x] else NL_)
        icp = len(net)
        net.append(P.cp_id[p])
        ph.append(p)
        kd.append(CP_)
        for x in main[pos:]:
            net.append(x)
            ph.append(x)
            kd.append(NH_ if is_nh[x] else NL_)
    net.append(dep)
    ph.append(dep)
    kd.append(D_)
    m = len(net)
    if cl.cv:
        for k in range(1, m - 1):
            if kd[k] == NL_ and not (idc < k < icp):
                return None  # a truck customer with the trailer attached
    tt = P.tt
    depa = [0.0] * m
    depa[0] = P.H0
    for k in range(1, m - 1):
        e_, l_, h_ = P.ehl(kd[k], ph[k])
        a = depa[k - 1] + tt[ph[k - 1]][ph[k]]
        if a < e_:
            a = e_
        if a > l_ + EPS:
            return None
        depa[k] = a + h_
    end = depa[m - 2] + tt[ph[m - 2]][ph[m - 1]]
    if end > P.end_lim + EPS:
        return None
    depa[m - 1] = end
    LA = [0.0] * m
    LA[m - 1] = P.end_lim
    for k in range(m - 2, 0, -1):
        e_, l_, h_ = P.ehl(kd[k], ph[k])
        v = LA[k + 1] - tt[ph[k]][ph[k + 1]] - h_
        LA[k] = v if v < l_ else l_
    LA[0] = INF
    pre = [0.0] * m
    s = 0.0
    q = P.q
    for k in range(m):
        if kd[k] == NH_ or kd[k] == NL_:
            s += q[ph[k]]
        pre[k] = s
    if s > cl.QL + cl.QH + EPS:
        return None
    if p is not None:
        A = pre[idc]
        S = pre[icp] - A
        if max(0.0, A - cl.QH) + S > cl.QL + EPS:
            return None
    r = Route()
    r.c, r.main, r.sub, r.p, r.pos = c, main, sub, p, pos
    r.net, r.ph, r.kd, r.dep, r.LA, r.pre, r.idc, r.icp = net, ph, kd, depa, LA, pre, idc, icp
    r.cost = route_cost(P, cl, ph, kd, 1 if p is not None else 0)
    return r


def route_cost(P, cl, ph, kd, n_park):
    d = P.d
    fac = cl.fac
    travel = 0.0
    for k in range(len(ph) - 1):
        travel += fac[kd[k]][kd[k + 1]] * d[ph[k]][ph[k + 1]]
    handling = n_park * P.dc_c + n_park * P.cp_c
    return cl.fixed + travel + handling


def service_starts(P, r):
    """arrival_times as the benchmark writes them: service start at every node (key = route_sequence id); the depot
    key holds the start of the planning horizon (start and end of a route share one key)."""
    out = {str(r.net[0]): P.H0}
    tt = P.tt
    t = P.H0
    for k in range(1, len(r.net) - 1):
        e_, l_, h_ = P.ehl(r.kd[k], r.ph[k])
        a = t + tt[r.ph[k - 1]][r.ph[k]]
        if a < e_:
            a = e_
        out[str(r.net[k])] = a
        t = a + h_
    return out


# ---- search state ------------------------------------------------------------------------------------------------
class State:
    __slots__ = ("routes", "ccnt", "tcnt", "hcnt")

    def __init__(self, P, routes=()):
        self.routes = list(routes)
        self.recount(P)

    def copy(self):
        st = State.__new__(State)
        st.routes = list(self.routes)
        st.ccnt = dict(self.ccnt)
        st.tcnt = dict(self.tcnt)
        st.hcnt = dict(self.hcnt)
        return st

    def recount(self, P):
        self.ccnt, self.tcnt, self.hcnt = {}, {}, {}
        for r in self.routes:
            self.add(P, r.c, 1)

    def add(self, P, c, k):
        cl = P.classes[c]
        self.ccnt[c] = self.ccnt.get(c, 0) + k
        self.tcnt[cl.truck] = self.tcnt.get(cl.truck, 0) + k
        if cl.cv:
            self.hcnt[cl.trailer] = self.hcnt.get(cl.trailer, 0) + k

    def can_open(self, P, c):
        cl = P.classes[c]
        if self.ccnt.get(c, 0) >= cl.avail:
            return False
        if self.tcnt.get(cl.truck, 0) >= P.truck_avail.get(cl.truck, 10 ** 9):
            return False
        if cl.cv and self.hcnt.get(cl.trailer, 0) >= P.trailer_avail.get(cl.trailer, 10 ** 9):
            return False
        return True

    def total(self):
        return sum(r.cost for r in self.routes)


def park_cands(P, u, a, b):
    out = list(P.near_park[u])
    for x in (a, b):
        if 0 <= x < P.n_orig and P.is_nh[x] and x not in out:
            out.append(x)
    return out


def best_insert(P, st, u, rng, blink=0.0, big=False):
    """Cheapest feasible insertion of customer u: (delta, route index or -1, expanded index k, parking or None,
    new Route for -1). None if u fits nowhere. big=True: a new route may only use the largest-capacity class that
    can still be opened (so later customers can join it)."""
    q = P.q[u]
    nh = P.is_nh[u]
    ku = NH_ if nh else NL_
    eu, lu, hu = P.e[u], P.l[u], P.svc[u]
    tt, d = P.tt, P.d
    tu, du = tt[u], d[u]
    hand = P.dc_c + P.cp_c
    best_d = INF
    best = None
    for ri, r in enumerate(st.routes):
        cl = P.classes[r.c]
        if r.pre[-1] + q > cl.QL + cl.QH + EPS:
            continue
        fac = cl.fac
        ph, kd, dep, LA, pre = r.ph, r.kd, r.dep, r.LA, r.pre
        m = len(ph)
        cv = cl.cv
        has = r.p is not None
        okA = okS = okB = False
        if cv and has:
            A = pre[r.idc]
            S = pre[r.icp] - A
            okA = nh and (max(0.0, A + q - cl.QH) + S <= cl.QL + EPS)
            okS = max(0.0, A - cl.QH) + S + q <= cl.QL + EPS
            okB = nh
        for k in range(m - 1):
            a_ph, b_ph, ka, kb = ph[k], ph[k + 1], kd[k], kd[k + 1]
            opensub = False
            if not cv:
                single = True
            elif not has:
                single = nh
                opensub = max(0.0, pre[k] - cl.QH) + q <= cl.QL + EPS
            elif k < r.idc:
                single = okA
            elif k < r.icp:
                single = okS
            else:
                single = okB
            if single:
                t = dep[k] + tt[a_ph][u]
                if t < eu:
                    t = eu
                if t <= lu + EPS and t + hu + tu[b_ph] <= LA[k + 1] + EPS:
                    delta = fac[ka][ku] * d[a_ph][u] + fac[ku][kb] * du[b_ph] - fac[ka][kb] * d[a_ph][b_ph]
                    if delta < best_d and (blink <= 0 or rng.random() >= blink):
                        best_d, best = delta, (ri, k, None)
            if opensub:
                base = hand - fac[ka][kb] * d[a_ph][b_ph]
                for p in park_cands(P, u, a_ph, b_ph):
                    delta = (base + fac[ka][DC_] * d[a_ph][p] + fac[DC_][ku] * d[p][u] + fac[ku][CP_] * du[p]
                             + fac[CP_][kb] * d[p][b_ph])
                    if delta >= best_d:
                        continue
                    t = dep[k] + tt[a_ph][p]
                    if t < P.dce[p]:
                        t = P.dce[p]
                    if t > P.dcl[p] + EPS:
                        continue
                    t = t + P.dch[p] + tt[p][u]
                    if t < eu:
                        t = eu
                    if t > lu + EPS:
                        continue
                    t = t + hu + tu[p]
                    if t < P.cpe[p]:
                        t = P.cpe[p]
                    if t > P.cpl[p] + EPS:
                        continue
                    if t + P.cph[p] + tt[p][b_ph] > LA[k + 1] + EPS:
                        continue
                    if blink > 0 and rng.random() < blink:
                        continue
                    best_d, best = delta, (ri, k, p)
    newr = None
    cands = [(ci, rr) for ci, rr in P.new_routes(u) if st.can_open(P, ci)]
    if big and cands:
        capmax = max(P.classes[ci].QL + P.classes[ci].QH for ci, _ in cands)
        cands = [(ci, rr) for ci, rr in cands if P.classes[ci].QL + P.classes[ci].QH >= capmax - EPS]
    for ci, rr in cands:
        if rr.cost < best_d:
            best_d, best, newr = rr.cost, (-1, 0, None), rr
    if best is None:
        return None
    return best_d, best[0], best[1], best[2], newr


def apply_insert(P, r, u, k, p=None):
    if p is not None:  # new subtour at expanded index k of a route without parking: main index k
        return make_route(P, r.c, r.main, [u], p, k)
    main, sub, pos = list(r.main), list(r.sub), r.pos
    if r.p is None:
        main.insert(k, u)
        return make_route(P, r.c, main)
    if k < r.idc:
        main.insert(k, u)
        pos += 1
    elif k < r.icp:
        sub.insert(k - r.idc, u)
    else:
        main.insert(pos + (k - r.icp), u)
    return make_route(P, r.c, main, sub, r.p, pos)


def remove_customers(P, st, gone):
    """Remove the customers in gone. A route that becomes infeasible (rounded matrices can break the triangle
    inequality) is emptied too; returns those extra customers."""
    gone = set(gone)
    extra = []
    keep = []
    for r in st.routes:
        cs = r.custs()
        if not any(x in gone for x in cs):
            keep.append(r)
            continue
        main = [x for x in r.main if x not in gone]
        sub = [x for x in r.sub if x not in gone]
        pos = r.pos - sum(1 for x in r.main[:r.pos] if x in gone) if r.p is not None else 0
        if not main and not sub:
            continue
        nr = make_route(P, r.c, main, sub, r.p if sub else None, pos)
        if nr is None:
            extra.extend(main + sub)
            continue
        keep.append(nr)
    st.routes = keep
    st.recount(P)
    return extra


def repark(P, r):
    """Best (parking location, main position) for a route's subtour."""
    if r.p is None:
        return r
    best = r
    cands = set(P.near_park[r.sub[0]]) | set(P.near_park[r.sub[-1]]) | {r.p}
    nm = len(r.main)
    for pos in range(nm + 1):
        local = set(cands)
        if pos > 0 and P.is_nh[r.main[pos - 1]]:
            local.add(r.main[pos - 1])
        if pos < nm and P.is_nh[r.main[pos]]:
            local.add(r.main[pos])
        for p in sorted(local):
            if p == r.p and pos == r.pos:
                continue
            nr = make_route(P, r.c, r.main, r.sub, p, pos)
            if nr is not None and nr.cost < best.cost - 1e-9:
                best = nr
    return best


def recreate(P, st, removed, rng, blink=0.01, keep_order=False, repark_p=0.3, big=False):
    if not keep_order:
        mode = rng.random()
        if mode < 0.35:
            rng.shuffle(removed)
        elif mode < 0.55:
            removed.sort(key=lambda v: -P.q[v])
        elif mode < 0.75:
            removed.sort(key=lambda v: -P.d[P.depot][v])
        elif mode < 0.9:
            removed.sort(key=lambda v: P.l[v] - P.e[v])
        else:
            removed.sort(key=lambda v: P.e[v])
    touched = set()
    for u in removed:
        res = best_insert(P, st, u, rng, blink, big)
        if res is None:
            return False
        _, ri, k, p, newr = res
        if ri < 0:
            st.routes.append(newr)
            st.add(P, newr.c, 1)
            touched.add(len(st.routes) - 1)
        else:
            nr = apply_insert(P, st.routes[ri], u, k, p)
            if nr is None:
                return False
            st.routes[ri] = nr
            touched.add(ri)
    for ri in touched:
        r = st.routes[ri]
        if r.p is not None and rng.random() < repark_p:
            st.routes[ri] = repark(P, r)
    return True


def ruin_sisr(P, st, rng, cbar=10.0, Lmax=10.0):
    routes = st.routes
    if not routes:
        return []
    orders = [r.custs() for r in routes]
    where = {}
    for ri, o in enumerate(orders):
        for v in o:
            where[v] = ri
    avg = sum(len(o) for o in orders) / len(orders)
    ls_max = min(Lmax, avg)
    ks_max = 4.0 * cbar / (1.0 + ls_max) - 1.0
    ks = max(1, int(rng.uniform(1.0, ks_max + 1.0)))
    seed = rng.choice(P.cust)
    removed = []
    ruined = set()
    for c in [seed] + P.nbr[seed]:
        if len(ruined) >= ks:
            break
        ri = where.get(c)
        if ri is None or ri in ruined:
            continue
        r = orders[ri]
        L = len(r)
        lt = max(1, min(L, int(rng.uniform(1.0, min(L, ls_max) + 1.0))))
        pos = r.index(c)
        if lt < L and rng.random() < 0.5:
            m = 1
            while lt + m < L and rng.random() < 0.5:
                m += 1
            w = lt + m
            lo, hi = max(0, pos - w + 1), min(pos, L - w)
            s0 = rng.randint(lo, hi)
            keep_at = rng.randint(0, w - m)
            window = r[s0:s0 + w]
            removed.extend(window[:keep_at] + window[keep_at + m:])
        else:
            lo, hi = max(0, pos - lt + 1), min(pos, L - lt)
            s0 = rng.randint(lo, hi)
            removed.extend(r[s0:s0 + lt])
        ruined.add(ri)
    removed.extend(remove_customers(P, st, removed))
    return removed


def ruin_route(P, st, rng):
    if not st.routes:
        return []
    ws = [1.0 / (1.0 + len(r.custs())) for r in st.routes]
    ri = rng.choices(range(len(st.routes)), weights=ws)[0]
    removed = st.routes[ri].custs()
    removed.extend(remove_customers(P, st, removed))
    return removed


def ruin_pair(P, st, rng):
    """Empty two routes for a joint rebuild: a random route and (mostly) the route whose customers lie nearest."""
    n = len(st.routes)
    if n < 2:
        return ruin_route(P, st, rng)
    i = rng.randrange(n)
    ci = st.routes[i].custs()
    if rng.random() < 0.3:
        j = rng.choice([x for x in range(n) if x != i])
    else:
        j, best_v = -1, INF
        d = P.d
        for x in range(n):
            if x == i:
                continue
            v = min(d[a][b] + d[b][a] for a in ci for b in st.routes[x].custs())
            if v < best_v:
                j, best_v = x, v
    removed = ci + st.routes[j].custs()
    removed.extend(remove_customers(P, st, removed))
    return removed


def op_class(P, st, rng):
    """Move one route to its best other vehicle class (fleet limits kept)."""
    if not st.routes:
        return False
    ri = rng.randrange(len(st.routes))
    r = st.routes[ri]
    cur = P.classes[r.c]
    st.add(P, r.c, -1)
    best = None
    cs = r.custs()
    for c, cl in enumerate(P.classes):
        if c == r.c or not st.can_open(P, c):
            continue
        if cl.cv and cur.cv:
            nr = make_route(P, c, r.main, r.sub, r.p, r.pos)
        elif not cl.cv:
            nr = make_route(P, c, cs)
        elif all(P.is_nh[x] for x in cs):
            nr = make_route(P, c, cs)
        else:
            nr = None
        if nr is not None and (best is None or nr.cost < best.cost):
            best = nr
    if best is None:
        st.add(P, r.c, 1)
        return False
    st.routes[ri] = best
    st.add(P, best.c, 1)
    return True


def valid(P, routes):
    flat = sorted(x for r in routes for x in r.custs())
    if flat != P.cust:
        return False
    st = State(P, ())
    for r in routes:
        if not st.can_open(P, r.c):
            return False
        st.add(P, r.c, 1)
    return True


# ---- output and the official checker's rules ------------------------------------------------------------------------
def build_solution(P, routes):
    out = []
    total = 0.0
    idx = {}
    for r in routes:
        cl = P.classes[r.c]
        vi = idx.get(cl.cid, 0)
        idx[cl.cid] = vi + 1
        locs = [r.p] if r.p is not None else []
        out.append({"vehicle_class": cl.cid, "vehicle_index": vi, "customers_served": r.custs(),
                    "route_sequence": list(r.net), "route_sequence_physical": list(r.ph),
                    "decouple_locations": list(locs), "couple_locations": list(locs),
                    "arrival_times": service_starts(P, r), "route_cost": r.cost})
        total += r.cost
    return {"objective_value": total, "routes": out}


def verify(inst, sol):
    """Mirror of the official rothenbacher2018 feasibility_check.py for answers in the benchmark's own ("gurobi")
    format: {"feasible", "objective", "reason"}. Other formats are reported as not mirrored (never written by us)."""
    try:
        return _verify(inst, sol)
    except Exception as ex:  # noqa: BLE001 - the official program turns exceptions into a rejection
        return {"feasible": False, "objective": None, "reason": "malformed: " + repr(ex)[:200]}


def _tw_of(inst, loc):
    for c in inst.get("truck_customers", []):
        if c.get("id") == loc:
            return c.get("time_window")
    for c in inst.get("trailer_customers", []):
        if c.get("id") == loc:
            return c.get("time_window")
    return None


def _events(rs, ps, dcl, cpl, taul, depot, NL, NH, T):
    ev = []
    if len(rs) == len(ps):
        dcu = tau_u = cpu = 0
        for i in range(len(ps)):
            loc, nv = ps[i], rs[i]
            if i == 0:
                ev.append(("D+", depot))
            elif i == len(ps) - 1:
                ev.append(("D-", depot))
            elif loc == depot:
                ev.append(("depot", loc))
            elif nv != loc:
                if dcu < len(dcl) and loc == dcl[dcu]:
                    ev.append(("DC", loc))
                    dcu += 1
                elif tau_u < len(taul) and loc == taul[tau_u]:
                    ev.append(("TAU", loc))
                    tau_u += 1
                elif cpu < len(cpl) and loc == cpl[cpu]:
                    ev.append(("CP", loc))
                    cpu += 1
                else:
                    ev.append(("TAU", loc))
            elif loc in NL:
                ev.append(("NL", loc))
            elif loc in NH:
                ev.append(("NH", loc))
            elif loc in T:
                ev.append(("TAU", loc))
            else:
                ev.append(("?", loc))
    else:
        for i, loc in enumerate(ps):
            if i == 0:
                ev.append(("D+", depot))
            elif i == len(ps) - 1:
                ev.append(("D-", depot))
            elif loc in NL:
                ev.append(("NL", loc))
            elif loc in NH:
                ev.append(("NH", loc))
            else:
                ev.append(("?", loc))
    return ev


def _verify(inst, sol):
    tol = 1e-5
    if not isinstance(sol, dict):
        return {"feasible": False, "objective": None, "reason": "not an object"}
    for f in ("objective_value", "routes"):
        if sol.get(f) is None:
            return {"feasible": False, "objective": None, "reason": "missing " + f}
    ov = sol.get("objective_value")
    if isinstance(ov, bool) or not isinstance(ov, (int, float)) or ov != ov or ov in (INF, -INF):
        return {"feasible": False, "objective": None, "reason": "objective_value must be a finite number"}
    routes = sol["routes"]
    if sol.get("solver") == "Gurobi":
        fmt = "gurobi"
    elif "algorithm" in sol:
        fmt = "efficient"
    elif routes and "route_sequence_physical" in routes[0]:
        fmt = "gurobi"
    else:
        fmt = "unknown"
    if fmt != "gurobi":
        return {"feasible": False, "objective": None, "reason": "format %s not mirrored" % fmt}
    par = inst["parameters"]
    H = par["planning_horizon"]
    depot = inst["depot"]["id"]
    supply = {}
    for c in inst["truck_customers"] + inst["trailer_customers"]:
        supply[c["id"]] = c["supply"]
    NL = set(c["id"] for c in inst["truck_customers"])
    NH = set(c["id"] for c in inst["trailer_customers"])
    T = set(t["id"] for t in inst["transshipment_locations"])
    vc_map = {vc["class_id"]: vc for vc in inst["fleet"]["vehicle_classes"]}
    bad = []
    count = {n: 0 for n in NL | NH}
    for r in routes:
        for c in r.get("customers_served", []):
            if c in count:
                count[c] += 1
    for n in sorted(count):
        if count[n] != 1:
            bad.append("customer %s served %d times" % (n, count[n]))
    tu, hu = {}, {}
    for r in routes:
        vc = vc_map.get(r.get("vehicle_class", r.get("vehicle_class_id")))
        if vc is None:
            continue
        tu[vc["truck_type_id"]] = tu.get(vc["truck_type_id"], 0) + 1
        if vc["trailer_type_id"] != 0:
            hu[vc["trailer_type_id"]] = hu.get(vc["trailer_type_id"], 0) + 1
    for tt_ in inst["fleet"]["truck_types"]:
        if tu.get(tt_["id"], 0) > tt_["num_available"] + tol:
            bad.append("truck type %s over" % tt_["id"])
    for tt_ in inst["fleet"]["trailer_types"]:
        if hu.get(tt_["id"], 0) > tt_["num_available"] + tol:
            bad.append("trailer type %s over" % tt_["id"])
    for ri, raw in enumerate(routes):
        vc = vc_map.get(raw.get("vehicle_class", raw.get("vehicle_class_id")))
        if vc is None:
            bad.append("route %d unknown class" % ri)
            continue
        has_tr = vc["trailer_type_id"] != 0
        QL = vc["truck_capacity"]
        QH = vc["trailer_capacity"] if has_tr else 0
        rs = raw.get("route_sequence", [])
        ps = raw.get("route_sequence_physical", [])
        ev = _events(rs, ps, raw.get("decouple_locations", []), raw.get("couple_locations", []),
                     raw.get("transfer_locations", []), depot, NL, NH, T)
        at = raw.get("arrival_times")
        if at is None:
            bad.append("route %d no arrival_times" % ri)
        else:
            for si, (vt, loc) in enumerate(ev):
                node = rs[si] if si < len(rs) else loc
                if str(node) in at:
                    tv = float(at[str(node)])
                elif node in at:
                    tv = float(at[node])
                else:
                    bad.append("route %d no time for %s" % (ri, node))
                    continue
                if vt in ("NL", "NH"):
                    tw = _tw_of(inst, loc)
                    if tw is not None and len(tw) == 2:
                        if tv < tw[0] - tol:
                            bad.append("route %d early at %s" % (ri, loc))
                        if tv > tw[1] + tol:
                            bad.append("route %d late at %s" % (ri, loc))
                if tv > H[1] + tol:
                    bad.append("route %d past horizon at %s" % (ri, loc))
        truck = trailer = 0.0
        on = has_tr
        for si, (vt, loc) in enumerate(ev):
            if vt == "NL":
                truck += supply.get(loc, 0)
            elif vt == "NH":
                qv = supply.get(loc, 0)
                if on:
                    x = min(qv, QH - trailer)
                    trailer += x
                    truck += qv - x
                else:
                    truck += qv
            elif vt == "DC":
                on = False
            elif vt in ("CP", "TAU"):
                if vt == "CP":
                    on = True
                x = min(truck, QH - trailer)
                truck -= x
                trailer += x
            if truck - QL > tol:
                bad.append("route %d truck load at step %d" % (ri, si))
            if has_tr and trailer - QH > tol:
                bad.append("route %d trailer load at step %d" % (ri, si))
            if truck + trailer - (QL + QH) > tol:
                bad.append("route %d total load at step %d" % (ri, si))
        on = has_tr
        parked = None
        for si, (vt, loc) in enumerate(ev):
            if vt == "DC":
                if not on:
                    bad.append("route %d decouple without trailer" % ri)
                on = False
                parked = loc
            elif vt == "CP":
                if on or parked is None or parked != loc:
                    bad.append("route %d couple where no trailer is parked" % ri)
                on = True
                parked = None
            elif vt == "NL" and on and has_tr:
                bad.append("route %d truck customer %s with trailer" % (ri, loc))
        seen = {}
        for c in raw.get("customers_served", []):
            seen[c] = seen.get(c, 0) + 1
            if seen[c] == 2:
                bad.append("route %d repeats %s" % (ri, c))
        if ev:
            if ev[0][1] != depot or ev[-1][1] != depot:
                bad.append("route %d not depot to depot" % ri)
        if has_tr:
            fin = True
            for vt, _ in ev:
                if vt == "DC":
                    fin = False
                elif vt == "CP":
                    fin = True
            if not fin:
                bad.append("route %d trailer not recoupled" % ri)
    # objective, exactly as the checker recomputes it (exceptions = rejection)
    dist = inst["distance_matrix"]
    n0 = len(dist)
    parks = sorted(NH | T)
    np_ = len(parks)
    dpn = {n0 + i for i in range(np_)}
    cpn = {n0 + np_ + i for i in range(np_)}

    def phys(node):
        if not isinstance(node, int):
            raise ValueError("non-integer node")
        if 0 <= node < n0:
            return node
        off = node - n0
        if 0 <= off < 2 * np_:
            return parks[off % np_]
        raise ValueError("node out of range")

    exact = 0.0
    if routes:
        for ri, raw in enumerate(routes):
            vc = vc_map.get(raw.get("vehicle_class", raw.get("vehicle_class_id")))
            if vc is None:
                raise ValueError("unknown class")
            has_tr = vc.get("trailer_type_id", 0) != 0
            cf = float(vc.get("truck_cost_factor", 0.0))
            tw = float(vc.get("trailer_towing_cost_multiplier", 0.0)) if has_tr else 0.0
            fixed = float(vc.get("truck_fixed_cost", 0.0))
            rs = raw.get("route_sequence")
            ps = raw.get("route_sequence_physical")
            if not isinstance(rs, list) or not isinstance(ps, list) or len(rs) != len(ps) or len(rs) < 2:
                raise ValueError("misaligned sequences")
            if [phys(x) for x in rs] != ps:
                raise ValueError("physical sequence mismatch")
            travel = 0.0
            for a, b in zip(rs, rs[1:]):
                towing = has_tr and (a == depot or a in NH or a in cpn) and (b == depot or b in NH or b in dpn)
                travel += (cf + (tw if towing else 0.0)) * float(dist[phys(a)][phys(b)])
            handling = (len(raw.get("decouple_locations", []) or []) * par.get("decoupling_cost", 0.0)
                        + len(raw.get("couple_locations", []) or []) * par.get("coupling_cost", 0.0)
                        + len(raw.get("transfer_locations", []) or []) * par.get("transfer_cost", 0.0))
            exact += fixed + travel + handling
        if abs(float(ov) - exact) > max(1e-3, 1e-8 * max(abs(exact), 1.0)):
            bad.append("objective mismatch: reported %s, recomputed %s" % (ov, exact))
    return {"feasible": not bad, "objective": exact, "reason": "; ".join(bad[:5])}


# ---- search ------------------------------------------------------------------------------------------------------
def construct(P, rng, tries=8):
    """Greedy constructions: orders 0-3 with cheapest route opening, then the same orders in big mode."""
    best = None
    for t in range(tries):
        st = State(P)
        order = list(P.cust)
        kind = t % 4
        if kind == 0:
            order.sort(key=lambda v: (P.l[v], v))
        elif kind == 1:
            order.sort(key=lambda v: (-P.q[v], v))
        elif kind == 2:
            order.sort(key=lambda v: (-P.d[P.depot][v], v))
        else:
            order.sort(key=lambda v: (P.is_nh[v], P.l[v], v))
        if t >= 8:
            rng.shuffle(order)
        if recreate(P, st, order, rng, blink=0.0, keep_order=True, repark_p=1.0, big=(t // 4) % 2 == 1):
            if best is None or st.total() < best.total():
                best = st
        if best is not None and t >= 8:
            break
    return best


def search(P, deadline, rng, on_best=None, log=None):
    cur = construct(P, rng, tries=8)
    if cur is None:
        cur = construct(P, rng, tries=16)
    if cur is None:
        if log is not None:
            log["error"] = "no construction"
        return None, INF
    cur_c = cur.total()
    best, best_c = cur.copy(), cur_c
    if on_best:
        on_best(best.routes, best_c, "construct")
    T0 = 0.3 * P.scale
    Tf = 0.003 * P.scale
    t_begin = time.monotonic()
    span = max(1e-6, deadline - t_begin)
    it = acc = imp = fails = 0
    moves = {k: [0, 0, 0] for k in ("sisr", "route", "pair", "class", "repark")}
    last_imp = 0
    events = [(0.0, round(best_c, 4), "construct")]
    last_write = t_begin
    T = T0
    while True:
        now = time.monotonic()
        if now >= deadline:
            break
        T = T0 * (Tf / T0) ** min(1.0, (now - t_begin) / span)
        it += 1
        cand = cur.copy()
        u = rng.random()
        if u < 0.05:
            kind = "class"
            moves[kind][0] += 1
            if not op_class(P, cand, rng):
                continue
        elif u < 0.10:
            kind = "repark"
            withp = [i for i, r in enumerate(cand.routes) if r.p is not None]
            if not withp:
                continue
            moves[kind][0] += 1
            i = rng.choice(withp)
            nr = repark(P, cand.routes[i])
            if nr is cand.routes[i]:
                continue
            cand.routes[i] = nr
        else:
            if u < 0.14:
                kind, big_p = "pair", 0.5
                removed = ruin_pair(P, cand, rng)
            elif u < 0.20:
                kind, big_p = "route", 0.25
                removed = ruin_route(P, cand, rng)
            else:
                kind, big_p = "sisr", 0.05
                removed = ruin_sisr(P, cand, rng)
            if not removed:
                continue
            moves[kind][0] += 1
            if not recreate(P, cand, removed, rng, big=rng.random() < big_p):
                fails += 1
                continue
        c = cand.total()
        if c < cur_c - T * math.log(max(1e-300, rng.random())):
            acc += 1
            moves[kind][1] += 1
            cur, cur_c = cand, c
            if c < best_c - 1e-9:
                imp += 1
                moves[kind][2] += 1
                last_imp = it
                best, best_c = cand.copy(), c
                now = time.monotonic()
                events.append((round(now - t_begin, 2), round(best_c, 4), kind))
                if on_best and now - last_write > 5.0:
                    on_best(best.routes, best_c, "search")
                    last_write = now
        if it - last_imp > 3000:
            cur, cur_c = best.copy(), best_c
            last_imp = it
    if log is not None:
        log.update({"iterations": it, "accepted": acc, "improved": imp, "recreate_failed": fails, "moves": moves,
                    "events": events[:3] + events[-12:] if len(events) > 15 else events})
    return best.routes, best_c


def solve(inst, time_limit=60.0, seed=1, t_start=None, on_write=None, log=None, budget=None, near_park=NEAR_PARK,
          strict=STRICT):
    t_start = time.monotonic() if t_start is None else t_start
    if budget is None:
        budget = max(0.3, min(0.9 * time_limit, time_limit - 3.0) - 1.0)
    deadline = t_start + budget
    rng = random.Random(seed)
    P = Problem(inst, strict=strict, near_park=near_park)
    best = {"routes": None, "cost": INF, "src": None}

    def offer(routes, cost, src):
        if routes is None or cost >= best["cost"] - 1e-9 or not valid(P, routes):
            return
        sol = build_solution(P, routes)
        if not verify(inst, sol)["feasible"]:
            if log is not None:
                log["verify_rejected"] = log.get("verify_rejected", 0) + 1
            return
        best.update(routes=list(routes), cost=cost, src=src)
        if on_write is not None:
            on_write(sol)

    routes, c = search(P, deadline, rng, on_best=offer, log=log)
    offer(routes, c, "final")
    if best["routes"] is None:
        if log is not None:
            log.update({"version": VERSION, "error": log.get("error", "no feasible solution found")})
        return None
    sol = build_solution(P, best["routes"])
    if log is not None:
        rs = best["routes"]
        log.update({"version": VERSION, "seed": seed, "strict": strict, "n_truck_customers": len(P.NL),
                    "n_trailer_customers": len(P.NH), "n_transshipment": len(P.T), "classes": len(P.classes),
                    "routes": len(rs), "solo_routes": sum(1 for r in rs if not P.classes[r.c].cv),
                    "complete_routes": sum(1 for r in rs if P.classes[r.c].cv),
                    "parkings": sum(1 for r in rs if r.p is not None),
                    "parked_at_transshipment": sum(1 for r in rs if r.p is not None and not P.is_cust[r.p]),
                    "fixed_cost": round(sum(P.classes[r.c].fixed for r in rs), 6),
                    "objective": sol["objective_value"], "best_source": best["src"],
                    "time_used_s": round(time.monotonic() - t_start, 3)})
    return sol


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def main(argv=None):
    t_start = time.monotonic()
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="rothenbacher2018")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=int(os.environ.get("MV2_TTR_SEED", "1")))
    a = ap.parse_args(argv)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    log = {} if os.environ.get("MV2_TTR_LOG") == "1" else None
    sol = solve(inst, a.time_limit, a.seed, t_start=t_start, on_write=lambda s: write_json(a.output, s), log=log)
    if sol is not None:
        write_json(a.output, sol)
    if log is not None:
        write_json(a.output + ".log.json", log)
    return 0 if sol is not None else 1


if __name__ == "__main__":
    sys.exit(main())

"""roberti2018 (two-echelon capacitated vehicle routing with grouping constraints, 2E-CVRPGC) solver for the
FrontierOR Challenge, v0.1.0.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Rules, read from the public FrontierOR benchmark's problem_description.txt, mathematical_formulation.md,
gurobi_code.py and feasibility_check.py (Hugging Face frontieror/FrontierOR, task roberti2018, CC BY 4.0):
- one depot, satellites and customers; travel cost = Euclidean distance on the raw coordinates, no rounding;
- first echelon: at most T1 trucks (vehicle ids 0..T1-1), each one tour depot -> satellites -> depot that visits a
  satellite at most once and delivers at most Q1 in total, only to satellites it visits (split deliveries allowed);
- satellite s: freight received <= capacity, at most max_vehicles second-echelon routes, handling cost h_s per unit
  received; freight received = total demand of the customers it serves (linking constraint);
- second echelon: every customer on exactly one route satellite -> customers -> same satellite with load <= Q2, at
  most T2 routes in all; all customers of a group are served from the same satellite;
- objective = first-echelon travel + sum_s h_s * received_s + second-echelon travel, recomputed by the checker
  (0.1% tolerance).

Method (standard library only):
- First echelon, exact over partitions: for the vector of satellite loads, every satellite subset is costed as one
  "block" (one truck tour if its load fits Q1; otherwise the block's optimal tour is cut into full-truck segments,
  trying every rotation and both directions), and a subset DP picks the cheapest partition of the loaded
  satellites into blocks (all partitions when at most 7 satellites carry freight). Truck tours over satellite
  subsets are exact (Held-Karp) up to 8 satellites. Results are cached per load vector.
- Second echelon: simulated annealing over group -> satellite assignment and routes, with capacity, satellite
  throughput and fleet limits as adaptive penalties. Moves: relocate (best / random), swap, 2-opt, 2-opt*, move a
  group to another satellite (best of all / random), swap two groups' satellites, ruin-and-recreate of nearby
  customers, and ruin-and-recreate of nearby groups (each group to its best satellite). Every move's change in
  handling cost and first-echelon cost is priced exactly through the cached first-echelon DP.
- Only solutions that pass verify() (an independent copy of the official rules with a tighter tolerance) are
  written, atomically. With 2 CPUs a forked child searches with a second seed. Deadline min(0.9 T, T - 3).
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
SLUG = "roberti2018"
INF = float("inf")
FEAS_TOL = 1e-7          # ours; the official checker allows 1e-5
E1_EXACT_P = 7           # all partitions of the loaded satellites when at most this many carry freight
HK_MAX = 8               # exact truck tours (Held-Karp) up to this many satellites


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# --------------------------------------------------------------------------------------------------- problem
class Problem:
    def __init__(self, inst):
        dep = inst["depot"]
        sats = list(inst["satellites"])
        custs = list(inst["customers"])
        self.depot_id = dep["id"]
        self.S = S = len(sats)
        self.C = C = len(custs)
        self.sat_id = [s["id"] for s in sats]
        self.cap = [s["capacity"] for s in sats]
        self.maxv = [int(s["max_vehicles"]) for s in sats]
        self.h = [s["handling_cost"] for s in sats]
        self.cust_id = [c["id"] for c in custs]
        self.Q1 = inst["Q1"]
        self.Q2 = inst["Q2"]
        self.T1 = int(inst["T1"])
        self.T2 = int(inst["T2"])
        if not self.Q1 > 0:
            raise ValueError("Q1 must be positive")
        self.base = 1 + S            # node 0 = depot, 1..S = satellites, base.. = customers
        self.xs = [dep["x"]] + [s["x"] for s in sats] + [c["x"] for c in custs]
        self.ys = [dep["y"]] + [s["y"] for s in sats] + [c["y"] for c in custs]
        N = 1 + S + C
        self.N = N
        xs, ys = self.xs, self.ys
        self.D = [[math.sqrt((xs[i] - xs[j]) ** 2 + (ys[i] - ys[j]) ** 2) for j in range(N)] for i in range(N)]
        self.dem = [0] * N
        for i, c in enumerate(custs):
            self.dem[self.base + i] = c["demand"]
        # groups -> blocks: groups sharing a customer are merged; a customer in no group is a block of its own
        cidx = {cid: i for i, cid in enumerate(self.cust_id)}
        parent = list(range(C))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        self.groups = []
        for g in inst.get("groups") or []:
            mem = [cidx[x] for x in (g.get("customer_ids") or []) if x in cidx]
            self.groups.append((g["group_id"], mem))
            for x in mem[1:]:
                ra, rb = find(mem[0]), find(x)
                if ra != rb:
                    parent[rb] = ra
        roots = {}
        self.blk = [0] * C
        for i in range(C):
            r = find(i)
            if r not in roots:
                roots[r] = len(roots)
            self.blk[i] = roots[r]
        self.B = len(roots)
        self.bmem = [[] for _ in range(self.B)]
        for i in range(C):
            self.bmem[self.blk[i]].append(self.base + i)
        self.bdem = [sum(self.dem[v] for v in m) for m in self.bmem]
        self.total = sum(self.bdem)
        self.slots = [max(0, min(self.maxv[s], self.T2, C)) for s in range(S)]
        self.usable = [s for s in range(S) if self.slots[s] > 0]
        if not self.usable:
            raise ValueError("no satellite may run a second-echelon route")
        self._tsp = {}
        self._e1 = {}
        self.e1_calls = 0

    def route_eval(self, s, seq):
        """(travel cost, load) of satellite s -> seq -> s, summed in route order."""
        if not seq:
            return (0.0, 0)
        D = self.D
        dem = self.dem
        sn = 1 + s
        prev = sn
        c = 0.0
        ld = 0
        for v in seq:
            c += D[prev][v]
            ld += dem[v]
            prev = v
        c += D[prev][sn]
        return (c, ld)

    # ---------------------------------------------------------------------------------- truck tours (depot side)
    def tour_cost(self, order):
        D = self.D
        prev = 0
        c = 0.0
        for s in order:
            c += D[prev][1 + s]
            prev = 1 + s
        return c + D[prev][0]

    def tsp(self, mask):
        """(cost, order) of the best depot tour over the satellites in mask (bit s = satellite index s)."""
        r = self._tsp.get(mask)
        if r is None:
            nodes = [s for s in range(self.S) if mask >> s & 1]
            order = self._held_karp(nodes) if len(nodes) <= HK_MAX else self._tsp_heur(nodes)
            r = (self.tour_cost(order), order)
            self._tsp[mask] = r
        return r

    def _held_karp(self, nodes):
        k = len(nodes)
        if k <= 1:
            return list(nodes)
        D = self.D
        vs = [1 + s for s in nodes]
        full = (1 << k) - 1
        dp = [[INF] * k for _ in range(full + 1)]
        par = [[-1] * k for _ in range(full + 1)]
        for i in range(k):
            dp[1 << i][i] = D[0][vs[i]]
        for sub in range(1, full + 1):
            row = dp[sub]
            for i in range(k):
                ci = row[i]
                if ci == INF or not (sub >> i & 1):
                    continue
                Di = D[vs[i]]
                for j in range(k):
                    if sub >> j & 1:
                        continue
                    nsub = sub | (1 << j)
                    v = ci + Di[vs[j]]
                    if v < dp[nsub][j]:
                        dp[nsub][j] = v
                        par[nsub][j] = i
        best = INF
        last = 0
        for i in range(k):
            v = dp[full][i] + D[vs[i]][0]
            if v < best:
                best, last = v, i
        order = []
        sub = full
        i = last
        while i != -1:
            order.append(nodes[i])
            pi = par[sub][i]
            sub ^= 1 << i
            i = pi
        order.reverse()
        return order

    def _tsp_heur(self, nodes):
        D = self.D
        left = set(nodes)
        order = []
        cur = 0
        while left:
            nx = min(left, key=lambda s: (D[cur][1 + s], s))
            order.append(nx)
            left.remove(nx)
            cur = 1 + nx
        improved = True
        while improved:
            improved = False
            seq = [0] + [1 + s for s in order] + [0]
            for i in range(1, len(seq) - 2):
                for j in range(i + 1, len(seq) - 1):
                    a, b, c, d = seq[i - 1], seq[i], seq[j], seq[j + 1]
                    if D[a][c] + D[b][d] < D[a][b] + D[c][d] - 1e-12:
                        seq[i:j + 1] = seq[i:j + 1][::-1]
                        improved = True
            order = [v - 1 for v in seq[1:-1]]
        return order

    # ------------------------------------------------------------------------------ first echelon for given loads
    def e1_cost(self, loads):
        """Cost of the first-echelon plan for a tuple of satellite loads (cached)."""
        v = self._e1.get(loads)
        if v is None:
            self.e1_calls += 1
            v = self.e1_solve(loads)[0]
            if len(self._e1) >= 300000:
                self._e1.clear()
            self._e1[loads] = v
        return v

    def _chunk(self, seq, loads, plan):
        """Cut the satellite sequence into full-truck segments (split at the boundaries)."""
        Q = self.Q1
        cost = 0.0
        nv = 0
        cur_mask = 0
        cur_load = 0
        cur = []
        routes = [] if plan else None
        for s in seq:
            rem = loads[s]
            while rem > 1e-12:
                room = Q - cur_load
                take = rem if rem <= room else room
                cur_mask |= 1 << s
                cur_load += take
                rem -= take
                if plan:
                    cur.append((s, take))
                if cur_load >= Q - 1e-12:
                    cost += self.tsp(cur_mask)[0]
                    nv += 1
                    if plan:
                        routes.append(cur)
                        cur = []
                    cur_mask = 0
                    cur_load = 0
        if cur_mask:
            cost += self.tsp(cur_mask)[0]
            nv += 1
            if plan:
                routes.append(cur)
        return cost, nv, routes

    def _block(self, gm, loads, plan=False):
        """(cost, trucks, routes) of serving the satellites in global mask gm on their own."""
        cost, order = self.tsp(gm)
        tot = 0
        for s in order:
            tot += loads[s]
        if tot <= self.Q1 + 1e-12:
            return cost, 1, ([[(s, loads[s]) for s in order]] if plan else None)
        best = None
        k = len(order)
        for d in (0, 1):
            seq0 = order if d == 0 else order[::-1]
            for r in range(k):
                c, nv, routes = self._chunk(seq0[r:] + seq0[:r], loads, plan)
                if best is None or c < best[0] - 1e-12:
                    best = (c, nv, routes)
        return best

    def e1_solve(self, loads, plan=False):
        """(cost, routes) of the first echelon; routes = list of [(satellite index, amount)]."""
        P = [s for s in range(self.S) if loads[s] > 0]
        if not P:
            return 0.0, []
        p = len(P)
        if p <= E1_EXACT_P:
            full = (1 << p) - 1
            gmask = [0] * (full + 1)
            for lm in range(1, full + 1):
                low = lm & -lm
                gmask[lm] = gmask[lm ^ low] | (1 << P[low.bit_length() - 1])
            bc = [None] * (full + 1)
            best = [INF] * (full + 1)
            nveh = [0] * (full + 1)
            choice = [0] * (full + 1)
            best[0] = 0.0
            for m in range(1, full + 1):
                low = m & -m
                rest = m ^ low
                sub = rest
                while True:
                    blk = sub | low
                    b = bc[blk]
                    if b is None:
                        b = bc[blk] = self._block(gmask[blk], loads)
                    v = b[0] + best[m ^ blk]
                    if v < best[m] - 1e-12:
                        best[m] = v
                        nveh[m] = b[1] + nveh[m ^ blk]
                        choice[m] = blk
                    if sub == 0:
                        break
                    sub = (sub - 1) & rest
            if nveh[full] <= self.T1:
                if not plan:
                    return best[full], None
                routes = []
                m = full
                while m:
                    blk = choice[m]
                    routes.extend(self._block(gmask[blk], loads, True)[2])
                    m ^= blk
                return best[full], routes
        # fallback: one block (fewest trucks) or every satellite on its own, the cheaper one that fits T1
        gm_all = 0
        for s in P:
            gm_all |= 1 << s
        one = self._block(gm_all, loads, plan)
        sing = [self._block(1 << s, loads, plan) for s in P]
        two = (sum(x[0] for x in sing), sum(x[1] for x in sing),
               [r for x in sing for r in x[2]] if plan else None)
        ok = [x for x in (one, two) if x[1] <= self.T1]
        pick = min(ok or [one], key=lambda x: x[0])
        return pick[0], pick[2]


# --------------------------------------------------------------------------------------------- verify / output
def verify(inst, sol, P=None, loose=False):
    """Independent re-implementation of the official rules. Returns {"feasible", "objective", "reason"}.

    Default tolerances are tighter than the checker's (used on our own answers). loose=True uses the checker's own
    tolerances (1e-5 on quantities, max(1e-3, 0.1%) on the objective), for judging other answers such as Gurobi's.
    """
    try:
        return _verify(inst, sol, P if P is not None else Problem(inst), loose)
    except Exception as e:  # noqa: BLE001 - malformed means rejected
        return {"feasible": False, "objective": None, "reason": "verify error %r" % (e,)}


def _no(reason):
    return {"feasible": False, "objective": None, "reason": reason}


def _verify(inst, sol, P, loose=False):
    TOL = 1e-5 if loose else FEAS_TOL
    LINK = 1e-5 if loose else 1e-6
    if not isinstance(sol, dict):
        return _no("solution is not an object")
    for f in ("first_echelon_routes", "group_assignments", "objective_value", "second_echelon_routes"):
        if sol.get(f) is None:
            return _no("missing field %s" % f)
    obj = sol["objective_value"]
    if not _is_num(obj):
        return _no("objective_value not a finite number")
    if not isinstance(sol["group_assignments"], dict) or not sol["group_assignments"]:
        return _no("group_assignments empty or not an object")
    D = P.D
    sidx = {sid: s for s, sid in enumerate(P.sat_id)}
    cidx = {cid: i for i, cid in enumerate(P.cust_id)}
    # first echelon
    w = [0.0] * P.S
    cost1 = 0.0
    seen_k = set()
    r1 = sol["first_echelon_routes"]
    if not isinstance(r1, list):
        return _no("first_echelon_routes not a list")
    for idx, r in enumerate(r1):
        k = r.get("vehicle")
        if not _is_int(k) or not 0 <= k < P.T1:
            return _no("truck %d: vehicle %r not in 0..%d" % (idx, k, P.T1 - 1))
        if k in seen_k:
            return _no("truck %d: vehicle %d used twice" % (idx, k))
        seen_k.add(k)
        route = r.get("route")
        if not isinstance(route, list) or len(route) < 3 or route[0] != P.depot_id or route[-1] != P.depot_id:
            return _no("truck %d: route must start and end at the depot and visit a satellite" % idx)
        mid = route[1:-1]
        if any(x not in sidx for x in mid):
            return _no("truck %d: a stop is not a satellite" % idx)
        if len(set(mid)) != len(mid):
            return _no("truck %d: visits a satellite twice" % idx)
        visited = {sidx[x] for x in mid}
        prev = 0
        for x in mid:
            cost1 += D[prev][1 + sidx[x]]
            prev = 1 + sidx[x]
        cost1 += D[prev][0]
        dl = r.get("deliveries", {})
        if not isinstance(dl, dict):
            return _no("truck %d: deliveries not an object" % idx)
        tot = 0.0
        for key, amt in dl.items():
            try:
                sid = int(key)
            except (TypeError, ValueError):
                return _no("truck %d: delivery key %r" % (idx, key))
            if sid not in sidx:
                return _no("truck %d: delivery to unknown satellite %r" % (idx, key))
            s = sidx[sid]
            if not _is_num(amt) or amt < -TOL:
                return _no("truck %d: bad amount %r" % (idx, amt))
            if amt > TOL and s not in visited:
                return _no("truck %d: delivers to satellite %d without visiting it" % (idx, sid))
            if amt > P.cap[s] + TOL:
                return _no("truck %d: delivers %s > satellite capacity" % (idx, amt))
            w[s] += amt
            tot += amt
        if tot > P.Q1 + TOL:
            return _no("truck %d: carries %s > Q1 %s" % (idx, tot, P.Q1))
    # second echelon
    r2 = sol["second_echelon_routes"]
    if not isinstance(r2, list):
        return _no("second_echelon_routes not a list")
    visits = [0] * P.C
    csat = [None] * P.C
    nroutes = [0] * P.S
    recv = [0.0] * P.S
    cost2 = 0.0
    for idx, r in enumerate(r2):
        sid = r.get("satellite")
        if sid not in sidx:
            return _no("route %d: unknown satellite %r" % (idx, sid))
        s = sidx[sid]
        route = r.get("route")
        if not isinstance(route, list) or len(route) < 3 or route[0] != sid or route[-1] != sid:
            return _no("route %d: must start and end at its satellite and visit a customer" % idx)
        mid = route[1:-1]
        if any(x not in cidx for x in mid):
            return _no("route %d: a stop is not a customer" % idx)
        load = 0
        prev = 1 + s
        for x in mid:
            i = cidx[x]
            visits[i] += 1
            csat[i] = s
            load += P.dem[P.base + i]
            cost2 += D[prev][P.base + i]
            prev = P.base + i
        cost2 += D[prev][1 + s]
        if load > P.Q2 + TOL:
            return _no("route %d: load %s > Q2 %s" % (idx, load, P.Q2))
        nroutes[s] += 1
        recv[s] += load
    for i in range(P.C):
        if visits[i] != 1:
            return _no("customer %r visited %d times" % (P.cust_id[i], visits[i]))
    for s in range(P.S):
        if nroutes[s] > P.maxv[s]:
            return _no("satellite %r runs %d routes > %d" % (P.sat_id[s], nroutes[s], P.maxv[s]))
        if abs(w[s] - recv[s]) > LINK:
            return _no("satellite %r receives %s but sends %s" % (P.sat_id[s], w[s], recv[s]))
        if w[s] > P.cap[s] + TOL:
            return _no("satellite %r over capacity" % (P.sat_id[s],))
    if sum(nroutes) > P.T2:
        return _no("%d second-echelon routes > T2 %d" % (sum(nroutes), P.T2))
    for gid, mem in P.groups:
        sats = {csat[i] for i in mem}
        if len(sats) > 1:
            return _no("group %r split over satellites" % (gid,))
    true = cost1 + sum(P.h[s] * w[s] for s in range(P.S)) + cost2
    obj_tol = max(1e-3, 1e-3 * abs(true)) if loose else 1e-6 * max(1.0, abs(true))
    if abs(obj - true) > obj_tol:
        return _no("objective %s != recomputed %s" % (obj, true))
    return {"feasible": True, "objective": true, "reason": ""}


def build_solution(P, snap):
    asg, R = snap
    load = [0] * P.S
    routes2 = []
    obj2 = 0.0
    for s in range(P.S):
        sid = P.sat_id[s]
        for seq in R[s]:
            if not seq:
                continue
            c, ld = P.route_eval(s, seq)
            load[s] += ld
            obj2 += c
            routes2.append({"satellite": sid, "route": [sid] + [P.cust_id[v - P.base] for v in seq] + [sid]})
    _, plan = P.e1_solve(tuple(load), plan=True)
    routes1 = []
    obj1 = 0.0
    for k, r in enumerate(plan):
        mask = 0
        for s, _ in r:
            mask |= 1 << s
        order = P.tsp(mask)[1]
        obj1 += P.tour_cost(order)
        routes1.append({"vehicle": k, "route": [P.depot_id] + [P.sat_id[s] for s in order] + [P.depot_id],
                        "deliveries": {str(P.sat_id[s]): amt for s, amt in r}})
    hand = sum(P.h[s] * load[s] for s in range(P.S))
    ga = {}
    for gid, mem in P.groups:
        if mem:
            ga[str(gid)] = P.sat_id[asg[P.blk[mem[0]]]]
    return {"objective_value": obj1 + hand + obj2, "first_echelon_routes": routes1,
            "second_echelon_routes": routes2, "group_assignments": ga,
            "solver": "MV2 roberti2018 2E-CVRPGC v%s (made with AI agents working in MV2's name)" % VERSION}


# ----------------------------------------------------------------------------------------------------- state
class State:
    """Group -> satellite assignment and route slots per satellite. Route lists are never mutated in place."""

    def __init__(self, P, lq, lc, lv):
        self.P = P
        self.lq, self.lc, self.lv = lq, lc, lv
        S = P.S
        self.asg = [None] * P.B
        self.R = [[[] for _ in range(P.slots[s])] for s in range(S)]
        self.rc = [[(0.0, 0) for _ in range(P.slots[s])] for s in range(S)]
        self.where = [0] * P.N
        self.load = [0] * S
        self.nr = 0
        self.cost2 = 0.0
        self.exq = 0
        self.e1 = 0.0
        self.j = None
        self.ja = None
        self._pending = None

    def sat_of(self, v):
        return self.asg[self.P.blk[v - self.P.base]]

    # totals
    def recompute(self):
        P = self.P
        c = 0.0
        ex = 0
        nr = 0
        load = [0] * P.S
        Q2 = P.Q2
        for s in range(P.S):
            for k in range(P.slots[s]):
                cc, ld = self.rc[s][k]
                c += cc
                load[s] += ld
                if ld > Q2:
                    ex += ld - Q2
                if self.R[s][k]:
                    nr += 1
        self.cost2, self.exq, self.nr, self.load = c, ex, nr, load
        self.e1 = P.e1_cost(tuple(load))

    def satpart(self, load):
        P = self.P
        v = 0.0
        for s in range(P.S):
            v += P.h[s] * load[s]
            e = load[s] - P.cap[s]
            if e > 0:
                v += self.lc * e
        return v

    def true_cost(self):
        P = self.P
        return self.cost2 + sum(P.h[s] * self.load[s] for s in range(P.S)) + self.e1

    def feasible(self):
        P = self.P
        if self.exq > FEAS_TOL or self.nr > P.T2:
            return False
        for s in range(P.S):
            if self.load[s] > P.cap[s] + FEAS_TOL:
                return False
        return True

    # journal
    def begin(self):
        self.j = {}
        self.ja = {}

    def set_route(self, s, k, seq):
        key = (s, k)
        if key not in self.j:
            self.j[key] = (self.R[s][k], self.rc[s][k])
        self.R[s][k] = seq
        self.rc[s][k] = self.P.route_eval(s, seq)
        w = self.where
        for v in seq:
            w[v] = k

    def set_asg(self, b, s):
        if b not in self.ja:
            self.ja[b] = self.asg[b]
        self.asg[b] = s

    def cur_loads(self):
        nl = list(self.load)
        if self.j:
            for (s, k), (_, orc) in self.j.items():
                nl[s] += self.rc[s][k][1] - orc[1]
        return nl

    def delta(self):
        P = self.P
        Q2 = P.Q2
        dc = 0.0
        dex = 0
        dnr = 0
        dl = None
        for (s, k), (oseq, orc) in self.j.items():
            nrc = self.rc[s][k]
            dc += nrc[0] - orc[0]
            nl, ol = nrc[1], orc[1]
            dex += (nl - Q2 if nl > Q2 else 0) - (ol - Q2 if ol > Q2 else 0)
            dnr += (1 if self.R[s][k] else 0) - (1 if oseq else 0)
            if nl != ol:
                if dl is None:
                    dl = {}
                dl[s] = dl.get(s, 0) + nl - ol
        newload = None
        e1n = self.e1
        dsat = 0.0
        if dl and any(x != 0 for x in dl.values()):
            newload = list(self.load)
            for s, x in dl.items():
                newload[s] += x
            dsat = self.satpart(newload) - self.satpart(self.load)
            e1n = P.e1_cost(tuple(newload))
        nr2 = self.nr + dnr
        dveh = self.lv * (max(0, nr2 - P.T2) - max(0, self.nr - P.T2))
        self._pending = (dc, dex, dnr, newload, e1n)
        return dc + self.lq * dex + dsat + (e1n - self.e1) + dveh

    def commit(self):
        dc, dex, dnr, newload, e1n = self._pending
        self.cost2 += dc
        self.exq += dex
        self.nr += dnr
        if newload is not None:
            self.load = newload
            self.e1 = e1n
        self.j = None
        self.ja = None

    def undo(self):
        w = self.where
        for (s, k), (seq, rc) in self.j.items():
            self.R[s][k] = seq
            self.rc[s][k] = rc
            for v in seq:
                w[v] = k
        for b, s in self.ja.items():
            self.asg[b] = s
        self.j = None
        self.ja = None

    # snapshots
    def snapshot(self):
        return (list(self.asg), [[list(r) for r in self.R[s]] for s in range(self.P.S)])

    def load_snap(self, snap):
        asg, R = snap
        P = self.P
        self.asg = list(asg)
        self.R = [[list(r) for r in R[s]] for s in range(P.S)]
        for s in range(P.S):
            for k in range(P.slots[s]):
                seq = self.R[s][k]
                self.rc[s][k] = P.route_eval(s, seq)
                for v in seq:
                    self.where[v] = k
        self.recompute()

    # insertion primitives
    def best_insert(self, s, v, rng=None, noise=0.0):
        P = self.P
        D = P.D
        Q2 = P.Q2
        lq = self.lq
        dv = P.dem[v]
        sn = 1 + s
        Dv = D[v]
        best = None
        empty_done = False
        open_pen = self.lv if self.nr >= P.T2 else 0.0
        Rs = self.R[s]
        rcs = self.rc[s]
        for k in range(P.slots[s]):
            seq = Rs[k]
            if not seq:
                if empty_done:
                    continue
                empty_done = True
                val = 2.0 * Dv[sn] + (lq * (dv - Q2) if dv > Q2 else 0.0) + open_pen
                if noise > 0:
                    val += noise * rng.random()
                if best is None or val < best[0]:
                    best = (val, k, 0)
                continue
            ld = rcs[k][1]
            nld = ld + dv
            pq = lq * ((nld - Q2 if nld > Q2 else 0) - (ld - Q2 if ld > Q2 else 0))
            prev = sn
            L = len(seq)
            for p in range(L + 1):
                nxt = seq[p] if p < L else sn
                val = D[prev][v] + Dv[nxt] - D[prev][nxt] + pq
                if noise > 0:
                    val += noise * rng.random()
                if best is None or val < best[0]:
                    best = (val, k, p)
                prev = nxt
        return best

    def insert_at(self, s, k, p, v):
        seq = self.R[s][k]
        self.set_route(s, k, seq[:p] + [v] + seq[p:])

    def remove_node(self, s, v):
        k = self.where[v]
        seq = self.R[s][k]
        self.set_route(s, k, [x for x in seq if x != v])

    def remove_block(self, b):
        s = self.asg[b]
        for v in self.P.bmem[b]:
            self.remove_node(s, v)

    def insert_block(self, b, s, rng=None, noise=0.0):
        self.set_asg(b, s)
        mem = list(self.P.bmem[b])
        if rng is not None:
            rng.shuffle(mem)
        for v in mem:
            _, k, p = self.best_insert(s, v, rng, noise)
            self.insert_at(s, k, p, v)

    def block_value(self, b, s, cl):
        """Estimated change of the penalised cost if removed block b goes to satellite s (loads cl)."""
        P = self.P
        ins = 0.0
        for v in P.bmem[b]:
            ins += self.best_insert(s, v)[0]
        nl = list(cl)
        nl[s] += P.bdem[b]
        return ins + self.satpart(nl) - self.satpart(cl) + P.e1_cost(tuple(nl)) - P.e1_cost(tuple(cl))

    def insert_block_best(self, b, rng, noise, exclude=None):
        P = self.P
        cl = self.cur_loads()
        best = None
        for s in P.usable:
            if s == exclude:
                continue
            val = self.block_value(b, s, cl)
            if noise > 0:
                val += noise * rng.random()
            if best is None or val < best[0]:
                best = (val, s)
        if best is None:
            return False
        self.insert_block(b, best[1], rng, 0.0)
        return True

    # moves (each returns False only before changing anything)
    def _cust(self, rng):
        v = self.P.base + rng.randrange(self.P.C)
        return v, self.sat_of(v)

    def mv_relocate(self, rng, best):
        v, s = self._cust(rng)
        self.remove_node(s, v)
        if best:
            _, k, p = self.best_insert(s, v)
        else:
            k = rng.randrange(self.P.slots[s])
            p = rng.randint(0, len(self.R[s][k]))
        self.insert_at(s, k, p, v)
        return True

    def mv_swap(self, rng):
        v, s = self._cust(rng)
        Rs = self.R[s]
        k1 = self.where[v]
        cand = [(k, i) for k in range(len(Rs)) for i, u in enumerate(Rs[k]) if u != v]
        if not cand:
            return False
        k2, i2 = rng.choice(cand)
        u = Rs[k2][i2]
        if k1 == k2:
            seq = list(Rs[k1])
            i1 = seq.index(v)
            seq[i1], seq[i2] = u, v
            self.set_route(s, k1, seq)
        else:
            self.set_route(s, k1, [u if x == v else x for x in Rs[k1]])
            self.set_route(s, k2, [v if x == u else x for x in Rs[k2]])
        return True

    def mv_2opt(self, rng):
        v, s = self._cust(rng)
        k = self.where[v]
        seq = self.R[s][k]
        if len(seq) < 3:
            return False
        i = rng.randrange(len(seq) - 1)
        j = rng.randrange(i + 1, len(seq))
        self.set_route(s, k, seq[:i] + seq[i:j + 1][::-1] + seq[j + 1:])
        return True

    def mv_2optstar(self, rng):
        v, s = self._cust(rng)
        m = self.P.slots[s]
        if m < 2:
            return False
        k1 = self.where[v]
        k2 = rng.randrange(m - 1)
        if k2 >= k1:
            k2 += 1
        A = self.R[s][k1]
        B = self.R[s][k2]
        i = rng.randint(0, len(A))
        j = rng.randint(0, len(B))
        if rng.random() < 0.5:
            nA = A[:i] + B[j:]
            nB = B[:j] + A[i:]
        else:
            nA = A[:i] + B[:j][::-1]
            nB = A[i:][::-1] + B[j:]
        self.set_route(s, k1, nA)
        self.set_route(s, k2, nB)
        return True

    def mv_group(self, rng, best):
        P = self.P
        b = rng.randrange(P.B)
        cur = self.asg[b]
        alts = [s for s in P.usable if s != cur]
        if not alts:
            return False
        if best:
            pick = None
            for s in alts:
                self.begin()
                self.remove_block(b)
                self.insert_block(b, s)
                d = self.delta()
                self.undo()
                if pick is None or d < pick[0]:
                    pick = (d, s)
            s = pick[1]
            self.begin()
            self.remove_block(b)
            self.insert_block(b, s)
        else:
            self.remove_block(b)
            self.insert_block(b, rng.choice(alts), rng)
        return True

    def mv_gswap(self, rng):
        P = self.P
        b1 = rng.randrange(P.B)
        s1 = self.asg[b1]
        others = [b for b in range(P.B) if self.asg[b] != s1]
        if not others:
            return False
        b2 = rng.choice(others)
        s2 = self.asg[b2]
        self.remove_block(b1)
        self.remove_block(b2)
        self.insert_block(b1, s2, rng)
        self.insert_block(b2, s1, rng)
        return True

    def mv_ruin(self, rng, near, qmax, noise):
        P = self.P
        if P.C < 2:
            return False
        v0 = rng.randrange(P.C)
        q = rng.randint(2, max(2, qmax))
        group = list(near[v0][:q])
        for v in group:
            self.remove_node(self.sat_of(v), v)
        if rng.random() < 0.5:
            rng.shuffle(group)
        else:
            group.sort(key=lambda v: -P.dem[v])
        for v in group:
            s = self.sat_of(v)
            _, k, p = self.best_insert(s, v, rng, noise)
            self.insert_at(s, k, p, v)
        return True

    def mv_bruin(self, rng, bnear, bqmax, noise):
        P = self.P
        if P.B < 1 or len(P.usable) < 2:
            return False
        b0 = rng.randrange(P.B)
        q = rng.randint(1, max(1, bqmax))
        blocks = list(bnear[b0][:q])
        for b in blocks:
            self.remove_block(b)
        if rng.random() < 0.5:
            rng.shuffle(blocks)
        else:
            blocks.sort(key=lambda b: -P.bdem[b])
        for b in blocks:
            self.insert_block_best(b, rng, noise)
        return True


# ---------------------------------------------------------------------------------------------------- search
def search(P, seed, t_end, offer, log):
    rng = random.Random(seed)
    C, base, D = P.C, P.base, P.D
    if C >= 2:
        tot = 0.0
        for i in range(C):
            Di = D[base + i]
            for j in range(C):
                if i != j:
                    tot += Di[base + j]
        avg = tot / (C * (C - 1))
    else:
        avg = max(1.0, max(D[0]))
    avg = max(avg, 1e-6)
    mean_dem = max(1e-9, P.total / max(1, C))
    lq0 = 2.0 * avg / mean_dem
    lc0 = lq0
    lv0 = 2.0 * avg
    st = State(P, lq0, lc0, lv0)
    near = [sorted(range(base, base + C), key=lambda u, v=base + i: (D[v][u], u)) for i in range(C)]
    cen = []
    for b in range(P.B):
        m = P.bmem[b]
        cen.append((sum(P.xs[v] for v in m) / len(m), sum(P.ys[v] for v in m) / len(m)))
    bnear = [sorted(range(P.B), key=lambda b2, b=b: ((cen[b][0] - cen[b2][0]) ** 2 + (cen[b][1] - cen[b2][1]) ** 2,
                                                     b2)) for b in range(P.B)]
    st.begin()
    for b in sorted(range(P.B), key=lambda b: (-P.bdem[b], rng.random())):
        st.insert_block_best(b, rng, 0.0)
    st.j = None
    st.ja = None
    st.recompute()
    log["construction"] = {"cost": round(st.true_cost(), 4), "feasible": st.feasible()}
    best = {"cost": None, "snap": None}

    def consider(source):
        st.recompute()
        if st.feasible():
            c = st.true_cost()
            if best["cost"] is None or c < best["cost"] - 1e-9:
                best["cost"] = c
                best["snap"] = st.snapshot()
                offer(best["snap"], source)

    consider("construction")
    qmax = max(2, min(15, C // 4))
    bqmax = max(1, min(4, P.B // 3))
    noise = 0.2 * avg
    t0 = time.monotonic()
    total = max(0.0, t_end - t0)
    plan = [("sa1", 0.40, 1.0), ("sa2", 0.27, 0.5), ("sa3", 0.20, 0.25), ("polish", 0.13, 0.0)]
    stats = {"iterations": 0, "accepted": 0, "phases": []}
    ph_start = t0
    for name, frac, scale in plan:
        ph_end = min(t_end, ph_start + frac * total)
        if name == "polish":
            ph_end = t_end
        if ph_end <= time.monotonic():
            break
        if name != "sa1" and best["snap"] is not None:
            st.load_snap(best["snap"])
        polish = scale == 0.0
        if polish:
            st.lq, st.lc, st.lv = lq0 * 1e4, lc0 * 1e4, lv0 * 1e4
        else:
            st.lq, st.lc, st.lv = max(st.lq, lq0), max(st.lc, lc0), max(st.lv, lv0)
        st.recompute()
        temp0 = 0.1 * avg * (scale if scale > 0 else 0.01)
        tend = 0.002 * avg if not polish else 1e-6 * avg
        temp = temp0
        it = 0
        acc = 0
        feas = 0
        cnt = 0
        start = time.monotonic()
        while True:
            if (it & 31) == 0:
                now = time.monotonic()
                if now >= ph_end:
                    break
                x = (now - start) / max(1e-9, ph_end - start)
                temp = temp0 * (tend / temp0) ** x if temp0 > tend else tend
            it += 1
            r = rng.random()
            st.begin()
            if r < 0.18:
                ok = st.mv_relocate(rng, True)
            elif r < 0.26:
                ok = st.mv_relocate(rng, False)
            elif r < 0.37:
                ok = st.mv_swap(rng)
            elif r < 0.48:
                ok = st.mv_2opt(rng)
            elif r < 0.58:
                ok = st.mv_2optstar(rng)
            elif r < 0.66:
                ok = st.mv_group(rng, True)
            elif r < 0.71:
                ok = st.mv_group(rng, False)
            elif r < 0.76:
                ok = st.mv_gswap(rng)
            elif r < 0.90:
                ok = st.mv_ruin(rng, near, qmax, noise)
            else:
                ok = st.mv_bruin(rng, bnear, bqmax, noise)
            if not ok:
                st.undo()
                continue
            dF = st.delta()
            if dF <= 1e-12 or rng.random() < math.exp(-dF / temp):
                st.commit()
                acc += 1
                if st.feasible() and (best["cost"] is None or st.true_cost() < best["cost"] - 1e-7):
                    consider(name)
            else:
                st.undo()
            cnt += 1
            if st.feasible():
                feas += 1
            if cnt >= 300:
                if not polish:
                    share = feas / float(cnt)
                    if share < 0.3:
                        st.lq = min(st.lq * 1.4, lq0 * 50)
                        st.lc = min(st.lc * 1.4, lc0 * 50)
                        st.lv = min(st.lv * 1.4, lv0 * 50)
                    elif share > 0.7:
                        st.lq = max(st.lq / 1.2, lq0 * 0.05)
                        st.lc = max(st.lc / 1.2, lc0 * 0.05)
                        st.lv = max(st.lv / 1.2, lv0 * 0.05)
                feas = 0
                cnt = 0
                st.recompute()
        stats["iterations"] += it
        stats["accepted"] += acc
        stats["phases"].append([name, it, acc, None if best["cost"] is None else round(best["cost"], 4)])
        ph_start = time.monotonic()
    stats["e1_evaluations"] = P.e1_calls
    log["search"] = stats
    return best["cost"], best["snap"]


# ----------------------------------------------------------------------------------------------------- driver
def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def solve(inst, out_path, time_limit, seed=1, workers=2, t0=None):
    T0 = T_START if t0 is None else t0
    P = Problem(inst)
    end = T0 + max(0.5, min(0.9 * time_limit, time_limit - 3.0))
    search_end = end - min(1.0, 0.08 * max(0.0, end - T0))
    log = {"version": VERSION, "seed": seed, "S": P.S, "C": P.C, "groups": len(P.groups), "blocks": P.B,
           "Q1": P.Q1, "Q2": P.Q2, "T1": P.T1, "T2": P.T2, "events": [], "workers": workers}
    best = {"obj": None, "sol": None, "last_write": 0.0, "source": None}

    def offer(snap, source):
        sol = build_solution(P, snap)
        v = verify(inst, sol, P)
        if not v["feasible"]:
            log.setdefault("verify_fail", []).append([source, v["reason"][:300]])
            return False
        cost = v["objective"]
        if best["obj"] is None or cost < best["obj"] - 1e-9:
            best["obj"], best["sol"], best["source"] = cost, sol, source
            log["events"].append([round(time.monotonic() - T0, 2), source, round(cost, 4)])
            now = time.monotonic()
            if out_path and (best["last_write"] == 0.0 or now - best["last_write"] >= 0.5):
                write_json(out_path, sol)
                best["last_write"] = now
            return True
        return False

    child, conn = None, None
    if workers >= 2 and hasattr(os, "fork"):
        try:
            import multiprocessing as mp
            ctx = mp.get_context("fork")
            conn, cconn = ctx.Pipe(duplex=False)

            def run_child():
                try:
                    clog = {}
                    cost, snap = search(P, seed + 7919, search_end, lambda s, src: None, clog)
                    cconn.send((cost, snap, clog.get("search")))
                except Exception as e:  # noqa: BLE001
                    cconn.send((None, None, repr(e)[:300]))
                finally:
                    cconn.close()

            child = ctx.Process(target=run_child, daemon=True)
            child.start()
        except Exception as e:  # noqa: BLE001
            log["fork_error"] = repr(e)[:300]
            child = None
    search(P, seed, search_end, offer, log)
    if child is not None:
        try:
            if conn.poll(max(0.05, end - time.monotonic() - 0.2)):
                ccost, csnap, cstats = conn.recv()
                log["child"] = {"cost": ccost, "search": cstats}
                if csnap is not None:
                    offer(csnap, "child")
            else:
                log["child"] = "no answer in time"
        except Exception as e:  # noqa: BLE001
            log["child_error"] = repr(e)[:300]
        try:
            child.terminate()
        except Exception:  # noqa: BLE001
            pass
    if best["sol"] is not None and out_path:
        write_json(out_path, best["sol"])
    log["final_objective"] = best["obj"]
    log["best_source"] = best["source"]
    if best["sol"] is not None:
        log["trucks"] = len(best["sol"]["first_echelon_routes"])
        log["routes2"] = len(best["sol"]["second_echelon_routes"])
    log["wall_s"] = round(time.monotonic() - T0, 3)
    return best["sol"], log


def main(argv=None):
    ap = argparse.ArgumentParser(description="roberti2018 (2E-CVRPGC) solver, MV2 of Munim, Inc.")
    ap.add_argument("--problem", default=SLUG)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=int(os.environ.get("MV2_ROBERTI_SEED", "1")))
    ap.add_argument("--workers", type=int, default=int(os.environ.get("MV2_ROBERTI_WORKERS", "2")))
    a, _ = ap.parse_known_args(argv)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    sol, log = solve(inst, a.output, a.time_limit, a.seed, a.workers)
    if os.environ.get("MV2_ROBERTI_LOG") == "1":
        try:
            write_json(a.output + ".log.json", log)
        except Exception:  # noqa: BLE001
            pass
    sys.stderr.write(json.dumps({k: log.get(k) for k in ("version", "S", "C", "blocks", "construction",
                                                         "final_objective", "best_source", "trucks", "routes2",
                                                         "wall_s")}) + "\n")
    return 0 if sol is not None else 1


if __name__ == "__main__":
    sys.exit(main())

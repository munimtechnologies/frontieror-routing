"""MV2 ESVRPTW engine v0.1.0 for FrontierOR task reinhardt2016 (standard library only).

The edge set cost vehicle routing problem with time windows (Reinhardt, Jepsen and Pisinger, Transportation Science
2016): a VRPTW from one depot in which every undirected edge is either free or belongs to an edge set; the first use
of any edge of a set costs that set's access cost once, after which all its edges are open to every vehicle.
Minimise travel distance + the access costs of the sets used.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python solve.py --problem reinhardt2016 --instance in.json --output out.json --time-limit 60 [--seed 1]

Rules, read on 2026-11-14 in the public FrontierOR reinhardt2016 files (Hugging Face frontieror/FrontierOR, CC BY 4.0:
problem_description.txt, gurobi_code.py, feasibility_check.py):
- nodes 0 (depot) and 1..n; distance_matrix is both cost and travel time; the time on arc (i, j) is
  distance(i, j) + service_time(i);
- a route starts at the depot at the depot's time_window_start, waits if early, must start service at every customer
  by its time_window_end and must be back at the depot by schedule_horizon; total demand <= vehicle_capacity; at most
  num_vehicles routes; every customer exactly once;
- every arc of a route whose edge is in an edge set needs that set in edge_sets_used; objective = sum of the
  distances of all arcs + the access costs of all sets in edge_sets_used (the checker allows 1.0 of difference).

Method: one search on the true objective. The solution keeps, for every edge set, how many of its arcs are in use, so
the exact change of the total (distance + access costs of sets that become used or unused) of inserting a customer
anywhere is known in O(1). Time windows are checked in O(1) per position with each route's earliest service starts
and latest feasible starts. The search is slack induction by string removals (SISR, Christiaens and Vanden Berghe
2020) with simulated annealing, plus two edge-set moves: 'drop' (remove every customer touching a used set's arcs and
re-insert them while that set is banned, unless a customer cannot go anywhere else) and 'open' (remove some customers
covered by an unused set and re-insert them as if that set were free). Every written solution passes verify(), a
mirror of the official checker.
"""
import argparse
import json
import math
import os
import random
import sys
import time

VERSION = "0.1.0"
EPS = 1e-7          # our insertion test margin
EPS_ROUTE = 1e-6    # our full route test margin (still far inside the checker's 1e-4)
CHK_TOL = 1e-4      # official checker: time windows, capacity
OBJ_TOL = 1.0       # official checker: |reported - recomputed| objective


class Problem:
    def __init__(self, inst):
        self.n = n = int(inst["num_customers"])
        nv = inst.get("num_vehicles")
        self.K = int(nv) if nv is not None else n
        self.Q = float(inst["vehicle_capacity"])
        self.H = float(inst["schedule_horizon"])
        self.d = [[float(v) for v in row] for row in inst["distance_matrix"]]
        N = n + 1
        self.N = N
        nd = {}
        for x in inst["nodes"]:
            nd[int(x["id"])] = x
        self.e = [float(nd[i]["time_window_start"]) for i in range(N)]
        self.l = [float(nd[i]["time_window_end"]) for i in range(N)]
        self.s = [float(nd[i].get("service_time", 0) or 0) for i in range(N)]
        self.q = [float(nd[i].get("demand", 0) or 0) for i in range(N)]
        self.q[0] = 0.0
        self.cust = list(range(1, N))
        # edge sets: internal index x -> instance id, cost, covered customers; need[a][b] = sets arc a->b needs
        self.set_ids = []
        self.cost = []
        self.cover = []
        need = [[() for _ in range(N)] for _ in range(N)]
        for es in inst.get("edge_sets") or []:
            x = len(self.set_ids)
            self.set_ids.append(es["id"])
            self.cost.append(float(es["access_cost"]))
            cov = set()
            for edge in es.get("edges") or []:
                u, v = int(edge[0]), int(edge[1])
                if not (0 <= u < N and 0 <= v < N):
                    continue
                for a, b in ((u, v), (v, u)):
                    if x not in need[a][b]:
                        need[a][b] = need[a][b] + (x,)
                if u != 0:
                    cov.add(u)
                if v != 0:
                    cov.add(v)
            self.cover.append(sorted(cov))
        self.need = need
        self.R = len(self.set_ids)
        self.multi_set_arcs = sum(1 for a in range(N) for b in range(N) if len(need[a][b]) > 1)
        self.nbr = {}
        for i in self.cust:
            o = [j for j in self.cust if j != i]
            o.sort(key=lambda j: self.d[i][j] + self.d[j][i])
            self.nbr[i] = o
        self.avg_dep = (sum(self.d[0][i] for i in self.cust) / n) if n else 1.0
        if self.avg_dep <= 0:
            self.avg_dep = 1.0

    # ---- one route ---------------------------------------------------------------------------------------------
    def forward(self, r, tol=EPS_ROUTE):
        """Earliest service starts along r (the official checker's own timing), or None if a window/horizon fails."""
        d, e, l, s = self.d, self.e, self.l, self.s
        t = e[0]
        prev = 0
        E = []
        for j in r:
            t = t + (d[prev][j] + s[prev])
            if t < e[j]:
                t = e[j]
            if t > l[j] + tol:
                return None
            E.append(t)
            prev = j
        if r and t + (d[prev][0] + s[prev]) > self.H + tol:
            return None
        return E

    def latest(self, r):
        """Latest service start at every position such that the rest of r stays feasible."""
        d, l, s = self.d, self.l, self.s
        m = len(r)
        L = [0.0] * m
        lim = self.H
        nxt = 0
        for k in range(m - 1, -1, -1):
            j = r[k]
            v = lim - (d[j][nxt] + s[j])
            if v > l[j]:
                v = l[j]
            L[k] = v
            lim = v
            nxt = j
        return L

    def route_dist(self, r):
        d = self.d
        prev = 0
        t = 0.0
        for j in r:
            t += d[prev][j]
            prev = j
        return t + d[prev][0] if r else 0.0

    def route_ok(self, r):
        if sum(self.q[j] for j in r) > self.Q + EPS_ROUTE:
            return False
        return self.forward(r) is not None

    def sets_of(self, routes):
        used = set()
        need = self.need
        for r in routes:
            prev = 0
            for j in list(r) + [0]:
                for x in need[prev][j]:
                    used.add(x)
                prev = j
        return used

    def total(self, routes):
        return sum(self.route_dist(r) for r in routes) + sum(self.cost[x] for x in self.sets_of(routes))

    def valid(self, routes):
        routes = [r for r in routes if r]
        if len(routes) > self.K:
            return False
        flat = sorted(j for r in routes for j in r)
        if flat != self.cust:
            return False
        return all(self.route_ok(r) for r in routes)

    def set_delta(self, cnt, rem, a1, a2, banned=None, free=None):
        """Change of the access-cost part when arcs needing rem go and arcs needing a1, a2 come; None if banned."""
        delta = 0.0
        seen = ()
        for x in rem + a1 + a2:
            if x in seen:
                continue
            seen = seen + (x,)
            if banned is not None and x in banned and (x in a1 or x in a2):
                return None
            c = cnt[x]
            new = c - (1 if x in rem else 0) + (1 if x in a1 else 0) + (1 if x in a2 else 0)
            if (new > 0) != (c > 0):
                w = 0.0 if (free is not None and x in free) else self.cost[x]
                delta += w if new > 0 else -w
        return delta


# ---- solution output and the official checker's rules ----------------------------------------------------------------
def build_solution(P, routes):
    routes = [list(r) for r in routes if r]
    d, e, s = P.d, P.e, P.s
    out = []
    total_arc = 0.0
    used = set()
    for vi, r in enumerate(routes):
        seq = [0] + r + [0]
        arcs = []
        times = {"0": e[0]}
        cur = e[0]
        for k in range(len(seq) - 1):
            i, j = seq[k], seq[k + 1]
            arcs.append([i, j])
            total_arc += d[i][j]
            for x in P.need[i][j]:
                used.add(x)
            arrival = cur + (d[i][j] + s[i])
            if j != 0:
                if arrival < e[j]:
                    arrival = e[j]
                times[str(j)] = arrival
                cur = arrival
        out.append({"vehicle": vi, "sequence": seq, "arcs": arcs, "visit_times": times})
    ids = sorted({P.set_ids[x] for x in used}, key=lambda v: (str(type(v)), v))
    cost_by_id = {}
    for x in range(P.R):
        cost_by_id[P.set_ids[x]] = P.cost[x]
    obj = total_arc + sum(cost_by_id[i] for i in set(ids))
    return {"objective_value": obj, "routes": out, "edge_sets_used": ids}


def verify(inst, sol):
    """Mirror of the official reinhardt2016 feasibility_check.py: {"feasible", "objective", "reason"}."""
    bad = []
    if not isinstance(sol, dict):
        return {"feasible": False, "objective": None, "reason": "not an object"}
    for f in ("edge_sets_used", "objective_value", "routes"):
        if sol.get(f) is None:
            bad.append("missing " + f)
    ov = sol.get("objective_value")
    if isinstance(ov, bool) or not isinstance(ov, (int, float)) or ov != ov or ov in (float("inf"), float("-inf")):
        bad.append("objective_value must be a finite number")
    if bad:
        return {"feasible": False, "objective": None, "reason": "; ".join(bad)}
    status = sol.get("status", sol.get("status_name", ""))
    sl = str(status).lower() if status else ""
    if "infeasible" in sl or "no_solution" in sl or status is None:
        return {"feasible": False, "objective": None, "reason": "status says no solution"}
    try:
        return _verify(inst, sol)
    except Exception as ex:  # noqa: BLE001 - the official program turns exceptions into a rejection
        return {"feasible": False, "objective": None, "reason": "malformed: " + repr(ex)[:200]}


def _verify(inst, sol):
    tol = CHK_TOL
    bad = []
    nodes = {nd["id"]: nd for nd in inst["nodes"]}
    dist = inst["distance_matrix"]
    n = inst["num_customers"]
    Q = inst["vehicle_capacity"]
    H = inst["schedule_horizon"]
    customers = set(range(1, n + 1))
    arc_set, set_cost = {}, {}
    for es in inst["edge_sets"]:
        set_cost[es["id"]] = es["access_cost"]
        for edge in es["edges"]:
            arc_set[(edge[0], edge[1])] = es["id"]
            arc_set[(edge[1], edge[0])] = es["id"]
    routes = sol.get("routes", [])
    used_ids = set(sol.get("edge_sets_used", []))
    for ridx, route in enumerate(routes):
        for v in route.get("sequence", []):
            if v not in nodes:
                bad.append("domain sequence")
        for a in route.get("arcs", []):
            for v in a[:2]:
                if v not in nodes:
                    bad.append("domain arc")
        for key in route.get("visit_times", {}):
            try:
                nid = int(key)
            except (ValueError, TypeError):
                nid = None
            if nid not in nodes:
                bad.append("domain visit_times")
    for x in used_ids:
        if x not in set_cost:
            bad.append("domain set id")
    if bad:
        return {"feasible": False, "objective": None, "reason": "; ".join(bad[:5])}
    K = inst.get("num_vehicles")
    if K is not None and len(routes) > K:
        bad.append("fleet")
    seen = set()
    for route in routes:
        for c in [v for v in route.get("sequence", []) if v != 0]:
            if c in seen:
                bad.append("visited twice %s" % c)
            seen.add(c)
    if customers - seen:
        bad.append("not visited %s" % sorted(customers - seen)[:5])
    if seen - customers:
        bad.append("invalid nodes")
    total_arc = 0.0
    needed = set()
    for ridx, route in enumerate(routes):
        seq = route.get("sequence", [])
        if len(seq) < 2:
            bad.append("route %d too short" % ridx)
            continue
        if seq[0] != 0 or seq[-1] != 0:
            bad.append("route %d ends" % ridx)
        if sum(nodes[c]["demand"] for c in seq if c != 0) > Q + tol:
            bad.append("route %d capacity" % ridx)
        cur = nodes[0]["time_window_start"]
        for k in range(len(seq) - 1):
            i, j = seq[k], seq[k + 1]
            arrival = cur + (dist[i][j] + nodes[i]["service_time"])
            total_arc += dist[i][j]
            if (i, j) in arc_set:
                needed.add(arc_set[(i, j)])
            if j == 0:
                if arrival > H + tol:
                    bad.append("route %d horizon" % ridx)
            else:
                arrival = max(arrival, nodes[j]["time_window_start"])
                if arrival > nodes[j]["time_window_end"] + tol:
                    bad.append("route %d window %s" % (ridx, j))
                cur = arrival
    for ridx, route in enumerate(routes):
        vt = route.get("visit_times", {}) if isinstance(route, dict) else {}
        for key, t in vt.items():
            try:
                nid = int(key)
            except (ValueError, TypeError):
                nid = key
            if not isinstance(t, (int, float)):
                bad.append("visit_times not numeric")
                continue
            if t < -tol:
                bad.append("visit_times negative")
            if nid in nodes:
                lo, hi = nodes[nid].get("time_window_start"), nodes[nid].get("time_window_end")
                if lo is not None and t < lo - tol:
                    bad.append("visit_times below window %s" % key)
                if hi is not None and t > hi + tol:
                    bad.append("visit_times above window %s" % key)
    for x in needed:
        if x not in used_ids:
            bad.append("edge set %s needed but not paid" % x)
    obj = total_arc + sum(set_cost[x] for x in used_ids)
    rep = sol.get("objective_value")
    if rep is not None and abs(obj - rep) > OBJ_TOL:
        bad.append("objective mismatch")
    return {"feasible": not bad, "objective": obj, "reason": "; ".join(bad[:5])}


# ---- search state -----------------------------------------------------------------------------------------------------
class State:
    __slots__ = ("routes", "E", "L", "load", "dist", "cnt")

    def __init__(self, P, routes=()):
        self.routes = [list(r) for r in routes if r]
        self.E, self.L, self.load, self.dist = [], [], [], []
        for k in range(len(self.routes)):
            self.E.append(None)
            self.L.append(None)
            self.load.append(0.0)
            self.dist.append(0.0)
            self.refresh(P, k)
        self.cnt = [0] * P.R
        self.recount(P)

    def copy(self):
        st = State.__new__(State)
        st.routes = [r[:] for r in self.routes]
        st.E = list(self.E)
        st.L = list(self.L)
        st.load = list(self.load)
        st.dist = list(self.dist)
        st.cnt = list(self.cnt)
        return st

    def refresh(self, P, k):
        r = self.routes[k]
        E = P.forward(r)
        if E is None:
            raise RuntimeError("internal: infeasible route after an insertion")
        self.E[k] = E
        self.L[k] = P.latest(r)
        self.load[k] = sum(P.q[j] for j in r)
        self.dist[k] = P.route_dist(r)

    def recount(self, P):
        cnt = [0] * P.R
        need = P.need
        for r in self.routes:
            prev = 0
            for j in r:
                for x in need[prev][j]:
                    cnt[x] += 1
                prev = j
            if r:
                for x in need[prev][0]:
                    cnt[x] += 1
        self.cnt = cnt

    def compact(self):
        keep = [k for k, r in enumerate(self.routes) if r]
        if len(keep) != len(self.routes):
            self.routes = [self.routes[k] for k in keep]
            self.E = [self.E[k] for k in keep]
            self.L = [self.L[k] for k in keep]
            self.load = [self.load[k] for k in keep]
            self.dist = [self.dist[k] for k in keep]

    def total(self, P):
        c = sum(self.dist)
        for x in range(P.R):
            if self.cnt[x] > 0:
                c += P.cost[x]
        return c


def remove_customers(P, st, gone):
    """Remove the customers in gone. Distances rounded to one decimal can break the triangle inequality, so a route
    can become infeasible when a customer leaves it; such a route is emptied too. Returns those extra customers."""
    gone = set(gone)
    extra = []
    for k, r in enumerate(st.routes):
        if any(j in gone for j in r):
            nr = [j for j in r if j not in gone]
            if nr and P.forward(nr) is None:
                extra.extend(nr)
                nr = []
            st.routes[k] = nr
            if nr:
                st.refresh(P, k)
    st.compact()
    st.recount(P)
    return extra


def ruin_sisr(P, st, rng, cbar=10.0, Lmax=10.0):
    routes = st.routes
    if not routes:
        return []
    where = {}
    for ri, r in enumerate(routes):
        for v in r:
            where[v] = ri
    avg = sum(len(r) for r in routes) / len(routes)
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
        r = routes[ri]
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


def ruin_drop_set(P, st, rng):
    used = [x for x in range(P.R) if st.cnt[x] > 0]
    if not used:
        return None, None
    x = rng.choices(used, weights=[max(1e-9, P.cost[y]) for y in used])[0]
    need = P.need
    gone = set()
    for r in st.routes:
        prev = 0
        for j in r + [0]:
            if x in need[prev][j]:
                if prev:
                    gone.add(prev)
                if j:
                    gone.add(j)
            prev = j
    removed = sorted(gone)
    removed.extend(remove_customers(P, st, removed))
    return removed, x


def ruin_open_set(P, st, rng):
    unused = [x for x in range(P.R) if st.cnt[x] == 0 and P.cover[x]]
    if not unused:
        return None, None
    x = rng.choice(unused)
    cand = list(P.cover[x])
    rng.shuffle(cand)
    removed = cand[:max(2, min(15, len(cand) // 2 + 1))]
    removed.extend(remove_customers(P, st, removed))
    return removed, x


def recreate(P, st, removed, rng, blink=0.01, banned=None, free=None):
    """Insert every removed customer at its cheapest feasible place (true objective change). False if impossible."""
    d, e, l, s, q, need, Q, H = P.d, P.e, P.l, P.s, P.q, P.need, P.Q, P.H
    mode = rng.random()
    if mode < 0.3:
        rng.shuffle(removed)
    elif mode < 0.5:
        removed.sort(key=lambda v: -q[v])
    elif mode < 0.7:
        removed.sort(key=lambda v: -d[0][v])
    elif mode < 0.85:
        removed.sort(key=lambda v: l[v] - e[v])
    else:
        removed.sort(key=lambda v: e[v])
    e0, s0 = e[0], s[0]
    for u in removed:
        eu, lu, su, qu = e[u], l[u], s[u], q[u]
        du = d[u]
        placed = False
        for ban in ((banned, None) if banned is not None else (None,)):
            best = None
            bri, bk = -1, 0
            cnt = st.cnt
            for ri in range(len(st.routes)):
                if st.load[ri] + qu > Q + EPS:
                    continue
                r = st.routes[ri]
                E, L = st.E[ri], st.L[ri]
                m = len(r)
                prev = 0
                tprev = e0
                for k in range(m + 1):
                    nxt = r[k] if k < m else 0
                    tu = tprev + (d[prev][u] + s[prev])
                    if tu < eu:
                        tu = eu
                    if tu <= lu + EPS:
                        raw = tu + (du[nxt] + su)
                        if raw <= (L[k] if k < m else H) + EPS:
                            delta = d[prev][u] + du[nxt] - d[prev][nxt]
                            nab, n1, n2 = need[prev][nxt], need[prev][u], need[u][nxt]
                            ok = True
                            if nab or n1 or n2:
                                sd = P.set_delta(cnt, nab, n1, n2, ban, free)
                                if sd is None:
                                    ok = False
                                else:
                                    delta += sd
                            if ok and (best is None or delta < best) and (blink <= 0 or rng.random() >= blink):
                                best, bri, bk = delta, ri, k
                    if k < m:
                        tprev = E[k]
                        prev = nxt
            if len(st.routes) < P.K and qu <= Q + EPS:
                tu = e0 + (d[0][u] + s0)
                if tu < eu:
                    tu = eu
                if tu <= lu + EPS and tu + (du[0] + su) <= H + EPS:
                    sd = P.set_delta(cnt, (), need[0][u], need[u][0], ban, free)
                    if sd is not None:
                        delta = d[0][u] + du[0] + sd
                        if best is None or delta < best:
                            best, bri, bk = delta, -1, 0
            if best is None:
                continue
            if bri < 0:
                st.routes.append([u])
                st.E.append(None)
                st.L.append(None)
                st.load.append(0.0)
                st.dist.append(0.0)
                st.refresh(P, len(st.routes) - 1)
                for x in need[0][u]:
                    cnt[x] += 1
                for x in need[u][0]:
                    cnt[x] += 1
            else:
                r = st.routes[bri]
                prev = r[bk - 1] if bk > 0 else 0
                nxt = r[bk] if bk < len(r) else 0
                for x in need[prev][nxt]:
                    cnt[x] -= 1
                for x in need[prev][u]:
                    cnt[x] += 1
                for x in need[u][nxt]:
                    cnt[x] += 1
                r.insert(bk, u)
                st.refresh(P, bri)
            placed = True
            break
        if not placed:
            return False
    return True


def construct(P, rng, banned=None, tries=12):
    for t in range(tries):
        st = State(P)
        order = list(P.cust)
        if t == 0:
            order.sort(key=lambda v: (P.l[v], v))
            ok = recreate_fixed(P, st, order, rng, banned)
        else:
            ok = recreate(P, st, order, rng, blink=0.0 if t < 3 else 0.05, banned=banned)
        if ok:
            return st
    return None


def recreate_fixed(P, st, order, rng, banned):
    """recreate() keeps the given order only through its 'random' branch; force a deterministic first build."""
    class _R:
        def random(self):
            return 0.9  # sort by window start: a classic VRPTW construction order
    return recreate(P, st, order, _R(), blink=0.0, banned=banned)


def own_search(P, deadline, rng, on_best=None, log=None):
    starts = []
    for name, ban in (("construct", None), ("construct-no-sets", set(range(P.R)) if P.R else None)):
        st = construct(P, rng, ban)
        if st is not None:
            starts.append((st.total(P), name, st))
    if not starts:
        if log is not None:
            log["error"] = "no construction"
        return None, math.inf
    starts.sort(key=lambda z: z[0])
    cur_c, src, cur = starts[0]
    best, best_c = cur.copy(), cur_c
    if on_best:
        on_best(best.routes, best_c, src)
    T0 = max(1e-6, 0.3 * P.avg_dep)
    Tf = max(1e-7, 0.003 * P.avg_dep)
    t_begin = time.monotonic()
    span = max(1e-6, deadline - t_begin)
    it = acc = imp = fails = 0
    moves = {"sisr": [0, 0, 0], "drop": [0, 0, 0], "open": [0, 0, 0]}
    last_imp = 0
    events = [(0.0, round(best_c, 4), src)]
    last_write = t_begin
    T = T0
    while True:
        if (it & 7) == 0:
            now = time.monotonic()
            if now >= deadline:
                break
            T = T0 * (Tf / T0) ** min(1.0, (now - t_begin) / span)
        it += 1
        cand = cur.copy()
        u = rng.random()
        banned = free = None
        if P.R and u < 0.08:
            kind = "drop"
            removed, x = ruin_drop_set(P, cand, rng)
            if removed is not None:
                banned = {x}
        elif P.R and u < 0.14:
            kind = "open"
            removed, x = ruin_open_set(P, cand, rng)
            if removed is not None:
                free = {x}
        else:
            kind = "sisr"
            removed = ruin_sisr(P, cand, rng)
        if not removed:
            continue
        moves[kind][0] += 1
        if not recreate(P, cand, removed, rng, banned=banned, free=free):
            fails += 1
            continue
        c = cand.total(P)
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
                    on_best(best.routes, best_c, "own")
                    last_write = now
        if it - last_imp > 4000:
            cur, cur_c = best.copy(), best_c
            last_imp = it
    if log is not None:
        log.update({"iterations": it, "accepted": acc, "improved": imp, "recreate_failed": fails, "moves": moves,
                    "starts": [(round(c, 4), nme) for c, nme, _ in starts],
                    "events": events[:3] + events[-12:] if len(events) > 15 else events})
    return best.routes, best_c


# ---- driver ----------------------------------------------------------------------------------------------------------
def solve(inst, time_limit=60.0, seed=1, t_start=None, on_write=None, log=None, budget=None):
    t_start = time.monotonic() if t_start is None else t_start
    if budget is None:
        budget = max(0.3, min(0.9 * time_limit, time_limit - 3.0) - 1.0)
    deadline = t_start + budget
    rng = random.Random(seed)
    P = Problem(inst)
    best = {"routes": None, "cost": math.inf, "src": None}

    def offer(routes, cost, src):
        if routes is None or cost >= best["cost"] - 1e-9 or not P.valid(routes):
            return
        sol = build_solution(P, routes)
        if not verify(inst, sol)["feasible"]:
            return
        best.update(routes=[list(r) for r in routes if r], cost=cost, src=src)
        if on_write is not None:
            on_write(sol)

    routes, c = own_search(P, deadline, rng, on_best=offer, log=log)
    offer(routes, c, "own")
    if best["routes"] is None:
        if log is not None:
            log.update({"version": VERSION, "error": "no feasible solution found"})
        return None
    sol = build_solution(P, best["routes"])
    if log is not None:
        log.update({"version": VERSION, "seed": seed, "n": P.n, "K": P.K, "capacity": P.Q, "edge_sets": P.R,
                    "multi_set_arcs": P.multi_set_arcs, "depot_window_end": P.l[0], "schedule_horizon": P.H,
                    "routes": len(sol["routes"]), "sets_used": len(sol["edge_sets_used"]),
                    "access_cost": round(sum(P.cost[x] for x in P.sets_of(best["routes"])), 6),
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
    ap.add_argument("--problem", default="reinhardt2016")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=int(os.environ.get("MV2_ESV_SEED", "1")))
    a = ap.parse_args(argv)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    log = {} if os.environ.get("MV2_ESV_LOG") == "1" else None
    sol = solve(inst, a.time_limit, a.seed, t_start=t_start, on_write=lambda s: write_json(a.output, s), log=log)
    if sol is not None:
        write_json(a.output, sol)
    if log is not None:
        write_json(a.output + ".log.json", log)
    return 0 if sol is not None else 1


if __name__ == "__main__":
    sys.exit(main())

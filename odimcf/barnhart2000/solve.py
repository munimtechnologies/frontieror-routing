"""barnhart2000 (ODIMCF: origin-destination integer multicommodity flow) solver for the FrontierOR Challenge.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Problem (Barnhart, Hane & Vance, Operations Research 48(2), 2000): route each commodity unsplit on one simple path
of a capacitated directed network, or reject it at a penalty (its lost revenue); minimise routing cost plus rejected
penalties.

Pipeline (each step offers its solution to the incumbent, which is written atomically; frontier_runtime's watchdog
ends the process before the limit):
1. all commodities rejected (always feasible, written at once);
2. three greedy insertions (value per unit of demand, value per unit of demand-hop, value) on min-cost, then min-hop
   paths through the residual network;
3. path-based column generation on the LP relaxation (scipy linprog / HiGHS), priced with one Dijkstra per origin
   and demand class (scipy.sparse.csgraph). Every pricing round also gives a Lagrangian lower bound that is valid for
   any multipliers, so the solver can stop early when it has proved its solution optimal;
4. LP rounding, then the restricted master problem solved as a MIP (scipy milp / HiGHS) over all generated paths;
5. ruin-and-recreate local search for the rest of the time: insert a rejected commodity on the path that is cheapest
   to clear, evict the cheapest blockers, re-insert them and other rejected commodities, keep the move if the
   objective does not get worse.
Without numpy/scipy, steps 3-4 are skipped.

Rejection penalty: see penalty_mode (the same reading as odimcf_check.py; OPEN QUESTION until the official
checker is readable).
"""
import bisect
import heapq
import json
import math
import random
import sys
import time

import frontier_runtime as R

try:
    import numpy as np
    import scipy.sparse as sp
    from scipy.optimize import Bounds, LinearConstraint, linprog, milp
    from scipy.sparse.csgraph import dijkstra as cs_dijkstra
    HAVE_SCIPY = True
except Exception:  # noqa: BLE001
    HAVE_SCIPY = False

INF = float("inf")


def log(**kw):
    sys.stderr.write("odimcf log " + json.dumps(kw, default=str) + "\n")


def _close(a, b):
    return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(b)))


def penalty_mode(coms):
    if coms and all("revenue" in c and _close(c["artificial_arc_cost"], c["revenue"]) for c in coms):
        return "total"
    if coms and all("revenue" in c and _close(c["artificial_arc_cost"] * c["demand"], c["revenue"]) for c in coms):
        return "per_unit"
    return "per_unit"


class Model:
    def __init__(self, inst):
        net = inst["network"]
        arcs = net["arcs"]
        coms = inst["commodities"]["commodity_list"]
        ids = list(net.get("nodes") or [])
        seen = set(ids)
        for a in arcs:
            for v in (a["from_node"], a["to_node"]):
                if v not in seen:
                    seen.add(v)
                    ids.append(v)
        for c in coms:
            for v in (c["origin"], c["destination"]):
                if v not in seen:
                    seen.add(v)
                    ids.append(v)
        self.node_ids = ids
        nidx = {v: i for i, v in enumerate(ids)}
        self.N = len(ids)
        self.A = len(arcs)
        self.arc_ids = [a["arc_id"] for a in arcs]
        self.tail = [nidx[a["from_node"]] for a in arcs]
        self.head = [nidx[a["to_node"]] for a in arcs]
        self.cap = [float(a["capacity"]) for a in arcs]
        self.cost = [float(a.get("cost", 0) or 0) for a in arcs]
        self.out = [[] for _ in range(self.N)]
        self.inn = [[] for _ in range(self.N)]
        for j in range(self.A):
            if self.tail[j] != self.head[j]:
                self.out[self.tail[j]].append(j)
                self.inn[self.head[j]].append(j)
        self.K = len(coms)
        self.com_ids = [c["commodity_id"] for c in coms]
        self.orig = [nidx[c["origin"]] for c in coms]
        self.dest = [nidx[c["destination"]] for c in coms]
        self.dem = [float(c["demand"]) for c in coms]
        self.mode = penalty_mode(coms)
        self.pen = [float(c["artificial_arc_cost"]) * (float(c["demand"]) if self.mode == "per_unit" else 1.0)
                    for c in coms]
        self.trivial = [self.orig[k] == self.dest[k] for k in range(self.K)]
        self.impossible = [False] * self.K
        self.base_obj = sum(self.pen)

    def path_cost(self, k, p):
        return self.dem[k] * sum(self.cost[a] for a in p)

    def compute_reach(self):
        """Mark commodities that have no path over arcs with capacity >= demand."""
        memo = {}
        for k in range(self.K):
            if self.trivial[k]:
                continue
            key = (self.orig[k], self.dem[k])
            if key not in memo:
                d = self.dem[k]
                seen = {self.orig[k]}
                stack = [self.orig[k]]
                while stack:
                    u = stack.pop()
                    for a in self.out[u]:
                        v = self.head[a]
                        if v not in seen and self.cap[a] >= d - 1e-9:
                            seen.add(v)
                            stack.append(v)
                memo[key] = seen
            if self.dest[k] not in memo[key]:
                self.impossible[k] = True

    def min_hops(self):
        """Hop distance origin -> destination ignoring capacity (for greedy ordering)."""
        res = [1] * self.K
        by_o = {}
        for k in range(self.K):
            by_o.setdefault(self.orig[k], []).append(k)
        for o, ks in by_o.items():
            dist = {o: 0}
            q = [o]
            i = 0
            while i < len(q):
                u = q[i]
                i += 1
                for a in self.out[u]:
                    v = self.head[a]
                    if v not in dist:
                        dist[v] = dist[u] + 1
                        q.append(v)
            for k in ks:
                res[k] = max(1, dist.get(self.dest[k], self.N))
        return res


class State:
    def __init__(self, m):
        self.m = m
        self.route = [None] * m.K
        self.res = list(m.cap)
        self.users = [set() for _ in range(m.A)]
        self.obj = m.base_obj
        self.journal = []

    def fits(self, k, p):
        d = self.m.dem[k]
        res = self.res
        for a in p:
            if res[a] < d - 1e-9:
                return False
        return True

    def _add(self, k, p):
        m = self.m
        d = m.dem[k]
        for a in p:
            self.res[a] -= d
            self.users[a].add(k)
        self.route[k] = p
        self.obj += m.path_cost(k, p) - m.pen[k]

    def _remove(self, k):
        m = self.m
        p = self.route[k]
        d = m.dem[k]
        for a in p:
            self.res[a] += d
            self.users[a].discard(k)
        self.route[k] = None
        self.obj += m.pen[k] - m.path_cost(k, p)
        return p

    def add(self, k, p):
        self._add(k, p)
        self.journal.append(("add", k))

    def remove(self, k):
        p = self._remove(k)
        self.journal.append(("rem", k, p))
        return p

    def mark(self):
        return len(self.journal)

    def undo(self, mark):
        while len(self.journal) > mark:
            op = self.journal.pop()
            if op[0] == "add":
                self._remove(op[1])
            else:
                self._add(op[1], op[2])


def residual_path(m, st, k):
    """Cheapest (cost, then hops) path for k through arcs with residual >= demand, or None."""
    o, t, d = m.orig[k], m.dest[k], m.dem[k]
    if o == t:
        return ()
    scale = m.N + 1.0
    dist = {o: 0.0}
    prev = {}
    done = set()
    heap = [(0.0, o)]
    res, cost, head = st.res, m.cost, m.head
    while heap:
        du, u = heapq.heappop(heap)
        if u in done:
            continue
        if u == t:
            break
        done.add(u)
        for a in m.out[u]:
            if res[a] < d - 1e-9:
                continue
            v = head[a]
            if v in done:
                continue
            nd = du + d * cost[a] * scale + 1.0
            if nd < dist.get(v, INF):
                dist[v] = nd
                prev[v] = a
                heapq.heappush(heap, (nd, v))
    if t not in prev:
        return None
    path = []
    v = t
    while v != o:
        a = prev[v]
        path.append(a)
        v = m.tail[a]
    path.reverse()
    return tuple(path)


def try_insert(m, st, k, pool=None):
    if st.route[k] is not None or m.impossible[k] or m.pen[k] <= 0:
        return False
    if m.trivial[k]:
        st.add(k, ())
        return True
    d = m.dem[k]
    # cheap necessary condition: some free arc out of the origin and into the destination
    if not any(st.res[a] >= d - 1e-9 for a in m.out[m.orig[k]]):
        return False
    if not any(st.res[a] >= d - 1e-9 for a in m.inn[m.dest[k]]):
        return False
    best = None
    if pool is not None and pool[k]:
        for p, c in pool[k]:
            if c < m.pen[k] - 1e-9 and st.fits(k, p):
                best = p
                break
    if best is None:
        p = residual_path(m, st, k)
        if p is not None and m.path_cost(k, p) < m.pen[k] - 1e-9:
            best = p
    if best is None:
        return False
    st.add(k, best)
    return True


def greedy(m, order):
    st = State(m)
    for k in order:
        try_insert(m, st, k)
    st.journal = []
    return st


def greedy_orders(m):
    hops = m.min_hops()
    ks = list(range(m.K))
    dens = lambda k: m.pen[k] / max(m.dem[k], 1e-9)  # noqa: E731
    return {
        "density": sorted(ks, key=lambda k: (-dens(k), -m.pen[k], k)),
        "density-hops": sorted(ks, key=lambda k: (-dens(k) / hops[k], -m.pen[k], k)),
        "value": sorted(ks, key=lambda k: (-m.pen[k], m.dem[k], k)),
    }


def feasible_routes(m, routes):
    load = [0.0] * m.A
    for k, p in enumerate(routes):
        if p is None:
            continue
        node = m.orig[k]
        seen = {node}
        for a in p:
            if m.tail[a] != node:
                return False
            node = m.head[a]
            if node in seen:
                return False
            seen.add(node)
            load[a] += m.dem[k]
        if node != m.dest[k]:
            return False
    return all(load[a] <= m.cap[a] + 1e-6 for a in range(m.A))


def to_output(m, routes):
    out = []
    obj = 0.0
    for k in range(m.K):
        p = routes[k]
        if p is None:
            obj += m.pen[k]
            out.append({"commodity_id": m.com_ids[k], "rejected": True, "path_arcs": []})
        else:
            obj += m.path_cost(k, p)
            out.append({"commodity_id": m.com_ids[k], "rejected": False,
                        "path_arcs": [{"from": m.node_ids[m.tail[a]], "to": m.node_ids[m.head[a]],
                                       "arc_id": m.arc_ids[a]} for a in p]})
    return obj, {"objective_value": float(obj), "commodities": out}


def repair(m, routes, order=None):
    """Load routes in order, dropping any that no longer fit; returns a feasible routes list."""
    st = State(m)
    ks = order if order is not None else range(m.K)
    for k in ks:
        p = routes[k]
        if p is not None and st.fits(k, p):
            st.add(k, tuple(p))
    for k in range(m.K):
        if m.trivial[k] and st.route[k] is None and m.pen[k] > 0:
            st.add(k, ())
    return st.route


class ColumnGen:
    """Path-based LP relaxation with column generation; r_k (reject) variables come first."""

    def __init__(self, m):
        self.m = m
        K = m.K
        self.cols = []
        self.keys = set()
        self.c = list(m.pen)
        self.eq_r = list(range(K))
        self.eq_c = list(range(K))
        self.ub_r, self.ub_c, self.ub_v = [], [], []
        self.capv = np.asarray(m.cap, dtype=float)
        self.costv = np.asarray(m.cost, dtype=float)
        self.tailv = np.asarray(m.tail, dtype=np.int64)
        self.headv = np.asarray(m.head, dtype=np.int64)
        self.ucap = sorted(set(m.cap))
        self.groups = {}
        for k in range(K):
            if m.trivial[k]:
                continue
            g = bisect.bisect_left(self.ucap, m.dem[k] - 1e-9)
            if g >= len(self.ucap):
                m.impossible[k] = True
                continue
            self.groups.setdefault(g, []).append(k)
        self.lp_value = None
        self.lb = -INF
        self.x = None
        self.converged = False
        self.iters = 0

    def add(self, k, p):
        p = tuple(p)
        if (k, p) in self.keys or self.m.trivial[k]:
            return False
        self.keys.add((k, p))
        j = len(self.c)
        cst = self.m.path_cost(k, p)
        self.cols.append((k, p, cst))
        self.c.append(cst)
        self.eq_r.append(k)
        self.eq_c.append(j)
        for a in p:
            self.ub_r.append(a)
            self.ub_c.append(j)
            self.ub_v.append(self.m.dem[k])
        return True

    def matrices(self):
        m = self.m
        n = len(self.c)
        aeq = sp.csr_matrix((np.ones(len(self.eq_r)), (np.asarray(self.eq_r, dtype=np.int64),
                                                        np.asarray(self.eq_c, dtype=np.int64))), shape=(m.K, n))
        aub = sp.csr_matrix((np.asarray(self.ub_v, dtype=float), (np.asarray(self.ub_r, dtype=np.int64),
                                                                   np.asarray(self.ub_c, dtype=np.int64))),
                            shape=(m.A, n))
        return np.asarray(self.c, dtype=float), aeq, aub

    def price(self, mu, u):
        """Shortest paths under arc weights cost + mu. Returns (new columns, Lagrangian lower bound)."""
        m = self.m
        N = m.N
        w = self.costv + mu
        eps = 1e-9 * max(1.0, float(w.max()) if len(w) else 1.0)
        wt = w + eps
        new = []
        lb_sum = 0.0
        for k in range(m.K):
            if m.impossible[k] and not m.trivial[k]:
                lb_sum += m.pen[k]
        for g, ks in self.groups.items():
            ks = [k for k in ks if not m.impossible[k]]
            if not ks:
                continue
            allowed = np.nonzero((self.capv >= self.ucap[g] - 1e-9) & (self.tailv != self.headv))[0]
            if len(allowed) == 0:
                for k in ks:
                    m.impossible[k] = True
                    lb_sum += m.pen[k]
                continue
            keyarr = self.tailv[allowed] * N + self.headv[allowed]
            order = np.lexsort((wt[allowed], keyarr))
            ksorted = keyarr[order]
            first = np.ones(len(order), dtype=bool)
            first[1:] = ksorted[1:] != ksorted[:-1]
            sel = allowed[order][first]
            graph = sp.csr_matrix((wt[sel], (self.tailv[sel], self.headv[sel])), shape=(N, N))
            pair = dict(zip((self.tailv[sel] * N + self.headv[sel]).tolist(), sel.tolist()))
            origins = sorted({m.orig[k] for k in ks})
            oi = {o: i for i, o in enumerate(origins)}
            dist, pred = cs_dijkstra(graph, directed=True, indices=origins, return_predecessors=True)
            dist = np.atleast_2d(dist)
            pred = np.atleast_2d(pred)
            for k in ks:
                r = oi[m.orig[k]]
                t = m.dest[k]
                dk = float(dist[r, t])
                if not math.isfinite(dk):
                    m.impossible[k] = True
                    lb_sum += m.pen[k]
                    continue
                lb_sum += min(m.pen[k], m.dem[k] * max(0.0, dk - eps * (N - 1)))
                o = m.orig[k]
                path = []
                v = t
                ok = True
                while v != o:
                    uu = int(pred[r, v])
                    if uu < 0 or len(path) > N:
                        ok = False
                        break
                    path.append(pair[uu * N + v])
                    v = uu
                if not ok:
                    continue
                path.reverse()
                rc = m.dem[k] * float(w[path].sum()) - float(u[k])
                if rc < -1e-7 * (1.0 + abs(float(u[k]))):
                    new.append((k, tuple(path)))
        return new, lb_sum - float(np.dot(mu, self.capv))

    def run(self, deadline, max_iters=500):
        m = self.m
        new, lb = self.price(np.zeros(m.A), np.asarray(m.pen, dtype=float))
        self.lb = max(self.lb, lb)
        for k, p in new:
            self.add(k, p)
        while time.monotonic() < deadline - 0.05 and self.iters < max_iters:
            c, aeq, aub = self.matrices()
            left = deadline - time.monotonic()
            res = linprog(c, A_ub=aub, b_ub=self.capv, A_eq=aeq, b_eq=np.ones(m.K), bounds=(0, None),
                          method="highs", options={"time_limit": max(0.1, left)})
            if res.status != 0 or res.x is None:
                log(event="lp-stop", status=int(res.status), msg=str(res.message)[:120])
                break
            self.iters += 1
            self.lp_value = float(res.fun)
            self.x = np.asarray(res.x)
            mu = np.maximum(0.0, -np.asarray(res.ineqlin.marginals, dtype=float))
            u = np.asarray(res.eqlin.marginals, dtype=float)
            if time.monotonic() > deadline:
                break
            new, lb = self.price(mu, u)
            self.lb = max(self.lb, lb)
            added = sum(1 for k, p in new if self.add(k, p))
            if added == 0:
                self.converged = True
                break
        return self

    def rounding(self):
        m = self.m
        K = m.K
        bestv = [0.0] * K
        bestp = [None] * K
        for j, (k, p, _c) in enumerate(self.cols):
            v = float(self.x[K + j]) if self.x is not None and K + j < len(self.x) else 0.0
            if v > bestv[k] + 1e-12:
                bestv[k] = v
                bestp[k] = p
        order = sorted(range(K), key=lambda k: (-bestv[k], -m.pen[k] / max(m.dem[k], 1e-9), k))
        st = State(m)
        for k in order:
            p = bestp[k]
            if p is not None and bestv[k] > 1e-6 and st.fits(k, p) and m.path_cost(k, p) < m.pen[k] - 1e-9:
                st.add(k, p)
            else:
                try_insert(m, st, k)
        return st.route

    def solve_mip(self, time_limit):
        m = self.m
        c, aeq, aub = self.matrices()
        n = len(c)
        res = milp(c, integrality=np.ones(n), bounds=Bounds(np.zeros(n), np.ones(n)),
                   constraints=[LinearConstraint(aeq, np.ones(m.K), np.ones(m.K)),
                                LinearConstraint(aub, np.full(m.A, -np.inf), self.capv)],
                   options={"time_limit": max(0.1, float(time_limit)), "disp": False, "mip_rel_gap": 0.0})
        if res.x is None:
            log(event="mip-none", status=int(res.status))
            return None
        routes = [None] * m.K
        for j, (k, p, _c) in enumerate(self.cols):
            if res.x[m.K + j] > 0.5 and routes[k] is None:
                routes[k] = p
        log(event="mip", status=int(res.status), fun=float(res.fun) if res.fun is not None else None,
            bound=res.get("mip_dual_bound"))
        return routes

    def pool(self):
        pools = [[] for _ in range(self.m.K)]
        for k, p, c in self.cols:
            pools[k].append((p, c))
        for lst in pools:
            lst.sort(key=lambda pc: (pc[1], len(pc[0])))
        return pools


def evict_path(m, st, k, rng, noise):
    """Dijkstra where entering an arc without room costs the cheapest set of its users' penalties."""
    o, t, d = m.orig[k], m.dest[k], m.dem[k]
    memo = {}
    hop = 1e-6 * max(1.0, m.pen[k])

    def evict_cost(a):
        if st.res[a] >= d - 1e-9:
            return 0.0
        if a in memo:
            return memo[a]
        need = d - st.res[a]
        users = sorted(st.users[a], key=lambda j: m.pen[j] / max(m.dem[j], 1e-9))
        freed = 0.0
        cost = 0.0
        for j in users:
            freed += m.dem[j]
            cost += m.pen[j] - m.path_cost(j, st.route[j])
            if freed >= need - 1e-9:
                break
        else:
            cost = INF
        if cost < INF and noise > 0:
            cost *= 1.0 + noise * rng.random()
        memo[a] = cost
        return cost

    dist = {o: 0.0}
    prev = {}
    done = set()
    heap = [(0.0, o)]
    while heap:
        du, u = heapq.heappop(heap)
        if u in done:
            continue
        if u == t:
            break
        done.add(u)
        for a in m.out[u]:
            if m.cap[a] < d - 1e-9:
                continue
            v = m.head[a]
            if v in done:
                continue
            ec = evict_cost(a)
            if ec == INF:
                continue
            nd = du + d * m.cost[a] + ec + hop
            if nd < dist.get(v, INF):
                dist[v] = nd
                prev[v] = a
                heapq.heappush(heap, (nd, v))
    if t not in prev:
        return None, INF
    path = []
    v = t
    while v != o:
        a = prev[v]
        path.append(a)
        v = m.tail[a]
    path.reverse()
    return tuple(path), dist[t]


def lns(m, st, pool, deadline, rng, on_better, lb=-INF):
    best = st.obj
    cand_all = [k for k in range(m.K) if not m.impossible[k] and not m.trivial[k] and m.pen[k] > 0]
    if not cand_all:
        return 0
    st.journal = []
    it = 0
    last_improve = 0
    while time.monotonic() < deadline:
        if best <= lb + 1e-6 * max(1.0, abs(best)):
            break
        it += 1
        rej = [k for k in cand_all if st.route[k] is None]
        if not rej:
            break
        k = rng.choices(rej, weights=[m.pen[j] for j in rej])[0]
        before = st.obj
        mark = st.mark()
        noise = 0.0 if it % 4 == 0 else 0.5
        p, est = evict_path(m, st, k, rng, noise)
        if p is None:
            m.impossible[k] = True
            cand_all = [j for j in cand_all if j != k]
            continue
        if m.path_cost(k, p) >= m.pen[k] - 1e-9:
            continue
        d = m.dem[k]
        removed = []
        for a in p:
            if st.res[a] < d - 1e-9:
                users = sorted(st.users[a], key=lambda j: (m.pen[j] / max(m.dem[j], 1e-9)) * (1.0 + 0.2 * rng.random()))
                for j in users:
                    if st.res[a] >= d - 1e-9:
                        break
                    st.remove(j)
                    removed.append(j)
        if not st.fits(k, p):
            st.undo(mark)
            continue
        st.add(k, p)
        removed.sort(key=lambda j: -m.pen[j])
        for j in removed:
            try_insert(m, st, j, pool)
        others = [j for j in rej if j != k and st.route[j] is None]
        if len(others) > 40:
            others = rng.sample(others, 40)
        others.sort(key=lambda j: -m.pen[j] / max(m.dem[j], 1e-9))
        for j in others:
            try_insert(m, st, j, pool)
        if st.obj < before - 1e-9 or (st.obj <= before + 1e-9 and rng.random() < 0.3):
            st.journal = []
            if st.obj < best - 1e-9:
                best = st.obj
                last_improve = it
                on_better(st)
        else:
            st.undo(mark)
            st.journal = []
        if it - last_improve > 4000 and it % 4000 == 0:
            # mild perturbation: drop a few random routed commodities and refill greedily
            routed = [j for j in cand_all if st.route[j] is not None]
            for j in rng.sample(routed, min(len(routed), 3)):
                st.remove(j)
            for j in sorted([j for j in cand_all if st.route[j] is None],
                            key=lambda j: -m.pen[j] / max(m.dem[j], 1e-9)):
                try_insert(m, st, j, pool)
            st.journal = []
    return it


def lagrangian_bound(inst, seconds):
    """For calibration: run column generation alone for `seconds`; returns its bound and LP value."""
    m = Model(inst)
    m.compute_reach()
    cg = ColumnGen(m)
    for name, order in greedy_orders(m).items():
        st = greedy(m, order)
        for k, p in enumerate(st.route):
            if p is not None:
                cg.add(k, p)
    cg.run(time.monotonic() + seconds)
    return {"lb": cg.lb, "lp": cg.lp_value, "converged": cg.converged, "iters": cg.iters, "cols": len(cg.cols)}


def greedy_best(inst):
    m = Model(inst)
    m.compute_reach()
    return min(greedy(m, order).obj for order in greedy_orders(m).values())


def solve(inst, clock, inc, args):
    t_start = time.monotonic()
    m = Model(inst)
    rng = random.Random(int(getattr(args, "seed", 0) or 0))
    info = {"N": m.N, "A": m.A, "K": m.K, "mode": m.mode, "scipy": HAVE_SCIPY}
    best = {"obj": INF, "routes": None}

    def consider(routes, source):
        routes = list(routes)
        for k in range(m.K):
            if m.trivial[k] and routes[k] is None and m.pen[k] > 0:
                routes[k] = ()
        if not feasible_routes(m, routes):
            log(event="infeasible-candidate", source=source)
            return False
        obj, sol = to_output(m, routes)
        if obj < best["obj"] - 1e-9:
            best["obj"] = obj
            best["routes"] = routes
        took = inc.offer(obj, sol, source)
        log(event="candidate", source=source, obj=obj, kept=took, t=round(time.monotonic() - t_start, 3))
        return took

    consider([None] * m.K, "all-rejected")
    m.compute_reach()
    for name, order in greedy_orders(m).items():
        if clock.remaining() < 0.3:
            break
        consider(greedy(m, order).route, "greedy-" + name)

    pool = None
    lb = -INF
    if HAVE_SCIPY and m.A > 0 and m.K > 0 and clock.remaining() > 2.0:
        try:
            cg = ColumnGen(m)
            for k, p in enumerate(best["routes"]):
                if p is not None:
                    cg.add(k, p)
            cg.run(time.monotonic() + clock.share(0.35))
            lb = cg.lb
            info.update(lp=cg.lp_value, lb=cg.lb, converged=cg.converged, iters=cg.iters, cols=len(cg.cols))
            if cg.x is not None:
                consider(cg.rounding(), "lp-round")
            if best["obj"] > lb + 1e-6 * max(1.0, abs(best["obj"])) and clock.remaining() > 1.5:
                for k, p in enumerate(best["routes"]):
                    if p is not None:
                        cg.add(k, p)
                r = cg.solve_mip(clock.share(0.5))
                if r is not None:
                    consider(repair(m, r), "rmp-mip")
            pool = cg.pool()
        except Exception as e:  # noqa: BLE001 - keep the greedy incumbent
            log(event="cg-error", err=repr(e))

    st = State(m)
    for k, p in enumerate(best["routes"]):
        if p is not None:
            st.add(k, p)
    st.journal = []
    last = {"t": time.monotonic()}

    def on_better(s):
        if time.monotonic() - last["t"] > 1.0:
            last["t"] = time.monotonic()
            consider(s.route, "lns")
        else:
            if s.obj < best["obj"] - 1e-9:
                best["obj"] = s.obj
                best["routes"] = list(s.route)
                best["pending"] = True

    its = 0
    if clock.remaining() > 0.3:
        its = lns(m, st, pool, time.monotonic() + clock.remaining(), rng, on_better, lb)
    if best.get("pending"):
        best["obj"] = INF
        consider(best_routes_or(st, best), "lns-final")
    consider(st.route, "lns-end")
    info.update(lns_iters=its, best=inc.value, time=round(time.monotonic() - t_start, 3),
                proved_optimal=bool(inc.value is not None and inc.value <= lb + 1e-6 * max(1.0, abs(inc.value))))
    log(event="final", **info)


def best_routes_or(st, best):
    return best["routes"] if best.get("routes") is not None else st.route


if __name__ == "__main__":
    R.main(solve, "min")

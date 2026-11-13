#!/usr/bin/env python3
"""MV2's solver for FrontierOR task bode2012: the capacitated arc-routing problem (CARP).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python solve.py --problem bode2012 --instance in.json --output out.json --time-limit 60

Standard library only. An undirected network, one depot, num_vehicles identical vehicles of capacity Q. Every
required edge is serviced by exactly one vehicle; each vehicle's route is a closed walk from the depot. Total cost =
service costs (a constant) + deadheading costs, each crossing of an edge without service paying its cost once.

Model: each required edge is a task with two directions (arcs). A route is a sequence of arcs; between consecutive
arcs, and from and back to the depot, the vehicle deadheads along a shortest path (Dijkstra from every node). That
walk is written out as the official solution format: serviced_edges plus deadheaded_edges with crossing counts,
which is a connected multigraph through the depot with every node of even degree (the two-index formulation of the
reference model). The answer always has exactly num_vehicles routes (unused vehicles stay empty, as in the reference
model); the solver never uses more vehicles than the fleet has.

Search: slack induction by string removals (SISR, Christiaens & Vanden Berghe 2020), written from the paper's
description and adapted to arcs: remove strings of consecutive tasks from routes near a random seed task, reinsert the
removed tasks one by one at the cheapest position AND direction (each position skipped with a 1% "blink" chance),
accept by simulated annealing on a schedule tied to the clock. Capacity overload is penalised far above any travel
cost. Every new best is polished route by route (exact 2-opt with direction flips, single-task relocation in both
directions, recomputed in full), checked by verify() (the official checker's rules) and written atomically.
With two CPUs a forked child runs the same search with another seed; the parent keeps the better answer.
The run stops at min(0.9 T, T - 3) seconds after start-up.
Environment: MV2_CARP_WORKERS (default 2; 1 = no child), MV2_CARP_SEED (default 1), MV2_CARP_LOG (write
<output>.log.json).
"""
import argparse
import heapq
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
TOL = 1e-5  # the official checker's tolerance
INF = float("inf")
BIG = 1e15  # "unreachable" distance; keeps arithmetic finite


class Problem:
    def __init__(self, inst):
        g = inst["graph"]
        self.depot = int(inst["depot"])
        fl = inst["fleet"]
        self.K = int(fl["num_vehicles"])
        self.Q = fl["vehicle_capacity"]
        self.edges = {}  # edge_id -> (u, v, cost, required, demand, service_cost)
        req = []
        top = max(int(g.get("num_nodes", 0)), self.depot + 1)
        for e in inst["edges"]:
            eid = int(e["edge_id"])
            u, v = int(e["endpoints"][0]), int(e["endpoints"][1])
            self.edges[eid] = (u, v, e["cost"], bool(e["is_required"]), e["demand"], e["service_cost"])
            if e["is_required"]:
                req.append(eid)
            top = max(top, u + 1, v + 1)
        self.N = top
        req.sort()
        self.req = req
        self.R = len(req)
        self.service_total = sum(self.edges[eid][5] for eid in req)
        # arcs: task t (required edge req[t]) has arc 2t = u->v and arc 2t+1 = v->u
        self.s_of = [0] * (2 * self.R)
        self.e_of = [0] * (2 * self.R)
        self.dem = [0] * self.R
        for t, eid in enumerate(req):
            u, v = self.edges[eid][0], self.edges[eid][1]
            self.s_of[2 * t], self.e_of[2 * t] = u, v
            self.s_of[2 * t + 1], self.e_of[2 * t + 1] = v, u
            self.dem[t] = self.edges[eid][4]
        self._shortest_paths()
        d = self.depot
        D = self.D
        fin = [x for row in D for x in row if x < BIG]
        self.maxd = max(1.0, float(max(fin) if fin else 1.0))
        unit = max(1e-6, float(min([q for q in self.dem if q > 0] or [1])))
        # one unit of overload costs more than any change in deadheading can buy back
        self.LAM = 4.0 * (self.R + self.K + 2) * self.maxd / unit
        self.reach = all(D[d][self.s_of[2 * t]] < BIG for t in range(self.R))
        # task neighbours by the shortest distance between their end nodes (for the ruin step)
        ends = [(self.s_of[2 * t], self.e_of[2 * t]) for t in range(self.R)]

        def td(a, b):
            return min(D[x][y] for x in ends[a] for y in ends[b])
        self.near = [sorted((b for b in range(self.R) if b != a), key=lambda b, a=a: (td(a, b), b))
                     for a in range(self.R)]
        self.dep_dist = [min(D[d][ends[t][0]], D[d][ends[t][1]]) for t in range(self.R)]

    def _shortest_paths(self):
        N = self.N
        adj = [[] for _ in range(N)]
        for eid, (u, v, c, _r, _q, _s) in self.edges.items():
            if u == v:
                continue
            adj[u].append((v, eid, c))
            adj[v].append((u, eid, c))
        self.D = []
        self.pred = []
        for src in range(N):
            dist = [BIG] * N
            pred = [-1] * N
            dist[src] = 0
            pq = [(0, src)]
            while pq:
                dx, x = heapq.heappop(pq)
                if dx > dist[x]:
                    continue
                for y, eid, c in adj[x]:
                    nd = dx + c
                    if nd < dist[y]:
                        dist[y] = nd
                        pred[y] = eid
                        heapq.heappush(pq, (nd, y))
            self.D.append(dist)
            self.pred.append(pred)

    def path(self, a, b):
        """Edge ids of a shortest path from node a to node b (None if unreachable)."""
        if a == b:
            return []
        if self.D[a][b] >= BIG:
            return None
        P = self.pred[a]
        out = []
        x = b
        guard = 0
        while x != a:
            eid = P[x]
            if eid < 0:
                return None
            out.append(eid)
            u, v = self.edges[eid][0], self.edges[eid][1]
            x = u if v == x else v
            guard += 1
            if guard > self.N + 1:
                return None
        out.reverse()
        return out

    def route_cost(self, seq):
        """Deadheading cost of a route (a list of arcs)."""
        D = self.D
        s_of, e_of = self.s_of, self.e_of
        prev = self.depot
        c = 0
        for a in seq:
            c += D[prev][s_of[a]]
            prev = e_of[a]
        return c + D[prev][self.depot]

    def load(self, seq):
        return sum(self.dem[a >> 1] for a in seq)


class Sol:
    """K routes of arcs plus per-route caches: deadhead cost, load, overload; where[t] = route of task t."""
    __slots__ = ("pb", "routes", "rcost", "ld", "exc", "where")

    def __init__(self, pb, routes=None):
        self.pb = pb
        K = pb.K
        self.routes = [list(r) for r in routes] if routes is not None else [[] for _ in range(K)]
        self.rcost = [0] * K
        self.ld = [0] * K
        self.exc = [0] * K
        self.where = [-1] * pb.R
        for r in range(K):
            self.refresh(r)

    def copy(self):
        s = Sol.__new__(Sol)
        s.pb = self.pb
        s.routes = [list(r) for r in self.routes]
        s.rcost = list(self.rcost)
        s.ld = list(self.ld)
        s.exc = list(self.exc)
        s.where = list(self.where)
        return s

    def refresh(self, r):
        pb = self.pb
        seq = self.routes[r]
        self.ld[r] = pb.load(seq)
        e = self.ld[r] - pb.Q
        self.exc[r] = e if e > 0 else 0
        self.rcost[r] = pb.route_cost(seq)
        for a in seq:
            self.where[a >> 1] = r

    def deadhead(self):
        return sum(self.rcost)

    def distance(self):
        """Total cost as the checker computes it: service costs + deadheading."""
        return self.pb.service_total + sum(self.rcost)

    def penalised(self):
        return sum(self.rcost) + self.pb.LAM * sum(self.exc)

    def feasible(self):
        if any(e > TOL for e in self.exc):
            return False
        if any(w < 0 for w in self.where):
            return False
        return self.pb.reach and sum(self.rcost) < BIG


def initial(pb, rng, order="demand"):
    s = Sol(pb)
    tasks = list(range(pb.R))
    if order == "demand":
        tasks.sort(key=lambda t: (-pb.dem[t], t))
    elif order == "far":
        tasks.sort(key=lambda t: (-pb.dep_dist[t], t))
    else:
        rng.shuffle(tasks)
    insert_all(s, tasks, rng, blink=0.0)
    return s


def insert_all(s, tasks, rng, blink=0.01):
    """Cheapest (penalised) insertion of each task in turn, over every route, position and direction."""
    pb = s.pb
    D = pb.D
    s_of, e_of = pb.s_of, pb.e_of
    Q, LAM = pb.Q, pb.LAM
    dep = pb.depot
    routes = s.routes
    K = pb.K
    for t in tasks:
        q = pb.dem[t]
        a0, a1 = 2 * t, 2 * t + 1
        s0, e0, s1, e1 = s_of[a0], e_of[a0], s_of[a1], e_of[a1]
        # an insertion can SAVE up to D[u][v] (the vehicle already deadheads along the edge), so a route is
        # skipped only when even that saving cannot beat the best found
        save = D[s0][e0]
        best, br, bp, ba = INF, -1, 0, a0
        empty_seen = False
        for r in range(K):
            seq = routes[r]
            if not seq:
                if empty_seen:
                    continue  # all empty routes are alike
                empty_seen = True
            nexc = s.ld[r] + q - Q
            if nexc < 0:
                nexc = 0
            base = LAM * (nexc - s.exc[r])
            if base - save >= best:
                continue
            prev = dep
            L = len(seq)
            for p in range(L + 1):
                nxt = s_of[seq[p]] if p < L else dep
                if blink and rng.random() < blink:
                    prev = e_of[seq[p]] if p < L else dep
                    continue
                Dp = D[prev]
                old = Dp[nxt]
                d = base + Dp[s0] + D[e0][nxt] - old
                if d < best:
                    best, br, bp, ba = d, r, p, a0
                d = base + Dp[s1] + D[e1][nxt] - old
                if d < best:
                    best, br, bp, ba = d, r, p, a1
                if p < L:
                    prev = e_of[seq[p]]
        if br < 0:  # every position blinked: append to the first route
            br, bp, ba = 0, len(routes[0]), a0
        routes[br].insert(bp, ba)
        s.refresh(br)


def ruin(s, rng, cbar, lmax):
    pb = s.pb
    routes = s.routes
    nonempty = [r for r in routes if r]
    if not nonempty or pb.R == 0:
        return []
    avg = sum(len(r) for r in nonempty) / float(len(nonempty))
    ls_max = min(float(lmax), avg)
    ks_max = 4.0 * cbar / (1.0 + ls_max) - 1.0
    ks = int(rng.uniform(1.0, ks_max + 1.0))
    if ks < 1:
        ks = 1
    seed = rng.randrange(pb.R)
    removed = []
    ruined = set()
    for t in [seed] + pb.near[seed]:
        if len(ruined) >= ks:
            break
        r = s.where[t]
        if r < 0 or r in ruined:
            continue
        seq = routes[r]
        L = len(seq)
        lmt = min(float(L), ls_max)
        ln = int(rng.uniform(1.0, lmt + 1.0))
        ln = max(1, min(L, ln))
        pos = -1
        for k, a in enumerate(seq):
            if (a >> 1) == t:
                pos = k
                break
        if pos < 0:
            continue
        if ln < L and rng.random() < 0.5:
            # split string: a window of ln + keep tasks holding t; the keep in the middle stay
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
        ids = set(idx)
        take = [seq[k] >> 1 for k in idx]
        routes[r] = [a for k, a in enumerate(seq) if k not in ids]
        for t2 in take:
            s.where[t2] = -1
        removed.extend(take)
        ruined.add(r)
        s.refresh(r)
    return removed


def sort_removed(pb, removed, rng):
    x = rng.random() * 11.0
    if x < 4.0:
        rng.shuffle(removed)
    elif x < 8.0:
        removed.sort(key=lambda t: -pb.dem[t])
    elif x < 10.0:
        removed.sort(key=lambda t: -pb.dep_dist[t])
    else:
        removed.sort(key=lambda t: pb.dep_dist[t])
    return removed


def polish_route(pb, seq):
    """Exact intra-route improvement: 2-opt (reverse a segment and flip its arcs, a single flip included) and
    relocation of one task to any position in either direction; full recomputation."""
    best = list(seq)
    bc = pb.route_cost(best)
    L = len(best)
    if L == 0:
        return best, bc
    improved = True
    rounds = 0
    while improved and rounds < 50:
        improved = False
        rounds += 1
        for i in range(L):
            for j in range(i, L):
                cand = best[:i] + [a ^ 1 for a in reversed(best[i:j + 1])] + best[j + 1:]
                cc = pb.route_cost(cand)
                if cc < bc - EPS:
                    best, bc, improved = cand, cc, True
        if L >= 2:
            for i in range(L):
                u = best[i]
                rest = best[:i] + best[i + 1:]
                for p in range(L):
                    for arc in (u, u ^ 1):
                        if p == i and arc == u:
                            continue
                        cand = rest[:p] + [arc] + rest[p:]
                        cc = pb.route_cost(cand)
                        if cc < bc - EPS:
                            best, bc, improved = cand, cc, True
                            break
                    if improved:
                        break
                if improved:
                    break
    return best, bc


def polish(s):
    for r in range(s.pb.K):
        if 1 <= len(s.routes[r]) <= 40:  # O(L^3) per pass; longer routes are left to the main search
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
        cur = None
        for order in ("demand", "far", "random"):
            c = initial(pb, rng, order)
            if cur is None or c.penalised() < cur.penalised():
                cur = c
        self.stats["construction"] = cur.distance()
        self.stats["construction_feasible"] = cur.feasible()
        fc = cur.penalised()
        best = polish(cur.copy())
        bf = best.penalised()
        events = [[round(time.time() - T_START, 3), best.distance(), best.feasible()]]
        if on_improve and best.feasible():
            on_improve(best)
        if pb.R == 0:
            self.stats["best"] = best.distance()
            self.stats["best_feasible"] = best.feasible()
            self.stats["events"] = events
            return best
        avg_edge = max(cur.deadhead(), 1.0) / float(max(1, pb.R + pb.K))
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
    """The official solution format, or None if some deadheading path does not exist."""
    routes = []
    total = 0
    dep = pb.depot
    for k in range(pb.K):
        seq = s.routes[k]
        serviced = [pb.req[a >> 1] for a in seq]
        dh = {}
        prev = dep
        ok = True
        for a in seq + [None]:
            nxt = dep if a is None else pb.s_of[a]
            p = pb.path(prev, nxt)
            if p is None:
                ok = False
                break
            for eid in p:
                dh[eid] = dh.get(eid, 0) + 1
            if a is not None:
                prev = pb.e_of[a]
        if not ok:
            return None
        rc = sum(pb.edges[eid][5] for eid in serviced) + sum(pb.edges[eid][2] * n for eid, n in dh.items())
        total += rc
        routes.append({"vehicle": k, "serviced_edges": serviced,
                       "deadheaded_edges": [{"edge_id": eid, "times": int(n)} for eid, n in sorted(dh.items())],
                       "total_demand": pb.load(seq), "route_cost": rc})
    return {"objective_value": float(total), "status": "feasible", "num_vehicles": pb.K,
            "vehicle_capacity": pb.Q, "routes": routes}


def _finite_number(v):
    return not isinstance(v, bool) and isinstance(v, (int, float)) and v == v and v not in (INF, -INF)


def verify(pb, sol, strict_fleet=True):
    """(ok, reason, objective): the official checker's rules (contract, constraints 2-7), applied to a dict.
    strict_fleet also rejects more routes with service than vehicles (the problem's fixed fleet; the official
    checker does not count routes)."""
    if not isinstance(sol, dict):
        return False, "solution is not a JSON object", None
    for f in ("objective_value", "routes"):
        if sol.get(f) is None:
            return False, "missing " + f, None
    ov = sol["objective_value"]
    if not _finite_number(ov):
        return False, "objective_value must be a finite number", None
    if sol.get("status_str", "") in ("NO_SOLUTION_FOUND", "INFEASIBLE", "INF_OR_UNBD"):
        return False, "status_str says no solution", None
    try:
        routes = sol.get("routes", [])
        E = pb.edges
        dep = pb.depot
        cnt = {}
        for rt in routes:
            for eid in rt.get("serviced_edges", []):
                cnt[eid] = cnt.get(eid, 0) + 1
        for eid in pb.req:
            if cnt.get(eid, 0) != 1:
                return False, "required edge %r serviced %d times" % (eid, cnt.get(eid, 0)), None
        for rt in routes:
            for eid in rt.get("serviced_edges", []):
                if eid not in E:
                    return False, "edge %r does not exist" % (eid,), None
                if not E[eid][3]:
                    return False, "non-required edge %r serviced" % (eid,), None
        if strict_fleet and sum(1 for rt in routes if rt.get("serviced_edges")) > pb.K:
            return False, "more routes with service than vehicles", None
        for k, rt in enumerate(routes):
            serviced = rt.get("serviced_edges", [])
            dhs = rt.get("deadheaded_edges", [])
            # (6) domain first (the checker reports it later, but the verdict is the same)
            seen = {}
            for eid in serviced:
                seen[eid] = seen.get(eid, 0) + 1
                if seen[eid] > 1:
                    return False, "vehicle %d services %r twice" % (k, eid), None
            for dh in dhs:
                tm = dh.get("times", 0)
                if not isinstance(tm, int) or tm < 0:
                    return False, "vehicle %d invalid times %r" % (k, tm), None
            # (3) connectivity of the serviced part to the depot
            if serviced:
                adj = {}
                nodes = set()
                used = [eid for eid in serviced if eid in E]
                used += [dh["edge_id"] for dh in dhs if dh["edge_id"] in E and dh.get("times", 0) > 0]
                for eid in used:
                    u, v = E[eid][0], E[eid][1]
                    adj.setdefault(u, set()).add(v)
                    adj.setdefault(v, set()).add(u)
                    nodes.add(u)
                    nodes.add(v)
                if dep not in nodes:
                    return False, "vehicle %d does not reach the depot" % k, None
                seen_n = {dep}
                stack = [dep]
                while stack:
                    x = stack.pop()
                    for y in adj.get(x, ()):
                        if y not in seen_n:
                            seen_n.add(y)
                            stack.append(y)
                for eid in serviced:
                    if eid in E and (E[eid][0] not in seen_n or E[eid][1] not in seen_n):
                        return False, "vehicle %d serviced edge %r not connected to the depot" % (k, eid), None
            # (4) parity
            deg = {}
            for eid in serviced:
                if eid in E:
                    u, v = E[eid][0], E[eid][1]
                    deg[u] = deg.get(u, 0) + 1
                    deg[v] = deg.get(v, 0) + 1
            for dh in dhs:
                eid = dh["edge_id"]
                tm = dh.get("times", 0)
                if eid in E and tm > 0:
                    u, v = E[eid][0], E[eid][1]
                    deg[u] = deg.get(u, 0) + tm
                    deg[v] = deg.get(v, 0) + tm
            for x, dgr in deg.items():
                if dgr % 2 != 0:
                    return False, "vehicle %d node %r odd degree %r" % (k, x, dgr), None
            # (5) capacity
            q = sum(E[eid][4] for eid in serviced if eid in E)
            if q - pb.Q > TOL:
                return False, "vehicle %d load %r over capacity %r" % (k, q, pb.Q), None
        # (7) objective
        true = 0.0
        for rt in routes:
            for eid in rt.get("serviced_edges", []):
                if eid in E:
                    true += float(E[eid][5])
            for dh in rt.get("deadheaded_edges", []):
                eid = dh["edge_id"]
                tm = dh.get("times", 0)
                if eid in E and isinstance(tm, (int, float)) and tm > 0:
                    true += float(E[eid][2]) * float(tm)
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
    ap.add_argument("--problem", default="bode2012")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    a = ap.parse_args(argv)
    T = float(a.time_limit)
    deadline = T_START + min(0.9 * T, T - 3.0)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    pb = Problem(inst)
    seed = int(os.environ.get("MV2_CARP_SEED", "1"))
    workers = int(os.environ.get("MV2_CARP_WORKERS", "2"))
    log = {"version": VERSION, "nodes": pb.N, "edges": len(pb.edges), "required": pb.R, "K": pb.K, "Q": pb.Q,
           "T": T, "load_s": round(time.time() - T_START, 3), "workers": workers, "reach": pb.reach}
    child_pid, child_path = None, None
    if workers >= 2 and hasattr(os, "fork") and pb.R > 0:
        child_path = os.path.join(tempfile.gettempdir(), "mv2_carp_child_%d.json" % os.getpid())
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
        if out is None:
            log.setdefault("verify_failures", []).append("no deadheading path")
            return
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
        if out is not None:
            ok, why, real = verify(pb, out)
            if ok and (state["written"] is None or real < state["written"] - EPS):
                write_atomic(a.output, out)
                state["written"] = real
            elif not ok:
                log.setdefault("verify_failures", []).append(why[:200])
    log["best"] = state["written"]
    log["wall_s"] = round(time.time() - T_START, 3)
    if os.environ.get("MV2_CARP_LOG"):
        try:
            write_atomic(a.output + ".log.json", log)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

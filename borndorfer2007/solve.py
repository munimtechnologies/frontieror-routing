"""borndorfer2007 (line planning in public transport, LPP) solver for the FrontierOR Challenge, v0.1.0.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Rules, read from the public FrontierOR benchmark's problem_description.txt, mathematical_formulation.md,
gurobi_code.py and feasibility_check.py (Hugging Face frontieror/FrontierOR, task borndorfer2007, CC BY 4.0):
- undirected edges, each in one mode; a line of mode m is a simple path over mode-m edges between two different
  terminals of m, with at most max_line_length_edges edges; it gets a frequency f >= 0 (at most F);
- every edge e: the frequencies of the lines using it add up to at most its edge_capacity;
- passengers of each OD pair travel on directed paths (arc 2e = endpoints[0] -> endpoints[1], arc 2e+1 the other
  way); flow on an arc <= sum of kappa(mode) * f over the lines on its edge; every OD demand is met exactly;
- objective = lambda * (sum of fixed costs of the lines + sum_l f_l * operating cost of l)
              + (1 - lambda) * sum over passenger paths of flow * travel time, recomputed by the checker.
The official checker does not check the line rules (mode edges, terminals, simple path, length); this solver obeys
them anyway and verify() checks them (strict mode).

Method (standard library only):
- For every edge, a shortest valid "anchor" line through it (breadth-first search to two different terminals);
  edges with no valid line are closed to passengers.
- Passengers: capacity-aware all-or-nothing routing on shortest paths (Dijkstra per origin) under a generalised
  arc cost (1 - lambda) * time + lambda * beta * operating cost / vehicle capacity.
- Lines for a routing: the frequency each edge needs is max(flow in either direction) / kappa. Candidate lines are
  the anchor lines and "corridor" lines grown from each busy edge along its busiest neighbours and closed at
  terminals. A lazy greedy (weighted set cover, cost per unit of covered need) picks lines and frequencies, then a
  reverse pass trims frequency that is not needed and drops lines left at zero.
- Search: a few start settings, then repeated partial re-routing of random origins with costs that make spare
  line capacity free and unserved edges dearer, re-planning the lines each time; improvements only.
- Only solutions that pass verify() (the official rules plus the line rules, tighter tolerances) are written,
  atomically. With 2 CPUs a forked child searches with a second seed. Deadline min(0.9 T, T - 3).
"""
import argparse
import heapq
import json
import math
import os
import random
import sys
import time
from collections import defaultdict, deque

T_START = time.monotonic()
VERSION = "0.1.0"
SLUG = "borndorfer2007"
INF = float("inf")
CHK_TOL, CHK_REL = 1e-4, 1e-5     # the official checker's tolerances
OUR_TOL, OUR_REL = 1e-5, 1e-6     # ours: ten times tighter
EPS = 1e-12


class Timeout(Exception):
    pass


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# --------------------------------------------------------------------------------------------------- problem
class Problem:
    def __init__(self, inst):
        t0 = time.monotonic()
        gp = inst.get("global_parameters") or {}
        try:
            self.lam = float(gp.get("lambda", 0.0))
        except (TypeError, ValueError):
            self.lam = 0.0
        Lm = gp.get("max_line_length_edges")
        self.L = int(Lm) if _is_num(Lm) and Lm >= 1 else None
        Fv = gp.get("frequency_upper_bound_F")
        self.F = float(Fv) if _is_num(Fv) else INF
        net = inst["network"]
        edges = net["edges"]
        ne = max([int(e["id"]) for e in edges] + [-1]) + 1
        self.E = E = max(ne, int(net.get("num_edges") or 0))
        self.eu, self.ev = [-1] * E, [-1] * E
        self.tt, self.cap, self.opc = [0.0] * E, [0.0] * E, [0.0] * E
        self.has = [False] * E
        maxn = int(net.get("num_nodes") or 0) - 1
        for e in edges:
            i = int(e["id"])
            u, v = int(e["endpoints"][0]), int(e["endpoints"][1])
            self.eu[i], self.ev[i] = u, v
            self.tt[i] = float(e["traveling_time_seconds"])
            self.cap[i] = float(e["edge_capacity"])
            self.opc[i] = float(e.get("operating_cost", 0.0) or 0.0)
            self.has[i] = True
            maxn = max(maxn, u, v)
        self.n = n = maxn + 1
        modes = inst.get("modes") or []
        self.M = len(modes)
        self.mname = [str(m["name"]) for m in modes]
        self.mindex = {}
        for i, nm in enumerate(self.mname):
            self.mindex[nm] = i            # the checker's dict keeps the LAST mode of a name
        self.kappa = [float(m.get("vehicle_capacity", 0) or 0) for m in modes]
        self.Cf = [float(m.get("fixed_cost_per_line", 0.0) or 0.0) for m in modes]
        self.term = [set(int(t) for t in (m.get("terminals") or [])) for m in modes]
        self.medges, self.emode = [], [-1] * E
        for mi, m in enumerate(modes):
            el, seen = [], set()
            for x in m.get("edge_indices") or []:
                x = int(x)
                if 0 <= x < E and self.has[x] and x not in seen:
                    seen.add(x)
                    el.append(x)
            self.medges.append(el)
            if self.mindex.get(self.mname[mi]) != mi or self.kappa[mi] <= 0:
                continue
            for x in el:
                if self.emode[x] < 0:
                    self.emode[x] = mi
        self.medge_set = [set(el) for el in self.medges]
        self.madj = []
        for mi in range(self.M):
            adj = [[] for _ in range(n)]
            for x in self.medges[mi]:
                u, v = self.eu[x], self.ev[x]
                if u != v:
                    adj[u].append((v, x))
                    adj[v].append((u, x))
            self.madj.append(adj)
        self.dT = []
        for mi in range(self.M):
            d = [INF] * n
            q = deque()
            for t in self.term[mi]:
                if 0 <= t < n and d[t] > 0:
                    d[t] = 0
                    q.append(t)
            while q:
                x = q.popleft()
                for y, _ in self.madj[mi][x]:
                    if d[y] == INF:
                        d[y] = d[x] + 1
                        q.append(y)
            self.dT.append(d)
        self.anchor = [None] * E
        for x in range(E):
            mi = self.emode[x]
            if mi >= 0 and self.eu[x] != self.ev[x]:
                self.anchor[x] = self.anchor_line(mi, x)
        A = 2 * E
        self.atail, self.ahead = [0] * A, [0] * A
        self.out = [[] for _ in range(n)]
        self.acap = [0.0] * A
        for x in range(E):
            if not self.has[x]:
                continue
            u, v = self.eu[x], self.ev[x]
            self.atail[2 * x], self.ahead[2 * x] = u, v
            self.atail[2 * x + 1], self.ahead[2 * x + 1] = v, u
            if self.anchor[x] is not None:
                self.out[u].append((v, 2 * x))
                self.out[v].append((u, 2 * x + 1))
                c = self.kappa[self.emode[x]] * min(self.cap[x], self.F)
                self.acap[2 * x] = self.acap[2 * x + 1] = max(0.0, c)
        self.od, self.od_dupes = {}, 0
        for o in inst.get("od_matrix") or []:
            key = (int(o["origin"]), int(o["destination"]))
            if key in self.od:
                self.od_dupes += 1
            self.od[key] = self.od.get(key, 0.0) + float(o["demand"])
        self.by_origin = defaultdict(list)
        for (o, d), dem in self.od.items():
            if dem > 0:
                self.by_origin[o].append((d, dem))
        for o in self.by_origin:
            self.by_origin[o].sort(key=lambda t: -t[1])
        self.origins = sorted(self.by_origin, key=lambda o: (-sum(d for _, d in self.by_origin[o]), o))
        self.coverable = sum(1 for x in range(E) if self.anchor[x] is not None)
        self.prep_s = round(time.monotonic() - t0, 3)

    # -- breadth-first search from start to a terminal of mode mi (not in excl), avoiding banned nodes
    def bfs_term(self, mi, start, banned, excl, maxd):
        T = self.term[mi]
        if start in T and start not in excl:
            return [start], []
        if maxd <= 0:
            return None
        prev = {start: None}
        q = deque([(start, 0)])
        adj = self.madj[mi]
        while q:
            x, dx = q.popleft()
            if dx >= maxd:
                continue
            for y, e in adj[x]:
                if y in prev or y in banned:
                    continue
                prev[y] = (x, e)
                if y in T and y not in excl:
                    nodes, edges, z = [y], [], y
                    while prev[z] is not None:
                        px, pe = prev[z]
                        edges.append(pe)
                        nodes.append(px)
                        z = px
                    nodes.reverse()
                    edges.reverse()
                    return nodes, edges
                q.append((y, dx + 1))
        return None

    def anchor_line(self, mi, x):
        Lmax = self.L if self.L is not None else 10 ** 9
        best = None
        for a, b in ((self.eu[x], self.ev[x]), (self.ev[x], self.eu[x])):
            p1 = self.bfs_term(mi, a, {b}, set(), Lmax - 1)
            if p1 is None:
                continue
            n1, e1 = p1
            p2 = self.bfs_term(mi, b, set(n1), {n1[-1]}, Lmax - 1 - len(e1))
            if p2 is None:
                continue
            n2, e2 = p2
            nodes = n1[::-1] + n2
            edges = e1[::-1] + [x] + e2
            if self.line_ok(mi, nodes, edges)[0] and (best is None or len(edges) < len(best[1])):
                best = (nodes, edges)
        return best

    def line_ok(self, mi, nodes, edges):
        if not (isinstance(mi, int) and 0 <= mi < self.M):
            return False, "unknown mode"
        if not isinstance(nodes, list) or not isinstance(edges, list) or not edges:
            return False, "line needs a node list and a non-empty edge list"
        if len(nodes) != len(edges) + 1:
            return False, "node list length != edges + 1"
        if self.L is not None and len(edges) > self.L:
            return False, "line has %d edges > max %d" % (len(edges), self.L)
        if len(set(nodes)) != len(nodes):
            return False, "line is not a simple path"
        T = self.term[mi]
        if nodes[0] not in T or nodes[-1] not in T:
            return False, "line does not start and end at terminals of its mode"
        for i, e in enumerate(edges):
            if not (isinstance(e, int) and not isinstance(e, bool) and 0 <= e < self.E and self.has[e]):
                return False, "unknown edge %r" % (e,)
            if e not in self.medge_set[mi]:
                return False, "edge %d is not in mode %s" % (e, self.mname[mi])
            a, b = nodes[i], nodes[i + 1]
            if not ((a == self.eu[e] and b == self.ev[e]) or (a == self.ev[e] and b == self.eu[e])):
                return False, "edge %d does not join nodes %r and %r" % (e, a, b)
        return True, ""


# --------------------------------------------------------------------------------------------------- verify
def verify(inst, sol, P=None, loose=False):
    """The official rules (feasibility_check.py, path-certificate route) plus, unless loose, the line rules.
    loose=True uses the checker's own tolerances and only its checks. Returns feasible, objective, reason."""
    tol, rel = (CHK_TOL, CHK_REL) if loose else (OUR_TOL, OUR_REL)

    def bad(lhs, rhs, op):
        if op == "le":
            va = max(0.0, lhs - rhs)
        elif op == "ge":
            va = max(0.0, rhs - lhs)
        else:
            va = abs(lhs - rhs)
        return va > max(tol, rel * max(abs(lhs), abs(rhs)))

    def no(reason, obj=None):
        return {"feasible": False, "objective": obj, "reason": reason}

    try:
        if not isinstance(sol, dict):
            return no("solution is not an object")
        for k in ("active_lines", "active_passenger_paths", "objective_value"):
            if k not in sol or sol[k] is None:
                return no("missing field " + k)
        for k in ("active_lines", "active_passenger_paths"):
            if sol[k] in ([], {}):
                return no("empty field " + k)
        rep = sol["objective_value"]
        if isinstance(rep, bool) or not isinstance(rep, (int, float)) or not math.isfinite(rep):
            return no("objective_value must be a finite number")
        if P is None:
            P = Problem(inst)
        lam = P.lam
        Fsum = defaultdict(float)
        acap = defaultdict(float)
        line_cost = 0.0
        for i, al in enumerate(sol["active_lines"]):
            name = al["mode"]
            if name not in P.mindex:
                return no("line %d: unknown mode %r" % (i, name))
            mi = P.mindex[name]
            f = al["frequency"]
            if isinstance(f, bool) or not isinstance(f, (int, float)):
                return no("line %d: frequency is not a number" % i)
            f = float(f)
            edges = al["edges"]
            if bad(-f, 0.0, "le"):
                return no("line %d: negative frequency %r" % (i, f))
            if bad(f, P.F, "le"):
                return no("line %d: frequency %r > F" % (i, f))
            if not loose:
                ok, why = P.line_ok(mi, al.get("nodes"), edges)
                if not ok:
                    return no("line %d: %s" % (i, why))
            c_l = 0.0
            for eid in edges:
                Fsum[eid] += f
                acap[2 * eid] += P.kappa[mi] * f
                acap[2 * eid + 1] += P.kappa[mi] * f
                if isinstance(eid, int) and 0 <= eid < P.E and P.has[eid]:
                    c_l += P.opc[eid]
            line_cost += P.Cf[mi] + c_l * f
        for eid in range(P.E):
            if P.has[eid] and bad(Fsum.get(eid, 0.0), P.cap[eid], "le"):
                return no("edge %d: total frequency %.6f > capacity %s" % (eid, Fsum.get(eid, 0.0), P.cap[eid]))
        paths = sol["active_passenger_paths"]
        flow_od = defaultdict(float)
        flow_arc = defaultdict(float)
        tt_paths = 0.0
        for ap in paths:
            key = (ap["origin"], ap["destination"])
            try:
                pf = float(ap["flow"])
            except (TypeError, ValueError):
                pf = -1.0
            arcs = ap.get("arcs", [])
            if key not in P.od or pf < -tol:
                return no("path %r: unknown OD pair or negative flow" % (key,))
            if not isinstance(arcs, list) or (not arcs and key[0] != key[1]):
                return no("path %r: no arcs" % (key,))
            cur = ap["origin"]
            ptt = 0.0
            for raw in arcs:
                try:
                    aid = int(raw)
                except (TypeError, ValueError):
                    return no("path %r: bad arc id" % (key,))
                e = aid >> 1
                if aid < 0 or e >= P.E or not P.has[e] or P.atail[aid] != cur:
                    return no("path %r: arcs do not form a walk from the origin" % (key,))
                cur = P.ahead[aid]
                ptt += P.tt[e]
            if cur != ap["destination"]:
                return no("path %r: does not end at the destination" % (key,))
            flow_od[key] += pf
            for raw in arcs:
                flow_arc[int(raw)] += pf
            tt_paths += pf * ptt
        for key, dem in P.od.items():
            if bad(flow_od.get(key, 0.0), dem, "eq"):
                return no("OD %r: served %.6f != demand %s" % (key, flow_od.get(key, 0.0), dem))
        for aid, tf in flow_arc.items():
            cap = acap.get(aid, 0.0)
            if tf > cap + tol and bad(tf, cap, "le"):
                return no("arc %d: flow %.6f > capacity %.6f" % (aid, tf, cap))
        atf = sol.get("arc_total_flow")
        if atf is not None:                 # the checker then takes travel time from this field
            tt = 0.0
            for k, fl in atf.items():
                try:
                    aid = int(k)
                    tt += float(fl) * (P.tt[aid >> 1] if 0 <= aid < 2 * P.E else 0.0)
                except (TypeError, ValueError):
                    pass
        else:
            tt = tt_paths
        true_obj = lam * line_cost + (1.0 - lam) * tt
        if bad(float(rep), true_obj, "eq"):
            return no("objective %r != recomputed %r" % (rep, true_obj), true_obj)
        return {"feasible": True, "objective": true_obj, "reason": ""}
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as e:
        return no("malformed solution: %r" % (e,))


def parts(P, sol):
    """Lines, mean line length, fixed cost, operating cost, travel time, line-rule breaches (ours or Gurobi's)."""
    try:
        lines = sol.get("active_lines") or []
        fixed = op = 0.0
        lens = []
        breaches = 0
        for al in lines:
            mi = P.mindex.get(al.get("mode"))
            f = float(al.get("frequency", 0.0))
            fixed += P.Cf[mi] if mi is not None else 0.0
            op += f * sum(P.opc[e] for e in al.get("edges") or [] if isinstance(e, int) and 0 <= e < P.E)
            lens.append(len(al.get("edges") or []))
            if mi is None or not P.line_ok(mi, al.get("nodes"), al.get("edges"))[0]:
                breaches += 1
        tt = 0.0
        for ap in sol.get("active_passenger_paths") or []:
            tt += float(ap.get("flow", 0.0)) * sum(P.tt[int(a) >> 1] for a in ap.get("arcs") or [])
        return {"lines": len(lines), "mean_line_edges": round(sum(lens) / len(lens), 3) if lens else None,
                "max_line_edges": max(lens) if lens else None, "fixed_cost": round(fixed, 4),
                "operating_cost": round(op, 4), "travel_time": round(tt, 4), "lambda": P.lam,
                "objective_recomputed": round(P.lam * (fixed + op) + (1 - P.lam) * tt, 4),
                "line_rule_breaches": breaches,
                "paths": len(sol.get("active_passenger_paths") or [])}
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e)[:200]}


# --------------------------------------------------------------------------------------------------- routing
def dijkstra(P, src, w, resid):
    dist = [INF] * P.n
    pred = [-1] * P.n
    dist[src] = 0.0
    h = [(0.0, src)]
    out = P.out
    while h:
        du, u = heapq.heappop(h)
        if du > dist[u]:
            continue
        for v, a in out[u]:
            if resid[a] <= 1e-9:
                continue
            nd = du + w[a]
            if nd < dist[v]:
                dist[v] = nd
                pred[v] = a
                heapq.heappush(h, (nd, v))
    return dist, pred


def route(P, w, deadline, keep=None, reroute=None):
    """Capacity-aware all-or-nothing routing. keep: paths dict whose origins outside `reroute` are kept.
    Returns (paths, arcflow) or None if some demand cannot be routed."""
    A = 2 * P.E
    resid = P.acap[:]
    arcflow = [0.0] * A
    paths = {}
    if keep is not None and reroute is not None:
        rs = set(reroute)
        for key, pd in keep.items():
            if key[0] in rs:
                continue
            paths[key] = dict(pd)
            for arcs, fl in pd.items():
                for a in arcs:
                    resid[a] -= fl
                    arcflow[a] += fl
        todo = [o for o in P.origins if o in rs]
    else:
        todo = P.origins
    atail = P.atail
    for o in todo:
        if time.monotonic() > deadline:
            raise Timeout()
        dist, pred = dijkstra(P, o, w, resid)
        for d, dem in P.by_origin[o]:
            if d == o:
                paths[(o, d)] = {(): dem}
                continue
            rem, tries = dem, 0
            while rem > EPS:
                if dist[d] == INF:
                    return None
                arcs = []
                x = d
                while x != o:
                    a = pred[x]
                    arcs.append(a)
                    x = atail[a]
                    if len(arcs) > P.n:
                        return None
                arcs.reverse()
                bott = min(resid[a] for a in arcs)
                if bott <= 1e-9:
                    tries += 1
                    if tries > 40:
                        return None
                    dist, pred = dijkstra(P, o, w, resid)
                    continue
                s = rem if rem <= bott else bott
                for a in arcs:
                    resid[a] -= s
                    arcflow[a] += s
                pk = paths.setdefault((o, d), {})
                t = tuple(arcs)
                pk[t] = pk.get(t, 0.0) + s
                rem -= s
    return paths, arcflow


# --------------------------------------------------------------------------------------------------- lines
def grow(P, x0, r):
    """A corridor line through edge x0 that follows the busiest neighbouring edges, closed at two terminals."""
    mi = P.emode[x0]
    L = P.L if P.L is not None else 10 ** 9
    dT, adj = P.dT[mi], P.madj[mi]
    u, v = P.eu[x0], P.ev[x0]
    if dT[u] == INF or dT[v] == INF:
        return None
    nodes, edges, used = deque([u, v]), deque([x0]), {u, v}
    grew = True
    while grew:
        grew = False
        for side in (0, 1):
            end = nodes[0] if side == 0 else nodes[-1]
            other = nodes[-1] if side == 0 else nodes[0]
            best = None
            for y, e in adj[end]:
                if y in used or r[e] <= 0.0:
                    continue
                if len(edges) + 1 + dT[y] + dT[other] > L:
                    continue
                if best is None or r[e] > best[0]:
                    best = (r[e], y, e)
            if best is not None:
                _, y, e = best
                if side == 0:
                    nodes.appendleft(y)
                    edges.appendleft(e)
                else:
                    nodes.append(y)
                    edges.append(e)
                used.add(y)
                grew = True
    nodes, edges = list(nodes), list(edges)
    room = L - len(edges)
    p1 = P.bfs_term(mi, nodes[0], used - {nodes[0]}, set(), room - dT[nodes[-1]])
    if p1 is None:
        return None
    n1, e1 = p1
    ban2 = used | set(n1)
    ban2.discard(nodes[-1])
    p2 = P.bfs_term(mi, nodes[-1], ban2, {n1[-1]}, room - len(e1))
    if p2 is None:
        return None
    n2, e2 = p2
    fn = n1[::-1][:-1] + nodes + n2[1:]
    fe = e1[::-1] + edges + e2
    if not P.line_ok(mi, fn, fe)[0]:
        return None
    return fn, fe


def design(P, arcflow, deadline, corridor=True):
    """Lines and frequencies that carry the given arc flows. Returns a list of [mode, nodes, edges, f, c_l]."""
    E = P.E
    r = [0.0] * E
    for x in range(E):
        R = arcflow[2 * x] if arcflow[2 * x] > arcflow[2 * x + 1] else arcflow[2 * x + 1]
        if R > EPS:
            mi = P.emode[x]
            if mi < 0:
                return None
            r[x] = R / P.kappa[mi]
    demanded = [x for x in range(E) if r[x] > 0.0]
    cands, seen = [], set()

    def add(mi, nodes, edges):
        key = (mi, tuple(sorted(edges)))
        if key not in seen:
            seen.add(key)
            cands.append((mi, nodes, edges, sum(P.opc[e] for e in edges)))

    for x in demanded:
        a = P.anchor[x]
        if a is None:
            return None
        add(P.emode[x], a[0], a[1])
        if corridor:
            g = grow(P, x, r)
            if g is not None:
                add(P.emode[x], g[0], g[1])
    if time.monotonic() > deadline:
        raise Timeout()
    pos = [P.opc[x] for x in range(E) if P.opc[x] > 0]
    epsw = 1e-6 * (sum(pos) / len(pos) if pos else 1.0)
    wgt = [P.opc[x] + epsw for x in range(E)]
    resid = r[:]
    Ft = [0.0] * E
    chosen_at = {}
    chosen = []
    open_cnt = len(demanded)

    def evaluate(ci):
        mi, nodes, edges, clen = cands[ci]
        avail = P.F - (chosen[chosen_at[ci]][3] if ci in chosen_at else 0.0)
        for e in edges:
            s = P.cap[e] - Ft[e]
            if s < avail:
                avail = s
        if avail <= 1e-12:
            return None
        vals = []
        for e in edges:
            re_ = resid[e]
            if re_ > EPS:
                vals.append((re_ if re_ < avail else avail, wgt[e]))
        if not vals:
            return None
        vals.sort()
        totw = sum(w for _, w in vals)
        pre = wbelow = 0.0
        fixed = 0.0 if ci in chosen_at else P.Cf[mi]
        best = None
        i, k = 0, len(vals)
        while i < k:
            f = vals[i][0]
            cov = pre + f * (totw - wbelow)
            ratio = (fixed + f * clen) / cov
            if best is None or ratio < best[0]:
                best = (ratio, f)
            while i < k and vals[i][0] == f:
                pre += vals[i][0] * vals[i][1]
                wbelow += vals[i][1]
                i += 1
        return best

    heap = []
    for ci in range(len(cands)):
        b = evaluate(ci)
        if b is not None:
            heap.append((b[0], ci))
    heapq.heapify(heap)
    pops = 0
    while heap and open_cnt > 0:
        pops += 1
        if (pops & 255) == 0 and time.monotonic() > deadline:
            raise Timeout()
        _, ci = heapq.heappop(heap)
        b = evaluate(ci)
        if b is None:
            continue
        if heap and b[0] > heap[0][0] * (1.0 + 1e-9) + 1e-15:
            heapq.heappush(heap, (b[0], ci))
            continue
        f = b[1]
        mi, nodes, edges, clen = cands[ci]
        for e in edges:
            Ft[e] += f
            if resid[e] > EPS:
                if resid[e] > f * (1.0 + 1e-12):
                    resid[e] -= f
                else:
                    resid[e] = 0.0
                    open_cnt -= 1
        if ci in chosen_at:
            chosen[chosen_at[ci]][3] += f
        else:
            chosen_at[ci] = len(chosen)
            chosen.append([mi, list(nodes), list(edges), f, clen])
        b2 = evaluate(ci)
        if b2 is not None:
            heapq.heappush(heap, (b2[0], ci))
    if open_cnt > 0:
        return None
    # trim: newest lines first, remove frequency no edge needs
    for idx in range(len(chosen) - 1, -1, -1):
        mi, nodes, edges, f, clen = chosen[idx]
        slack = f
        for e in edges:
            s = Ft[e] - r[e]
            if s < slack:
                slack = s
        if slack > EPS:
            chosen[idx][3] = f - slack
            for e in edges:
                Ft[e] -= slack
    lines = [c for c in chosen if c[3] > EPS]
    return lines


def line_freq(P, lines):
    Ft = [0.0] * P.E
    for mi, nodes, edges, f, clen in lines:
        for e in edges:
            Ft[e] += f
    return Ft


def objective(P, lines, arcflow):
    lc = sum(P.Cf[mi] + f * clen for mi, _, _, f, clen in lines)
    tt = 0.0
    for a, fl in enumerate(arcflow):
        if fl:
            tt += P.tt[a >> 1] * fl
    return P.lam * lc + (1.0 - P.lam) * tt


def build_solution(P, lines, paths):
    al = []
    lc = 0.0
    for i, (mi, nodes, edges, f, clen) in enumerate(lines):
        al.append({"line_index": i, "mode": P.mname[mi], "nodes": list(nodes), "edges": list(edges),
                   "frequency": f})
        lc += P.Cf[mi] + f * sum(P.opc[e] for e in edges)
    if not al:      # no passenger needs a line: the checker still wants one listed line; frequency 0
        best = None
        for x in range(P.E):
            a = P.anchor[x]
            if a is not None and (best is None or P.Cf[P.emode[x]] < best[0]):
                best = (P.Cf[P.emode[x]], P.emode[x], a)
        if best is not None:
            al.append({"line_index": 0, "mode": P.mname[best[1]], "nodes": list(best[2][0]),
                       "edges": list(best[2][1]), "frequency": 0.0})
            lc += best[0]
    ap = []
    tt = 0.0
    for (o, d), pd in paths.items():
        for arcs, fl in pd.items():
            if fl <= 0.0:
                continue
            ap.append({"origin": o, "destination": d, "arcs": list(arcs), "flow": fl})
            tt += fl * sum(P.tt[a >> 1] for a in arcs)
    obj = P.lam * lc + (1.0 - P.lam) * tt
    return {"objective_value": obj, "active_lines": al, "active_passenger_paths": ap,
            "num_active_lines": len(al), "total_travel_time": tt, "line_cost": lc,
            "solver": "MV2 of Munim, Inc. borndorfer2007 v%s (made with AI agents)" % VERSION}


# --------------------------------------------------------------------------------------------------- search
def search(P, seed, end, offer, log):
    rng = random.Random(seed)
    A = 2 * P.E
    lam = P.lam
    tw = [(1.0 - lam) * P.tt[a >> 1] for a in range(A)]
    capc = [0.0] * A
    for a in range(A):
        mi = P.emode[a >> 1]
        if mi >= 0:
            capc[a] = lam * P.opc[a >> 1] / P.kappa[mi]
    best = None
    stats = {"starts": [], "iters": 0, "improved": 0, "route_fail": 0, "design_fail": 0, "timeouts": 0}
    log["search"] = stats
    for beta in (0.0, 1.0, 0.5, 2.0):
        if time.monotonic() > end:
            break
        w = [tw[a] + beta * capc[a] for a in range(A)]
        try:
            res = route(P, w, end)
            if res is None:
                stats["route_fail"] += 1
                continue
            paths, af = res
            lines = design(P, af, end)
            if lines is None:
                stats["design_fail"] += 1
                continue
        except Timeout:
            stats["timeouts"] += 1
            break
        obj = objective(P, lines, af)
        stats["starts"].append([beta, round(obj, 4), len(lines)])
        if best is None or obj < best[0] - 1e-9:
            best = (obj, lines, paths, af)
            offer(obj, lines, paths, "start-beta%s" % beta)
    if best is None:
        return None, None
    norig = len(P.origins)
    while time.monotonic() < end:
        stats["iters"] += 1
        obj0, lines0, paths0, af0 = best
        beta = rng.choice((0.0, 0.25, 0.5, 1.0))
        rho = rng.choice((0.0, 0.5, 1.0, 2.0, 4.0))
        noise = rng.choice((0.0, 0.05, 0.15, 0.3))
        Ft = line_freq(P, lines0)
        w = [0.0] * A
        for a in range(A):
            e = a >> 1
            mi = P.emode[e]
            if mi < 0:
                w[a] = tw[a]
                continue
            if Ft[e] > EPS:
                spare = P.kappa[mi] * Ft[e] - af0[a]
                extra = 0.0 if spare > 1e-9 else beta
            else:
                extra = beta + rho
            c = tw[a] + capc[a] * extra
            if noise:
                c *= 1.0 + noise * rng.random()
            w[a] = c
        if rng.random() < 0.08:
            reroute = None
        else:
            frac = rng.choice((0.05, 0.1, 0.2, 0.35))
            k = max(1, int(round(frac * norig)))
            reroute = rng.sample(P.origins, min(k, norig))
        try:
            res = route(P, w, end, keep=paths0 if reroute is not None else None, reroute=reroute)
            if res is None:
                stats["route_fail"] += 1
                continue
            paths, af = res
            lines = design(P, af, end, corridor=True)
            if lines is None:
                stats["design_fail"] += 1
                continue
        except Timeout:
            stats["timeouts"] += 1
            break
        obj = objective(P, lines, af)
        if obj < obj0 - 1e-9 * max(1.0, abs(obj0)):
            stats["improved"] += 1
            best = (obj, lines, paths, af)
            offer(obj, lines, paths, "iter")
    stats["best"] = round(best[0], 4)
    stats["lines"] = len(best[1])
    return best[0], (best[1], best[2])


# --------------------------------------------------------------------------------------------------- driver
def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def solve(inst, out_path, time_limit, seed=1, workers=2, t0=None):
    T0 = T_START if t0 is None else t0
    end = T0 + max(0.5, min(0.9 * time_limit, time_limit - 3.0))
    P = Problem(inst)
    search_end = end - min(1.5, 0.1 * max(0.0, end - T0))
    log = {"version": VERSION, "seed": seed, "nodes": P.n, "edges": P.E, "modes": P.M, "lambda": P.lam,
           "L": P.L, "F": P.F, "od_pairs": len(P.od), "origins": len(P.origins), "od_dupes": P.od_dupes,
           "coverable_edges": P.coverable, "prep_s": P.prep_s, "events": [], "workers": workers,
           "terminals": [len(t) for t in P.term], "kappa": P.kappa, "fixed_cost": P.Cf}
    state = {"obj": None, "sol": None, "pending": None, "last": -1.0, "source": None}

    def flush():
        p = state["pending"]
        if p is None:
            return
        state["pending"] = None
        obj, lines, paths, source = p
        sol = build_solution(P, lines, paths)
        v = verify(inst, sol, P)
        state["last"] = time.monotonic()
        if not v["feasible"]:
            log.setdefault("verify_fail", []).append([source, v["reason"][:300]])
            return
        if state["obj"] is None or v["objective"] < state["obj"] - 1e-9:
            state.update(obj=v["objective"], sol=sol, source=source)
            log["events"].append([round(time.monotonic() - T0, 2), source, round(v["objective"], 4),
                                  len(sol["active_lines"])])
            if out_path:
                write_json(out_path, sol)

    def offer(obj, lines, paths, source):
        if state["pending"] is None or obj < state["pending"][0]:
            state["pending"] = (obj, lines, paths, source)
        if time.monotonic() - state["last"] >= 0.5:
            flush()

    child, conn = None, None
    if workers >= 2 and hasattr(os, "fork"):
        try:
            import multiprocessing as mp
            ctx = mp.get_context("fork")
            conn, cconn = ctx.Pipe(duplex=False)

            def run_child():
                try:
                    clog = {}
                    cobj, snap = search(P, seed + 7919, search_end, lambda *a: None, clog)
                    cconn.send((cobj, snap, clog.get("search")))
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
    flush()
    if child is not None:
        try:
            if conn.poll(max(0.05, end - time.monotonic() - 0.3)):
                cobj, snap, cstats = conn.recv()
                log["child"] = {"objective": cobj, "search": cstats}
                if snap is not None and (state["obj"] is None or cobj < state["obj"] - 1e-9):
                    state["pending"] = None
                    offer(cobj, snap[0], snap[1], "child")
                    flush()
            else:
                log["child"] = "no answer in time"
        except Exception as e:  # noqa: BLE001
            log["child_error"] = repr(e)[:300]
        try:
            child.terminate()
        except Exception:  # noqa: BLE001
            pass
    if state["sol"] is not None and out_path:
        write_json(out_path, state["sol"])
    log["final_objective"] = state["obj"]
    log["best_source"] = state["source"]
    if state["sol"] is not None:
        log["parts"] = parts(P, state["sol"])
    log["wall_s"] = round(time.monotonic() - T0, 3)
    return state["sol"], log


def main(argv=None):
    ap = argparse.ArgumentParser(description="borndorfer2007 (line planning) solver, MV2 of Munim, Inc.")
    ap.add_argument("--problem", default=SLUG)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=int(os.environ.get("MV2_BORN_SEED", "1")))
    ap.add_argument("--workers", type=int, default=int(os.environ.get("MV2_BORN_WORKERS", "2")))
    a, _ = ap.parse_known_args(argv)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    sol, log = solve(inst, a.output, a.time_limit, a.seed, a.workers)
    if os.environ.get("MV2_BORN_LOG") == "1":
        try:
            write_json(a.output + ".log.json", log)
        except Exception:  # noqa: BLE001
            pass
    sys.stderr.write(json.dumps({k: log.get(k) for k in ("version", "nodes", "edges", "od_pairs", "lambda",
                                                         "coverable_edges", "prep_s", "final_objective",
                                                         "best_source", "wall_s")}) + "\n")
    return 0 if sol is not None else 1


if __name__ == "__main__":
    sys.exit(main())

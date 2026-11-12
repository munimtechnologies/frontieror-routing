#!/usr/bin/env python3
"""MV2's solver for FrontierOR task laporte2003: the undirected travelling purchaser problem (TPP).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python solve.py --problem laporte2003 --instance in.json --output out.json --time-limit 60

Standard library only. The instance is read exactly the way the task's official feasibility_check.py reads it
(travel_costs "i,j"; purchase_costs "market,product"; supplies "product,market"; supply_type "unlimited" means
q = demand at every market that sells the product; a missing travel or purchase cost counts as 0).

For a fixed set S of visited markets, the cheapest purchase plan is exact and easy: every product is bought
greedily from the cheapest markets in S until its demand is met (each product is a separate fractional
knapsack). So the search is over S and the tour through S:
  * construction: the mandatory markets (the checker's M*) by cheapest insertion, then a feasibility repair that
    adds the market with the best (insertion + purchase) cost per unit of missing demand covered; a second
    construction starts from every useful market on a nearest-neighbour tour and lets the drop moves thin it out;
  * local search until nothing improves: 2-opt and node relocation on the tour; DROP a market (travel saved vs
    purchase cost added); ADD a market at its cheapest insertion (purchase saved vs travel added); SWAP a market
    for one of its 12 nearest unvisited markets in place. Purchase deltas are exact and incremental: only products
    the dropped market is actually used for, or products where the added market is no dearer than the current
    marginal price, are recomputed;
  * iterated local search: perturb (drop k random markets and repair, add k random markets, or a double bridge),
    accept a result no worse than the current one, go back to the best after 50 failures, restart from a new
    construction after 300.
With two CPUs a forked child runs the same search with another seed, starting from the other construction; the
parent keeps the better answer. Every answer is checked by verify() (the official checker's rules) before it is
written, and the file is replaced atomically. The run stops at min(0.9 T, T - 3) seconds after start-up.
Environment: MV2_TPP_WORKERS (default 2; 1 = no child), MV2_TPP_SEED (default 1), MV2_TPP_LOG (write
<output>.log.json).
"""
import argparse
import json
import os
import random
import sys
import tempfile
import time

T_START = time.time()
VERSION = "0.1.0"
EPS = 1e-6
QEPS = 1e-9
TOL = 1e-5  # the official checker's tolerance
INF = float("inf")
REQUIRED = ("objective_value", "purchases", "tour", "tour_edges", "visited_markets")


class Problem:
    def __init__(self, inst):
        n = int(inst["num_vertices"])
        if n < 3:
            raise ValueError("need at least 3 vertices")
        self.n = n
        depot = int(inst["depot"])
        if not 0 <= depot < n:
            raise ValueError("depot %r outside 0..%d" % (depot, n - 1))
        self.depot = depot
        P = int(inst["num_products"])
        self.P = P
        D = [[0] * n for _ in range(n)]
        for key, c in inst["travel_costs"].items():
            a, b = (int(s) for s in key.split(","))
            D[a][b] = c
            D[b][a] = c
        for i in range(n):
            D[i][i] = 0
        self.D = D
        dem = [inst["product_demands"][k] for k in range(P)]
        self.dem = dem
        pm = {}
        for ks, ms in inst["product_markets"].items():
            pm[int(ks)] = [int(v) for v in ms]
        self.pm = pm
        price = {}
        for key, c in inst["purchase_costs"].items():
            parts = key.split(",")
            price.setdefault(int(parts[1]), {})[int(parts[0])] = c  # checker: "market,product"
        self.price = price
        supply = {}
        self.supply_type = inst.get("supply_type")
        if self.supply_type == "unlimited":
            for k in range(P):
                supply[k] = {i: dem[k] for i in pm.get(k, [])}
        else:
            for key, v in (inst.get("supplies") or {}).items():
                parts = key.split(",")
                supply.setdefault(int(parts[0]), {})[int(parts[1])] = v  # checker: "product,market"
        self.supply = supply
        # mandatory markets, the checker's rule: some product cannot be bought in full without the market
        mand = [False] * n
        mand[depot] = True
        for k in range(P):
            mk = pm.get(k, [])
            sk = supply.get(k, {})
            total = sum(sk.get(j, 0) for j in mk)
            cnt = {}
            for j in mk:
                cnt[j] = cnt.get(j, 0) + 1
            for i, c in cnt.items():
                if i != depot and 0 <= i < n and total - c * sk.get(i, 0) < dem[k]:
                    mand[i] = True
        self.mand = mand
        # purchase options per product, cheapest first (ties by market id)
        opts = []
        prods_of = [[] for _ in range(n)]
        self.infeasible_products = []
        for k in range(P):
            seen = set()
            lst = []
            pk = price.get(k, {})
            sk = supply.get(k, {})
            for m in pm.get(k, []):
                if m in seen or not 0 <= m < n:
                    continue
                seen.add(m)
                q = sk.get(m, 0)
                if q > 0:
                    lst.append((pk.get(m, 0), m, q))
            lst.sort()
            opts.append(lst)
            for p, m, q in lst:
                prods_of[m].append((k, p, q))
            if dem[k] > QEPS and sum(q for _, _, q in lst) < dem[k] - QEPS:
                self.infeasible_products.append(k)
        self.opts = opts
        self.prods_of = prods_of
        self.markets = [i for i in range(n) if i != depot]
        self.useful = [i for i in self.markets if prods_of[i]]
        self.mand_markets = [i for i in self.markets if mand[i]]
        self.metric = inst.get("coordinates") is not None and self._looks_metric()
        self.near = []
        for i in range(n):
            Di = D[i]
            others = sorted((j for j in self.markets if j != i), key=lambda j: (Di[j], j))
            self.near.append(others[:12])

    def _looks_metric(self):
        rng = random.Random(12345)
        D, n = self.D, self.n
        for _ in range(3000):
            a, b, c = rng.randrange(n), rng.randrange(n), rng.randrange(n)
            if D[a][c] > D[a][b] + D[b][c] + 2:
                return False
        return True


def route_cost(pb, t):
    D = pb.D
    s = 0
    prev = t[-1]
    for v in t:
        s += D[prev][v]
        prev = v
    return s


def build_solution(pb, route):
    """The full answer for a cyclic route containing the depot (None if it cannot be a feasible answer)."""
    if pb.depot not in route or len(route) < 3 or len(set(route)) != len(route):
        return None
    i = route.index(pb.depot)
    r = route[i:] + route[:i]
    inS = bytearray(pb.n)
    for v in r:
        inS[v] = 1
    purchases = {}
    pc = 0
    for k in range(pb.P):
        need = pb.dem[k]
        amounts = {}
        if need > QEPS:
            for price, m, q in pb.opts[k]:
                if inS[m]:
                    if q >= need - QEPS:
                        amounts[str(m)] = need
                        pc += price * need
                        need = 0
                        break
                    amounts[str(m)] = q
                    pc += price * q
                    need -= q
            if need > QEPS:
                return None
        purchases[str(k)] = amounts
    L = len(r)
    rc = route_cost(pb, r)
    return {"objective_value": float(rc + pc), "visited_markets": sorted(r[1:]), "tour": list(r),
            "tour_edges": [[r[j], r[(j + 1) % L]] for j in range(L)], "purchases": purchases,
            "routing_cost": rc, "purchase_cost": pc}


def _finite_number(v):
    return not isinstance(v, bool) and isinstance(v, (int, float)) and v == v and v not in (INF, -INF)


def verify(pb, sol):
    """(ok, reason, objective): the official checker's rules (constraints 2-10), applied to a solution dict."""
    if not isinstance(sol, dict):
        return False, "solution is not a JSON object", None
    missing = [f for f in REQUIRED if sol.get(f) is None]
    if missing:
        return False, "missing " + ", ".join(missing), None
    if sol["tour"] in ([], {}):
        return False, "empty tour", None
    ov = sol["objective_value"]
    if not _finite_number(ov):
        return False, "objective_value must be a finite number", None
    try:
        n, depot = pb.n, pb.depot
        vis = set(sol["visited_markets"])
        y = [0] * n
        y[depot] = 1
        for i in pb.markets:
            if i in vis:
                y[i] = 1
        x = set()
        for e in sol["tour_edges"]:
            a, b = e[0], e[1]
            x.add((min(a, b), max(a, b)))
        deg = {}
        for a, b in x:
            deg[a] = deg.get(a, 0) + 1
            if b != a:
                deg[b] = deg.get(b, 0) + 1
        for v in range(n):
            if deg.get(v, 0) != 2 * y[v]:
                return False, "degree of vertex %d is %d, expected %d" % (v, deg.get(v, 0), 2 * y[v]), None
        vd = vis | {depot}
        adj = {}
        for a, b in x:
            if a in vd and b in vd:
                adj.setdefault(a, set()).add(b)
                adj.setdefault(b, set()).add(a)
        reach = {depot}
        stack = [depot]
        while stack:
            u = stack.pop()
            for w in adj.get(u, ()):
                if w not in reach:
                    reach.add(w)
                    stack.append(w)
        for v in vd - reach:
            if isinstance(v, int) and 0 <= v < n and y[v]:
                return False, "vertex %d not connected to the depot" % v, None
        z = {k: {} for k in range(pb.P)}
        for ks, md in sol["purchases"].items():
            k = int(ks)
            if k not in z:
                return False, "unknown product %r" % ks, None
            for ms, qty in md.items():
                z[k][int(ms)] = float(qty)
        for k in range(pb.P):
            tot = sum(z[k].values())
            if abs(tot - pb.dem[k]) > TOL:
                return False, "product %d: bought %r, demand %r" % (k, tot, pb.dem[k]), None
            for m, qty in z[k].items():
                if qty > TOL:
                    q = pb.supply.get(k, {}).get(m, 0)
                    ym = y[m] if 0 <= m < n else 0
                    if qty - q * ym > TOL:
                        return False, "product %d: %r bought at market %d (supply %r, visited %d)" % (
                            k, qty, m, q, ym), None
            for m in pb.pm.get(k, []):
                if z[k].get(m, 0.0) < -TOL:
                    return False, "negative purchase", None
        for i in pb.mand_markets:
            if not y[i]:
                return False, "mandatory market %d not visited" % i, None
        D = pb.D
        route = 0
        for a, b in x:
            if 0 <= a < n and 0 <= b < n and a != b:
                route += D[a][b]
        purchase = 0
        for k in z:
            pk = pb.price.get(k, {})
            for m, zq in z[k].items():
                purchase += pk.get(m, 0) * zq
        true = float(route + purchase)
        if abs(ov - true) > max(1e-3, 1e-3 * abs(true)):
            return False, "objective_value %r differs from the recomputed %r" % (ov, true), None
        return True, "", true
    except (TypeError, ValueError, KeyError, IndexError, AttributeError) as e:
        return False, "malformed solution: %r" % (e,), None


class Search:
    def __init__(self, pb, seed, deadline, start="add"):
        self.pb = pb
        self.rng = random.Random(seed)
        self.deadline = deadline
        self.start = start
        n, P = pb.n, pb.P
        self.inS = bytearray(n)
        self.t = []
        self.pcost = [0] * P
        self.marg = [-INF] * P
        self.used = [[] for _ in range(P)]
        self.usedby = [set() for _ in range(n)]
        self.cand = pb.useful if pb.metric else pb.markets
        self.stats = {"seed": seed, "start": start, "iterations": 0, "restarts": 0, "ls_calls": 0,
                      "moves_2opt": 0, "moves_relocate": 0, "drops": 0, "adds": 0, "swaps": 0}

    def late(self):
        return time.time() >= self.deadline

    # ------------------------------------------------------------------ purchase bookkeeping
    def prod_cost(self, k):
        inS = self.inS
        need = self.pb.dem[k]
        if need <= QEPS:
            return 0
        c = 0
        for price, m, q in self.pb.opts[k]:
            if inS[m]:
                if q >= need - QEPS:
                    return c + price * need
                c += price * q
                need -= q
        return INF

    def refresh(self, k):
        inS = self.inS
        need = self.pb.dem[k]
        c = 0
        used = []
        marg = -INF
        if need > QEPS:
            done = False
            for price, m, q in self.pb.opts[k]:
                if inS[m]:
                    used.append(m)
                    if q >= need - QEPS:
                        c = c + price * need
                        marg = price
                        done = True
                        break
                    c += price * q
                    need -= q
            if not done:
                c, marg = INF, INF
        ub = self.usedby
        for m in self.used[k]:
            ub[m].discard(k)
        for m in used:
            ub[m].add(k)
        self.used[k] = used
        self.pcost[k] = c
        self.marg[k] = marg

    def set_route(self, t):
        pb = self.pb
        self.t = list(t)
        inS = self.inS
        for i in range(pb.n):
            inS[i] = 0
        for v in self.t:
            inS[v] = 1
        inS[pb.depot] = 1
        for s in self.usedby:
            s.clear()
        for k in range(pb.P):
            self.used[k] = []
            self.refresh(k)

    def purchase_feasible(self):
        return all(c < INF for c in self.pcost)

    def is_feasible(self):
        return len(self.t) >= 3 and self.purchase_feasible()

    def total(self):
        return route_cost(self.pb, self.t) + sum(self.pcost)

    # ------------------------------------------------------------------ deltas
    def best_insertion(self, j):
        D = self.pb.D
        Dj = D[j]
        t = self.t
        best, bi = INF, 0
        prev = t[-1]
        for idx in range(len(t)):
            v = t[idx]
            c = D[prev][j] + Dj[v] - D[prev][v]
            if c < best:
                best, bi = c, idx
            prev = v
        return best, bi

    def removal_gain(self, idx):
        t = self.t
        D = self.pb.D
        p, u, q = t[idx - 1], t[idx], t[(idx + 1) % len(t)]
        return D[p][u] + D[u][q] - D[p][q]

    def add_affected(self, j):
        marg = self.marg
        return [k for k, p, _ in self.pb.prods_of[j] if p <= marg[k]]

    def add_purchase_delta(self, j):
        inS = self.inS
        inS[j] = 1
        d = 0
        for k in self.add_affected(j):
            d += self.prod_cost(k) - self.pcost[k]
        inS[j] = 0
        return d

    def drop_purchase_delta(self, i):
        inS = self.inS
        inS[i] = 0
        d = 0
        for k in self.usedby[i]:
            nc = self.prod_cost(k)
            if nc == INF:
                d = INF
                break
            d += nc - self.pcost[k]
        inS[i] = 1
        return d

    def swap_affected(self, i, j):
        ks = set(self.usedby[i])
        ks.update(self.add_affected(j))
        return ks

    def swap_purchase_delta(self, i, j):
        inS = self.inS
        ks = self.swap_affected(i, j)
        inS[i] = 0
        inS[j] = 1
        d = 0
        for k in ks:
            nc = self.prod_cost(k)
            if nc == INF:
                d = INF
                break
            d += nc - self.pcost[k]
        inS[i] = 1
        inS[j] = 0
        return d

    # ------------------------------------------------------------------ applying moves
    def apply_add(self, j, idx):
        affected = self.add_affected(j)
        self.t.insert(idx, j)
        self.inS[j] = 1
        for k in affected:
            self.refresh(k)

    def apply_drop(self, i):
        idx = self.t.index(i)
        self.t.pop(idx)
        self.inS[i] = 0
        for k in list(self.usedby[i]):
            self.refresh(k)

    def apply_swap(self, i, j):
        ks = self.swap_affected(i, j)
        idx = self.t.index(i)
        self.t[idx] = j
        self.inS[i] = 0
        self.inS[j] = 1
        for k in ks:
            self.refresh(k)

    # ------------------------------------------------------------------ tour moves (purchases unchanged)
    def two_opt(self, t):
        m = len(t)
        if m < 4:
            return False
        D = self.pb.D
        any_imp = False
        improved = True
        while improved:
            improved = False
            for i in range(m - 2):
                if self.late():
                    return any_imp
                a, b = t[i], t[i + 1]
                Da, Db = D[a], D[b]
                dab = Da[b]
                jmax = m if i > 0 else m - 1
                j = i + 2
                while j < jmax:
                    c = t[j]
                    d = t[j + 1] if j + 1 < m else t[0]
                    delta = Da[c] + Db[d] - dab - D[c][d]
                    if delta < -EPS:
                        t[i + 1:j + 1] = t[i + 1:j + 1][::-1]
                        self.stats["moves_2opt"] += 1
                        improved = any_imp = True
                        b = t[i + 1]
                        Db = D[b]
                        dab = Da[b]
                    j += 1
        return any_imp

    def relocate(self, t):
        if len(t) < 4:
            return False
        D = self.pb.D
        any_imp = False
        improved = True
        while improved:
            improved = False
            i = 0
            while i < len(t):
                if self.late():
                    return any_imp
                m = len(t)
                p, u, q = t[i - 1], t[i], t[(i + 1) % m]
                gain = D[p][u] + D[u][q] - D[p][q]
                Du = D[u]
                best, ba = gain - EPS, None
                for j in range(m):
                    a = t[j]
                    b = t[j + 1] if j + 1 < m else t[0]
                    if a == u or b == u:
                        continue
                    ins = D[a][u] + Du[b] - D[a][b]
                    if ins < best:
                        best, ba = ins, a
                if ba is not None:
                    t.pop(i)
                    k = t.index(ba)
                    t.insert(k + 1, u)
                    self.stats["moves_relocate"] += 1
                    improved = any_imp = True
                else:
                    i += 1
        return any_imp

    # ------------------------------------------------------------------ market moves
    def drop_pass(self):
        mand = self.pb.mand
        any_imp = False
        while not self.late() and len(self.t) >= 4:
            cands = []
            for idx in range(len(self.t)):
                v = self.t[idx]
                if mand[v]:
                    continue
                d = self.drop_purchase_delta(v) - self.removal_gain(idx)
                if d < -EPS:
                    cands.append((d, v))
            if not cands:
                break
            cands.sort()
            applied = False
            for _, v in cands:
                if self.late() or len(self.t) < 4:
                    break
                d = self.drop_purchase_delta(v) - self.removal_gain(self.t.index(v))
                if d < -EPS:
                    self.apply_drop(v)
                    self.stats["drops"] += 1
                    applied = any_imp = True
            if not applied:
                break
        return any_imp

    def add_pass(self):
        metric = self.pb.metric
        any_imp = False
        while not self.late():
            cands = []
            for j in self.cand:
                if self.inS[j]:
                    continue
                pd = self.add_purchase_delta(j)
                if metric and pd > -EPS:
                    continue  # with metric travel costs an insertion never pays for itself
                ins, _ = self.best_insertion(j)
                if pd + ins < -EPS:
                    cands.append((pd + ins, j))
            if not cands:
                break
            cands.sort()
            applied = False
            for _, j in cands:
                if self.late():
                    break
                if self.inS[j]:
                    continue
                pd = self.add_purchase_delta(j)
                ins, idx = self.best_insertion(j)
                if pd + ins < -EPS:
                    self.apply_add(j, idx)
                    self.stats["adds"] += 1
                    applied = any_imp = True
            if not applied:
                break
        return any_imp

    def swap_pass(self):
        pb = self.pb
        D = pb.D
        any_imp = False
        order = [v for v in self.t if not pb.mand[v]]
        self.rng.shuffle(order)
        for i in order:
            if self.late():
                break
            if not self.inS[i]:
                continue
            idx = self.t.index(i)
            p, q = self.t[idx - 1], self.t[(idx + 1) % len(self.t)]
            base = D[p][i] + D[i][q]
            best, bj = -EPS, -1
            for j in pb.near[i]:
                if self.inS[j] or (pb.metric and not pb.prods_of[j]):
                    continue
                rd = D[p][j] + D[j][q] - base
                d = rd + self.swap_purchase_delta(i, j)
                if d < best:
                    best, bj = d, j
            if bj >= 0:
                self.apply_swap(i, bj)
                self.stats["swaps"] += 1
                any_imp = True
        return any_imp

    def local_search(self):
        self.stats["ls_calls"] += 1
        while not self.late():
            imp = self.two_opt(self.t)
            imp = self.relocate(self.t) or imp
            imp = self.drop_pass() or imp
            imp = self.add_pass() or imp
            imp = self.swap_pass() or imp
            if not imp:
                break

    # ------------------------------------------------------------------ construction and repair
    def repair(self, noisy):
        pb = self.pb
        for _ in range(pb.n + 1):
            bad = [k for k in range(pb.P) if self.pcost[k] == INF]
            if not bad:
                return True
            deficit = {}
            for k in bad:
                deficit[k] = pb.dem[k] - sum(q for _, m, q in pb.opts[k] if self.inS[m])
            scores = []
            for j in pb.useful:
                if self.inS[j]:
                    continue
                cover = 0.0
                buy = 0.0
                for k, p, q in pb.prods_of[j]:
                    if k in deficit:
                        u = min(q, deficit[k])
                        cover += u / float(pb.dem[k])
                        buy += p * u
                if cover <= 0:
                    continue
                ins, idx = self.best_insertion(j)
                scores.append(((max(ins, 0) + buy + 1e-9) / cover, j, idx))
            if not scores:
                return False
            scores.sort()
            pick = scores[self.rng.randrange(min(3, len(scores)))] if noisy else scores[0]
            self.apply_add(pick[1], pick[2])
        return self.purchase_feasible()

    def ensure_min2(self):
        """A simple cycle needs the depot and at least two markets."""
        while len(self.t) < 3 and self.purchase_feasible():
            best, bj, bidx = INF, -1, 0
            for j in self.pb.markets:
                if self.inS[j]:
                    continue
                ins, idx = self.best_insertion(j)
                d = ins + self.add_purchase_delta(j)
                if d < best:
                    best, bj, bidx = d, j, idx
            if bj < 0:
                return
            self.apply_add(bj, bidx)

    def construct(self, mode, noisy):
        pb = self.pb
        if mode == "drop":
            S = set(pb.useful) | set(pb.mand_markets)
            D = pb.D
            t = [pb.depot]
            cur = pb.depot
            while S:
                Dc = D[cur]
                ranked = sorted(S, key=lambda v: (Dc[v], v))
                nxt = ranked[1] if noisy and len(ranked) > 1 and self.rng.random() < 0.2 else ranked[0]
                t.append(nxt)
                S.remove(nxt)
                cur = nxt
            self.set_route(t)
            self.two_opt(self.t)
            self.repair(noisy)
        else:
            self.set_route([pb.depot])
            mk = list(pb.mand_markets)
            if noisy:
                self.rng.shuffle(mk)
            for j in mk:
                ins, idx = self.best_insertion(j)
                self.apply_add(j, idx)
            self.two_opt(self.t)
            self.repair(noisy)
        self.ensure_min2()

    def perturb(self):
        pb = self.pb
        rng = self.rng
        k = rng.randint(1, max(1, min(6, (len(self.t) - 1) // 3)))
        r = rng.random()
        if r < 0.45:
            droppable = [v for v in self.t if not pb.mand[v]]
            rng.shuffle(droppable)
            for v in droppable[:k]:
                if len(self.t) <= 3:
                    break
                self.apply_drop(v)
            self.repair(True)
        elif r < 0.75:
            outs = [j for j in self.cand if not self.inS[j]]
            rng.shuffle(outs)
            for j in outs[:k]:
                ins, idx = self.best_insertion(j)
                self.apply_add(j, idx)
        else:
            t = self.t
            m = len(t)
            if m >= 6:
                L = max(2, min(50, m // 3))
                p1 = rng.randint(1, m - 3)
                p2 = p1 + rng.randint(1, min(L, m - p1 - 2))
                p3 = p2 + rng.randint(1, min(L, m - p2 - 1))
                self.t = t[:p1] + t[p2:p3] + t[p1:p2] + t[p3:]
        self.ensure_min2()

    # ------------------------------------------------------------------ driver
    def run(self, on_improve=None):
        pb = self.pb
        self.construct(self.start, noisy=False)
        if not self.is_feasible():
            self.stats["infeasible"] = True
            return None, INF
        self.stats["construction"] = self.total()
        self.local_search()
        best, bc = list(self.t), self.total()
        self.stats["first_local_search"] = bc
        self.stats["events"] = [[round(time.time() - T_START, 3), bc]]
        if on_improve:
            on_improve(best, bc)
        cur, cc = list(best), bc
        since = 0
        mode = self.start
        while not self.late():
            self.stats["iterations"] += 1
            self.perturb()
            if not self.is_feasible():
                self.set_route(cur)
                since += 1
                continue
            self.local_search()
            nc = self.total()
            if nc < bc - EPS:
                best, bc = list(self.t), nc
                since = 0
                self.stats["events"].append([round(time.time() - T_START, 3), bc])
                if on_improve:
                    on_improve(best, bc)
            else:
                since += 1
            if nc <= cc + EPS:
                cur, cc = list(self.t), nc
            else:
                self.set_route(cur)
            if since and since % 300 == 0 and not self.late():
                self.stats["restarts"] += 1
                mode = "drop" if mode == "add" else "add"
                self.construct(mode, noisy=True)
                if self.is_feasible():
                    self.local_search()
                    cur, cc = list(self.t), self.total()
                    if cc < bc - EPS:
                        best, bc = list(cur), cc
                        since = 0
                        self.stats["events"].append([round(time.time() - T_START, 3), bc])
                        if on_improve:
                            on_improve(best, bc)
                else:
                    self.set_route(best)
                    cur, cc = list(best), bc
            elif since and since % 50 == 0:
                self.set_route(best)
                cur, cc = list(best), bc
        self.stats["best"] = bc
        self.stats["markets_in_best"] = len(best) - 1
        self.stats["events"] = self.stats["events"][:5] + self.stats["events"][-15:]
        return best, bc


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="laporte2003")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    a = ap.parse_args(argv)
    T = float(a.time_limit)
    deadline = T_START + min(0.9 * T, T - 3.0)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    pb = Problem(inst)
    seed = int(os.environ.get("MV2_TPP_SEED", "1"))
    workers = int(os.environ.get("MV2_TPP_WORKERS", "2"))
    log = {"version": VERSION, "n": pb.n, "products": pb.P, "mandatory": len(pb.mand_markets),
           "useful": len(pb.useful), "metric": pb.metric, "supply_type": pb.supply_type, "T": T,
           "load_s": round(time.time() - T_START, 3), "workers": workers,
           "infeasible_products": pb.infeasible_products[:20]}
    child_pid, child_path = None, None
    if workers >= 2 and hasattr(os, "fork"):
        child_path = os.path.join(tempfile.gettempdir(), "mv2_tpp_child_%d.json" % os.getpid())
        try:
            pid = os.fork()
        except OSError:
            pid = None
        if pid == 0:
            code = 0
            try:
                s = Search(pb, seed + 1000, deadline - 0.25, start="drop")
                bt, bcost = s.run()
                write_atomic(child_path, {"route": bt, "cost": bcost, "stats": s.stats})
            except BaseException:  # noqa: BLE001 - the child must never outlive its parent's budget
                code = 1
            os._exit(code)
        child_pid = pid
    state = {"last_write": 0.0, "written": None}

    def on_improve(route, cost, force=False):
        now = time.time()
        if not force and now - state["last_write"] < 0.5 and state["written"] is not None:
            return
        sol = build_solution(pb, route)
        if sol is None:
            log.setdefault("verify_failures", []).append("build_solution returned None")
            return
        ok, why, real = verify(pb, sol)
        if ok:
            write_atomic(a.output, sol)
            state["last_write"] = now
            state["written"] = real
        else:
            log.setdefault("verify_failures", []).append(why)

    s = Search(pb, seed, deadline, start="add")
    best, bc = s.run(on_improve)
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
            ct, ccost = ch["route"], ch["cost"]
            if ct is not None and ccost < bc - EPS:
                sol = build_solution(pb, ct)
                if sol is not None and verify(pb, sol)[0]:
                    best, bc = ct, ccost
                    log["best_source"] = "child"
        except Exception as e:  # noqa: BLE001
            log["child_error"] = repr(e)[:200]
    if best is not None and (state["written"] is None or bc < state["written"] - EPS):
        on_improve(best, bc, force=True)
    log["best"] = state["written"]
    log["wall_s"] = round(time.time() - T_START, 3)
    if os.environ.get("MV2_TPP_LOG"):
        try:
            write_atomic(a.output + ".log.json", log)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

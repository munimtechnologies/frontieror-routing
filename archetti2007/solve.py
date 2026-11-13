"""solve.py: MV2's candidate solver for FrontierOR task archetti2007.

Vendor-managed inventory routing with the order-up-to policy and one vehicle (Archetti, Bertazzi, Laporte and
Speranza 2007, Transportation Science 41(3)). MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working
in MV2's name. License: Apache-2.0. Standard library only.

Method
- Under the order-up-to rule a retailer's whole plan is fixed by WHICH periods it is visited: every visit fills it
  to its maximum. So each retailer gets the list of its stockout-free visit patterns (at most 2^H, 64 for H = 6)
  that ship something at every visit, each with its delivery vector and its exact holding cost (its own holding
  cost minus the supplier holding cost its shipments remove).
- Total cost = a constant + the chosen patterns' holding costs + one closed tour from the supplier per period.
- Simulated annealing picks one retailer at a time and prices ALL its other patterns at once: holding change +
  exact removal / cheapest-insertion change in every period whose visit flips (exact re-optimised tours when a
  tour holds at most 4 retailers) + an adaptive penalty on vehicle-capacity and supplier-stock excess.
  2-opt after each accepted move, 2-opt + or-opt sweeps, three cooling cycles restarting from the best plan, and a
  strict feasible descent at the end.
- Two workers (fork) with different seeds when available. The best plan is written only after verify() (the
  official checker's rules) accepts it, atomically, and re-written whenever it improves.

python solve.py --problem archetti2007 --instance inst.json --output sol.json --time-limit 60
"""
import argparse
import itertools
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
TOL = 1e-5          # the official checker's tolerance
VTOL = 1e-7         # capacity / supplier excess treated as zero
EXACT_MAX = 4       # tours with at most this many retailers are priced and ordered exactly
MAX_ALL_CANDS = 128  # above this many patterns, a move only looks at patterns one or two flips away


class Pattern(object):
    __slots__ = ("mask", "x", "inv", "hc")

    def __init__(self, mask, x, inv, hc):
        self.mask = mask  # bit t = visited in period t + 1
        self.x = x        # shipped quantity per period (length H)
        self.inv = inv    # inventory I_1 .. I_{H+1} (length H + 1)
        self.hc = hc      # h_s * sum(inv) - h_0 * sum_t x_t * (H + 1 - t)


class Problem(object):
    def __init__(self, inst):
        self.n = int(inst["num_retailers"])
        self.H = int(inst["time_horizon"])
        self.C = inst["vehicle_capacity"]
        self.dist = inst["distance_matrix"]
        n, H = self.n, self.H
        # the checker prices segment {i, j} as dist[max][min]; use exactly that everywhere
        self.D = [[self.dist[max(i, j)][min(i, j)] for j in range(n + 1)] for i in range(n + 1)]
        sup = inst["supplier"]
        self.B0 = sup["starting_inventory"]
        self.r0 = sup["production_rate"]
        self.h0 = sup["inventory_cost"]
        by = {}
        for ret in inst["retailers"]:
            by[int(ret["id"])] = ret
        self.r = [0] * (n + 1)
        self.U = [0] * (n + 1)
        self.I0 = [0] * (n + 1)
        self.h = [0.0] * (n + 1)
        for s in range(1, n + 1):
            ret = by[s]
            self.r[s] = ret["demand"]
            self.U[s] = ret["max_inventory"]
            self.I0[s] = ret["starting_inventory"]
            self.h[s] = ret["inventory_cost"]
        # cumulative shipments up to period t (0-based) may not exceed B0 + t * r0 (B_t >= shipped_t)
        self.SC = [self.B0 + t * self.r0 for t in range(H)]
        self.const = self.h0 * sum(self.B0 + t * self.r0 for t in range(H + 1))
        self.pats = [[]] + [self.patterns(s) for s in range(1, n + 1)]
        self.by_mask = [dict((p.mask, k) for k, p in enumerate(P)) for P in self.pats]
        self.feasible_patterns = all(self.pats[s] for s in range(1, n + 1))
        pairs = [self.D[i][j] for i in range(n + 1) for j in range(n + 1) if i != j]
        self.dbar = float(sum(pairs)) / len(pairs) if pairs else 1.0
        self.ex = {}

    def patterns(self, s):
        H, U, r, h, h0 = self.H, self.U[s], self.r[s], self.h[s], self.h0
        out = []

        def rec(t, inv, mask, xs, invs):
            if t == H:
                hc = h * sum(invs) - h0 * sum(xs[k] * (H - k) for k in range(H))
                out.append(Pattern(mask, tuple(xs), tuple(invs), hc))
                return
            nxt = inv - r
            if nxt >= -EPS:
                rec(t + 1, nxt, mask, xs + [0], invs + [nxt])
            if U - inv > EPS:
                nxt = U - r
                if nxt >= -EPS:
                    rec(t + 1, nxt, mask | (1 << t), xs + [U - inv], invs + [nxt])

        if self.I0[s] >= -EPS:
            rec(0, self.I0[s], 0, [], [self.I0[s]])
        return out


# ---------------------------------------------------------------------------------------------------------------
# tours (lists of retailers; the supplier 0 is implicit at both ends)

def tour_cost(D, tour):
    c = 0
    prev = 0
    for v in tour:
        c += D[prev][v]
        prev = v
    return c + D[prev][0]


def exact_tour(pb, nodes):
    """Optimal order of a small set of retailers (all permutations); returns (cost, new list)."""
    key = tuple(sorted(nodes))
    hit = pb.ex.get(key)
    if hit is None:
        if not key:
            hit = (0, ())
        else:
            best, bo = None, None
            for p in itertools.permutations(key):
                c = tour_cost(pb.D, p)
                if best is None or c < best:
                    best, bo = c, p
            hit = (best, tuple(bo))
        if len(pb.ex) > 200000:
            pb.ex.clear()
        pb.ex[key] = hit
    return hit[0], list(hit[1])


def best_insert(D, tour, s):
    Ds = D[s]
    prev = 0
    bc, bp = None, 0
    for k, v in enumerate(tour):
        c = D[prev][s] + Ds[v] - D[prev][v]
        if bc is None or c < bc:
            bc, bp = c, k
        prev = v
    c = D[prev][s] + Ds[0] - D[prev][0]
    if bc is None or c < bc:
        bc, bp = c, len(tour)
    return bc, bp


def two_opt(D, seq, max_passes=50):
    """seq starts and ends with 0; in place; True if improved."""
    n = len(seq)
    any_imp = False
    for _ in range(max_passes):
        imp = False
        for i in range(n - 3):
            a = seq[i]
            b = seq[i + 1]
            Da = D[a]
            dab = Da[b]
            for j in range(i + 2, n - 1):
                c = seq[j]
                d = seq[j + 1]
                if Da[c] + D[b][d] - dab - D[c][d] < -EPS:
                    seq[i + 1:j + 1] = seq[i + 1:j + 1][::-1]
                    imp = True
                    b = seq[i + 1]
                    dab = Da[b]
        if not imp:
            break
        any_imp = True
    return any_imp


def or_opt(D, seq, max_passes=50):
    """Move a segment of 1-3 retailers elsewhere (either direction); in place; True if improved."""
    any_imp = False
    for _ in range(max_passes):
        imp = False
        n = len(seq)
        for L in (1, 2, 3):
            if imp:
                break
            for i in range(1, n - L):
                seg = seq[i:i + L]
                f, l = seg[0], seg[-1]
                p = seq[i - 1]
                q = seq[i + L]
                gain_rm = D[p][f] + D[l][q] - D[p][q]
                if gain_rm <= EPS:
                    continue
                rest = seq[:i] + seq[i + L:]
                best, bk, brev = EPS, -1, False
                for k in range(len(rest) - 1):
                    u = rest[k]
                    w = rest[k + 1]
                    duw = D[u][w]
                    g = gain_rm - (D[u][f] + D[l][w] - duw)
                    if g > best:
                        best, bk, brev = g, k, False
                    if L > 1:
                        g = gain_rm - (D[u][l] + D[f][w] - duw)
                        if g > best:
                            best, bk, brev = g, k, True
                if bk >= 0:
                    ins = seg[::-1] if brev else seg
                    seq[:] = rest[:bk + 1] + ins + rest[bk + 1:]
                    imp = True
                    break
        if not imp:
            break
        any_imp = True
    return any_imp


def improve_tour(pb, tour):
    m = len(tour)
    if m <= 1:
        return list(tour)
    if m <= EXACT_MAX + 1:
        return exact_tour(pb, tour)[1]
    D = pb.D
    seq = [0] + list(tour) + [0]
    for _ in range(6):
        a = two_opt(D, seq)
        b = or_opt(D, seq)
        if not (a or b):
            break
    new = seq[1:-1]
    if tour_cost(D, new) <= tour_cost(D, tour):
        return new
    return list(tour)


def viol_of(pb, q):
    v = 0
    cum = 0
    C, SC = pb.C, pb.SC
    for t in range(pb.H):
        qt = q[t]
        if qt > C:
            v += qt - C
        cum += qt
        if cum > SC[t]:
            v += cum - SC[t]
    return v


# ---------------------------------------------------------------------------------------------------------------
# search

class Search(object):
    def __init__(self, pb, seed, deadline):
        self.pb = pb
        self.rng = random.Random(seed)
        self.deadline = deadline
        self.t0 = time.time()
        self.stats = {"seed": seed, "iterations": 0, "accepted": 0, "improvements": 0, "first_feasible_s": None,
                      "initial_viol": None, "repair_viol": None, "cycles": 0, "polish_moves": 0, "events": []}
        self.best = None
        self.best_cost = math.inf

    # state ---------------------------------------------------------------------------------------------------
    def set_state(self, pat, tours):
        pb = self.pb
        self.pat = list(pat)
        self.tours = [list(t) for t in tours]
        self.tcost = [tour_cost(pb.D, t) for t in self.tours]
        q = [0] * pb.H
        hold = 0.0
        for s in range(1, pb.n + 1):
            p = pb.pats[s][self.pat[s]]
            hold += p.hc
            for t in range(pb.H):
                q[t] += p.x[t]
        self.q = q
        self.hold = hold
        self.viol = viol_of(pb, q)

    def cost(self):
        return self.pb.const + self.hold + sum(self.tcost)

    def tours_for(self, pat):
        pb = self.pb
        tours = []
        for t in range(pb.H):
            members = [s for s in range(1, pb.n + 1) if pb.pats[s][pat[s]].mask >> t & 1]
            members.sort(key=lambda s: -pb.D[0][s])
            tour = []
            for s in members:
                tour.insert(best_insert(pb.D, tour, s)[1], s)
            tours.append(improve_tour(pb, tour))
        return tours

    def initial(self):
        pb = self.pb
        pat = [0] * (pb.n + 1)
        for s in range(1, pb.n + 1):
            best, bi = None, 0
            for k, p in enumerate(pb.pats[s]):
                est = p.hc + bin(p.mask).count("1") * pb.D[0][s]
                if best is None or est < best:
                    best, bi = est, k
            pat[s] = bi
        return pat, self.tours_for(pat)

    def full_improve(self):
        for t in range(self.pb.H):
            self.tours[t] = improve_tour(self.pb, self.tours[t])
            self.tcost[t] = tour_cost(self.pb.D, self.tours[t])

    def record(self, on_improve=None):
        if self.viol > VTOL:
            return
        c = self.cost()
        if c < self.best_cost - 1e-7:
            self.best_cost = c
            self.best = (list(self.pat), [list(t) for t in self.tours])
            self.stats["improvements"] += 1
            if self.stats["first_feasible_s"] is None:
                self.stats["first_feasible_s"] = round(time.time() - self.t0, 3)
            if on_improve is not None:
                on_improve(self.best)

    # moves ---------------------------------------------------------------------------------------------------
    def cands(self, s):
        P = self.pb.pats[s]
        if len(P) <= MAX_ALL_CANDS:
            return range(len(P))
        cm = P[self.pat[s]].mask
        bm = self.pb.by_mask[s]
        out = []
        for a in range(self.pb.H):
            m1 = cm ^ (1 << a)
            k = bm.get(m1)
            if k is not None:
                out.append(k)
            for b in range(a + 1, self.pb.H):
                k = bm.get(m1 ^ (1 << b))
                if k is not None:
                    out.append(k)
        return out

    def price(self, s):
        """Route change in each period if s's visit there flipped, and how to carry it out."""
        pb = self.pb
        D = pb.D
        cm = pb.pats[s][self.pat[s]].mask
        add = [0.0] * pb.H
        how = [None] * pb.H
        for t in range(pb.H):
            tour = self.tours[t]
            if cm >> t & 1:
                if len(tour) - 1 <= EXACT_MAX:
                    c, order = exact_tour(pb, [v for v in tour if v != s])
                    add[t] = c - self.tcost[t]
                    how[t] = order
                else:
                    k = tour.index(s)
                    a = tour[k - 1] if k > 0 else 0
                    b = tour[k + 1] if k + 1 < len(tour) else 0
                    add[t] = D[a][b] - D[a][s] - D[s][b]
            else:
                if len(tour) + 1 <= EXACT_MAX:
                    c, order = exact_tour(pb, tour + [s])
                    add[t] = c - self.tcost[t]
                    how[t] = order
                else:
                    c, k = best_insert(D, tour, s)
                    add[t] = c
                    how[t] = k
        return cm, add, how

    def deltas(self, s, cm, add, lam, cands):
        pb = self.pb
        P = pb.pats[s]
        cur = P[self.pat[s]]
        xc = cur.x
        hc0 = cur.hc
        H, C, SC = pb.H, pb.C, pb.SC
        qm = [self.q[t] - xc[t] for t in range(H)]
        viol = self.viol
        out = []
        for k in cands:
            p = P[k]
            diff = p.mask ^ cm
            if not diff:
                continue
            rd = 0.0
            t = 0
            while diff:
                if diff & 1:
                    rd += add[t]
                diff >>= 1
                t += 1
            px = p.x
            v = 0
            cum = 0
            for t in range(H):
                qt = qm[t] + px[t]
                if qt > C:
                    v += qt - C
                cum += qt
                if cum > SC[t]:
                    v += cum - SC[t]
            out.append((p.hc - hc0 + rd + lam * (v - viol), k, v))
        return out

    def touch(self, t):
        pb = self.pb
        tour = self.tours[t]
        if len(tour) <= EXACT_MAX + 1:
            if len(tour) >= 3:
                tour = exact_tour(pb, tour)[1]
        else:
            seq = [0] + tour + [0]
            if two_opt(pb.D, seq):
                cand = seq[1:-1]
                if tour_cost(pb.D, cand) <= tour_cost(pb.D, tour):
                    tour = cand
        self.tours[t] = tour
        self.tcost[t] = tour_cost(pb.D, tour)

    def apply(self, s, newk, cm, how):
        pb = self.pb
        P = pb.pats[s]
        old = P[self.pat[s]]
        new = P[newk]
        diff = old.mask ^ new.mask
        for t in range(pb.H):
            if not (diff >> t & 1):
                continue
            h = how[t]
            if isinstance(h, list):
                self.tours[t] = list(h)
            elif cm >> t & 1:
                self.tours[t].remove(s)
            else:
                self.tours[t].insert(h, s)
            self.touch(t)
        for t in range(pb.H):
            self.q[t] += new.x[t] - old.x[t]
        self.hold += new.hc - old.hc
        self.pat[s] = newk
        self.viol = viol_of(pb, self.q)

    def repair(self, until):
        """Greedy: lower capacity + supplier excess, cheapest first."""
        pb = self.pb
        order = list(range(1, pb.n + 1))
        for _ in range(100):
            if self.viol <= VTOL or time.time() > until:
                break
            moved = False
            self.rng.shuffle(order)
            for s in order:
                if self.viol <= VTOL:
                    break
                if len(pb.pats[s]) < 2:
                    continue
                cm, add, how = self.price(s)
                best = None
                for d, k, v in self.deltas(s, cm, add, 0.0, self.cands(s)):
                    if v < self.viol - VTOL and (best is None or (v, d) < best[0]):
                        best = ((v, d), k)
                if best is not None:
                    self.apply(s, best[1], cm, how)
                    moved = True
            if not moved:
                break

    def polish(self, on_improve=None):
        """Strict descent from the best plan: feasible improving pattern changes only."""
        pb = self.pb
        order = list(range(1, pb.n + 1))
        self.full_improve()
        self.record(on_improve)
        for _ in range(50):
            if time.time() > self.deadline:
                break
            moved = False
            self.rng.shuffle(order)
            for s in order:
                if time.time() > self.deadline:
                    break
                if len(pb.pats[s]) < 2:
                    continue
                cm, add, how = self.price(s)
                best = None
                for d, k, v in self.deltas(s, cm, add, 0.0, self.cands(s)):
                    if v <= VTOL and d < -1e-7 and (best is None or d < best[0]):
                        best = (d, k)
                if best is not None:
                    self.apply(s, best[1], cm, how)
                    self.stats["polish_moves"] += 1
                    moved = True
            self.full_improve()
            self.record(on_improve)
            if not moved:
                break

    def run(self, on_improve=None):
        pb = self.pb
        rng = self.rng
        st = self.stats
        n = pb.n
        if not pb.feasible_patterns:
            st["events"].append("a retailer has no stockout-free pattern")
            return None
        self.set_state(*self.initial())
        st["initial_viol"] = self.viol
        start = time.time()
        total = max(0.05, self.deadline - start)
        polish_at = self.deadline - max(0.15, 0.08 * total)
        self.repair(polish_at)
        st["repair_viol"] = self.viol
        self.record(on_improve)
        samples = []
        for _ in range(min(300, 20 * n)):
            s = rng.randint(1, n)
            if len(pb.pats[s]) < 2:
                continue
            cm, add, how = self.price(s)
            cs = self.cands(s)
            if not len(cs):
                continue
            for d, k, v in self.deltas(s, cm, add, 0.0, [cs[rng.randrange(len(cs))]]):
                if d > EPS:
                    samples.append(d)
        if samples:
            T0 = 0.5 * sum(samples) / len(samples)
        else:
            T0 = 0.08 * pb.dbar if pb.dbar > 0 else 1.0
        st["T0"] = T0
        mean_u = sum(pb.U[1:]) / float(max(1, n))
        lam0 = max(1.0, 5.0 * pb.dbar / max(1.0, mean_u))
        lam = lam0
        ncyc = 3
        start = time.time()
        cyc_len = max(1e-3, (polish_at - start) / ncyc)
        cyc = 0
        Tc0 = T0
        T = T0
        it = 0
        while True:
            it += 1
            if (it & 31) == 0:
                now = time.time()
                if now >= polish_at:
                    break
                c = min(ncyc - 1, int((now - start) / cyc_len))
                if c != cyc:
                    cyc = c
                    st["cycles"] = cyc
                    Tc0 = T0 * (0.5 ** cyc)
                    if self.best is not None:
                        self.set_state(*self.best)
                    self.full_improve()
                frac = min(1.0, max(0.0, (now - start - cyc * cyc_len) / cyc_len))
                T = Tc0 * (0.005 ** frac)
            if it % 100 == 0:
                if self.viol > VTOL:
                    lam = min(lam * 1.25, lam0 * 1e4)
                else:
                    lam = max(lam / 1.05, lam0 * 0.05)
            if it % 4000 == 0:
                self.full_improve()
                self.record(on_improve)
            s = rng.randint(1, n)
            if len(pb.pats[s]) < 2:
                continue
            cm, add, how = self.price(s)
            cs = self.cands(s)
            if not len(cs):
                continue
            if rng.random() < 0.3:
                ds = self.deltas(s, cm, add, lam, [cs[rng.randrange(len(cs))]])
            else:
                ds = self.deltas(s, cm, add, lam, cs)
            if not ds:
                continue
            d, k, v = min(ds)
            if d > EPS:
                if d / T > 50.0 or rng.random() >= math.exp(-d / T):
                    continue
            self.apply(s, k, cm, how)
            st["accepted"] += 1
            self.record(on_improve)
        st["iterations"] = it
        if self.best is None:
            return None
        self.set_state(*self.best)
        self.polish(on_improve)
        st["best_cost"] = self.best_cost
        return self.best


# ---------------------------------------------------------------------------------------------------------------
# output and checking

def build_solution(pb, pat, tours):
    n, H = pb.n, pb.H
    deliveries = dict((str(t + 1), {}) for t in range(H))
    q = [0] * H
    inv = {}
    hold_r = 0.0
    for s in range(1, n + 1):
        p = pb.pats[s][pat[s]]
        for t in range(H):
            if p.mask >> t & 1:
                deliveries[str(t + 1)][str(s)] = p.x[t]
                q[t] += p.x[t]
        inv[str(s)] = dict((str(t + 1), p.inv[t]) for t in range(H + 1))
        hold_r += pb.h[s] * sum(p.inv)
    routes = {}
    tc = 0
    for t in range(H):
        tour = tours[t]
        if not tour:
            continue
        if len(tour) == 1:
            edges = [[0, tour[0], 2]]
        else:
            seq = [0] + list(tour) + [0]
            edges = [[min(a, b), max(a, b), 1] for a, b in zip(seq, seq[1:])]
        routes[str(t + 1)] = edges
        tc += sum(pb.dist[e[1]][e[0]] * e[2] for e in edges)
    B = [pb.B0]
    for t in range(H):
        B.append(B[-1] + pb.r0 - q[t])
    obj = pb.h0 * sum(B) + hold_r + tc
    return {"objective_value": float(obj), "deliveries": deliveries, "routes": routes,
            "supplier_inventory": dict((str(t + 1), B[t]) for t in range(H + 1)),
            "retailer_inventory": inv}


def _finite(v):
    return (not isinstance(v, bool)) and isinstance(v, (int, float)) and v == v and v not in (math.inf, -math.inf)


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def verify(pb, sol):
    """The official checker's rules (constraints 1-16), independently written; stricter only on types
    (edge endpoints must be JSON integers). Returns (ok, reason, recomputed objective)."""
    try:
        if not isinstance(sol, dict):
            return False, "solution is not an object", None
        for k in ("deliveries", "objective_value", "retailer_inventory", "routes", "supplier_inventory"):
            if sol.get(k) is None:
                return False, "missing " + k, None
        ov = sol["objective_value"]
        if not _finite(ov):
            return False, "objective_value must be a finite number", None
        n, H = pb.n, pb.H
        dl, rt = sol["deliveries"], sol["routes"]
        si, ri = sol["supplier_inventory"], sol["retailer_inventory"]
        T = range(1, H + 1)
        TP = range(1, H + 2)
        x, z, y = {}, {}, {}
        for t in T:
            for i in range(n + 1):
                for j in range(i):
                    y[i, j, t] = 0
        for t in T:
            pd = dl.get(str(t), {})
            for s in range(1, n + 1):
                x[s, t] = float(pd.get(str(s), 0.0))
            for i in range(n + 1):
                z[i, t] = 0
            for sk, qty in pd.items():
                if float(qty) > TOL:
                    s = int(sk)
                    if 0 <= s <= n:
                        z[s, t] = 1
            for e in rt.get(str(t), []):
                if not isinstance(e, (list, tuple)) or len(e) < 2:
                    return False, "period %d: malformed route segment %r" % (t, e), None
                for node in e[:2]:
                    if not _int(node):
                        return False, "period %d: segment endpoint %r is not an integer" % (t, node), None
                    if 0 <= node <= n:
                        z[node, t] = 1
            if any(z[s, t] == 1 for s in range(1, n + 1)):
                z[0, t] = 1
            for e in rt.get(str(t), []):
                val = int(round(e[2])) if len(e) > 2 else 1
                i, j = max(e[0], e[1]), min(e[0], e[1])
                if (i, j, t) in y:
                    y[i, j, t] += val
        B = dict((t, float(si.get(str(t), 0.0))) for t in TP)
        I = {}
        for s in range(1, n + 1):
            rs = ri.get(str(s), {})
            for t in TP:
                I[s, t] = float(rs.get(str(t), 0.0))
        M = range(1, n + 1)
        for t in TP:
            rhs = pb.B0 if t == 1 else B[t - 1] + pb.r0 - sum(x[s, t - 1] for s in M)
            if abs(B[t] - rhs) > TOL:
                return False, "supplier inventory definition broken at period %d" % t, None
        for t in T:
            if sum(x[s, t] for s in M) - B[t] > TOL:
                return False, "supplier stockout at period %d" % t, None
        for s in M:
            for t in TP:
                rhs = pb.I0[s] if t == 1 else I[s, t - 1] + x[s, t - 1] - pb.r[s]
                if abs(I[s, t] - rhs) > TOL:
                    return False, "retailer %d inventory definition broken at period %d" % (s, t), None
                if -I[s, t] > TOL:
                    return False, "retailer %d stockout at period %d" % (s, t), None
        for s in M:
            for t in T:
                if (pb.U[s] * z[s, t] - I[s, t]) - x[s, t] > TOL:
                    return False, "retailer %d period %d: not filled to its maximum" % (s, t), None
                if x[s, t] - (pb.U[s] - I[s, t]) > TOL:
                    return False, "retailer %d period %d: shipped above its maximum" % (s, t), None
                if x[s, t] - pb.U[s] * z[s, t] > TOL:
                    return False, "retailer %d period %d: shipped without a visit" % (s, t), None
                if -x[s, t] > TOL:
                    return False, "retailer %d period %d: negative shipment" % (s, t), None
        for t in T:
            tot = sum(x[s, t] for s in M)
            if tot - pb.C > TOL:
                return False, "vehicle capacity exceeded at period %d" % t, None
            if tot - pb.C * z[0, t] > TOL:
                return False, "shipment without the supplier on the route at period %d" % t, None
        for t in T:
            for i in range(n + 1):
                deg = 0
                for j in range(n + 1):
                    if j < i:
                        deg += y[i, j, t]
                    elif j > i:
                        deg += y[j, i, t]
                if abs(deg - 2 * z[i, t]) > TOL:
                    return False, "period %d: location %d has degree %s, needs %d" % (t, i, deg, 2 * z[i, t]), None
            for i in M:
                if y[i, 0, t] not in (0, 1, 2):
                    return False, "period %d: segment (0,%d) used %s times" % (t, i, y[i, 0, t]), None
                for j in range(1, i):
                    if y[i, j, t] not in (0, 1):
                        return False, "period %d: segment (%d,%d) used %s times" % (t, j, i, y[i, j, t]), None
            visited = [s for s in M if z[s, t] == 1]
            if len(visited) > 1:
                adj = dict((s, set()) for s in visited)
                for i in visited:
                    for j in visited:
                        if j < i and y[i, j, t] >= 1:
                            adj[i].add(j)
                            adj[j].add(i)
                seen = set()
                stack = [s for s in visited if y[s, 0, t] >= 1]
                while stack:
                    v = stack.pop()
                    if v in seen:
                        continue
                    seen.add(v)
                    stack.extend(adj[v] - seen)
                left = set(visited) - seen
                while left:
                    comp = set()
                    stack = [next(iter(left))]
                    while stack:
                        v = stack.pop()
                        if v in comp:
                            continue
                        comp.add(v)
                        stack.extend(adj[v] - comp)
                    left -= comp
                    inside = sum(y[i, j, t] for i in comp for j in comp if j < i)
                    if inside - (len(comp) - 1) > TOL:
                        return False, "period %d: subtour among %s" % (t, sorted(comp)), None
        true = pb.h0 * sum(B[t] for t in TP) + sum(pb.h[s] * I[s, t] for s in M for t in TP)
        true += sum(pb.dist[i][j] * y[i, j, t] for (i, j, t) in y)
        if abs(float(ov) - true) > max(1e-3, 1e-3 * abs(true)):
            return False, "objective_value %r differs from the recomputed %r" % (ov, true), None
        return True, "", true
    except (TypeError, ValueError, KeyError, IndexError, AttributeError) as e:
        return False, "malformed solution: %r" % (e,), None


def plan_cost(pb, plan):
    pat, tours = plan
    return pb.const + sum(pb.pats[s][pat[s]].hc for s in range(1, pb.n + 1)) + sum(tour_cost(pb.D, t)
                                                                                   for t in tours)


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="archetti2007")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    a = ap.parse_args(argv)
    T = float(a.time_limit)
    deadline = T_START + min(0.9 * T, T - 3.0)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    pb = Problem(inst)
    seed = int(os.environ.get("MV2_IRP_SEED", "1"))
    workers = int(os.environ.get("MV2_IRP_WORKERS", "2"))
    want_log = bool(os.environ.get("MV2_IRP_LOG"))
    counts = [len(P) for P in pb.pats[1:]]
    log = {"version": VERSION, "n": pb.n, "H": pb.H, "T": T, "workers": workers,
           "patterns_total": sum(counts), "patterns_max": max(counts) if counts else 0,
           "load_s": round(time.time() - T_START, 3)}
    if not pb.feasible_patterns:
        log["infeasible"] = "a retailer has no stockout-free pattern"
        if want_log:
            write_atomic(a.output + ".log.json", log)
        return 0
    child_pid, child_path = None, None
    if workers >= 2 and hasattr(os, "fork") and pb.n > 1:
        child_path = os.path.join(tempfile.gettempdir(), "mv2_irp_child_%d.json" % os.getpid())
        try:
            pid = os.fork()
        except OSError:
            pid = None
        if pid == 0:
            code = 0
            try:
                s = Search(pb, seed + 1000, deadline - 0.25)
                b = s.run()
                write_atomic(child_path, {"plan": b, "stats": s.stats})
            except BaseException:  # noqa: BLE001 - the child must never outlive its parent's budget
                code = 1
            os._exit(code)
        child_pid = pid
    state = {"last_write": 0.0, "written": None}

    def on_improve(plan, force=False):
        now = time.time()
        if not force and now - state["last_write"] < 0.5 and state["written"] is not None:
            return
        out = build_solution(pb, plan[0], plan[1])
        ok, why, real = verify(pb, out)
        if ok:
            if state["written"] is None or real < state["written"] - 1e-7:
                write_atomic(a.output, out)
                state["last_write"] = now
                state["written"] = real
        else:
            log.setdefault("verify_failures", []).append(why[:200])

    s = Search(pb, seed, deadline)
    best = s.run(on_improve)
    log["parent"] = s.stats
    log["best_source"] = "parent" if best is not None else None
    if best is not None:
        on_improve(best, True)  # the parent's best is on disk before the child's plan is considered
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
            cp = ch.get("plan")
            if cp is not None:
                cand = (list(cp[0]), [list(t) for t in cp[1]])
                if len(cand[0]) == pb.n + 1 and len(cand[1]) == pb.H and \
                        all(0 <= cand[0][k] < len(pb.pats[k]) for k in range(1, pb.n + 1)):
                    if best is None or plan_cost(pb, cand) < plan_cost(pb, best) - 1e-7:
                        before = state["written"]
                        on_improve(cand, True)  # written only if verify() accepts it and it is better
                        if state["written"] is not None and state["written"] != before:
                            log["best_source"] = "child"
        except Exception as e:  # noqa: BLE001
            log["child_error"] = repr(e)[:200]
    log["best"] = state["written"]
    log["wall_s"] = round(time.time() - T_START, 3)
    if want_log:
        try:
            write_atomic(a.output + ".log.json", log)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

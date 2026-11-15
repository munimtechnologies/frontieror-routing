"""MV2 delivery-site routing engine v0.1.0 for FrontierOR task reihaneh2019 (standard library only).

The vehicle routing with demand allocation problem (VRDAP; Reihaneh and Ghoniem, 2019): a fleet of identical vehicles
leaves one depot and visits a chosen subset of candidate delivery sites; every customer travels to exactly one opened
site to collect its order. Each opened site is on exactly one tour, and the demand of all customers collected on a tour
must fit in the vehicle. Minimise routing cost (depot and sites) plus customer-to-site assignment cost.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python solve.py --problem reihaneh2019 --instance in.json --output out.json --time-limit 60 [--seed 1]

Rules, read on 2026-11-15 in the public FrontierOR reihaneh2019 files (Hugging Face frontieror/FrontierOR, CC BY 4.0:
problem_description.txt, instance_schema.json, solution_schema.json, gurobi_code.py, feasibility_check.py):
- nodes: depot 0 and sites 1..num_delivery_sites; routing_cost_matrix[i][j] over those nodes; customers 1..num_customers
  with assignment_cost_matrix[k-1][i-1]; at most num_vehicles tours (route keys "1".."V");
- the answer carries routes (arcs and sequence, from and back to the depot), assignments (customer -> site) and
  customer_tours (customer -> {vehicle, site}); the checker rebuilds the model's variables from them and tests
  constraints (4b)-(4l): a site on at most one tour, one depot exit per tour, flow balance, the cumulative-load
  constraint (4e) with the load of every site taken from the assignments, linking of customer, site and tour, and
  every customer served once; then it recomputes routing + assignment cost and allows a 0.1% difference.
verify() mirrors those checks, and every written answer passes it.

Method: a state is a set of tours over opened sites plus each customer's site. Ruin and recreate with simulated
annealing: customers are removed (related by location, random, all customers of one or two sites, or of a whole tour);
a site whose last customer leaves is closed and cut out of its tour. Each removed customer is then re-inserted at its
cheapest option: an opened site whose tour still has room (cost = assignment cost), or a closed site opened at its
cheapest position in a tour with room or on a new tour (assignment cost + exact insertion cost). Further moves: move one
site with all its customers to another tour, and replace an opened site by a nearby closed one for all its customers.
Changed tours are re-sequenced by 2-opt and site relocation (exact costs, any matrix), and near-best states get a
customer relocation pass. A first-fit-decreasing packing gives a fallback start when greedy insertion cannot fit all
customers into num_vehicles tours.
"""
import argparse
import json
import math
import os
import random
import sys
import time

VERSION = "0.1.0"
INF = float("inf")
EPS = 1e-9
SLUG = "reihaneh2019"


class Problem:
    def __init__(self, inst):
        self.m = int(inst["num_delivery_sites"])
        self.n = int(inst["num_customers"])
        self.Q = float(inst["vehicle_capacity"])
        self.V = int(inst["num_vehicles"])
        self.c = [[float(x) for x in row] for row in inst["routing_cost_matrix"]]
        fm = inst["assignment_cost_matrix"]
        m, n = self.m, self.n
        self.d = [0.0] * (n + 1)
        self.xy = [(0.0, 0.0)] * (n + 1)
        for cu in inst["customers"]:
            k = int(cu["id"])
            if 1 <= k <= n:
                self.d[k] = float(cu["demand"])
                self.xy[k] = (float(cu.get("x", 0.0)), float(cu.get("y", 0.0)))
        self.f = [None] + [[0.0] + [float(fm[k - 1][i - 1]) for i in range(1, m + 1)] for k in range(1, n + 1)]
        self.sites_by_f = [None] + [sorted(range(1, m + 1), key=lambda i, k=k: self.f[k][i]) for k in range(1, n + 1)]
        self.site_near = [None] + [sorted((j for j in range(1, m + 1) if j != i),
                                          key=lambda j, i=i: self.c[i][j] + self.c[j][i]) for i in range(1, m + 1)]
        self.cnear = [None]
        for k in range(1, n + 1):
            xk, yk = self.xy[k]
            self.cnear.append(sorted(range(1, n + 1),
                                     key=lambda h: (h != k, (self.xy[h][0] - xk) ** 2 + (self.xy[h][1] - yk) ** 2)))
        self.reg = [0.0] * (n + 1)
        for k in range(1, n + 1):
            s = self.sites_by_f[k]
            self.reg[k] = (self.f[k][s[1]] - self.f[k][s[0]]) if len(s) > 1 else 0.0


def tour_cost(c, seq):
    if not seq:
        return 0.0
    tot = c[0][seq[0]] + c[seq[-1]][0]
    for x in range(len(seq) - 1):
        tot += c[seq[x]][seq[x + 1]]
    return tot


def best_pos(c, seq, j):
    """Cheapest position to insert site j into tour seq (between depot legs); returns (delta, position)."""
    if not seq:
        return c[0][j] + c[j][0], 0
    best, bp = INF, 0
    prev = 0
    for p in range(len(seq) + 1):
        nxt = seq[p] if p < len(seq) else 0
        delta = c[prev][j] + c[j][nxt] - c[prev][nxt]
        if delta < best:
            best, bp = delta, p
        prev = nxt
    return best, bp


def opt_tour(c, seq):
    """2-opt (segment reversal) and single-site relocation until no improvement; exact costs, any matrix."""
    best = list(seq)
    bc = tour_cost(c, best)
    L = len(best)
    if L < 2:
        return best, bc
    improved = True
    rounds = 0
    while improved and rounds < 50:
        improved = False
        rounds += 1
        for i in range(L - 1):
            for j in range(i + 1, L):
                cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                cc = tour_cost(c, cand)
                if cc < bc - EPS:
                    best, bc, improved = cand, cc, True
        for i in range(L):
            x = best[i]
            rest = best[:i] + best[i + 1:]
            for p in range(L):
                if p == i:
                    continue
                cand = rest[:p] + [x] + rest[p:]
                cc = tour_cost(c, cand)
                if cc < bc - EPS:
                    best, bc, improved = cand, cc, True
                    break
    return best, bc


class State:
    __slots__ = ("asg", "sload", "tour_of", "tours", "tload", "tcost", "fcost")

    def copy(self):
        s = State.__new__(State)
        s.asg = self.asg[:]
        s.sload = self.sload[:]
        s.tour_of = self.tour_of[:]
        s.tours = [t[:] for t in self.tours]
        s.tload = self.tload[:]
        s.tcost = self.tcost[:]
        s.fcost = self.fcost
        return s

    def cost(self):
        return self.fcost + sum(self.tcost)


def empty_state(P):
    s = State.__new__(State)
    s.asg = [0] * (P.n + 1)
    s.sload = [0.0] * (P.m + 1)
    s.tour_of = [-1] * (P.m + 1)
    s.tours, s.tload, s.tcost = [], [], []
    s.fcost = 0.0
    return s


def members(P, S, sites):
    ss = set(sites)
    return [k for k in range(1, P.n + 1) if S.asg[k] in ss]


def remove_customer(P, S, k, changed):
    i = S.asg[k]
    if i == 0:
        return
    S.asg[k] = 0
    S.fcost -= P.f[k][i]
    dk = P.d[k]
    S.sload[i] -= dk
    t = S.tour_of[i]
    S.tload[t] -= dk
    if S.sload[i] <= EPS:
        S.sload[i] = 0.0
        S.tours[t].remove(i)
        S.tour_of[i] = -1
        S.tcost[t] = tour_cost(P.c, S.tours[t])
        changed.add(t)


def best_option(P, S, k, noise, rng, forbid=()):
    dk = P.d[k]
    cap = P.Q + EPS
    fk = P.f[k]
    best, opt = INF, None
    can_new = len(S.tours) < P.V
    for i in P.sites_by_f[k]:
        fi = fk[i]
        if fi >= best:
            break
        t = S.tour_of[i]
        if t >= 0:
            if S.tload[t] + dk <= cap:
                cost = fi * (1.0 + noise * rng.random()) if noise else fi
                if cost < best:
                    best, opt = cost, (i, t, -1)
            continue
        if i in forbid:
            continue
        for t2 in range(len(S.tours)):
            if S.tload[t2] + dk > cap:
                continue
            delta, pos = best_pos(P.c, S.tours[t2], i)
            cost = fi + delta
            if noise:
                cost *= 1.0 + noise * rng.random()
            if cost < best:
                best, opt = cost, (i, t2, pos)
        if can_new and dk <= cap:
            cost = fi + P.c[0][i] + P.c[i][0]
            if noise:
                cost *= 1.0 + noise * rng.random()
            if cost < best:
                best, opt = cost, (i, len(S.tours), 0)
    return best, opt


def apply_option(P, S, k, opt, changed):
    i, t, pos = opt
    if t == len(S.tours):
        S.tours.append([])
        S.tload.append(0.0)
        S.tcost.append(0.0)
    if S.tour_of[i] < 0:
        S.tours[t].insert(pos, i)
        S.tour_of[i] = t
        S.tcost[t] = tour_cost(P.c, S.tours[t])
        changed.add(t)
    S.asg[k] = i
    S.fcost += P.f[k][i]
    S.sload[i] += P.d[k]
    S.tload[t] += P.d[k]


def recreate(P, S, ks, rng, noise, changed, forbid=()):
    for k in ks:
        _, opt = best_option(P, S, k, noise, rng, forbid)
        if opt is None:
            return False
        apply_option(P, S, k, opt, changed)
    return True


def compact(S):
    if all(S.tours):
        return
    keep = [t for t in range(len(S.tours)) if S.tours[t]]
    S.tours = [S.tours[t] for t in keep]
    S.tload = [S.tload[t] for t in keep]
    S.tcost = [S.tcost[t] for t in keep]
    for idx, tour in enumerate(S.tours):
        for i in tour:
            S.tour_of[i] = idx


def finalize(P, S, changed):
    for t in changed:
        if t < len(S.tours) and S.tours[t]:
            S.tours[t], S.tcost[t] = opt_tour(P.c, S.tours[t])
    compact(S)


def polish(P, S, max_passes=3):
    """Move single customers to a cheaper opened site whose tour has room (closing a site that empties)."""
    cap = P.Q + EPS
    passes = 0
    improved = True
    while improved and passes < max_passes:
        improved = False
        passes += 1
        for k in range(1, P.n + 1):
            i = S.asg[k]
            t = S.tour_of[i]
            dk = P.d[k]
            fk = P.f[k]
            cur = fk[i]
            close_save = 0.0
            if S.sload[i] - dk <= EPS:
                seq = S.tours[t]
                idx = seq.index(i)
                a = seq[idx - 1] if idx > 0 else 0
                b = seq[idx + 1] if idx + 1 < len(seq) else 0
                close_save = P.c[a][i] + P.c[i][b] - P.c[a][b]
            for j in P.sites_by_f[k]:
                if fk[j] >= cur + close_save - EPS:
                    break
                if j == i:
                    continue
                tj = S.tour_of[j]
                if tj < 0:
                    continue
                if tj != t and S.tload[tj] + dk > cap:
                    continue
                ch = set()
                remove_customer(P, S, k, ch)
                apply_option(P, S, k, (j, tj, -1), ch)
                improved = True
                break
    compact(S)


def move_site(P, S, rng, changed):
    opened = [i for i in range(1, P.m + 1) if S.tour_of[i] >= 0]
    if not opened:
        return False
    i = rng.choice(opened)
    t = S.tour_of[i]
    L = S.sload[i]
    S.tours[t].remove(i)
    S.tcost[t] = tour_cost(P.c, S.tours[t])
    S.tload[t] -= L
    changed.add(t)
    best, opt = INF, None
    for t2 in range(len(S.tours)):
        if t2 == t and rng.random() < 0.5:
            continue
        if S.tload[t2] + L > P.Q + EPS:
            continue
        delta, pos = best_pos(P.c, S.tours[t2], i)
        if delta < best:
            best, opt = delta, (t2, pos)
    if len(S.tours) < P.V and P.c[0][i] + P.c[i][0] < best:
        opt = (len(S.tours), 0)
    if opt is None:
        delta, pos = best_pos(P.c, S.tours[t], i)
        opt = (t, pos)
    t2, pos = opt
    if t2 == len(S.tours):
        S.tours.append([])
        S.tload.append(0.0)
        S.tcost.append(0.0)
    S.tours[t2].insert(pos, i)
    S.tour_of[i] = t2
    S.tload[t2] += L
    S.tcost[t2] = tour_cost(P.c, S.tours[t2])
    changed.add(t2)
    return True


def swap_site(P, S, rng, changed):
    opened = [i for i in range(1, P.m + 1) if S.tour_of[i] >= 0]
    if not opened:
        return False
    i = rng.choice(opened)
    cands = [j for j in P.site_near[i] if S.tour_of[j] < 0][:6]
    if not cands:
        return False
    j = rng.choice(cands)
    t = S.tour_of[i]
    ks = members(P, S, [i])
    S.tours[t][S.tours[t].index(i)] = j
    S.tour_of[i] = -1
    S.tour_of[j] = t
    S.sload[j] = S.sload[i]
    S.sload[i] = 0.0
    for k in ks:
        S.asg[k] = j
        S.fcost += P.f[k][j] - P.f[k][i]
    S.tcost[t] = tour_cost(P.c, S.tours[t])
    changed.add(t)
    return True


def ruin(P, S, rng, changed):
    n = P.n
    qmax = max(1, min(n, max(3, n // 4), 30))
    r = rng.random()
    forbid = ()
    if r < 0.35:
        kind = "related"
        k0 = rng.randint(1, n)
        ks = P.cnear[k0][:rng.randint(1, qmax)]
    elif r < 0.65:
        kind = "random"
        ks = rng.sample(range(1, n + 1), rng.randint(1, qmax))
    elif r < 0.90 or len(S.tours) < 2:
        kind = "site"
        opened = [i for i in range(1, P.m + 1) if S.tour_of[i] >= 0]
        i = rng.choice(opened)
        sites = [i]
        if rng.random() < 0.5:
            near = [j for j in P.site_near[i] if S.tour_of[j] >= 0]
            if near:
                sites.append(near[0])
        ks = members(P, S, sites)
        if rng.random() < 0.5:
            forbid = set(sites)
    else:
        kind = "tour"
        t = rng.randrange(len(S.tours))
        ks = members(P, S, S.tours[t])
    for k in ks:
        remove_customer(P, S, k, changed)
    return kind, list(ks), forbid


def order(P, ks, rng):
    r = rng.random()
    ks = list(ks)
    rng.shuffle(ks)
    if r < 0.4:
        return ks
    if r < 0.7:
        return sorted(ks, key=lambda k: -P.d[k])
    return sorted(ks, key=lambda k: -P.reg[k])


def ffd_state(P):
    """First-fit-decreasing packing of customers into at most V tours, each customer at its cheapest site not used by
    another tour; a fallback start when greedy insertion fails."""
    ks = sorted(range(1, P.n + 1), key=lambda k: -P.d[k])
    bins = []
    for k in ks:
        placed = False
        for b in bins:
            if b[0] + P.d[k] <= P.Q + EPS:
                b[0] += P.d[k]
                b[1].append(k)
                placed = True
                break
        if not placed:
            if len(bins) >= P.V or P.d[k] > P.Q + EPS:
                return None
            bins.append([P.d[k], [k]])
    S = empty_state(P)
    owner = {}
    for bi, (_, kb) in enumerate(bins):
        S.tours.append([])
        S.tload.append(0.0)
        S.tcost.append(0.0)
        for k in kb:
            site = None
            for i in P.sites_by_f[k]:
                if owner.get(i, bi) == bi:
                    site = i
                    break
            if site is None:
                return None
            if site not in owner:
                owner[site] = bi
                S.tours[bi].append(site)
                S.tour_of[site] = bi
            S.asg[k] = site
            S.fcost += P.f[k][site]
            S.sload[site] += P.d[k]
            S.tload[bi] += P.d[k]
    for t in range(len(S.tours)):
        S.tours[t], S.tcost[t] = opt_tour(P.c, S.tours[t])
    compact(S)
    return S


def construct(P, rng, tries=8):
    best, best_c = None, INF
    for a in range(tries):
        S = empty_state(P)
        ks = list(range(1, P.n + 1))
        rng.shuffle(ks)
        if a == 0:
            ks.sort(key=lambda k: -P.d[k])
        ch = set()
        if not recreate(P, S, ks, rng, 0.0 if a == 0 else 0.1, ch):
            continue
        finalize(P, S, ch)
        polish(P, S)
        c = S.cost()
        if c < best_c:
            best, best_c = S, c
    if best is None:
        best = ffd_state(P)
    return best


def build_solution(P, S):
    routes, asg, ct = {}, {}, {}
    vehicle_of = {}
    rcost = 0.0
    v = 0
    for tour in S.tours:
        if not tour:
            continue
        v += 1
        seq = [0] + list(tour) + [0]
        arcs = [[seq[x], seq[x + 1]] for x in range(len(seq) - 1)]
        routes[str(v)] = {"arcs": arcs, "sequence": seq}
        for i in tour:
            vehicle_of[i] = v
        for a, b in arcs:
            rcost += P.c[a][b]
    fc = 0.0
    for k in range(1, P.n + 1):
        i = S.asg[k]
        asg[str(k)] = i
        ct[str(k)] = {"vehicle": vehicle_of.get(i, 0), "site": i}
        fc += P.f[k][i]
    return {"objective_value": rcost + fc, "routes": routes, "assignments": asg, "customer_tours": ct}


def verify(inst, sol):
    """Mirror of the official reihaneh2019 feasibility_check.py: {"feasible", "objective" (recomputed), "reason"}."""
    try:
        return _verify(inst, sol)
    except Exception as e:  # noqa: BLE001 - the official checker turns a crash into a rejection too
        return {"feasible": False, "objective": None, "reason": "malformed: %r" % (e,)}


def _verify(inst, sol):
    if not isinstance(sol, dict):
        return {"feasible": False, "objective": None, "reason": "solution must be a JSON object"}
    for key in ("assignments", "customer_tours", "objective_value", "routes"):
        if sol.get(key) is None:
            return {"feasible": False, "objective": None, "reason": "missing " + key}
    obj = sol["objective_value"]
    if isinstance(obj, bool) or not isinstance(obj, (int, float)) or obj != obj or obj in (INF, -INF):
        return {"feasible": False, "objective": None, "reason": "objective_value must be a finite number"}
    m, n = inst["num_delivery_sites"], inst["num_customers"]
    Q, nv = inst["vehicle_capacity"], inst["num_vehicles"]
    d = {cu["id"]: cu["demand"] for cu in inst["customers"]}
    Sset = set(range(1, m + 1))
    Kset = set(range(1, n + 1))
    Vset = set(range(1, nv + 1))
    N = [0] + list(range(1, m + 1))
    Nset = set(N)
    tol = 1e-5
    reasons = []
    s = set()
    for k_str, site in sol["assignments"].items():
        k = int(k_str)
        if k not in Kset:
            reasons.append("domain: customer %r" % (k_str,))
        if site not in Sset:
            reasons.append("domain: assignments[%s] = %r" % (k_str, site))
        s.add((site, k))
    e = set()
    seqs = {}
    for v_str, rd in sol["routes"].items():
        v = int(v_str)
        if v not in Vset:
            reasons.append("domain: vehicle %r" % (v_str,))
        if "arcs" in rd:
            arcs = [(a[0], a[1]) for a in rd["arcs"]]
            for a in rd["arcs"]:
                for node in a[:2]:
                    if node not in Nset:
                        reasons.append("domain: arc node %r" % (node,))
        else:
            sq = rd["sequence"]
            arcs = [(sq[x], sq[x + 1]) for x in range(len(sq) - 1)]
        for i, j in arcs:
            if i != j:
                e.add((v, i, j))
        seq = rd["sequence"]
        for node in seq:
            if node not in Nset:
                reasons.append("domain: sequence node %r" % (node,))
        seqs[v] = seq
    theta = set()
    for k_str, info in sol["customer_tours"].items():
        theta.add((info["vehicle"], info["site"], int(k_str)))
    th_vi = {}
    for (v, i, k) in theta:
        if v in Vset and i in Sset and k in Kset:
            th_vi.setdefault((v, i), []).append(k)
    q = {}
    for v, seq in seqs.items():
        cum = 0.0
        for node in seq:
            if node == 0:
                continue
            cum += sum(d[k] for k in th_vi.get((v, node), ()))
            q[(v, node)] = cum
    out_d, in_d = {}, {}
    for (v, i, j) in e:
        if v in Vset and i in Nset and j in Nset:
            out_d[(v, i)] = out_d.get((v, i), 0) + 1
            in_d[(v, j)] = in_d.get((v, j), 0) + 1
    # C1: each site entered by at most one arc over all tours
    for j in Sset:
        if sum(in_d.get((v, j), 0) for v in Vset) > 1 + tol:
            reasons.append("C1: site %d visited more than once" % j)
    for v in Vset:
        # C2: at most one arc out of the depot (to a site)
        if sum(1 for j in Sset if (v, 0, j) in e) > 1 + tol:
            reasons.append("C2: tour %d leaves the depot more than once" % v)
        # C3: flow balance
        for j in N:
            if in_d.get((v, j), 0) != out_d.get((v, j), 0):
                reasons.append("C3: flow imbalance at node %d on tour %d" % (j, v))
    D = {j: 0.0 for j in Sset}
    for (i, k) in s:
        if i in Sset and k in Kset:
            D[i] += d[k]
    # C4: cumulative-load (lifted MTZ) constraint, literally
    for v in Vset:
        for i in Sset:
            qi = q.get((v, i), 0.0)
            for j in Sset:
                if i == j:
                    continue
                eij = 1 if (v, i, j) in e else 0
                eji = 1 if (v, j, i) in e else 0
                if qi + D[j] - 2 * Q * (1 - eij) + Q * eji - q.get((v, j), 0.0) > tol:
                    reasons.append("C4: tour %d arc (%d,%d)" % (v, i, j))
    # C5: a visited site serves every customer assigned to it on that tour
    for (v, i), o in out_d.items():
        if v not in Vset or i not in Sset:
            continue
        for k in Kset:
            sv = 1 if (i, k) in s else 0
            th = 1 if (v, i, k) in theta else 0
            if sv + o - 1 - th > tol:
                reasons.append("C5: customer %d at site %d not served by tour %d" % (k, i, v))
    for (v, i, k) in theta:
        if v not in Vset or i not in Sset or k not in Kset:
            continue
        # C6 / C7
        if 1 - out_d.get((v, i), 0) > tol:
            reasons.append("C6: customer %d served at site %d not on tour %d" % (k, i, v))
        if (i, k) not in s:
            reasons.append("C7: customer %d served at site %d it is not assigned to" % (k, i))
    for v in Vset:
        for i in Sset:
            qv = q.get((v, i), 0.0)
            # C8: load bound at a visited site, zero elsewhere
            if qv - Q * out_d.get((v, i), 0) > tol:
                reasons.append("C8: tour %d load %.6g at site %d over capacity" % (v, qv, i))
            # C9
            if sum(d[k] for k in th_vi.get((v, i), ())) - qv > tol:
                reasons.append("C9: tour %d site %d" % (v, i))
    # C10: every customer served exactly once
    cnt = {}
    for (v, i, k) in theta:
        if v in Vset and i in Sset:
            cnt[k] = cnt.get(k, 0) + 1
    for k in Kset:
        if cnt.get(k, 0) != 1:
            reasons.append("C10: customer %d served %d times" % (k, cnt.get(k, 0)))
    # C12: objective consistency
    c = inst["routing_cost_matrix"]
    fm = inst["assignment_cost_matrix"]
    rc = sum(float(c[i][j]) for (v, i, j) in e if v in Vset and i in Nset and j in Nset)
    ac = sum(float(fm[k - 1][i - 1]) for (i, k) in s if i in Sset and k in Kset)
    true_obj = rc + ac
    if abs(float(obj) - true_obj) > max(1e-3, 1e-3 * abs(true_obj)):
        reasons.append("C12: objective %r vs recomputed %r" % (obj, true_obj))
    return {"feasible": not reasons, "objective": true_obj, "reason": "; ".join(reasons[:5]),
            "reasons": reasons[:200]}


def search(P, S0, deadline, rng, offer, log=None):
    cur = S0
    cur_c = cur.cost()
    best_c = cur_c
    T0 = max(1e-6, 0.01 * cur_c)
    Tf = T0 * 0.01
    t_begin = time.monotonic()
    span = max(1e-6, deadline - t_begin)
    it = acc = imp = fails = 0
    moves = {}
    while True:
        now = time.monotonic()
        if now >= deadline:
            break
        it += 1
        T = T0 * (Tf / T0) ** min(1.0, (now - t_begin) / span)
        S = cur.copy()
        changed = set()
        r = rng.random()
        if r < 0.08:
            kind = "site_move"
            ok = move_site(P, S, rng, changed)
        elif r < 0.16:
            kind = "site_swap"
            ok = swap_site(P, S, rng, changed)
        else:
            kind, ks, forbid = ruin(P, S, rng, changed)
            ok = recreate(P, S, order(P, ks, rng), rng, rng.choice((0.0, 0.0, 0.05, 0.2)), changed, forbid)
        st = moves.setdefault(kind, [0, 0, 0])
        st[0] += 1
        if not ok:
            fails += 1
            continue
        finalize(P, S, changed)
        c = S.cost()
        if c < best_c * 1.02:
            polish(P, S)
            c = S.cost()
        if c < cur_c - T * math.log(1.0 - rng.random()):
            cur, cur_c = S, c
            acc += 1
            st[1] += 1
            if c < best_c - EPS:
                best_c = c
                imp += 1
                st[2] += 1
                offer(S, kind)
    if log is not None:
        log.update({"iterations": it, "accepted": acc, "improved": imp, "recreate_failed": fails, "moves": moves})
    return cur


def solve(inst, time_limit=60.0, seed=1, t_start=None, on_write=None, log=None, budget=None):
    t_start = time.monotonic() if t_start is None else t_start
    if budget is None:
        budget = max(0.3, min(0.9 * time_limit, time_limit - 3.0) - 1.0)
    deadline = t_start + budget
    rng = random.Random(seed)
    P = Problem(inst)
    # best = newest candidate (verified at most every 0.25 s); good = last answer that passed verify().
    best = {"sol": None, "obj": INF, "src": None, "written": -INF, "verified": True}
    good = {"sol": None, "obj": INF, "src": None}

    def flush():
        if best["verified"] or best["sol"] is None:
            return
        best["verified"] = True
        best["written"] = time.monotonic()
        v = verify(inst, best["sol"])
        if not v["feasible"] or v["objective"] >= good["obj"] - EPS:
            if not v["feasible"] and log is not None:
                log["verify_rejected"] = log.get("verify_rejected", 0) + 1
                log.setdefault("verify_reasons", []).append(v["reason"][:300])
            best["obj"] = good["obj"]
            return
        good.update(sol=best["sol"], obj=v["objective"], src=best["src"])
        if on_write is not None:
            on_write(good["sol"])

    def offer(S, src):
        sol = build_solution(P, S)
        obj = sol["objective_value"]
        if obj >= best["obj"] - EPS:
            return
        best.update(sol=sol, obj=obj, src=src, verified=False)
        if time.monotonic() - best["written"] >= 0.25:
            flush()

    S0 = construct(P, rng)
    if S0 is None:
        if log is not None:
            log.update({"version": VERSION, "error": "no feasible start found"})
        return None
    offer(S0, "construct")
    flush()
    if log is not None:
        log["construct_objective"] = good["obj"]
    search(P, S0, deadline, rng, offer, log)
    flush()
    sol = good["sol"]
    best = good
    if log is not None:
        log.update({"version": VERSION, "seed": seed, "m": P.m, "n": P.n, "Q": P.Q, "V": P.V,
                    "objective": best["obj"], "best_source": best["src"],
                    "tours": len(sol["routes"]) if sol else None,
                    "sites_opened": sum(len(r["sequence"]) - 2 for r in sol["routes"].values()) if sol else None,
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
    ap.add_argument("--problem", default=SLUG)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=int(os.environ.get("MV2_VRDAP_SEED", "1")))
    a = ap.parse_args(argv)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    log = {} if os.environ.get("MV2_VRDAP_LOG") == "1" else None
    sol = solve(inst, a.time_limit, a.seed, t_start=t_start, on_write=lambda s: write_json(a.output, s), log=log)
    if sol is not None:
        write_json(a.output, sol)
    if log is not None:
        write_json(a.output + ".log.json", log)
    return 0 if sol is not None else 1


if __name__ == "__main__":
    sys.exit(main())

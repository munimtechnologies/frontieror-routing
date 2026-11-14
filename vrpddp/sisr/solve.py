"""MV2 VRPDDP SISR engine v0.1.0 for FrontierOR task nagy2015 (standard library only).

A second, dependency-free engine next to vrpddp/nagy2015/solve.py (v0.2.0, PyVRP portfolio + numpy search), with a
mirror of the official checker (including its rule that no arc may go from a customer's pickup node straight to its
own delivery node).

Vehicle routing with divisible deliveries and pickups (Nagy, Wassan, Speranza and Archetti, Transportation Science
2015): every customer has a delivery request (from the depot) and a pickup request (back to the depot). The two may be
served on separate visits by different vehicles, but each request is served whole in one visit. A vehicle leaves the
depot with all the deliveries of its route; at every moment the load on board (deliveries still to drop + pickups
already collected) must stay within the capacity. Minimise total distance.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python solve.py --problem nagy2015 --instance in.json --output out.json --time-limit 60 [--seed 1]

Model (the official checker's own): expanded nodes 0 (depot), 1..n (linehaul i = delivery of customer i),
n+1..2n (backhaul n+i = pickup of customer i, at the same place). d(a, b) = distance_matrix[orig(a)][orig(b)].
Every expanded node is visited exactly once; an arc n+i -> i is not allowed (we never need it: putting the delivery
first costs the same distance and never more load).

Load rule used for O(1) insertion checks: on a route v1..vm, load_0 = sum of its deliveries and
load_k = load_(k-1) - delivery(v_k) + pickup(v_k). Inserting u between v_k and v_(k+1) is feasible iff
max(load_0..load_k) + delivery(u) <= C and max(load_k..load_m) + pickup(u) <= C.

Search: slack induction by string removals (SISR, Christiaens and Vanden Berghe 2020): remove a few strings of
consecutive visits from routes near a random seed visit, re-insert the removed visits one by one at their cheapest
feasible position (with rare random 'blinks'), accept by simulated annealing whose temperature falls geometrically
over the time budget.
The written objective_value is recomputed exactly as the official checker's constraint 18 does; verify() mirrors
the official checks (constraints 2-15 and 18).
"""
import argparse
import json
import math
import os
import random
import sys
import time

VERSION = "0.1.0"
EPS = 1e-9
CHK_TOL = 1e-5


class Problem:
    def __init__(self, inst):
        n = int(inst["num_customers"])
        self.n = n
        self.C = inst["vehicle_capacity"]
        raw = inst["distance_matrix"]
        cust = {int(c["id"]): c for c in inst["customers"]}
        N = 2 * n + 1
        self.N = N
        dd = [0] * N
        pp = [0] * N
        for i in range(1, n + 1):
            c = cust[i]
            dd[i] = c.get("delivery_demand", 0) or 0
            pp[n + i] = c.get("pickup_demand", 0) or 0
        self.dd = dd
        self.pp = pp
        orig = [0] + list(range(1, n + 1)) + list(range(1, n + 1))
        self.orig = orig
        self.D = [[raw[orig[a]][orig[b]] for b in range(N)] for a in range(N)]
        self.nodes = list(range(1, N))
        self.depot_xy = (inst.get("depot") or {}).get("x", 0), (inst.get("depot") or {}).get("y", 0)
        self.xy = [self.depot_xy] + [(cust[i].get("x", 0), cust[i].get("y", 0)) for i in range(1, n + 1)] * 2
        # neighbour lists (nearest first, the node itself first)
        K = min(N - 1, 120)
        self.nbr = [None] * N
        for a in range(1, N):
            row = self.D[a]
            self.nbr[a] = sorted(range(1, N), key=lambda b: (b != a, row[b], b))[:K]
        dep = self.D[0]
        self.avg_dep = sum(dep[v] for v in self.nodes) / max(1, len(self.nodes))

    # ---- routes -------------------------------------------------------------------------------------------------
    def profile(self, r):
        """(PM, SM): prefix and suffix maxima of the loads load_0..load_m of route r (customers only)."""
        dd, pp = self.dd, self.pp
        load = 0
        for v in r:
            load += dd[v]
        loads = [load]
        for v in r:
            load += pp[v] - dd[v]
            loads.append(load)
        m = len(loads)
        PM = loads[:]
        for k in range(1, m):
            if PM[k - 1] > PM[k]:
                PM[k] = PM[k - 1]
        SM = loads[:]
        for k in range(m - 2, -1, -1):
            if SM[k + 1] > SM[k]:
                SM[k] = SM[k + 1]
        return PM, SM

    def route_ok(self, r):
        return self.profile(r)[0][-1] <= self.C + EPS

    def route_len(self, r):
        D = self.D
        prev = 0
        s = 0
        for v in r:
            s += D[prev][v]
            prev = v
        return s + D[prev][0]

    def valid(self, routes):
        seen = []
        for r in routes:
            if not r or not self.route_ok(r):
                return False
            seen.extend(r)
        return len(seen) == len(self.nodes) and sorted(seen) == self.nodes

    def fix_order(self, routes):
        """Swap every backhaul n+i that is directly followed by its own linehaul i (arc n+i -> i is forbidden by the
        checker). Same distance (the two are at one place), and the load in between only goes down."""
        n = self.n
        out = []
        for r in routes:
            r = list(r)
            for k in range(len(r) - 1):
                if r[k] > n and r[k + 1] == r[k] - n:
                    r[k], r[k + 1] = r[k + 1], r[k]
            out.append(r)
        return out

    def total(self, routes):
        return sum(self.route_len(r) for r in routes if r)


def build_solution(P, routes):
    routes = P.fix_order([r for r in routes if r])
    n = P.n
    full = [[0] + list(r) + [0] for r in routes]
    detailed = []
    for r in full:
        rd = []
        for v in r:
            if v == 0:
                rd.append({"node": 0, "type": "depot"})
            elif v <= n:
                rd.append({"node": v, "type": "linehaul", "original_customer": v, "delivery_demand": P.dd[v]})
            else:
                rd.append({"node": v, "type": "backhaul", "original_customer": v - n, "pickup_demand": P.pp[v]})
        detailed.append(rd)
    obj = 0
    D = P.D
    for r in full:
        for a, b in zip(r, r[1:]):
            obj += D[a][b]
    return {"objective_value": float(obj), "routes": full, "routes_detailed": detailed, "num_routes": len(full),
            "solver": "MV2 nagy2015 v" + VERSION}


def verify(inst, sol):
    """Mirror of the official feasibility_check.py for solutions in its 'Gurobi format' (routes = lists of expanded
    node ids). Returns {"feasible", "objective", "reason"}."""
    try:
        P = Problem(inst)
    except Exception as e:  # noqa: BLE001
        return {"feasible": False, "objective": None, "reason": "bad instance: %r" % (e,)}
    if not isinstance(sol, dict):
        return {"feasible": False, "objective": None, "reason": "not an object"}
    for f in ("objective_value", "routes", "routes_detailed"):
        if f not in sol or sol[f] is None:
            return {"feasible": False, "objective": None, "reason": "missing " + f}
    if sol["routes_detailed"] in ([], {}):
        return {"feasible": False, "objective": None, "reason": "empty routes_detailed"}
    ov = sol["objective_value"]
    if isinstance(ov, bool) or not isinstance(ov, (int, float)) or ov != ov or ov in (float("inf"), float("-inf")):
        return {"feasible": False, "objective": None, "reason": "objective_value not finite"}
    routes = sol["routes"]
    if not routes or not isinstance(routes[0], list):
        return {"feasible": False, "objective": None, "reason": "unrecognised routes format"}
    n, C, N, D = P.n, P.C, P.N, P.D
    x, R, Pf = {}, {}, {}
    q = [P.dd[v] + P.pp[v] for v in range(N)]
    try:
        for rt in routes:
            inner = rt[1:-1]
            dl = sum(q[v] for v in inner if 1 <= v <= n)
            pl = 0.0
            for k in range(len(rt) - 1):
                v = rt[k]
                if 1 <= v <= n:
                    dl -= q[v]
                elif n + 1 <= v <= 2 * n:
                    pl += q[v]
                arc = (rt[k], rt[k + 1])
                x[arc] = x.get(arc, 0) + 1
                R[arc] = R.get(arc, 0) + dl
                Pf[arc] = Pf.get(arc, 0) + pl
    except Exception as e:  # noqa: BLE001
        return {"feasible": False, "objective": None, "reason": "malformed routes: %r" % (e,)}
    bad = []
    indeg, outdeg = {}, {}
    rin, rout, pin, pout = {}, {}, {}, {}
    for (i, j), v in x.items():
        outdeg[i] = outdeg.get(i, 0) + v
        indeg[j] = indeg.get(j, 0) + v
    for (i, j), v in R.items():
        rout[i] = rout.get(i, 0) + v
        rin[j] = rin.get(j, 0) + v
    for (i, j), v in Pf.items():
        pout[i] = pout.get(i, 0) + v
        pin[j] = pin.get(j, 0) + v
    for j in range(1, N):
        if abs(indeg.get(j, 0) - 1) > CHK_TOL:
            bad.append("in-degree of %d is %s" % (j, indeg.get(j, 0)))
        if abs(outdeg.get(j, 0) - 1) > CHK_TOL:
            bad.append("out-degree of %d is %s" % (j, outdeg.get(j, 0)))
    for j in range(1, n + 1):
        if abs(rin.get(j, 0) - rout.get(j, 0) - q[j]) > CHK_TOL:
            bad.append("delivery flow at %d" % j)
        if abs(pin.get(j, 0) - pout.get(j, 0)) > CHK_TOL:
            bad.append("pickup flow at %d" % j)
    for j in range(n + 1, N):
        if abs(rin.get(j, 0) - rout.get(j, 0)) > CHK_TOL:
            bad.append("delivery flow at %d" % j)
        if abs(pout.get(j, 0) - pin.get(j, 0) - q[j]) > CHK_TOL:
            bad.append("pickup flow at %d" % j)
    if abs(sum(v for (i, j), v in Pf.items() if i == 0 and 1 <= j < N)) > CHK_TOL:
        bad.append("pickup load leaving depot")
    if abs(sum(v for (i, j), v in R.items() if j == 0 and 1 <= i < N)) > CHK_TOL:
        bad.append("delivery load returning to depot")
    for arc in set(x) | set(R) | set(Pf):
        if R.get(arc, 0.0) + Pf.get(arc, 0.0) - C * x.get(arc, 0) > CHK_TOL:
            bad.append("capacity on arc %s" % (arc,))
        if R.get(arc, 0.0) < -CHK_TOL or Pf.get(arc, 0.0) < -CHK_TOL:
            bad.append("negative flow on arc %s" % (arc,))
    for arc, v in x.items():
        if v not in (0, 1):
            bad.append("arc %s used %s times" % (arc, v))
        if arc[0] == arc[1]:
            bad.append("self-loop %s" % (arc,))
        if 1 <= arc[1] <= n and arc[0] == arc[1] + n:
            bad.append("arc from backhaul %d to its linehaul %d" % arc)
    try:
        true_obj = float(sum(D[i][j] * v for (i, j), v in x.items()))
    except (IndexError, TypeError) as e:
        return {"feasible": False, "objective": None, "reason": "node id out of range: %r" % (e,)}
    if abs(float(ov) - true_obj) > max(1e-3, 1e-3 * abs(true_obj)):
        bad.append("objective %s != recomputed %s" % (ov, true_obj))
    return {"feasible": not bad, "objective": true_obj, "reason": "; ".join(bad[:5])}


# ---- own engine: SISR -----------------------------------------------------------------------------------------------
class State:
    def __init__(self, P, routes):
        self.P = P
        self.routes = [list(r) for r in routes if r]
        self.prof = [P.profile(r) for r in self.routes]
        self.cost = [P.route_len(r) for r in self.routes]

    def copy(self):
        s = State.__new__(State)
        s.P = self.P
        s.routes = [r[:] for r in self.routes]
        s.prof = list(self.prof)
        s.cost = list(self.cost)
        return s

    def total(self):
        return sum(self.cost)

    def refresh(self, ri):
        r = self.routes[ri]
        self.prof[ri] = self.P.profile(r)
        self.cost[ri] = self.P.route_len(r)

    def compact(self):
        keep = [k for k, r in enumerate(self.routes) if r]
        if len(keep) != len(self.routes):
            self.routes = [self.routes[k] for k in keep]
            self.prof = [self.prof[k] for k in keep]
            self.cost = [self.cost[k] for k in keep]


def ruin(st, rng, cbar=10.0, Lmax=10.0):
    P = st.P
    routes = st.routes
    where = {}
    for ri, r in enumerate(routes):
        for v in r:
            where[v] = ri
    nonempty = sum(1 for r in routes if r)
    if not nonempty:
        return []
    avg = sum(len(r) for r in routes) / nonempty
    ls_max = min(Lmax, avg)
    ks_max = 4.0 * cbar / (1.0 + ls_max) - 1.0
    ks = max(1, int(rng.uniform(1.0, ks_max + 1.0)))
    seed = rng.choice(P.nodes)
    removed = []
    ruined = set()
    for c in P.nbr[seed]:
        if len(ruined) >= ks:
            break
        ri = where.get(c)
        if ri is None or ri in ruined:
            continue
        r = routes[ri]
        L = len(r)
        lmax_t = min(L, ls_max)
        lt = max(1, min(L, int(rng.uniform(1.0, lmax_t + 1.0))))
        pos = r.index(c)
        if lt < L and rng.random() < 0.5:
            # split string: a window of lt + m visits around c, of which m consecutive ones stay
            m = 1
            while lt + m < L and rng.random() < 0.5:
                m += 1
            w = lt + m
            lo, hi = max(0, pos - w + 1), min(pos, L - w)
            s = rng.randint(lo, hi)
            keep_at = rng.randint(0, w - m)
            window = r[s:s + w]
            stay = window[keep_at:keep_at + m]
            gone = window[:keep_at] + window[keep_at + m:]
            r[s:s + w] = stay
            removed.extend(gone)
        else:
            lo, hi = max(0, pos - lt + 1), min(pos, L - lt)
            s = rng.randint(lo, hi)
            removed.extend(r[s:s + lt])
            del r[s:s + lt]
        ruined.add(ri)
    for ri in ruined:
        st.refresh(ri)
    return removed


def recreate(st, removed, rng, blink=0.01):
    P = st.P
    D, dd, pp, C = P.D, P.dd, P.pp, P.C + EPS
    mode = rng.random()
    if mode < 4 / 11:
        rng.shuffle(removed)
    elif mode < 8 / 11:
        removed.sort(key=lambda v: -(dd[v] + pp[v]))
    elif mode < 10 / 11:
        removed.sort(key=lambda v: -D[0][v])
    else:
        removed.sort(key=lambda v: D[0][v])
    D0 = D[0]
    for u in removed:
        du, pu = dd[u], pp[u]
        Du = D[u]
        best = D0[u] + Du[0]
        bri, bk = -1, 0
        routes, prof = st.routes, st.prof
        for ri in range(len(routes)):
            r = routes[ri]
            m = len(r)
            if not m:
                continue
            PM, SM = prof[ri]
            prev = 0
            for k in range(m + 1):
                if PM[k] + du > C:
                    break
                nxt = r[k] if k < m else 0
                if SM[k] + pu <= C:
                    delta = Du[prev] + Du[nxt] - D[prev][nxt]
                    if delta < best and rng.random() >= blink:
                        best, bri, bk = delta, ri, k
                prev = nxt
        if bri < 0:
            st.routes.append([u])
            st.prof.append(P.profile([u]))
            st.cost.append(D0[u] + Du[0])
        else:
            st.routes[bri].insert(bk, u)
            st.refresh(bri)
    st.compact()


def own_search(P, deadline, rng, st=None, on_best=None, log=None):
    if st is None:
        st = State(P, [])
        rem = list(P.nodes)
        recreate(st, rem, rng, blink=0.0)
    cur = st
    cur_c = cur.total()
    best, best_c = cur.copy(), cur_c
    if on_best:
        on_best(best.routes, best_c, "own-construct")
    T0 = max(1e-6, 0.2 * P.avg_dep)
    Tf = max(1e-7, 0.002 * P.avg_dep)
    t_begin = time.monotonic()
    span = max(1e-6, deadline - t_begin)
    it = acc = imp = 0
    events = [(0.0, best_c)]
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
        removed = ruin(cand, rng)
        if not removed:
            continue
        recreate(cand, removed, rng)
        c = cand.total()
        if c < cur_c - T * math.log(max(1e-300, rng.random())):
            acc += 1
            cur, cur_c = cand, c
            if c < best_c - EPS:
                imp += 1
                best, best_c = cand.copy(), c
                now = time.monotonic()
                events.append((round(now - t_begin, 2), best_c))
                if on_best and now - last_write > 5.0:
                    on_best(best.routes, best_c, "own")
                    last_write = now
    if log is not None:
        log.update({"own_iterations": it, "own_accepted": acc, "own_improved": imp,
                    "own_events": events[:3] + events[-10:] if len(events) > 13 else events})
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
        if cost < best["cost"] - EPS and P.valid(routes):
            best.update(routes=[list(r) for r in routes], cost=cost, src=src)
            if on_write is not None:
                on_write(build_solution(P, best["routes"]))

    routes, c = own_search(P, deadline, rng, on_best=offer, log=log)
    offer(routes, c, "own")
    sol = build_solution(P, best["routes"])
    if log is not None:
        log.update({"version": VERSION, "seed": seed, "n": P.n,
                    "capacity": P.C, "routes": len(best["routes"]), "objective": sol["objective_value"],
                    "best_source": best["src"], "time_used_s": round(time.monotonic() - t_start, 3)})
    return sol


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def main(argv=None):
    t_start = time.monotonic()
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="nagy2015")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=int(os.environ.get("MV2_NAGY_SEED", "1")))
    a = ap.parse_args(argv)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    log = {} if os.environ.get("MV2_NAGY_LOG") == "1" else None
    sol = solve(inst, a.time_limit, a.seed, t_start=t_start, on_write=lambda s: write_json(a.output, s), log=log)
    write_json(a.output, sol)
    if log is not None:
        write_json(a.output + ".log.json", log)
    return 0


if __name__ == "__main__":
    sys.exit(main())

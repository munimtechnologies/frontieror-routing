#!/usr/bin/env python3
"""VRP with divisible deliveries and pickups (VRPDDP) solver for the FrontierOR practice problem nagy2015.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name.
License: Apache-2.0.

Contract (FrontierOR Main track):
    python solve.py --problem nagy2015 --instance in.json --output out.json --time-limit 60

Instance (as documented on the problem page): num_customers, vehicle_capacity, depot {id 0, x, y},
customers [{id 1..n, x, y, delivery_demand, pickup_demand}], distance_matrix [n+1][n+1].
Each delivery and each pickup is one request that must be served whole in one visit; a customer's
delivery and pickup may go on different vehicles. Load on board (deliveries still to drop plus pickups
collected) must never exceed the capacity. Unlimited fleet. Minimise total distance.

Model: every customer i becomes two requests, a linehaul node i and a backhaul node n+i, at the same
place (distance 0 between them). A route visiting both one after the other is the classic
simultaneous pickup-and-delivery visit, so VRPSPD solutions are a subset of what is searched.

Engines:
- "pyvrp": PyVRP (MIT, Wouda, Lan and Kool), a hybrid genetic search that supports simultaneous
  pickup and delivery loads. Used when the package can be imported (it is not in the FrontierOR
  image; it would be listed as an extra open-source PyPI package). Works with the PyVRP 0.14
  Location/ProblemData API and falls back to the older x/y API.
- "own": a numpy-only ruin-and-recreate search in the spirit of SISR (Christiaens and Vanden Berghe,
  2020) with O(1) load checks per insertion position, simulated-annealing acceptance. In the
  divisible case it first solves the non-divisible variant (30% of the time) and seeds the divisible
  search with it, so the split can only help (v2; v1 searched the larger space from scratch and
  ended about 6.5% worse than its own non-divisible runs).
- "auto" (default): a fast own construction is written to the output first as a safety net, then a
  portfolio: PyVRP on the divisible model (50% of the time), PyVRP on the non-divisible model (20%),
  then the own search seeded with the best so far. Every candidate is checked; the best is kept.
Set with --engine or the NAGY_ENGINE environment variable. --spd solves the non-divisible variant
(VRPSPD: a customer's delivery and pickup in one visit), used only for calibration.

Seeded, but searches stop on wall-clock time, so results can differ with machine speed. The solver
stops well before the limit (min(88% of it, limit - 5 s)).
"""
import argparse
import json
import math
import os
import random
import sys
import time

_T_START = time.time()

import numpy as np  # noqa: E402

EPS = 1e-6
VERSION = "0.2.0"


def log(msg):
    sys.stderr.write("[%6.1fs] %s\n" % (time.time() - _T_START, msg))
    sys.stderr.flush()


# ---------------------------------------------------------------- instance
def parse_instance(inst):
    """Return a dict with n, C, D (location matrix, depot 0, customer i at i), deliv, pick, coords."""
    custs = sorted(inst["customers"], key=lambda c: int(c["id"]))
    n = len(custs)
    ids = [int(c["id"]) for c in custs]
    if ids != list(range(1, n + 1)):
        raise ValueError("customer ids must be 1..n")
    C = float(inst["vehicle_capacity"])
    dep = inst.get("depot", {}) or {}
    coords = [(float(dep.get("x", 0)), float(dep.get("y", 0)))]
    coords += [(float(c.get("x", 0)), float(c.get("y", 0))) for c in custs]
    dm = inst.get("distance_matrix")
    if dm is not None and len(dm) == n + 1:
        D = np.asarray(dm, dtype=float)
    else:
        xy = np.asarray(coords, dtype=float)
        D = np.floor(np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(axis=2)) + 0.5)
    deliv = np.array([float(c.get("delivery_demand", 0) or 0) for c in custs], dtype=float)
    pick = np.array([float(c.get("pickup_demand", 0) or 0) for c in custs], dtype=float)
    return {"n": n, "C": C, "D": D, "deliv": deliv, "pick": pick, "coords": coords}


def requests(P, spd=False):
    """Requests as arrays (loc, qd, qp). DDP: r < n is linehaul of customer r+1, r >= n backhaul of r-n+1.
    SPD: r is customer r+1 with both quantities."""
    n = P["n"]
    if spd:
        loc = np.arange(1, n + 1)
        return loc, P["deliv"].copy(), P["pick"].copy()
    loc = np.concatenate((np.arange(1, n + 1), np.arange(1, n + 1)))
    qd = np.concatenate((P["deliv"], np.zeros(n)))
    qp = np.concatenate((np.zeros(n), P["pick"]))
    return loc, qd, qp


def spd_to_ddp(routes_spd, n):
    """Non-divisible request routes -> divisible request routes (customer r -> linehaul r, backhaul n+r)."""
    out = []
    for rt in routes_spd:
        if not rt:
            continue
        rr = []
        for r in rt:
            rr += [int(r), n + int(r)]
        out.append(rr)
    return out


def expand(routes_req, n, spd=False):
    """Request routes -> expanded node-id routes [0, ..., 0] (linehaul 1..n, backhaul n+1..2n)."""
    out = []
    for rt in routes_req:
        if len(rt) == 0:
            continue
        ids = [0]
        for r in rt:
            r = int(r)
            if spd:
                ids += [r + 1, n + r + 1]
            else:
                ids.append(r + 1)
        ids.append(0)
        out.append(ids)
    return out


def check_expanded(P, routes):
    """Internal checker on expanded routes. Returns (ok, reason, cost)."""
    n, C, D = P["n"], P["C"], P["D"]
    seen = np.zeros(2 * n + 1, dtype=int)
    total = 0.0
    for rt in routes:
        if len(rt) < 3 or rt[0] != 0 or rt[-1] != 0:
            return False, "route must start and end at 0 and visit something", None
        inner = rt[1:-1]
        load = 0.0
        for v in inner:
            if v <= 0 or v > 2 * n:
                return False, "bad node %r" % (v,), None
            seen[v] += 1
            if v <= n:
                load += P["deliv"][v - 1]
        if load > C + EPS:
            return False, "start load over capacity", None
        for v in inner:
            if v <= n:
                load -= P["deliv"][v - 1]
            else:
                load += P["pick"][v - n - 1]
            if load > C + EPS:
                return False, "load over capacity", None
        locs = [0 if v == 0 else (v if v <= n else v - n) for v in rt]
        total += float(sum(D[a, b] for a, b in zip(locs[:-1], locs[1:])))
    if (seen[1:] != 1).any():
        return False, "every node 1..2n must be visited exactly once", None
    return True, "ok", total


def build_solution(P, routes):
    n = P["n"]
    ok, why, cost = check_expanded(P, routes)
    detailed = []
    for rt in routes:
        det = []
        for v in rt:
            if v == 0:
                det.append({"node": 0, "role": "depot", "customer": 0, "quantity": 0})
            elif v <= n:
                q = P["deliv"][v - 1]
                det.append({"node": v, "role": "linehaul", "customer": v,
                            "quantity": int(q) if float(q).is_integer() else float(q)})
            else:
                q = P["pick"][v - n - 1]
                det.append({"node": v, "role": "backhaul", "customer": v - n,
                            "quantity": int(q) if float(q).is_integer() else float(q)})
        detailed.append(det)
    return {"objective_value": float(cost) if cost is not None else None,
            "routes": [[int(v) for v in rt] for rt in routes],
            "routes_detailed": detailed}, ok, why


# ---------------------------------------------------------------- own engine
class Own:
    """Ruin-and-recreate search over request routes with O(1) load checks per insertion position.

    For a route with arc loads L[0..m] (L[0] = deliveries on board when leaving the depot), inserting a
    request with delivery qd and pickup qp on arc p is load-feasible iff
        max(L[0..p]) + qd <= C   and   max(L[p..m]) + qp <= C.
    """

    def __init__(self, D, loc, qd, qp, C, seed=20261109):
        self.D, self.loc, self.qd, self.qp, self.C = D, np.asarray(loc), qd, qp, C
        self.N = len(loc)
        self.rng = random.Random(seed)
        self.nrng = np.random.default_rng(seed)
        self.routes, self.cache = [], []
        self._glob = None
        self.iterations = 0
        nloc = D.shape[0]
        # requests ordered by distance from each location
        dist_to_req = D[:, self.loc]  # nloc x N
        self.nbr = np.argsort(dist_to_req, axis=1, kind="stable")[:, :min(self.N, 200)]
        self.depot_dist = D[0, self.loc] + D[self.loc, 0]
        self.size = qd + qp
        self.nloc = nloc

    # -- route arrays
    def arrays(self, rt):
        rt = np.asarray(rt, dtype=int)
        m = rt.size
        L = np.empty(m + 1)
        L[0] = self.qd[rt].sum() if m else 0.0
        if m:
            L[1:] = L[0] + np.cumsum(self.qp[rt] - self.qd[rt])
        pref = np.maximum.accumulate(L)
        suf = np.maximum.accumulate(L[::-1])[::-1]
        locs = self.loc[rt]
        A = np.concatenate(([0], locs)).astype(int)
        B = np.concatenate((locs, [0])).astype(int)
        dab = self.D[A, B]
        return (A, B, pref, suf, float(dab.sum()), dab, float(L.max()))

    def set_routes(self, routes):
        self.routes = [list(r) for r in routes if len(r)]
        self.cache = [self.arrays(r) for r in self.routes]
        self._glob = None

    def cost(self):
        return float(sum(c[4] for c in self.cache))

    def _rebuild(self):
        if not self.cache:
            self._glob = None
            return
        A = np.concatenate([c[0] for c in self.cache])
        B = np.concatenate([c[1] for c in self.cache])
        PR = np.concatenate([c[2] for c in self.cache])
        SU = np.concatenate([c[3] for c in self.cache])
        DAB = np.concatenate([c[5] for c in self.cache])
        rid = np.concatenate([np.full(len(c[0]), i) for i, c in enumerate(self.cache)])
        pos = np.concatenate([np.arange(len(c[0])) for c in self.cache])
        self._glob = (A, B, PR, SU, DAB, rid, pos)

    def insert(self, reqs, blink=0.0):
        D, C = self.D, self.C
        for v in reqs:
            lv = int(self.loc[v])
            qd, qp = self.qd[v], self.qp[v]
            if self._glob is None:
                self._rebuild()
            best_cost, best_ri, best_p = math.inf, -1, -1
            if self._glob is not None:
                A, B, PR, SU, DAB, rid, pos = self._glob
                delta = D[A, lv] + D[lv, B] - DAB
                ok = (PR + qd <= C + EPS) & (SU + qp <= C + EPS)
                if blink > 0:
                    ok &= self.nrng.random(ok.size) >= blink
                if ok.any():
                    delta = np.where(ok, delta, np.inf)
                    k = int(np.argmin(delta))
                    best_cost, best_ri, best_p = float(delta[k]), int(rid[k]), int(pos[k])
            new_cost = D[0, lv] + D[lv, 0]
            if best_ri < 0 or new_cost < best_cost - 1e-12:
                self.routes.append([v])
                self.cache.append(self.arrays([v]))
            else:
                self.routes[best_ri].insert(best_p, v)
                self.cache[best_ri] = self.arrays(self.routes[best_ri])
            self._glob = None

    def ruin(self, cbar=10.0, lmax_cfg=10.0):
        rng = self.rng
        R = len(self.routes)
        if R == 0:
            return []
        avg = self.N / R
        lsmax = min(lmax_cfg, avg)
        ksmax = 4.0 * cbar / (1.0 + lsmax) - 1.0
        ks = int(rng.uniform(1.0, ksmax + 1.0))
        where = {}
        for ri, rt in enumerate(self.routes):
            for v in rt:
                where[v] = ri
        seed = rng.randrange(self.N)
        removed, ruined = [], set()
        for v in self.nbr[self.loc[seed]]:
            if len(ruined) >= ks:
                break
            v = int(v)
            ri = where.get(v)
            if ri is None or ri in ruined:
                continue
            rt = self.routes[ri]
            lm = min(lsmax, len(rt))
            ln = max(1, min(len(rt), int(rng.uniform(1.0, lm + 1.0))))
            idx = rt.index(v)
            lo, hi = max(0, idx - ln + 1), min(idx, len(rt) - ln)
            st = rng.randint(lo, hi) if hi >= lo else max(0, min(idx, len(rt) - ln))
            removed += rt[st:st + ln]
            self.routes[ri] = rt[:st] + rt[st + ln:]
            ruined.add(ri)
        for ri in ruined:
            self.cache[ri] = self.arrays(self.routes[ri])
        keep = [i for i, rt in enumerate(self.routes) if len(rt)]
        self.routes = [self.routes[i] for i in keep]
        self.cache = [self.cache[i] for i in keep]
        self._glob = None
        return removed

    def order(self, removed):
        rng = self.rng
        x = rng.random() * 11.0
        if x < 4.0:
            rng.shuffle(removed)
        elif x < 8.0:
            removed.sort(key=lambda v: -self.size[v])
        elif x < 10.0:
            removed.sort(key=lambda v: -self.depot_dist[v])
        else:
            removed.sort(key=lambda v: self.depot_dist[v])
        return removed

    def construct(self):
        self.set_routes([])
        reqs = sorted(range(self.N), key=lambda v: -self.depot_dist[v])
        self.insert(reqs)
        return self.cost()

    def search(self, end_time, start_routes=None):
        if start_routes is not None:
            self.set_routes(start_routes)
        elif not self.routes:
            self.construct()
        cur = self.cost()
        best, best_routes = cur, [list(r) for r in self.routes]
        avg_arc = max(cur / max(1, self.N + len(self.routes)), 1e-9)
        T0, Tf = 0.1 * avg_arc, 0.001 * avg_arc
        t_begin = time.time()
        span = max(end_time - t_begin, 1e-3)
        it = 0
        while True:
            now = time.time()
            if now >= end_time:
                break
            it += 1
            frac = (now - t_begin) / span
            T = T0 * (Tf / T0) ** min(1.0, frac)
            saved_r = [list(r) for r in self.routes]
            saved_c = list(self.cache)
            removed = self.ruin()
            self.insert(self.order(removed), blink=0.01)
            new = self.cost()
            if new < cur - T * math.log(1.0 - self.rng.random()):
                cur = new
                if new < best - 1e-9:
                    best, best_routes = new, [list(r) for r in self.routes]
            else:
                self.routes, self.cache, self._glob = saved_r, saved_c, None
        self.iterations += it
        return best, best_routes


# ---------------------------------------------------------------- PyVRP engine
def _is_client_activity(act):
    f = getattr(act, "is_client", None)
    if callable(f):
        return bool(f())
    if f is not None:
        return bool(f)
    t = getattr(act, "type", None)
    return getattr(t, "name", str(t)).upper().endswith("CLIENT")


def _route_raw(route):
    """Client numbers in visit order: old API visits() (clients after depots), new API activities (0-based)."""
    if hasattr(route, "visits"):
        return [int(v) for v in route.visits()]
    acts = route.schedule() if hasattr(route, "schedule") else list(route)
    return [int(a.idx) for a in acts if _is_client_activity(a)]


def normalise_routes(raw_routes, N):
    """Map raw client numbers to 0..N-1. Accepts exactly the sets {0..N-1} or {1..N}; else None."""
    flat = sorted(v for r in raw_routes for v in r)
    if flat == list(range(N)):
        off = 0
    elif flat == list(range(1, N + 1)):
        off = 1
    else:
        return None
    return [[v - off for v in r] for r in raw_routes if r]


def pyvrp_data(P, loc, qd, qp):
    """Build a PyVRP ProblemData for request arrays; works with 0.14 (Location API) and older x/y API."""
    from pyvrp import Client, Depot, ProblemData, VehicleType
    N = len(loc)
    vals = np.concatenate((qd, qp, [P["C"]]))
    qs = 1 if np.all(np.abs(vals - np.round(vals)) < 1e-9) else 100000
    D = P["D"]
    ds = 1 if np.all(np.abs(D - np.round(D)) < 1e-9) else 1000
    dist = np.rint(D * ds).astype(np.int64)
    np.fill_diagonal(dist, 0)
    co = P["coords"]
    dl = [int(math.ceil(qd[r] * qs - 1e-6)) for r in range(N)]
    pk = [int(math.ceil(qp[r] * qs - 1e-6)) for r in range(N)]
    cap = int(math.floor(P["C"] * qs + 1e-6))
    vt = VehicleType(num_available=max(1, N), capacity=[cap])
    try:
        from pyvrp import Location
    except ImportError:
        Location = None
    if Location is not None:
        locs = [Location(float(x), float(y)) for (x, y) in co]
        depot = Depot(location=0)
        clients = [Client(location=int(loc[r]), delivery=[dl[r]], pickup=[pk[r]]) for r in range(N)]
        dur = np.zeros_like(dist)
        return ProblemData(locs, clients, [depot], [vt], [dist], [dur])
    idx = np.concatenate(([0], np.asarray(loc, dtype=int)))
    distc = dist[np.ix_(idx, idx)]
    np.fill_diagonal(distc, 0)
    durc = np.zeros_like(distc)
    depot = Depot(x=int(round(co[0][0])), y=int(round(co[0][1])))
    clients = []
    for r in range(N):
        x, y = co[int(loc[r])]
        clients.append(Client(x=int(round(x)), y=int(round(y)), delivery=[dl[r]], pickup=[pk[r]]))
    return ProblemData(clients=clients, depots=[depot], vehicle_types=[vt],
                       distance_matrices=[distc], duration_matrices=[durc], groups=[])


def pyvrp_routes(P, loc, qd, qp, end_time, seed=20261109):
    """Solve with PyVRP; returns request routes (0-based) or None. Quantities are scaled to integers if
    needed (demands rounded up, capacity down, so a PyVRP-feasible route is feasible in the real data)."""
    import pyvrp
    from pyvrp.stop import MaxRuntime

    data = pyvrp_data(P, loc, qd, qp)
    budget = end_time - time.time()
    if budget < 0.5:
        return None
    res = pyvrp.solve(data, stop=MaxRuntime(budget), seed=int(seed), collect_stats=False, display=False)
    if not res.best.is_feasible():
        return None
    return normalise_routes([_route_raw(r) for r in res.best.routes()], len(loc))


# ---------------------------------------------------------------- driver
def write(path, sol):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sol, f)
    os.replace(tmp, path)


def solve(inst, time_limit_s, engine="auto", spd=False, output=None, start=None, seed=20261109):
    t_start = _T_START if start is None else start
    end = t_start + max(0.8, min(0.88 * time_limit_s, time_limit_s - 5.0))
    P = parse_instance(inst)
    n = P["n"]
    loc, qd, qp = requests(P, spd)
    if (qd > P["C"] + EPS).any() or (qp > P["C"] + EPS).any():
        log("a single request exceeds the capacity: no feasible solution exists")
    own = Own(P["D"], loc, qd, qp, P["C"], seed=seed)
    own.construct()
    best = {"req": [list(r) for r in own.routes], "cost": own.cost(), "eng": "construct"}
    sol, ok, why = build_solution(P, expand(best["req"], n, spd))
    if output and ok:
        write(output, sol)
    stats = {"version": VERSION, "construct": best["cost"]}

    def offer(req, name, from_spd=False):
        """Check a candidate (request routes of this model, or SPD routes if from_spd) and keep it if better."""
        if req is None:
            stats[name] = None
            return
        rr = spd_to_ddp(req, n) if (from_spd and not spd) else req
        s2, ok2, why2 = build_solution(P, expand(rr, n, spd))
        stats[name] = s2["objective_value"] if ok2 else "infeasible: " + why2
        if ok2 and s2["objective_value"] < best["cost"] - 1e-9:
            best.update({"req": [list(r) for r in rr], "cost": s2["objective_value"], "eng": name})
            if output:
                write(output, s2)

    def until(frac):
        now = time.time()
        return now + max(0.0, end - now) * frac

    pyvrp_ok = False
    if engine in ("auto", "pyvrp"):
        try:
            offer(pyvrp_routes(P, loc, qd, qp, until(0.5 if not spd else 0.75), seed=seed), "pyvrp")
            pyvrp_ok = stats.get("pyvrp") is not None
            if not spd:
                lo2, qd2, qp2 = requests(P, spd=True)
                offer(pyvrp_routes(P, lo2, qd2, qp2, until(0.4), seed=seed + 1), "pyvrp_spd", from_spd=True)
        except Exception as e:  # missing package or API change: fall back to the own engine
            stats["pyvrp_error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    if not spd and not pyvrp_ok:
        lo2, qd2, qp2 = requests(P, spd=True)
        own_spd = Own(P["D"], lo2, qd2, qp2, P["C"], seed=seed + 2)
        own_spd.construct()
        c_spd, r_spd = own_spd.search(until(0.3))
        stats["own_spd_iterations"] = own_spd.iterations
        offer(r_spd, "own_spd", from_spd=True)
    cost, rr = own.search(end, start_routes=best["req"])
    stats["own_iterations"] = own.iterations
    offer(rr, "own")
    sol, ok, why = build_solution(P, expand(best["req"], n, spd))
    stats.update({"engine": best["eng"], "objective": sol["objective_value"], "feasible": ok, "why": why,
                  "elapsed": round(time.time() - t_start, 2), "spd": spd})
    log("NAGY_SOLVER_STATS " + json.dumps(stats))
    if output and ok:
        write(output, sol)
    return sol


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="nagy2015")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--engine", default=os.environ.get("NAGY_ENGINE", "auto"),
                    choices=["auto", "own", "pyvrp"])
    ap.add_argument("--spd", action="store_true", help="non-divisible variant (calibration only)")
    args = ap.parse_args(argv)
    with open(args.instance, "r", encoding="utf-8") as f:
        inst = json.load(f)
    solve(inst, args.time_limit, engine=args.engine, spd=args.spd, output=args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""desaulniers2010 (split-delivery VRPTW, SDVRPTW) solver for the FrontierOR Challenge, v0.1.0.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Rules, read from the public FrontierOR benchmark's problem_description.txt and feasibility_check.py (Hugging Face
frontieror/FrontierOR, task desaulniers2010, CC BY 4.0):
- nodes 0 (departure depot), 1..n (customers), n+1 (return depot; distances mirror node 0);
- cost c_ij = distance_matrix[i][j] (Euclidean, truncated to one decimal); travel time t_ij = c_ij + service_i;
- visit start s_0 = e_0, s_j = max(e_j, s_i + t_ij) <= l_j at every node including n+1 (the depot window);
- a vehicle may deliver any quantity 0 <= q <= min(d_i, Q) to a customer it visits; per-vehicle total <= Q;
  every customer receives at least its demand d_i in total (split deliveries allowed) and is visited at least
  ceil(d_i / Q) times; each route is a simple path 0 -> ... -> n+1 (no arc used twice);
- objective = total arc cost, recomputed by the checker (0.1% tolerance); num_vehicles_used = len(routes).
Output: {"objective_value", "num_vehicles_used", "routes": [{"vehicle", "route", "deliveries"}], "deliveries"}.

Pipeline (every candidate is re-checked exactly before it is written, atomically):
1. customers with d_i > Q first get floor(d_i / Q) dedicated full-load out-and-back routes (each is feasible
   whenever the instance is, because the arc 0 -> i -> n+1 must exist for the customer to be servable at all);
2. one route per remaining customer (written at once), then sequential cheapest feasible insertion;
3. unsplit VRPTW search: PyVRP's iterated local search (pip package pyvrp, MIT) on an EXACT integer copy (all
   distances have one decimal, so x10 makes every time and cost an integer; nothing is rounded); with 2 CPUs a
   forked child runs a second PyVRP seed. Without pyvrp, a pure-Python relocate + 2-opt* local search runs instead;
4. split-delivery improvement: (a) route elimination by split re-insertion (empty a route, re-insert each of its
   deliveries into routes with spare capacity, at zero cost where the customer is already visited, otherwise at
   the cheapest feasible position, splitting the quantity over several routes when needed); (b) visit removal by
   split re-insertion (take one customer out of one route and spread its quantity over other routes);
   (c) intra-route or-opt. Each move is accepted only if the total cost strictly decreases.
"""
import argparse
import json
import math
import os
import sys
import tempfile
import time

T_START = time.monotonic()
VERSION = "0.1.0"
TOL = 1e-7
EPS = 1e-6


class Problem:
    def __init__(self, inst):
        n = int(inst["num_customers"])
        self.n = n
        self.sink = n + 1
        self.Q = inst["vehicle_capacity"]
        dep = inst["depot"]
        D = inst["distance_matrix"]
        N2 = n + 2
        self.e = [0] * N2
        self.l = [0] * N2
        self.svc = [0] * N2
        self.dem = [0] * N2
        self.e[0] = self.e[self.sink] = dep["time_window"][0]
        self.l[0] = self.l[self.sink] = dep["time_window"][1]
        self.svc[0] = dep.get("service_time", 0) or 0
        self.x = [0.0] * N2
        self.y = [0.0] * N2
        self.x[0], self.y[0] = float(dep.get("x", 0) or 0), float(dep.get("y", 0) or 0)
        for c in inst["customers"]:
            i = int(c["id"])
            self.x[i], self.y[i] = float(c.get("x", 0) or 0), float(c.get("y", 0) or 0)
            self.e[i], self.l[i] = c["time_window"][0], c["time_window"][1]
            self.svc[i] = c.get("service_time", 0) or 0
            self.dem[i] = c["demand"]
        # C[i][j] for i in 0..n, j in 0..n+1 (column n+1 = return to depot)
        self.C = []
        self.T = []
        for i in range(n + 1):
            row = [float(D[i][j]) for j in range(n + 1)] + [float(D[i][0])]
            self.C.append(row)
            self.T.append([x + self.svc[i] for x in row])
        self.customers = [i for i in range(1, n + 1) if self.dem[i] > 0]

    def sched_ok(self, seq):
        T, e, l = self.T, self.e, self.l
        s = e[0]
        prev = 0
        for j in seq:
            s = s + T[prev][j]
            if s < e[j]:
                s = e[j]
            if s > l[j] + TOL:
                return False
            prev = j
        return s + T[prev][self.sink] <= l[self.sink] + TOL

    def seq_cost(self, seq):
        C = self.C
        prev = 0
        tot = 0.0
        for j in seq:
            tot += C[prev][j]
            prev = j
        return tot + C[prev][self.sink]


# ----------------------------------------------------------------------------------------------- routes / state
class Route:
    __slots__ = ("seq", "q")

    def __init__(self, seq, q):
        self.seq = list(seq)
        self.q = dict(q)

    def load(self):
        return sum(self.q.values())

    def copy(self):
        return Route(self.seq, self.q)


def total_cost(pb, routes):
    return sum(pb.seq_cost(r.seq) for r in routes if r.seq)


def verify(pb, routes):
    """Independent re-implementation of the official constraints (stricter tolerance). Returns (ok, why)."""
    got = {}
    visits = {}
    for k, r in enumerate(routes):
        if not r.seq:
            return False, "route %d empty" % k
        if len(set(r.seq)) != len(r.seq):
            return False, "route %d repeats a customer" % k
        if any(not (1 <= c <= pb.n) for c in r.seq):
            return False, "route %d has a bad node" % k
        if not pb.sched_ok(r.seq):
            return False, "route %d time windows" % k
        if r.load() > pb.Q + TOL:
            return False, "route %d over capacity %s" % (k, r.load())
        for c, x in r.q.items():
            if c not in r.seq:
                return False, "route %d delivers to unvisited %d" % (k, c)
            if x < -TOL or x > min(pb.dem[c], pb.Q) + TOL:
                return False, "route %d bad quantity %s at %d" % (k, x, c)
            got[c] = got.get(c, 0) + x
        for c in r.seq:
            visits[c] = visits.get(c, 0) + 1
    for c in range(1, pb.n + 1):
        if pb.dem[c] > 0:
            if got.get(c, 0) < pb.dem[c] - TOL:
                return False, "customer %d short %s < %s" % (c, got.get(c, 0), pb.dem[c])
            if visits.get(c, 0) < math.ceil(pb.dem[c] / pb.Q):
                return False, "customer %d too few visits" % c
    return True, ""


def solution_json(pb, routes):
    used = [r for r in routes if r.seq]
    out_routes = []
    tot = {}
    for k, r in enumerate(used):
        dl = {str(c): r.q[c] for c in r.seq if r.q.get(c, 0) > 0}
        for c in r.seq:
            tot[c] = tot.get(c, 0) + r.q.get(c, 0)
        out_routes.append({"vehicle": k, "route": [0] + list(r.seq) + [pb.sink], "deliveries": dl})
    deliveries = {str(c): {"demand": pb.dem[c], "total_delivered": tot.get(c, 0)} for c in range(1, pb.n + 1)}
    return {"objective_value": round(total_cost(pb, used), 6), "num_vehicles_used": len(used),
            "routes": out_routes, "deliveries": deliveries,
            "solver": "MV2 desaulniers2010 SDVRPTW v%s (made with AI agents working in MV2's name)" % VERSION}


# ------------------------------------------------------------------------------------------ unsplit construction
def dedicated_and_residual(pb):
    """Full-load out-and-back routes for d_i > Q; returns (routes, residual demand dict)."""
    fixed = []
    res = {}
    for c in pb.customers:
        d = pb.dem[c]
        k = 0
        while d > pb.Q + TOL:
            fixed.append(Route([c], {c: pb.Q}))
            d -= pb.Q
            k += 1
        if d > TOL:
            res[c] = d
    return fixed, res


def insertion(pb, res, deadline):
    left = set(res)
    out = []
    while left:
        if time.monotonic() > deadline:
            out.extend([c] for c in sorted(left))
            break
        seed = max(left, key=lambda c: (pb.C[0][c], -pb.l[c], c))
        r = [seed]
        load = res[seed]
        left.discard(seed)
        while left and time.monotonic() < deadline:
            best = None
            for c in left:
                if load + res[c] > pb.Q + TOL:
                    continue
                for p in range(len(r) + 1):
                    a = 0 if p == 0 else r[p - 1]
                    b = pb.sink if p == len(r) else r[p]
                    delta = pb.C[a][c] + pb.C[c][b] - pb.C[a][b]
                    if best is not None and delta >= best[0]:
                        continue
                    if pb.sched_ok(r[:p] + [c] + r[p:]):
                        best = (delta, c, p)
            if best is None:
                break
            _, c, p = best
            r.insert(p, c)
            load += res[c]
            left.discard(c)
        out.append(r)
    return out


def ls_unsplit(pb, seqs, res, deadline):
    """Pure-Python relocate + 2-opt* on unsplit routes (fallback when pyvrp is missing)."""
    seqs = [list(s) for s in seqs if s]
    loads = [sum(res[c] for c in s) for s in seqs]
    improved = True
    while improved and time.monotonic() < deadline:
        improved = False
        # relocate
        for ai in range(len(seqs)):
            A = seqs[ai]
            pos = 0
            while pos < len(A) and time.monotonic() < deadline:
                c = A[pos]
                remA = A[:pos] + A[pos + 1:]
                gain = pb.seq_cost(A) - (pb.seq_cost(remA) if remA else 0.0)
                best = None
                for bi, B in enumerate(seqs):
                    if bi == ai:
                        base = remA
                    else:
                        if not B or loads[bi] + res[c] > pb.Q + TOL:
                            continue
                        base = B
                    for p in range(len(base) + 1):
                        a = 0 if p == 0 else base[p - 1]
                        b = pb.sink if p == len(base) else base[p]
                        delta = pb.C[a][c] + pb.C[c][b] - pb.C[a][b]
                        if bi == ai and not base:
                            continue
                        lim = gain if best is None else min(gain, best[0])
                        if delta >= lim - EPS:
                            continue
                        if pb.sched_ok(base[:p] + [c] + base[p:]):
                            best = (delta, bi, p)
                if best is None:
                    pos += 1
                    continue
                _, bi, p = best
                if bi == ai:
                    seqs[ai] = remA[:p] + [c] + remA[p:]
                else:
                    seqs[ai] = remA
                    seqs[bi] = seqs[bi][:p] + [c] + seqs[bi][p:]
                    loads[ai] -= res[c]
                    loads[bi] += res[c]
                A = seqs[ai]
                improved = True
        # 2-opt* (exchange tails)
        for ai in range(len(seqs)):
            for bi in range(ai + 1, len(seqs)):
                if time.monotonic() > deadline:
                    break
                A, B = seqs[ai], seqs[bi]
                if not A or not B:
                    continue
                base = pb.seq_cost(A) + pb.seq_cost(B)
                done = False
                for i in range(len(A) + 1):
                    for j in range(len(B) + 1):
                        nA = A[:i] + B[j:]
                        nB = B[:j] + A[i:]
                        cA = pb.seq_cost(nA) if nA else 0.0
                        cB = pb.seq_cost(nB) if nB else 0.0
                        if cA + cB >= base - EPS:
                            continue
                        lA = sum(res[c] for c in nA)
                        lB = sum(res[c] for c in nB)
                        if lA > pb.Q + TOL or lB > pb.Q + TOL:
                            continue
                        if (not nA or pb.sched_ok(nA)) and (not nB or pb.sched_ok(nB)):
                            seqs[ai], seqs[bi] = nA, nB
                            loads[ai], loads[bi] = lA, lB
                            improved = done = True
                            break
                    if done:
                        break
        seqs_nz = [(s, ld) for s, ld in zip(seqs, loads) if s]
        seqs = [s for s, _ in seqs_nz]
        loads = [ld for _, ld in seqs_nz]
    return seqs


# ------------------------------------------------------------------------------------------------------ PyVRP
SCALE = 10


def vrplib_text(pb, res):
    locs = [0] + sorted(res)
    n = len(locs)

    def iv(x):
        return int(round(x * SCALE))

    lines = ["NAME: frontieror-desaulniers2010", "TYPE: VRPTW", "DIMENSION: %d" % n,
             "CAPACITY: %d" % int(math.floor(pb.Q + TOL)), "VEHICLES: %d" % max(1, n - 1),
             "EDGE_WEIGHT_TYPE: EXPLICIT", "EDGE_WEIGHT_FORMAT: FULL_MATRIX", "NODE_COORD_SECTION"]
    for k, i in enumerate(locs):
        lines.append("%d %d %d" % (k + 1, int(round(pb.x[i] * SCALE)), int(round(pb.y[i] * SCALE))))
    lines.append("EDGE_WEIGHT_SECTION")
    for a in locs:
        lines.append(" ".join("0" if a == b else str(iv(pb.C[a][b])) for b in locs))
    lines.append("DEMAND_SECTION")
    for k, i in enumerate(locs):
        lines.append("%d %d" % (k + 1, 0 if i == 0 else int(math.ceil(res[i] - TOL))))
    lines.append("SERVICE_TIME_SECTION")
    for k, i in enumerate(locs):
        lines.append("%d %d" % (k + 1, iv(pb.svc[i])))
    lines.append("TIME_WINDOW_SECTION")
    for k, i in enumerate(locs):
        lines.append("%d %d %d" % (k + 1, iv(pb.e[i]), iv(pb.l[i])))
    lines += ["DEPOT_SECTION", "1", "-1", "EOF"]
    return "\n".join(lines) + "\n", locs


def exact_integer_copy(pb, res):
    """True when x10 makes every distance, window and service time an integer (then PyVRP is exact)."""
    vals = [pb.C[a][b] for a in [0] + list(res) for b in [0] + list(res)]
    vals += [pb.e[i] for i in [0] + list(res)] + [pb.l[i] for i in [0] + list(res)]
    vals += [pb.svc[i] for i in [0] + list(res)]
    return all(abs(x * SCALE - round(x * SCALE)) < 1e-6 for x in vals)


def pyvrp_run(pb, res, deadline, seed, offer):
    import pyvrp
    from pyvrp import SolveParams, solve
    try:
        from pyvrp import IteratedLocalSearchCallbacks, IteratedLocalSearchParams
    except ImportError:  # older versions
        IteratedLocalSearchCallbacks, IteratedLocalSearchParams = object, None

    text, locs = vrplib_text(pb, res)
    fd, path = tempfile.mkstemp(suffix=".vrp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        data = pyvrp.read(path, round_func="none")
    finally:
        os.remove(path)
    want = sorted(res)
    shift = {"k": None}

    def route_clients(r):
        """Client indices of a PyVRP route: visits() where it exists (location numbering in older versions),
        else the client activities of schedule() (0-based client numbering); convert() finds the shift."""
        v = getattr(r, "visits", None)
        if callable(v):
            try:
                return [int(x) for x in v()]
            except Exception:  # noqa: BLE001
                pass
        sch = getattr(r, "schedule", None)
        if callable(sch):
            out = []
            for act in sch():
                isc = getattr(act, "is_client", None)
                if callable(isc) and isc():
                    out.append(int(act.idx))
            return out
        return [int(x) for x in r]

    def convert(sol):
        raw = [route_clients(r) for r in sol.routes()]
        for k in ([shift["k"]] if shift["k"] is not None else [0, 1]):
            try:
                out = [[locs[v + k] for v in r] for r in raw]
            except IndexError:
                continue
            if sorted(c for r in out for c in r) == want:
                shift["k"] = k
                return out
        return None

    class Until:
        def __init__(self, t):
            self.t = t

        def __call__(self, best_cost):  # noqa: ARG002
            return time.monotonic() >= self.t

    class OnBest(IteratedLocalSearchCallbacks):
        def on_best(self, sol):
            if sol.is_feasible():
                s = convert(sol)
                if s is not None:
                    offer(s, "pyvrp")

    try:
        params = SolveParams(ils=IteratedLocalSearchParams(callbacks=OnBest()))
    except Exception:  # noqa: BLE001 - other versions: no callbacks, final answer only
        params = SolveParams()
    r = solve(data, stop=Until(deadline), seed=int(seed) % (2 ** 31), collect_stats=False, display=False,
              params=params)
    best = convert(r.best) if r.best.is_feasible() else None
    if best is not None:
        offer(best, "pyvrp-final")
    return best, int(getattr(r, "num_iterations", 0) or 0)


# ------------------------------------------------------------------------------------------- split improvement
def best_position(pb, seq, c):
    best = None
    for p in range(len(seq) + 1):
        a = 0 if p == 0 else seq[p - 1]
        b = pb.sink if p == len(seq) else seq[p]
        delta = pb.C[a][c] + pb.C[c][b] - pb.C[a][b]
        if best is not None and delta >= best[0]:
            continue
        if pb.sched_ok(seq[:p] + [c] + seq[p:]):
            best = (delta, p)
    return best


def spread(pb, routes, c, x, exclude, budget):
    """Place quantity x of customer c into routes (not indices in exclude). Mutates routes. Returns added cost, or
    None if it cannot be placed for less than budget."""
    added = 0.0
    left = x
    cap_c = min(pb.dem[c], pb.Q)
    guard = 0
    while left > TOL:
        guard += 1
        if guard > len(routes) + 2:
            return None
        best = None
        for k, r in enumerate(routes):
            if k in exclude or not r.seq:
                continue
            room = pb.Q - r.load()
            if c in r.seq:
                room = min(room, cap_c - r.q.get(c, 0))
                if room > TOL:
                    key = (0.0, -room)
                    if best is None or key < best[0]:
                        best = (key, k, None, room)
                continue
            if room <= TOL:
                continue
            bp = best_position(pb, r.seq, c)
            if bp is None:
                continue
            take = min(room, cap_c)
            key = (bp[0] / min(take, left), -take)
            if best is None or key < best[0]:
                best = (key, k, bp, take)
        if best is None:
            return None
        _, k, bp, take = best
        r = routes[k]
        y = min(take, left)
        if bp is not None:
            r.seq.insert(bp[1], c)
            added += bp[0]
        r.q[c] = r.q.get(c, 0) + y
        left -= y
        if added >= budget - EPS:
            return None
    return added


def try_eliminate(pb, routes, ai):
    A = routes[ai]
    saved = pb.seq_cost(A.seq)
    trial = [r.copy() for r in routes]
    trial[ai] = Route([], {})
    added = 0.0
    for c in sorted(A.seq, key=lambda c: -A.q.get(c, 0)):
        x = A.q.get(c, 0)
        if x <= TOL:
            continue
        a = spread(pb, trial, c, x, {ai}, saved - added)
        if a is None:
            return None
        added += a
        if added >= saved - EPS:
            return None
    return [r for r in trial if r.seq]


def try_remove_visit(pb, routes, ai, c):
    A = routes[ai]
    x = A.q.get(c, 0)
    rem = [v for v in A.seq if v != c]
    saved = pb.seq_cost(A.seq) - (pb.seq_cost(rem) if rem else 0.0)
    if saved <= EPS:
        return None
    trial = [r.copy() for r in routes]
    trial[ai] = Route(rem, {k: v for k, v in A.q.items() if k != c})
    if x > TOL:
        a = spread(pb, trial, c, x, {ai}, saved)
        if a is None:
            return None
    if sum(1 for r in trial if c in r.seq) < math.ceil(pb.dem[c] / pb.Q):
        return None
    return [r for r in trial if r.seq]


def oropt(pb, r):
    seq = r.seq
    improved = True
    while improved:
        improved = False
        base = pb.seq_cost(seq)
        for L in (1, 2, 3):
            for i in range(len(seq) - L + 1):
                seg = seq[i:i + L]
                rest = seq[:i] + seq[i + L:]
                for p in range(len(rest) + 1):
                    if p == i:
                        continue
                    cand = rest[:p] + seg + rest[p:]
                    if pb.seq_cost(cand) < base - EPS and pb.sched_ok(cand):
                        seq = cand
                        improved = True
                        break
                if improved:
                    break
            if improved:
                break
    if seq != r.seq:
        r.seq = seq
        return True
    return False


def split_improve(pb, routes, deadline, offer):
    routes = [r.copy() for r in routes if r.seq]
    stats = {"elim": 0, "visit": 0, "oropt": 0, "passes": 0}
    improved = True
    while improved and time.monotonic() < deadline:
        improved = False
        stats["passes"] += 1
        # (a) route elimination, lightest routes first
        order = sorted(range(len(routes)), key=lambda k: routes[k].load())
        for ai in order:
            if time.monotonic() > deadline:
                break
            if ai >= len(routes):
                continue
            new = try_eliminate(pb, routes, ai)
            if new is not None and total_cost(pb, new) < total_cost(pb, routes) - EPS:
                routes = new
                stats["elim"] += 1
                improved = True
                offer(routes, "split-elim")
                break
        if improved:
            continue
        # (b) visit removal by split re-insertion
        for ai in range(len(routes)):
            if time.monotonic() > deadline:
                break
            for c in list(routes[ai].seq):
                new = try_remove_visit(pb, routes, ai, c)
                if new is not None and total_cost(pb, new) < total_cost(pb, routes) - EPS:
                    routes = new
                    stats["visit"] += 1
                    improved = True
                    offer(routes, "split-visit")
                    break
            if improved:
                break
        if improved:
            continue
        # (c) intra-route or-opt
        for r in routes:
            if time.monotonic() > deadline:
                break
            if oropt(pb, r):
                stats["oropt"] += 1
                improved = True
        if improved:
            offer(routes, "oropt")
    return routes, stats


# ----------------------------------------------------------------------------------------------------- driver
def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def solve(inst, out_path, time_limit, seed=1, workers=2, t0=None):
    T0 = T_START if t0 is None else t0
    pb = Problem(inst)
    end = T0 + max(0.5, min(0.9 * time_limit, time_limit - 3.0))
    log = {"version": VERSION, "n": pb.n, "Q": pb.Q, "events": []}
    fixed, res = dedicated_and_residual(pb)
    log["dedicated_routes"] = len(fixed)
    best = {"obj": None, "routes": None, "last_write": 0.0}

    def offer_routes(routes, source, force_write=False):
        ok, why = verify(pb, routes)
        if not ok:
            log.setdefault("verify_fail", []).append([source, why])
            return False
        obj = total_cost(pb, routes)
        if best["obj"] is None or obj < best["obj"] - 1e-9:
            best["obj"], best["routes"] = obj, [r.copy() for r in routes]
            log["events"].append([round(time.monotonic() - T0, 2), source, round(obj, 3), len(routes)])
            now = time.monotonic()
            if force_write or now - best["last_write"] >= 1.0 or best["last_write"] == 0.0:
                write_json(out_path, solution_json(pb, best["routes"]))
                best["last_write"] = now
            return True
        return False

    unsplit = {"obj": None, "seqs": None}

    def offer_seqs(seqs, source):
        seqs = [list(s) for s in seqs if s]
        routes = fixed + [Route(s, {c: res[c] for c in s}) for s in seqs]
        if verify(pb, routes)[0]:
            obj = total_cost(pb, routes)
            if unsplit["obj"] is None or obj < unsplit["obj"] - 1e-9:
                unsplit["obj"], unsplit["seqs"] = obj, seqs
        return offer_routes(routes, source)

    offer_seqs([[c] for c in sorted(res)], "singletons")
    unsplit_end = T0 + 0.6 * (end - T0)
    offer_seqs(insertion(pb, res, T0 + 0.1 * (end - T0)), "insertion")
    use_pyvrp = os.environ.get("MV2_DESAUL_NOPYVRP") != "1" and bool(res) and exact_integer_copy(pb, res)
    log["pyvrp_used"] = False
    if use_pyvrp:
        child, conn = None, None
        if workers >= 2 and hasattr(os, "fork"):
            try:
                import multiprocessing as mp
                ctx = mp.get_context("fork")
                conn, cconn = ctx.Pipe(duplex=False)

                def run_child():
                    try:
                        b, it = pyvrp_run(pb, res, unsplit_end, seed + 7919, lambda s, src: None)
                        cconn.send((b, it))
                    except Exception as e:  # noqa: BLE001
                        cconn.send((None, repr(e)[:300]))
                    finally:
                        cconn.close()
                child = ctx.Process(target=run_child, daemon=True)
                child.start()
            except Exception as e:  # noqa: BLE001
                log["fork_error"] = repr(e)[:300]
                child = None
        try:
            b, it = pyvrp_run(pb, res, unsplit_end, seed, offer_seqs)
            log["pyvrp_used"] = True
            log["pyvrp_iterations"] = it
        except Exception as e:  # noqa: BLE001 - fall back to the pure-Python search
            log["pyvrp_error"] = repr(e)[:300]
        if child is not None:
            try:
                if conn.poll(max(0.2, min(3.0, end - time.monotonic() - 1.0))):
                    cb, cit = conn.recv()
                    log["child"] = cit
                    if cb is not None:
                        offer_seqs(cb, "pyvrp-child")
                else:
                    log["child"] = "no answer in time"
            except Exception as e:  # noqa: BLE001
                log["child_error"] = repr(e)[:300]
            try:
                child.terminate()
            except Exception:  # noqa: BLE001
                pass
    if not log["pyvrp_used"] and res and unsplit["seqs"] is not None:
        offer_seqs(ls_unsplit(pb, unsplit["seqs"], res, unsplit_end), "ls-unsplit")
    log["unsplit_best"] = unsplit["obj"]
    if best["routes"] is None:
        log["wall_s"] = round(time.monotonic() - T0, 3)
        log["final_objective"] = None
        return None, log
    routes, st = split_improve(pb, best["routes"], end, offer_routes)
    log["split"] = st
    offer_routes(routes, "split-final")
    if best["routes"] is not None:
        write_json(out_path, solution_json(pb, best["routes"]))
    log["final_objective"] = best["obj"]
    log["final_routes"] = len(best["routes"]) if best["routes"] else None
    log["split_customers"] = sum(1 for c in pb.customers
                                 if sum(1 for r in (best["routes"] or []) if c in r.seq) > 1)
    log["wall_s"] = round(time.monotonic() - T0, 3)
    return best["obj"], log


def main(argv=None):
    ap = argparse.ArgumentParser(description="desaulniers2010 (SDVRPTW) solver, MV2 of Munim, Inc.")
    ap.add_argument("--problem", default="desaulniers2010")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    obj, log = solve(inst, a.output, a.time_limit, a.seed, a.workers)
    if os.environ.get("MV2_DESAUL_LOG") == "1":
        try:
            write_json(a.output + ".log.json", log)
        except Exception:  # noqa: BLE001
            pass
    sys.stderr.write(json.dumps({k: log.get(k) for k in ("version", "n", "dedicated_routes", "pyvrp_used",
                                                         "unsplit_best", "split", "final_objective",
                                                         "final_routes", "split_customers", "wall_s")}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

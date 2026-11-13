"""pecin2017 (VRPTW, distance only, unlimited fleet) solver for the FrontierOR Challenge, v0.1.1.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Rules (read from the public FrontierOR benchmark's problem description and feasibility_check.py, Hugging Face
frontieror/FrontierOR, CC BY 4.0): nodes[] holds depot_source (id 0), customers (1..n) and depot_sink (id n_nodes-1);
travel cost = travel time = exact Euclidean distance (no rounding); service start T_j = max(open_j, T_i + service_i +
d_ij) with T_source = open_source; T_j <= close_j for every node including the sink; route load <= capacity; every
customer exactly once; any number of routes; objective = total distance. Output: {"objective_value", "routes":
[[0, c1, ..., n_nodes-1], ...]}.

Pipeline (each step offers its solution to the incumbent, which frontier_runtime writes atomically):
1. one route per customer (feasible whenever the instance is), written at once;
2. cheapest feasible insertion (sequential routes), then
3. PyVRP's iterated local search (pip package pyvrp, MIT) on an integer copy of the instance scaled by SCALE with
   CONSERVATIVE rounding: travel and service times rounded up, window openings rounded up, window closings rounded
   down. Every schedule PyVRP accepts is then feasible on the float data (start times only grow under the rounding),
   and every route is re-checked on the exact float data before it is offered. Distances in PyVRP are the rounded-up
   ones; the objective written is always recomputed exactly.
Without pyvrp, steps 1-2 run and the solver still writes a feasible answer.

v0.1.1 (2026-11-13) changes nothing in the method of v0.1.0. It only (a) silences PyVRP's INFO logger, (b) falls back
to PyVRP's plain solve() if the improvement callback cannot be set up, (c) reads the seed from MV2_PECIN_SEED when
set, and (d) records the installed pyvrp version from package metadata (pyvrp has no __version__).
"""
import json
import logging
import math
import os
import sys
import tempfile
import time

import frontier_runtime as R

__version__ = "0.1.1"
SCALE = 1000
TOL = 1e-5


def log(**kw):
    sys.stderr.write("pecin log " + json.dumps(kw, default=str) + "\n")


class Inst:
    def __init__(self, inst):
        pp = inst.get("problem_parameters") or {}
        nodes = sorted(inst["nodes"], key=lambda v: int(v["id"]))
        self.n_nodes = int(pp.get("n_nodes") or len(nodes))
        self.cap = float(pp.get("vehicle_capacity"))
        self.horizon = float(pp.get("planning_horizon") or 0.0)
        byid = {int(v["id"]): v for v in nodes}
        self.src = 0
        self.sink = self.n_nodes - 1
        for v in nodes:
            if v.get("type") == "depot_source":
                self.src = int(v["id"])
            elif v.get("type") == "depot_sink":
                self.sink = int(v["id"])
        self.ids = list(range(self.n_nodes))
        self.x = [0.0] * self.n_nodes
        self.y = [0.0] * self.n_nodes
        self.dem = [0.0] * self.n_nodes
        self.svc = [0.0] * self.n_nodes
        self.open = [0.0] * self.n_nodes
        self.close = [self.horizon] * self.n_nodes
        for i in self.ids:
            v = byid.get(i)
            if v is None:
                continue
            self.x[i] = float(v.get("x", 0.0))
            self.y[i] = float(v.get("y", 0.0))
            self.dem[i] = float(v.get("demand", 0) or 0)
            self.svc[i] = float(v.get("service_time", 0) or 0)
            self.open[i] = float(v.get("time_window_open", 0.0) or 0.0)
            c = v.get("time_window_close")
            self.close[i] = float(c) if c is not None else self.horizon
        self.customers = [i for i in self.ids if i not in (self.src, self.sink)
                          and (byid.get(i) is None or byid[i].get("type", "customer") == "customer")]

    def d(self, i, j):
        return math.sqrt((self.x[i] - self.x[j]) ** 2 + (self.y[i] - self.y[j]) ** 2)

    def route_ok(self, r):
        """r: customers only. Exact float check of time windows and capacity."""
        load = sum(self.dem[c] for c in r)
        if load > self.cap + TOL:
            return False
        t = self.open[self.src]
        prev = self.src
        for j in list(r) + [self.sink]:
            t = max(self.open[j], t + self.svc[prev] + self.d(prev, j))
            if t > self.close[j] + TOL:
                return False
            prev = j
        return True

    def route_cost(self, r):
        seq = [self.src] + list(r) + [self.sink]
        return sum(self.d(a, b) for a, b in zip(seq, seq[1:]))

    def solution(self, routes):
        routes = [list(r) for r in routes if r]
        obj = sum(self.route_cost(r) for r in routes)
        return obj, {"objective_value": float(obj), "routes": [[self.src] + r + [self.sink] for r in routes]}

    def valid(self, routes):
        seen = []
        for r in routes:
            if r and not self.route_ok(r):
                return False
            seen.extend(r)
        return sorted(seen) == sorted(self.customers)


def singletons(I):
    return [[c] for c in I.customers]


def insertion(I, deadline):
    """Sequential cheapest feasible insertion; seeds = farthest unrouted customer by due time."""
    left = set(I.customers)
    routes = []
    while left and time.monotonic() < deadline:
        seed = max(left, key=lambda c: (I.d(I.src, c), -I.close[c], c))
        r = [seed]
        left.discard(seed)
        while left and time.monotonic() < deadline:
            best = None
            for c in left:
                for p in range(len(r) + 1):
                    a = I.src if p == 0 else r[p - 1]
                    b = I.sink if p == len(r) else r[p]
                    delta = I.d(a, c) + I.d(c, b) - I.d(a, b)
                    if best is not None and delta >= best[0]:
                        continue
                    cand = r[:p] + [c] + r[p:]
                    if I.route_ok(cand):
                        best = (delta, c, p)
            if best is None:
                break
            _, c, p = best
            r.insert(p, c)
            left.discard(c)
        routes.append(r)
    routes.extend([c] for c in left)
    return routes


def vrplib_text(I):
    """Integer VRPLIB copy, conservative rounding (see module doc). Location 0 = depot, 1..n = I.customers."""
    locs = [I.src] + list(I.customers)
    n = len(locs)

    def dur(a, b):
        # into the depot means into the sink
        bb = I.sink if b == I.src else b
        return int(math.ceil(I.d(a, bb) * SCALE))

    lines = ["NAME: frontieror-pecin2017", "TYPE: VRPTW", "DIMENSION: %d" % n,
             "CAPACITY: %d" % int(math.floor(I.cap + TOL)), "VEHICLES: %d" % max(1, n - 1),
             "EDGE_WEIGHT_TYPE: EXPLICIT", "EDGE_WEIGHT_FORMAT: FULL_MATRIX", "NODE_COORD_SECTION"]
    for k, i in enumerate(locs):
        lines.append("%d %d %d" % (k + 1, int(round(I.x[i] * SCALE)), int(round(I.y[i] * SCALE))))
    lines.append("EDGE_WEIGHT_SECTION")
    for a in locs:
        lines.append(" ".join("0" if a == b else str(dur(a, b)) for b in locs))
    lines.append("DEMAND_SECTION")
    for k, i in enumerate(locs):
        lines.append("%d %d" % (k + 1, int(math.ceil(I.dem[i] - TOL)) if i != I.src else 0))
    lines.append("SERVICE_TIME_SECTION")
    for k, i in enumerate(locs):
        lines.append("%d %d" % (k + 1, int(math.ceil(I.svc[i] * SCALE)) if i != I.src else 0))
    lines.append("TIME_WINDOW_SECTION")
    for k, i in enumerate(locs):
        if i == I.src:
            # the depot's window: leave no earlier than the source opens, be back by the sink's close
            e, l_ = I.open[I.src], I.close[I.sink]
        else:
            e, l_ = I.open[i], I.close[i]
        lines.append("%d %d %d" % (k + 1, int(math.ceil(e * SCALE)), int(math.floor(l_ * SCALE))))
    lines += ["DEPOT_SECTION", "1", "-1", "EOF"]
    return "\n".join(lines) + "\n", locs


def pyvrp_version():
    try:
        from importlib.metadata import version
        return version("pyvrp")
    except Exception:  # noqa: BLE001
        return "?"


def pyvrp_phase(I, deadline, offer, seed=0):
    import pyvrp

    logging.getLogger("pyvrp").setLevel(logging.WARNING)
    text, locs = vrplib_text(I)
    fd, path = tempfile.mkstemp(suffix=".vrp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        data = pyvrp.read(path, round_func="none")
    finally:
        os.remove(path)

    shift = {"k": None}

    def convert(sol):
        """PyVRP visits are location indices (depot 0, clients 1..n). If a version numbers clients from 0, the
        first conversion is not a valid cover and the shifted one is used from then on."""
        raw = [[int(v) for v in (r.visits() if hasattr(r, "visits") else list(r))] for r in sol.routes()]
        for k in ([shift["k"]] if shift["k"] is not None else [0, 1]):
            try:
                out = [[locs[v + k] for v in r] for r in raw]
            except IndexError:
                continue
            if shift["k"] is not None or I.valid(out):
                shift["k"] = k
                return out
        return [[locs[v] for v in r if v < len(locs)] for r in raw]

    class Until:
        def __init__(self, t):
            self.t = t

        def __call__(self, best_cost):  # noqa: ARG002
            return time.monotonic() >= self.t

    mode = "callbacks"
    try:
        from pyvrp import IteratedLocalSearchCallbacks, IteratedLocalSearchParams, SolveParams

        class OnBest(IteratedLocalSearchCallbacks):
            def on_best(self, best):
                if best.is_feasible():
                    offer(convert(best), "pyvrp-ils")

        params = SolveParams(ils=IteratedLocalSearchParams(callbacks=OnBest()))
    except Exception as e:  # noqa: BLE001 - older/newer API: plain solve, final answer only
        log(event="no-callbacks", error=repr(e)[:200])
        params, mode = None, "plain"
    kw = {"stop": Until(deadline), "seed": int(seed) % (2 ** 31), "collect_stats": False, "display": False}
    if params is not None:
        kw["params"] = params
    res = pyvrp.solve(data, **kw)
    if res.best.is_feasible():
        offer(convert(res.best), "pyvrp-final")
    return {"iterations": int(getattr(res, "num_iterations", 0) or 0), "pyvrp": pyvrp_version(), "mode": mode,
            "index_shift": shift["k"]}


def solve(inst, clock, inc, args):
    t0 = time.monotonic()
    I = Inst(inst)
    seed = int(os.environ.get("MV2_PECIN_SEED", getattr(args, "seed", 0) or 0))
    info = {"version": __version__, "n_customers": len(I.customers), "n_nodes": I.n_nodes, "seed": seed}
    stats = {"offers": 0, "rejected": 0}

    def offer(routes, source):
        stats["offers"] += 1
        if not I.valid(routes):
            stats["rejected"] += 1
            log(event="invalid-candidate", source=source)
            return False
        obj, sol = I.solution(routes)
        took = inc.offer(obj, sol, source)
        if took:
            log(event="incumbent", source=source, obj=round(obj, 4), t=round(time.monotonic() - t0, 2),
                routes=len([r for r in routes if r]))
        return took

    offer(singletons(I), "singletons")
    offer(insertion(I, time.monotonic() + clock.share(0.15)), "insertion")
    info["insertion_obj"] = inc.value
    if clock.remaining() > 1.0:
        try:
            info.update(pyvrp_phase(I, time.monotonic() + clock.remaining(), offer, seed))
        except Exception as e:  # noqa: BLE001 - keep the incumbent
            info["pyvrp_error"] = repr(e)[:300]
    info.update(stats, best=inc.value, time=round(time.monotonic() - t0, 2),
                sources=[h[2] for h in inc.history][-5:],
                first_pyvrp_s=next((h[0] for h in inc.history if h[2].startswith("pyvrp")), None))
    log(event="final", **info)
    if os.environ.get("MV2_PECIN_LOG") == "1":
        try:
            with open(args.output + ".log.json", "w", encoding="utf-8") as f:
                json.dump(info, f, default=str)
        except Exception:  # noqa: BLE001 - the log is optional
            pass


if __name__ == "__main__":
    R.main(solve, "min")

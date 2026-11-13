"""Independent checker for pecin2017 (VRPTW) solutions. Shares no code with the solver.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Follows the rules of the official feasibility_check.py of the FrontierOR benchmark (Hugging Face
frontieror/FrontierOR, CC BY 4.0) as read on 2026-11-11: routes are lists of node ids from 0 to n_nodes-1; every
customer exactly once; depots only at the ends; load (depots included) <= capacity + 1e-5; service start
T = max(open, previous start + previous service + Euclidean distance), first node at its own opening, and
T <= close + 1e-5 at every node including the sink; objective = sum of exact Euclidean distances, and a stated value
off by more than max(1e-3, 1e-3 |true|) is rejected. Copied unchanged in its rules from vrptw/pecin_check.py
(2026-11-11).
"""
import json
import math
import sys

TOL = 1e-5


def check(instance, sol):
    try:
        return _check(instance, sol)
    except Exception as e:  # noqa: BLE001
        return {"feasible": False, "objective": None, "reason": "malformed: %r" % (e,)}


def _check(instance, sol):
    pp = instance["problem_parameters"]
    n_nodes = int(pp["n_nodes"])
    n_cust = int(pp["n_customers"])
    cap = float(pp["vehicle_capacity"])
    horizon = float(pp.get("planning_horizon") or 0.0)
    node = {int(v["id"]): v for v in instance["nodes"]}
    sink = n_nodes - 1

    def get(i, key, default):
        v = node.get(i)
        if v is None or v.get(key) is None:
            return default
        return float(v[key])

    def dist(i, j):
        return math.hypot(get(i, "x", 0.0) - get(j, "x", 0.0), get(i, "y", 0.0) - get(j, "y", 0.0))

    routes = sol.get("routes")
    ov = sol.get("objective_value")
    if not isinstance(routes, list) or isinstance(ov, bool) or not isinstance(ov, (int, float)) or \
            not math.isfinite(ov):
        return {"feasible": False, "objective": None, "reason": "schema"}
    count = {}
    total = 0.0
    for r in routes:
        if not isinstance(r, list) or len(r) < 2 or r[0] != 0 or r[-1] != sink:
            return {"feasible": False, "objective": None, "reason": "route ends %r" % (r,)}
        for v in r:
            if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v >= n_nodes:
                return {"feasible": False, "objective": None, "reason": "bad node %r" % (v,)}
        if any(v in (0, sink) for v in r[1:-1]):
            return {"feasible": False, "objective": None, "reason": "depot inside a route"}
        load = sum(get(v, "demand", 0.0) for v in r)
        if load > cap + TOL:
            return {"feasible": False, "objective": None, "reason": "load %s > %s" % (load, cap)}
        t = get(r[0], "time_window_open", 0.0)
        for a, b in zip(r, r[1:]):
            t = max(get(b, "time_window_open", 0.0), t + get(a, "service_time", 0.0) + dist(a, b))
            if t > get(b, "time_window_close", horizon) + TOL:
                return {"feasible": False, "objective": None, "reason": "late at %d (%.6f)" % (b, t)}
            total += dist(a, b)
        for v in r[1:-1]:
            count[v] = count.get(v, 0) + 1
    for c in range(1, n_cust + 1):
        if count.get(c, 0) != 1:
            return {"feasible": False, "objective": None, "reason": "customer %d visited %d times" % (c, count.get(c, 0))}
    if abs(ov - total) > max(1e-3, 1e-3 * abs(total)):
        return {"feasible": False, "objective": total, "reason": "objective %s != %s" % (ov, total)}
    return {"feasible": True, "objective": total, "reason": ""}


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        inst = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        s = json.load(f)
    print(json.dumps(check(inst, s)))

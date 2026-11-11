"""cordeau2006 (Dial-a-Ride) solver v0.3.0: the v0.2.0 search, with its output written the way the official checker reads it.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Folder layout (one contest folder): solve.py (this file) + darp_core.py (= v0.2.0 darp/cordeau2006/solve.py of
github.com/munimtechnologies/frontieror-routing, unchanged). This file runs the core as a child process with a
slightly shorter limit and then rewrites its output.

What the official FrontierOR feasibility_check.py for cordeau2006 requires (Hugging Face frontieror/FrontierOR,
CC BY 4.0; read 2026-11-11) and v0.2.0 did not do:
1. `routes` must hold exactly one route for every vehicle k = 0..num_vehicles-1 ("Route map must contain exactly one
   route for every vehicle"), and every vehicle needs one arc out of node 0 and one into node 2n+1. An unused vehicle
   is therefore the route [0, 2n+1], with its own depot_start_k / depot_end_k service times. v0.2.0 left unused
   vehicles out, so a plan with fewer routes than vehicles was rejected.
2. `ride_times` keys are the pickup node ids 1..n (the drop-off of pickup i is node n+i). v0.2.0 keyed them by the
   node's user_id field, which is only right when user_id equals the pickup node id.
3. The objective is the Euclidean length of every arc of every route, so the 0 -> 2n+1 arc of an unused vehicle is
   counted too (zero when both depots share a location).
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time

_T0 = time.monotonic()
HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "darp_core.py")
VERSION = "0.3.0"
TOL = 1e-9


def _dist(nodes, a, b):
    return math.sqrt((float(nodes[a]["x"]) - float(nodes[b]["x"])) ** 2 +
                     (float(nodes[a]["y"]) - float(nodes[b]["y"])) ** 2)


def empty_schedule(data, nodes):
    """(depot_start, depot_end) for an unused vehicle, inside both depot windows and the route-duration limit."""
    n = int(data["num_users"])
    dest = 2 * n + 1
    T = float(data["maximum_route_duration"])
    o, d = nodes[0], nodes[dest]
    travel = float(o.get("service_duration", 0.0)) + _dist(nodes, 0, dest)
    s = float(o["earliest_time"])
    e = max(float(d["earliest_time"]), s + travel)
    if e - s > T + TOL:  # the destination window opens late: leave the origin later
        s = min(float(o["latest_time"]), e - T)
        e = max(float(d["earliest_time"]), s + travel)
    return s, e


def normalise(data, sol):
    """Rewrite a v0.2.0 solution so it meets points 1-3 of the module docstring. Visits and times are unchanged."""
    n = int(data["num_users"])
    K = int(data["num_vehicles"])
    dest = 2 * n + 1
    nodes = {int(r["node_id"]): r for r in data["nodes"]}
    st = dict(sol.get("service_times") or {})
    old = sol.get("routes") or {}
    keys = sorted(old, key=lambda s: int(s))
    used = [(k, [int(v) for v in old[k]]) for k in keys if len(old[k]) > 2]
    routes, new_st = {}, {}
    for i in range(1, 2 * n + 1):
        if str(i) in st:
            new_st[str(i)] = float(st[str(i)])
    for v, (k, r) in enumerate(used):
        routes[str(v)] = r
        s0, e0 = st.get("depot_start_%s" % k), st.get("depot_end_%s" % k)
        if s0 is None or e0 is None:
            s0, e0 = empty_schedule(data, nodes)
        new_st["depot_start_%d" % v] = float(s0)
        new_st["depot_end_%d" % v] = float(e0)
    for v in range(len(used), K):
        s0, e0 = empty_schedule(data, nodes)
        routes[str(v)] = [0, dest]
        new_st["depot_start_%d" % v] = s0
        new_st["depot_end_%d" % v] = e0
    ride = {}
    for p in range(1, n + 1):
        a, b = str(p), str(n + p)
        if a in new_st and b in new_st:
            ride[a] = new_st[b] - (new_st[a] + float(nodes[p].get("service_duration", 0.0)))
    total = sum(_dist(nodes, a, b) for r in routes.values() for a, b in zip(r[:-1], r[1:]))
    out = dict(sol)
    out.update(objective_value=total, routes=routes, service_times=new_st, ride_times=ride)
    return out


def _write(path, obj):
    tmp = os.path.join(os.path.dirname(os.path.abspath(path)) or ".", ".%s.tmp" % os.path.basename(path))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="cordeau2006")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=float(os.environ.get("SANDBOX_TIMEOUT_S", "60") or 60))
    ap.add_argument("--seed", type=int, default=20261109)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    limit = float(a.time_limit)
    core_limit = max(1.0, limit - max(2.5, 0.05 * limit))
    cmd = [sys.executable, CORE, "--problem", a.problem, "--instance", a.instance, "--output", a.output,
           "--time-limit", "%.3f" % core_limit, "--seed", str(a.seed), "--workers", str(a.workers)]
    hard = max(0.5, limit - 1.5 - (time.monotonic() - _T0))
    try:
        p = subprocess.run(cmd, cwd=HERE, timeout=hard, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        sys.stderr.write((p.stderr or "")[-4000:])
    except subprocess.TimeoutExpired:
        sys.stderr.write("core stopped at the wrapper's hard limit\n")
    if not os.path.exists(a.output):
        return 1
    try:
        with open(a.instance, encoding="utf-8") as f:
            data = json.load(f)
        with open(a.output, encoding="utf-8") as f:
            sol = json.load(f)
        fixed = normalise(data, sol)
        _write(a.output, fixed)
        sys.stderr.write("DARP_WRAPPER %s\n" % json.dumps({"version": VERSION, "routes_in": len(sol.get("routes") or {}),
                                                           "routes_out": len(fixed["routes"]),
                                                           "objective": fixed["objective_value"]}))
    except Exception as e:  # noqa: BLE001 - keep the core's own output
        sys.stderr.write("normalise failed: %r\n" % (e,))
    return 0


if __name__ == "__main__":
    sys.exit(main())

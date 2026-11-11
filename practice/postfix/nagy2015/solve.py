"""nagy2015 (VRP with divisible deliveries and pickups) solver v3: the v2 search, with its output made to meet one
rule of the official checker that v2 did not know.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Folder layout (one contest folder): solve.py (this file) + nagy_core.py (= v2 vrpddp/nagy2015/solve.py of
github.com/munimtechnologies/frontieror-routing, unchanged). This file runs the core as a child process with a
slightly shorter limit and then rewrites its output.

The official FrontierOR feasibility_check.py for nagy2015 (Hugging Face frontieror/FrontierOR, CC BY 4.0; read
2026-11-11), constraint 15: x_(n+i, i) = 0, i.e. a route may not go straight from customer i's backhaul node n+i to
the same customer's linehaul node i. v2 treats the two nodes as one place (distance 0) and may visit them in either
order. Here every such pair is swapped to i, n+i: same place, so the distance is unchanged, and the load is lower
between the two visits (the delivery is dropped before the pickup is loaded), so capacity still holds. Nothing else
changes. routes_detailed is permuted the same way.
"""
import argparse
import json
import os
import subprocess
import sys
import time

_T0 = time.monotonic()
HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "nagy_core.py")
VERSION = "3"


def _detail(data, node):
    n = int(data["num_customers"])
    cust = {int(c["id"]): c for c in data["customers"]}
    if node == 0:
        return {"node": 0, "role": "depot", "customer": 0, "quantity": 0}
    if node <= n:
        return {"node": node, "role": "linehaul", "customer": node, "quantity": cust[node]["delivery_demand"]}
    return {"node": node, "role": "backhaul", "customer": node - n, "quantity": cust[node - n]["pickup_demand"]}


def normalise(data, sol):
    """Return (solution, swaps). Swaps every adjacent (n+i, i) to (i, n+i); recomputes the objective exactly as the
    official checker does (distance_matrix over original customer ids)."""
    n = int(data["num_customers"])
    D = data["distance_matrix"]
    det = sol.get("routes_detailed")
    routes, details, swaps = [], [], 0
    for ri, r0 in enumerate(sol.get("routes") or []):
        r = [int(v) for v in r0]
        d = None
        if isinstance(det, list) and ri < len(det) and isinstance(det[ri], list) and len(det[ri]) == len(r):
            d = list(det[ri])
        changed = True
        while changed:
            changed = False
            for t in range(1, len(r) - 2):
                a, b = r[t], r[t + 1]
                if a > n and b == a - n:
                    r[t], r[t + 1] = b, a
                    if d is not None:
                        d[t], d[t + 1] = d[t + 1], d[t]
                    swaps += 1
                    changed = True
        routes.append(r)
        details.append(d if d is not None else [_detail(data, v) for v in r])

    def orig(v):
        return v if v <= n else v - n

    total = float(sum(float(D[orig(a)][orig(b)]) for r in routes for a, b in zip(r[:-1], r[1:])))
    out = dict(sol)
    out.update(objective_value=total, routes=routes, routes_detailed=details)
    return out, swaps


def _write(path, obj):
    tmp = os.path.join(os.path.dirname(os.path.abspath(path)) or ".", ".%s.tmp" % os.path.basename(path))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="nagy2015")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=float(os.environ.get("SANDBOX_TIMEOUT_S", "60") or 60))
    a, rest = ap.parse_known_args(argv)
    limit = float(a.time_limit)
    core_limit = max(1.0, limit - max(2.5, 0.05 * limit))
    cmd = [sys.executable, CORE, "--problem", a.problem, "--instance", a.instance, "--output", a.output,
           "--time-limit", "%.3f" % core_limit] + list(rest)
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
        if sol.get("routes"):
            fixed, swaps = normalise(data, sol)
            _write(a.output, fixed)
            sys.stderr.write("NAGY_WRAPPER %s\n" % json.dumps({"version": VERSION, "swaps": swaps,
                                                               "objective": fixed["objective_value"]}))
    except Exception as e:  # noqa: BLE001 - keep the core's own output
        sys.stderr.write("normalise failed: %r\n" % (e,))
    return 0


if __name__ == "__main__":
    sys.exit(main())

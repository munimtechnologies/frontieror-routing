"""clash_probe: which open-source solvers can share one Python process in the FrontierOR Challenge image?

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python clash_probe.py --out-dir /out

The FrontierOR Challenge sandbox lists highspy 1.15.1 and ortools 9.15.6755 (plus scipy). On Linux both highspy and
OR-Tools >= 9.14 ship a HiGHS shared library under the same name; google/or-tools issue 5246 (open) reports that
importing highspy first breaks OR-Tools' GLOP/PDLP. This probe runs every ordered pair of {highspy, CP-SAT, GLOP,
routing, scipy HiGHS} in a fresh process, solving a tiny model with each, and records which step fails and how.
Writes OUT/clash/{clash.json, clash.md}.
"""
import argparse
import itertools
import json
import os
import subprocess
import sys
import time

STEPS = {
    "highspy": (
        "import highspy, numpy as np\n"
        "h = highspy.Highs(); h.setOptionValue('output_flag', False)\n"
        "h.addVar(0, 4); h.addVar(0, 4)\n"
        "h.changeColCost(0, -1.0); h.changeColCost(1, -2.0)\n"
        "h.addRow(-highspy.kHighsInf, 5.0, 2, np.array([0, 1], dtype=np.int32), np.array([1.0, 1.0]))\n"
        "h.run(); v = h.getInfo().objective_function_value\n"
        "assert abs(v - (-9.0)) < 1e-6, v\n"),
    "cpsat": (
        "from ortools.sat.python import cp_model\n"
        "m = cp_model.CpModel(); x = m.new_int_var(0, 4, 'x'); y = m.new_int_var(0, 4, 'y')\n"
        "m.add(x + y <= 5); m.maximize(x + 2 * y)\n"
        "s = cp_model.CpSolver(); s.parameters.num_workers = 1; st = s.solve(m)\n"
        "assert st == cp_model.OPTIMAL and s.objective_value == 9, (st, s.objective_value)\n"),
    "glop": (
        "from ortools.linear_solver import pywraplp\n"
        "s = pywraplp.Solver.CreateSolver('GLOP'); assert s is not None, 'GLOP not created'\n"
        "x = s.NumVar(0, 4, 'x'); y = s.NumVar(0, 4, 'y'); s.Add(x + y <= 5); s.Maximize(x + 2 * y)\n"
        "assert s.Solve() == s.OPTIMAL and abs(s.Objective().Value() - 9) < 1e-6\n"),
    "routing": (
        "from ortools.constraint_solver import pywrapcp, routing_enums_pb2\n"
        "D = [[0, 2, 9, 10], [1, 0, 6, 4], [15, 7, 0, 8], [6, 3, 12, 0]]\n"
        "man = pywrapcp.RoutingIndexManager(4, 1, 0); r = pywrapcp.RoutingModel(man)\n"
        "cb = r.RegisterTransitCallback(lambda i, j: D[man.IndexToNode(i)][man.IndexToNode(j)])\n"
        "r.SetArcCostEvaluatorOfAllVehicles(cb); p = pywrapcp.DefaultRoutingSearchParameters()\n"
        "p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC\n"
        "sol = r.SolveWithParameters(p); assert sol is not None and sol.ObjectiveValue() >= 21, "
        "sol and sol.ObjectiveValue()\n"),
    "scipy_milp": (
        "import numpy as np\n"
        "from scipy.optimize import milp, LinearConstraint, Bounds\n"
        "r = milp(c=np.array([-1.0, -2.0]), constraints=LinearConstraint(np.array([[1.0, 1.0]]), -np.inf, 5.0), "
        "integrality=np.ones(2), bounds=Bounds(0, 4))\n"
        "assert r.success and abs(r.fun + 9) < 1e-6, r\n"),
}


def run(order, timeout=120):
    code = ["import json, sys, traceback", "done = []"]
    for name in order:
        body = STEPS[name].replace("\n", "\n    ")
        code.append("try:\n    %s\n    done.append(%r)\nexcept BaseException as e:\n"
                    "    print(json.dumps({'ok': done, 'failed': %r, 'error': repr(e)[:500]}))\n"
                    "    sys.exit(0)" % (body.rstrip(), name, name))
    code.append("print(json.dumps({'ok': done, 'failed': None, 'error': None}))")
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, "-c", "\n".join(code)], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"order": list(order), "result": "timeout"}
    last = [x for x in p.stdout.splitlines() if x.startswith("{")]
    row = {"order": list(order), "exit": p.returncode, "seconds": round(time.time() - t0, 2)}
    if last:
        row.update(json.loads(last[-1]))
    else:
        row["failed"] = "process"
        row["error"] = (p.stderr or "")[-500:]
    return row


def versions():
    out = {"python": sys.version.split()[0]}
    try:
        from importlib.metadata import version
    except ImportError:  # pragma: no cover
        return out
    for dist in ("highspy", "ortools", "scipy", "numpy"):
        try:
            out[dist] = version(dist)
        except Exception as e:  # noqa: BLE001
            out[dist] = "missing (%s)" % type(e).__name__
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    out = os.path.join(a.out_dir, "clash")
    os.makedirs(out, exist_ok=True)
    rows = [run((s,)) for s in STEPS]
    rows += [run(pair) for pair in itertools.permutations(STEPS, 2)]
    res = {"versions": versions(), "platform": sys.platform, "rows": rows,
           "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with open(os.path.join(out, "clash.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    lines = ["# Solver import-order probe (FrontierOR image)", "",
             "Versions: `%s`, platform %s, %s. Each row is a fresh Python process that solves a tiny model with each "
             "step in order. Made with AI agents working in MV2's name (MV2 of Munim, Inc.)." % (
                 json.dumps(res["versions"]), sys.platform, res["at"]), "",
             "| order | result | error |", "|---|---|---|"]
    for r in rows:
        ok = r.get("failed") is None and r.get("result") != "timeout"
        err = (r.get("error") or "").replace("|", "/").replace("\n", " ")[:160]
        lines.append("| %s | %s | %s |" % (" then ".join(r["order"]),
                                           "ok" if ok else "FAILS at %s" % (r.get("failed") or r.get("result")),
                                           err))
    with open(os.path.join(out, "clash.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

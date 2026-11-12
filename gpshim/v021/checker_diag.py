"""Run a FrontierOR task's official checker on our census output AND on the benchmark's stored Gurobi solution, and
record exit code, stdout and stderr, so a checker that exits with an error can be told apart from a real rejection.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python checker_diag.py --data-dir /data/hf --scratch /tmp/gpshim --out /out/gpshim021/checker_diag.json \
        --cases adulyasak2015:tiny he2020:tiny kobayashi2021:tiny

Files used (all already downloaded by gpshim_census.py into the data volume):
  <data>/tasks/<slug>/feasibility_check.py, instance/<instance>.json, gurobi_solution/<solution>.json
  <scratch>/work/<slug>/<case>.solution.json (the census output)
"""
import argparse
import json
import os
import subprocess
import sys

FILES = {"tiny": ("tiny_instance.json", "tiny_solution.json"),
         "large_1": ("large_instance_1.json", "large_solution_1.json")}


def check(checker, ip, sp, rp):
    if not os.path.exists(sp):
        return {"solution_missing": True}
    if os.path.exists(rp):
        os.remove(rp)
    try:
        p = subprocess.run([sys.executable, checker, "--instance_path", ip, "--solution_path", sp, "--result_path", rp],
                           capture_output=True, text=True, timeout=600, cwd=os.path.dirname(rp))
    except subprocess.TimeoutExpired:
        return {"exit": "timeout"}
    out = {"exit": p.returncode, "stdout_tail": p.stdout[-1500:], "stderr_tail": p.stderr[-1500:]}
    if os.path.exists(rp):
        try:
            with open(rp, encoding="utf-8") as f:
                r = json.load(f)
            out["feasible"] = r.get("feasible")
            out["violated"] = r.get("violated_constraints")
            out["violations"] = str(r.get("violations"))[:600]
        except ValueError as e:
            out["result_error"] = repr(e)[:200]
    else:
        out["result_written"] = False
    try:
        with open(sp, encoding="utf-8") as f:
            sol = json.load(f)
        out["objective_value"] = sol.get("objective_value") if isinstance(sol, dict) else None
        out["solution_keys"] = sorted(sol)[:30] if isinstance(sol, dict) else str(type(sol))
    except Exception as e:  # noqa: BLE001
        out["solution_error"] = repr(e)[:200]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--scratch", default="/tmp/gpshim")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", nargs="+", required=True)
    a = ap.parse_args(argv)
    res = []
    for spec in a.cases:
        slug, case = spec.split(":")
        inst, sol = FILES[case]
        task = os.path.join(a.data_dir, "tasks", slug)
        checker = os.path.join(task, "feasibility_check.py")
        ip = os.path.join(task, "instance", inst)
        work = os.path.join(a.scratch, "diag", slug)
        os.makedirs(work, exist_ok=True)
        row = {"slug": slug, "case": case}
        if not (os.path.exists(checker) and os.path.exists(ip)):
            row["missing"] = [p for p in (checker, ip) if not os.path.exists(p)]
        else:
            row["ours"] = check(checker, ip, os.path.join(a.scratch, "work", slug, case + ".solution.json"),
                                os.path.join(work, case + ".ours.result.json"))
            row["gurobi"] = check(checker, ip, os.path.join(task, "gurobi_solution", sol),
                                  os.path.join(work, case + ".gurobi.result.json"))
        res.append(row)
        print("diag", slug, case, json.dumps({k: (v.get("exit"), v.get("feasible")) for k, v in row.items()
                                              if isinstance(v, dict)}), flush=True)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

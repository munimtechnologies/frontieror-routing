"""bodur2017 (SCFLP) solver on the public FrontierOR instances, checked by the official checker.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Downloads the bodur2017 task from the FrontierOR benchmark on Hugging Face (frontieror/FrontierOR, CC BY 4.0) at
one pinned revision: tiny_instance + large_instance_1..5, the Gurobi reference solutions and feasibility_check.py.
For every instance:
- runs our solver the contest way (kit/harness.py, subprocess, --time-limit 60) and checks it with our checker;
- runs the official feasibility_check.py on the same solution file;
- takes the Gurobi solution's objective_value as the reference, re-scores the Gurobi solution with our checker and
  with the official checker, and scores ours as min(2, ref/obj).
Writes /out/scflp-real/{results.json, results.md, rows.jsonl, manifest.json}.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOLVER_DIR = os.path.join(HERE, "bodur2017")
for p in (os.path.join(ROOT, "kit"), HERE, SOLVER_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import frontieror_hf as HF  # noqa: E402
import harness as H  # noqa: E402
import scflp_check  # noqa: E402

SLUG = "bodur2017"
NAMES = [("tiny", "tiny_instance.json", "tiny_solution.json")] + [
    ("large_%d" % k, "large_instance_%d.json" % k, "large_solution_%d.json" % k) for k in range(1, 6)]


def official(checker, inst_path, sol_path, res_path):
    p = subprocess.run([sys.executable, checker, "--instance_path", inst_path, "--solution_path", sol_path,
                        "--result_path", res_path], capture_output=True, text=True, timeout=600,
                       cwd=os.path.dirname(res_path))
    out = {"exit": p.returncode, "stdout_tail": p.stdout[-400:], "stderr_tail": p.stderr[-400:]}
    if os.path.exists(res_path):
        with open(res_path, encoding="utf-8") as f:
            r = json.load(f)
        out.update(feasible=r.get("feasible"), violated=r.get("violated_constraints"),
                   violations=str(r.get("violations"))[:600])
    return out


def size_info(inst):
    return {"F": inst.get("num_facilities"), "m": inst.get("num_customers"), "S": inst.get("num_scenarios"),
            "cf": inst.get("capacity_factor"), "var": inst.get("variance_level")}


def run(a):
    out = os.path.join(a.out_dir, "scflp-real")
    work = os.path.join(out, "work")
    os.makedirs(work, exist_ok=True)
    man = HF.task(SLUG, a.hf_dir)
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1)
    tdir = os.path.join(a.hf_dir, "tasks", SLUG)
    checker = os.path.join(tdir, "feasibility_check.py")
    solve_py = os.path.join(SOLVER_DIR, "solve.py")
    rows_p = os.path.join(out, "rows.jsonl")
    done = set()
    if os.path.exists(rows_p):
        with open(rows_p, encoding="utf-8") as f:
            done = {json.loads(line)["name"] for line in f if line.strip()}
    hb = H.Heartbeat()
    for name, ifile, sfile in NAMES:
        if name in done:
            continue
        ip = os.path.join(tdir, "instance", ifile)
        gp = os.path.join(tdir, "gurobi_solution", sfile)
        if not os.path.exists(ip):
            print("missing", ip, flush=True)
            continue
        with open(ip, encoding="utf-8") as f:
            inst = json.load(f)
        ref = None
        gref = {}
        if os.path.exists(gp):
            with open(gp, encoding="utf-8") as f:
                gsol = json.load(f)
            ref = gsol.get("objective_value")
            g = scflp_check.check(inst, gsol)
            gref = {"gurobi_stated": ref, "gurobi_ours_feasible": g["feasible"], "gurobi_ours_objective":
                    g.get("objective"), "gurobi_ours_reason": g.get("reason", ""),
                    "gurobi_open": len(gsol.get("open_facilities") or [])}
            o = official(checker, ip, gp, os.path.join(work, name + ".gurobi.result.json"))
            gref.update({"gurobi_official_feasible": o.get("feasible"), "gurobi_official_violated": o.get("violated")})
        row = H.evaluate_case({"name": name, "instance_path": ip, "reference": ref}, solve_py, SLUG, a.time_limit,
                              scflp_check.check, "min", work, hb=hb)
        row.update(size_info(inst))
        row.update(gref)
        sp = os.path.join(work, name + ".solution.json")
        if os.path.exists(sp):
            row["solution_bytes"] = os.path.getsize(sp)
            o = official(checker, ip, sp, os.path.join(work, name + ".result.json"))
            row.update({"official_feasible": o.get("feasible"), "official_violated": o.get("violated"),
                        "official_violations": o.get("violations"), "official_exit": o.get("exit")})
            with open(sp, encoding="utf-8") as f:
                ours = json.load(f)
            row["open"] = len(ours.get("open_facilities") or [])
            row["ours_feasible"] = scflp_check.check(inst, ours)["feasible"]
        with open(rows_p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print("real", name, row["status"], row.get("objective"), ref, row.get("score"), row.get("official_feasible"),
              row["wall_s"], flush=True)
    hb.stop()
    rows = []
    with open(rows_p, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    large = [r for r in rows if r["name"].startswith("large")]
    tally = H.summarise(rows, a.time_limit) if rows else {}
    tally.update({
        "revision": man.get("revision"),
        "R1_official_feasible": sum(1 for r in rows if r.get("official_feasible") is True),
        "R2_large_mean_score": round(sum(r["score"] for r in large) / len(large), 6) if large else None,
        "R3_checkers_agree": sum(1 for r in rows if r.get("official_feasible") is not None and
                                 bool(r.get("official_feasible")) == bool(r.get("ours_feasible"))) +
        sum(1 for r in rows if r.get("gurobi_official_feasible") is not None and
            bool(r.get("gurobi_official_feasible")) == bool(r.get("gurobi_ours_feasible"))),
        "R3_comparisons": sum(1 for r in rows if r.get("official_feasible") is not None) +
        sum(1 for r in rows if r.get("gurobi_official_feasible") is not None),
        "R4_large_at_or_better_than_gurobi": sum(1 for r in large if r.get("score", 0) >= 1.0 - 1e-9),
    })
    intro = ("bodur2017 (SCFLP) solver v0.1.0 on the public FrontierOR instances (Hugging Face frontieror/FrontierOR, "
             "revision %s, CC BY 4.0), %ss per instance, checked by our checker and by the official "
             "feasibility_check.py; reference = the Gurobi solution's objective_value. Made with AI agents working "
             "in MV2's name (MV2 of Munim, Inc.)." % (man.get("revision"), a.time_limit))
    H.write_report(out, "SCFLP on the public FrontierOR instances", intro, rows, tally,
                   extra_cols=("F", "m", "S", "cf", "var", "open", "gurobi_open", "official_feasible",
                               "official_violated", "gurobi_ours_objective", "gurobi_official_feasible",
                               "solution_bytes"))
    print("tally", json.dumps(tally), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    a = ap.parse_args()
    run(a)


if __name__ == "__main__":
    main()

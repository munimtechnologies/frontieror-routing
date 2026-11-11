"""frontieror_real: run a FrontierOR Main-track solver on one task's public instances, with the official checker.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

For a task SLUG of the FrontierOR benchmark (Hugging Face frontieror/FrontierOR, CC BY 4.0), downloaded at one pinned
revision by frontieror_hf.task, and for each of tiny_instance + large_instance_1..5:
- runs solve.py the contest way (harness.evaluate_case: subprocess, --time-limit T, host-pause detection) and checks
  the output with OUR checker (a function instance, solution -> {"feasible", "objective", "reason"});
- runs the official feasibility_check.py on the same file;
- reference = the Gurobi solution's objective_value; the Gurobi solution is re-checked by both checkers;
- records the last line of the Gurobi log if there is one.
Writes OUT/rows.jsonl (one line per instance as it finishes), results.json, results.md, manifest.json.

  run_task(slug, solve_py, checker, sense, hf_dir, out, time_limit, size_info=None, title="")
"""
import json
import os
import subprocess
import sys

import frontieror_hf as HF
import harness as H

CASES = [("tiny", "tiny_instance.json", "tiny_solution.json", "tiny_log.jsonl")] + [
    ("large_%d" % k, "large_instance_%d.json" % k, "large_solution_%d.json" % k, "large_log_%d.jsonl" % k)
    for k in range(1, 6)]


def official(checker_py, inst_path, sol_path, res_path):
    p = subprocess.run([sys.executable, checker_py, "--instance_path", inst_path, "--solution_path", sol_path,
                        "--result_path", res_path], capture_output=True, text=True, timeout=600,
                       cwd=os.path.dirname(res_path))
    out = {"exit": p.returncode, "stderr_tail": p.stderr[-400:]}
    if os.path.exists(res_path):
        with open(res_path, encoding="utf-8") as f:
            r = json.load(f)
        out.update(feasible=r.get("feasible"), violated=r.get("violated_constraints"),
                   violations=str(r.get("violations"))[:600])
    return out


def log_tail(path):
    if not os.path.exists(path):
        return None
    last, n = None, 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
                try:
                    last = json.loads(line)
                except ValueError:
                    last = {"raw": line.strip()[:300]}
    return {"lines": n, "last": last}


def run_task(slug, solve_py, checker, sense, hf_dir, out, time_limit, size_info=None, title="", intro_extra=""):
    work = os.path.join(out, "work")
    os.makedirs(work, exist_ok=True)
    man = HF.task(slug, hf_dir)
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1)
    tdir = os.path.join(hf_dir, "tasks", slug)
    checker_py = os.path.join(tdir, "feasibility_check.py")
    rows_p = os.path.join(out, "rows.jsonl")
    done = set()
    if os.path.exists(rows_p):
        with open(rows_p, encoding="utf-8") as f:
            done = {json.loads(line)["name"] for line in f if line.strip()}
    hb = H.Heartbeat()
    for name, ifile, sfile, lfile in CASES:
        if name in done:
            continue
        ip = os.path.join(tdir, "instance", ifile)
        gp = os.path.join(tdir, "gurobi_solution", sfile)
        if not os.path.exists(ip):
            print("missing", ip, flush=True)
            continue
        with open(ip, encoding="utf-8") as f:
            inst = json.load(f)
        ref, gref = None, {}
        if os.path.exists(gp):
            with open(gp, encoding="utf-8") as f:
                gsol = json.load(f)
            ref = gsol.get("objective_value")
            g = checker(inst, gsol)
            gref = {"gurobi_ours_feasible": g.get("feasible"), "gurobi_ours_objective": g.get("objective"),
                    "gurobi_ours_reason": g.get("reason", "")}
            o = official(checker_py, ip, gp, os.path.join(work, name + ".gurobi.result.json"))
            gref.update(gurobi_official_feasible=o.get("feasible"), gurobi_official_violated=o.get("violated"))
        gref["gurobi_log"] = log_tail(os.path.join(tdir, "gurobi_solution_log", lfile))
        row = H.evaluate_case({"name": name, "instance_path": ip, "reference": ref}, solve_py, slug, time_limit,
                              checker, sense, work, hb=hb)
        if size_info:
            try:
                row.update(size_info(inst))
            except Exception as e:  # noqa: BLE001
                row["size_info_error"] = repr(e)
        row.update(gref)
        sp = os.path.join(work, name + ".solution.json")
        if os.path.exists(sp):
            o = official(checker_py, ip, sp, os.path.join(work, name + ".result.json"))
            row.update(official_feasible=o.get("feasible"), official_violated=o.get("violated"),
                       official_violations=o.get("violations"), official_exit=o.get("exit"))
            with open(sp, encoding="utf-8") as f:
                row["ours_feasible"] = checker(inst, json.load(f)).get("feasible")
        with open(rows_p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        print("real", slug, name, row["status"], row.get("objective"), ref, row.get("score"),
              row.get("official_feasible"), row["wall_s"], flush=True)
    hb.stop()
    with open(rows_p, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    large = [r for r in rows if r["name"].startswith("large")]
    tally = H.summarise(rows, time_limit) if rows else {}
    tally.update({
        "task": slug,
        "revision": man.get("revision"),
        "official_feasible": sum(1 for r in rows if r.get("official_feasible") is True),
        "checkers_agree": sum(1 for r in rows if r.get("official_feasible") is not None and
                              bool(r.get("official_feasible")) == bool(r.get("ours_feasible"))) +
        sum(1 for r in rows if r.get("gurobi_official_feasible") is not None and
            bool(r.get("gurobi_official_feasible")) == bool(r.get("gurobi_ours_feasible"))),
        "checker_comparisons": sum(1 for r in rows if r.get("official_feasible") is not None) +
        sum(1 for r in rows if r.get("gurobi_official_feasible") is not None),
        "large_mean_score": round(sum(r["score"] for r in large) / len(large), 6) if large else None,
        "large_within_1pct": sum(1 for r in large if r["status"] == "ok" and r.get("gap_pct", 99) <= 1.0),
        "large_strictly_better": sum(1 for r in large if r["status"] == "ok" and r.get("gap_pct", 0) < -1e-6),
    })
    intro = ("%s on the public FrontierOR instances (Hugging Face frontieror/FrontierOR, revision %s, CC BY 4.0), "
             "%ss per instance, checked by our checker and by the official feasibility_check.py; reference = the "
             "Gurobi solution's objective_value. %sMade with AI agents working in MV2's name (MV2 of Munim, Inc.)."
             % (title or slug, man.get("revision"), time_limit, intro_extra))
    H.write_report(out, (title or slug) + " on the public FrontierOR instances", intro, rows, tally,
                   extra_cols=("official_feasible", "official_violated", "gurobi_ours_objective",
                               "gurobi_official_feasible"))
    print("tally", json.dumps(tally), flush=True)
    return tally

"""gpshim_census: how many of the 180 FrontierOR reference models run unchanged on open-source HiGHS, and how good
their answers are under the contest's own rules.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python gpshim_census.py --data-dir /data/hf --out-dir /out [--tiny-limit 20] [--large-limit 60]
                          [--large-max-bytes 1500000] [--budget-min 150] [--only slug ...]

For every task of the public FrontierOR benchmark (Hugging Face frontieror/FrontierOR, CC BY 4.0), at one pinned
revision:
1. builds a contest-style folder /tmp/gpshim/solvers/<slug>/ = gp_solve.py (as solve.py) + gpshim.py + the task's own
   gurobi_code.py (unchanged; written for gurobipy, run here with gpshim standing in for it, so on HiGHS);
2. runs it the contest way (python solve.py --problem --instance --output --time-limit T, wall clock measured) on the
   tiny instance (T = --tiny-limit), then, smallest first and while the budget lasts, on large_instance_1 when that
   file is at most --large-max-bytes (T = --large-limit);
3. judges each output with the task's official feasibility_check.py; reference = objective_value of the stored Gurobi
   solution; score = contest score (harness.contest_score: min(2, ref/obj) when minimising, obj/ref when maximising)
   when the checker accepts the file and the run finished within T, else 0. The optimisation sense is the one the
   model itself set (logged by gpshim).
Writes OUT/gpshim/{rows.jsonl (one line per run, as it finishes), summary.json, results.md, repo.json}.
"""
import argparse
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "munimtechnologies/frontieror-routing"
UA = "MV2-of-Munim-Inc FrontierOR practice (mv2@munimtech.com)"
STATIC = {
    "callback": re.compile(r"cbLazy|cbCut|cbGet|\.optimize\(\s*[A-Za-z_]"),
    "quadratic_or_general": re.compile(r"addGenConstr(?!Indicator)|gp\.max_|gp\.min_|gp\.abs_|gp\.and_|gp\.or_|"
                                       r"addSOS|setPWL|addQConstr|QuadExpr|setObjectiveN|addMVar|addMConstr|"
                                       r"NonConvex"),
}


def get(url, tries=4, timeout=120):
    err = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retry network errors
            err = e
            time.sleep(2.0 * (k + 1))
    raise err


def fetch_repo(dest):
    sha = json.loads(get("https://api.github.com/repos/%s/commits/main" % REPO).decode("utf-8"))["sha"]
    body = get("https://codeload.github.com/%s/zip/%s" % (REPO, sha))
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        z.extractall(dest)
    tops = [d for d in os.listdir(dest) if os.path.isdir(os.path.join(dest, d))]
    if len(tops) != 1:
        raise RuntimeError("unexpected archive layout: %r" % tops)
    return os.path.join(dest, tops[0]), sha


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def err_kind(stderr):
    lines = [x.strip() for x in (stderr or "").splitlines() if x.strip()]
    for line in reversed(lines):
        if re.match(r"^[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt)\b", line):
            return line[:300]
    return lines[-1][:300] if lines else ""


def run_case(folder, slug, ip, op, T):
    log = op + ".shim.jsonl"
    for p in (op, log):
        if os.path.exists(p):
            os.remove(p)
    env = dict(os.environ)
    env["MV2_GPSHIM_LOG"] = log
    env.pop("MV2_GPSHIM_DEADLINE", None)
    cmd = [sys.executable, "solve.py", "--problem", slug, "--instance", ip, "--output", op, "--time-limit", str(T)]
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=folder, capture_output=True, text=True, timeout=T + 15, env=env)
        code, err = p.returncode, p.stderr[-3000:]
    except subprocess.TimeoutExpired as e:
        s = e.stderr
        if isinstance(s, bytes):
            s = s.decode("utf-8", "replace")
        code, err = "killed", (s or "")[-3000:]
    wall = time.monotonic() - t0
    stats = []
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            for line in f:
                try:
                    stats.append(json.loads(line))
                except ValueError:
                    pass
    return {"exit": code, "wall_s": round(wall, 3), "stderr_tail": err[-800:], "err_kind": err_kind(err),
            "optimize_calls": len(stats), "shim": stats[-3:]}


def official(checker_py, ip, sp, rp):
    if os.path.exists(rp):
        os.remove(rp)
    try:
        p = subprocess.run([sys.executable, checker_py, "--instance_path", ip, "--solution_path", sp,
                            "--result_path", rp], capture_output=True, text=True, timeout=600,
                           cwd=os.path.dirname(rp))
        out = {"checker_exit": p.returncode}
    except subprocess.TimeoutExpired:
        return {"checker_exit": "timeout"}
    if os.path.exists(rp):
        try:
            with open(rp, encoding="utf-8") as f:
                r = json.load(f)
            out.update(official_feasible=r.get("feasible"), official_violated=r.get("violated_constraints"),
                       official_violations=str(r.get("violations"))[:400])
        except ValueError as e:
            out["checker_error"] = repr(e)[:200]
    return out


def read_obj(path):
    try:
        with open(path, encoding="utf-8") as f:
            sol = json.load(f)
    except Exception:  # noqa: BLE001
        return None, False
    v = sol.get("objective_value") if isinstance(sol, dict) else None
    return (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None), True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--tiny-limit", type=float, default=20.0)
    ap.add_argument("--large-limit", type=float, default=60.0)
    ap.add_argument("--large-max-bytes", type=int, default=1500000)
    ap.add_argument("--budget-min", type=float, default=150.0)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--scratch", default="/tmp/gpshim")
    a = ap.parse_args(argv)
    t_job = time.time()
    out = os.path.join(a.out_dir, "gpshim")
    os.makedirs(out, exist_ok=True)
    repo, sha = fetch_repo(os.path.join(a.scratch, "repo"))
    sys.path.insert(0, os.path.join(repo, "kit"))
    import frontieror_hf as HF  # noqa: E402
    import harness as H  # noqa: E402
    rev = HF.revision()
    try:
        import highspy
        hv = getattr(highspy, "__version__", None) or "present"
    except Exception as e:  # noqa: BLE001
        hv = "missing: %r" % (e,)
    meta = {"repo": REPO, "sha": sha, "benchmark_revision": rev, "highspy": hv, "python": sys.version,
            "cpu_count": os.cpu_count(), "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tiny_limit": a.tiny_limit, "large_limit": a.large_limit, "large_max_bytes": a.large_max_bytes}
    with open(os.path.join(out, "repo.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    print("meta", json.dumps(meta), flush=True)
    slugs = sorted(e["path"].split("/")[-1] for e in HF.tree("tasks", rev) if e.get("type") == "directory")
    if a.only:
        slugs = [s for s in slugs if s in a.only]
    rows_p = os.path.join(out, "rows.jsonl")
    done = set()
    if os.path.exists(rows_p):
        with open(rows_p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    done.add((r["slug"], r["case"]))
    listings, static = {}, {}

    def files_of(slug):
        if slug not in listings:
            fl = HF.tree("tasks/" + slug, rev, recursive=True)
            listings[slug] = {e["path"][len("tasks/" + slug) + 1:]: int(e.get("size") or 0)
                              for e in fl if e.get("type") == "file"}
        return listings[slug]

    def fetch(slug, rel):
        size = files_of(slug).get(rel)
        if size is None:
            return None
        dest = os.path.join(a.data_dir, "tasks", slug, rel)
        HF.download("tasks/%s/%s" % (slug, rel), rev, dest, expect_size=size)
        return dest

    def folder(slug):
        d = os.path.join(a.scratch, "solvers", slug)
        if not os.path.isdir(d):
            os.makedirs(d)
            shutil.copyfile(os.path.join(HERE, "gp_solve.py"), os.path.join(d, "solve.py"))
            shutil.copyfile(os.path.join(HERE, "gpshim.py"), os.path.join(d, "gpshim.py"))
            shutil.copyfile(fetch(slug, "gurobi_code.py"), os.path.join(d, "gurobi_code.py"))
        if slug not in static:
            with open(os.path.join(d, "gurobi_code.py"), encoding="utf-8", errors="replace") as f:
                src = f.read()
            static[slug] = sorted(k for k, rx in STATIC.items() if rx.search(src))
        return d

    def one(slug, case, ifile, sfile, T):
        if (slug, case) in done:
            return
        row = {"slug": slug, "case": case, "T": T}
        try:
            d = folder(slug)
            row["static_flags"] = static.get(slug, [])
            ip = fetch(slug, "instance/" + ifile)
            sp_ref = fetch(slug, "gurobi_solution/" + sfile)
            checker = fetch(slug, "feasibility_check.py")
            if ip is None or checker is None:
                row["status"] = "missing_files"
            else:
                work = os.path.join(a.scratch, "work", slug)
                os.makedirs(work, exist_ok=True)
                op = os.path.join(work, case + ".solution.json")
                row.update(run_case(d, slug, ip, op, T))
                ref = None
                if sp_ref:
                    ref, _ = read_obj(sp_ref)
                row["reference"] = ref
                obj, wrote = read_obj(op)
                row["objective"] = obj
                sense = None
                if row.get("shim"):
                    sense = row["shim"][-1].get("sense")
                row["sense"] = sense
                if not wrote:
                    row["status"] = "overtime_no_output" if row["exit"] == "killed" else (
                        "crash" if row["exit"] not in (0, "0") else "no_output")
                else:
                    row.update(official(checker, ip, op, os.path.join(work, case + ".result.json")))
                    if row["wall_s"] > T:
                        row["status"] = "overtime"
                    elif row.get("official_feasible") is True:
                        row["status"] = "accepted"
                    elif obj is None:
                        row["status"] = "no_solution"
                    else:
                        row["status"] = "rejected"
                score = 0.0
                if row["status"] == "accepted" and obj is not None and sense in ("min", "max"):
                    score = H.contest_score(obj, ref, sense)
                row["score"] = round(float(score), 6)
        except Exception as e:  # noqa: BLE001 - one task must not stop the census
            row["status"] = "census_error"
            row["census_error"] = repr(e)[:400]
        with open(rows_p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        print("case", slug, case, row.get("status"), row.get("objective"), row.get("reference"), row.get("score"),
              row.get("wall_s"), (row.get("err_kind") or "")[:120], flush=True)

    # stage 1: every task's tiny instance
    for slug in slugs:
        one(slug, "tiny", "tiny_instance.json", "tiny_solution.json", a.tiny_limit)
    # stage 2: large_instance_1, smallest first, within the budget
    sizes = []
    for slug in slugs:
        try:
            s = files_of(slug).get("instance/large_instance_1.json")
        except Exception:  # noqa: BLE001
            s = None
        if s is not None and s <= a.large_max_bytes:
            sizes.append((s, slug))
    sizes.sort()
    skipped_budget = []
    for s, slug in sizes:
        if (time.time() - t_job) / 60.0 + (a.large_limit + 20) / 60.0 > a.budget_min:
            skipped_budget.append(slug)
            continue
        one(slug, "large_1", "large_instance_1.json", "large_solution_1.json", a.large_limit)
    # summary
    with open(rows_p, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    summary = {"meta": meta, "tasks": len(slugs), "skipped_for_budget": skipped_budget,
               "large_eligible": len(sizes), "stages": {}}
    for case in ("tiny", "large_1"):
        rs = [r for r in rows if r["case"] == case]
        by = {}
        for r in rs:
            by[r.get("status")] = by.get(r.get("status"), 0) + 1
        kinds = {}
        for r in rs:
            if r.get("status") in ("crash", "no_output", "census_error"):
                k = re.sub(r"\d+", "N", (r.get("err_kind") or r.get("census_error") or "")[:160])
                kinds.setdefault(k, []).append(r["slug"])
        acc = [r for r in rs if r.get("status") == "accepted"]
        sc = sorted(r["score"] for r in acc)
        summary["stages"][case] = {
            "runs": len(rs), "by_status": by,
            "accepted": len(acc),
            "mean_score_all_runs": round(sum(r.get("score", 0.0) for r in rs) / len(rs), 6) if rs else None,
            "median_score_accepted": sc[len(sc) // 2] if sc else None,
            "score_ge_0_99": sum(1 for x in sc if x >= 0.99),
            "score_gt_1": [r["slug"] for r in acc if r["score"] > 1.0001],
            "static_callback_accepted": [r["slug"] for r in acc if "callback" in r.get("static_flags", [])],
            "static_callback_runs": sum(1 for r in rs if "callback" in r.get("static_flags", [])),
            "failure_kinds": sorted(([k, len(v), v[:12]] for k, v in kinds.items()), key=lambda x: -x[1])[:40],
            "accepted_tasks": sorted(r["slug"] for r in acc),
        }
    summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary["elapsed_min"] = round((time.time() - t_job) / 60.0, 2)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    lines = ["# gpshim census: FrontierOR's reference models on open-source HiGHS", "",
             "Benchmark revision %s (Hugging Face frontieror/FrontierOR, CC BY 4.0); repository %s at %s; highspy %s. "
             "Each task's own gurobi_code.py ran unchanged with gpshim standing in for gurobipy, the contest way; the "
             "official feasibility_check.py judged every output. Made with AI agents working in MV2's name "
             "(MV2 of Munim, Inc.)." % (rev, REPO, sha, hv), "",
             "| stage | runs | accepted | score >= 0.99 | median score (accepted) | mean score (all runs) | statuses |",
             "|---|---|---|---|---|---|---|"]
    for case, s in summary["stages"].items():
        lines.append("| %s | %d | %d | %d | %s | %s | %s |" % (
            case, s["runs"], s["accepted"], s["score_ge_0_99"], s["median_score_accepted"],
            s["mean_score_all_runs"], ", ".join("%s %d" % kv for kv in sorted(s["by_status"].items(),
                                                                               key=lambda kv: str(kv[0])))))
    lines += ["", "## Most common failures (tiny)", ""]
    for k, cnt, sl in summary["stages"].get("tiny", {}).get("failure_kinds", [])[:20]:
        lines.append("- %d: `%s` (%s)" % (cnt, k.replace("`", "'"), ", ".join(sl)))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", json.dumps({c: (s["runs"], s["accepted"], s["score_ge_0_99"]) for c, s in
                              summary["stages"].items()}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

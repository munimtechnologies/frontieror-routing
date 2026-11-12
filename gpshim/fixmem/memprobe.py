"""memprobe: how much memory FrontierOR's own reference models need when run through gpshim, under a 4 GB cap.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python memprobe.py --data-dir /data/hf --out-dir /out [--limit 60] [--cap-mb 3900] [--max-bytes 20000000]
                     [--download-budget-mb 1500] [--budget-min 220] [--only slug ...] [--first slug ...]

For every task of the public FrontierOR benchmark (Hugging Face frontieror/FrontierOR, CC BY 4.0) at one pinned
revision whose large_instance_1.json is at most --max-bytes, smallest instance first (tasks named by --first go
first), the task's unchanged gurobi_code.py runs the contest way (python solve.py --problem --instance --output
--time-limit T) through gpshim 0.2.0 on HiGHS (no OR-Tools), with gpshim_objfix and memory stage marks
(solve_probe.py). The parent polls the child's VmRSS every 0.2 s and kills it above --cap-mb (the FrontierOR
sandbox has 4 GB in all). The official feasibility_check.py judges every written solution; score = contest score
against the stored Gurobi solution when accepted and on time.
Writes OUT/memprobe/{rows.jsonl, summary.json, results.md, repo.json}.
"""
import argparse
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
SHIP = ("solve_probe.py", "gpshim.py", "gpshim_objfix.py")
SENSE_OVERRIDES = {"furini2017": "min"}  # checked by hand against solution_schema.json (see gpshim_ab.py)


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


def code_sense(path):
    """('min' | 'max' | None, declared senses) from the task's gurobi_code.py; None when mixed or absent."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None, []
    found = re.findall(r"GRB\.(MINIMIZE|MAXIMIZE)\b", text)
    found += ["MAXIMIZE" if v.strip() == "-1" else "MINIMIZE" for v in re.findall(r"ModelSense\s*=\s*(-?1)\b", text)]
    kinds = sorted(set(found))
    if len(kinds) == 1:
        return ("min" if kinds[0] == "MINIMIZE" else "max"), kinds
    return None, kinds


def read_obj(path):
    try:
        with open(path, encoding="utf-8") as f:
            sol = json.load(f)
    except Exception:  # noqa: BLE001
        return None, False
    v = sol.get("objective_value") if isinstance(sol, dict) else None
    return (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None), True


def official(checker_py, ip, sp, rp):
    if os.path.exists(rp):
        os.remove(rp)
    try:
        p = subprocess.run([sys.executable, checker_py, "--instance_path", ip, "--solution_path", sp,
                            "--result_path", rp], capture_output=True, text=True, timeout=300,
                           cwd=os.path.dirname(rp))
        out = {"checker_exit": p.returncode}
    except subprocess.TimeoutExpired:
        return {"checker_exit": "timeout"}
    if os.path.exists(rp):
        try:
            with open(rp, encoding="utf-8") as f:
                r = json.load(f)
            out.update(official_feasible=r.get("feasible"), official_violations=str(r.get("violations"))[:300])
        except ValueError as e:
            out["checker_error"] = repr(e)[:200]
    return out


def proc_mb(pid):
    out = {}
    try:
        with open("/proc/%d/status" % pid, encoding="utf-8") as f:
            for line in f:
                if line.startswith(("VmRSS:", "VmHWM:")):
                    k, v = line.split(":", 1)
                    out[k.strip()] = int(v.split()[0]) / 1024.0
    except (OSError, ValueError):
        pass
    return out


def read_jsonl(path):
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    return rows


def run_case(folder, slug, ip, op, T, cap_mb):
    memlog, fixlog, shimlog, errp = op + ".mem.jsonl", op + ".objfix.jsonl", op + ".shim.jsonl", op + ".stderr"
    for p in (op, memlog, fixlog, shimlog, errp):
        if os.path.exists(p):
            os.remove(p)
    env = dict(os.environ)
    for k in ("MV2_GPSHIM_BACKEND", "MV2_GPSHIM_CPSAT_WORKERS", "MV2_GPSHIM_DEADLINE"):
        env.pop(k, None)
    env.update(MV2_MEM_LOG=memlog, MV2_OBJFIX_LOG=fixlog, MV2_GPSHIM_LOG=shimlog, MV2_OBJFIX="1")
    cmd = [sys.executable, "solve.py", "--problem", slug, "--instance", ip, "--output", op, "--time-limit", str(T)]
    t0 = time.monotonic()
    peak_rss = 0.0
    killed = None
    with open(errp, "w", encoding="utf-8") as ef:
        p = subprocess.Popen(cmd, cwd=folder, stdout=subprocess.DEVNULL, stderr=ef, env=env)
        while p.poll() is None:
            rss = proc_mb(p.pid).get("VmRSS", 0.0)
            peak_rss = max(peak_rss, rss)
            if cap_mb and rss > cap_mb:
                killed = "over_cap"
            elif time.monotonic() - t0 > T + 15:
                killed = "overtime"
            if killed:
                p.kill()
                p.wait()
                break
            time.sleep(0.2)
    wall = time.monotonic() - t0
    with open(errp, encoding="utf-8", errors="replace") as f:
        err = f.read()[-3000:]
    marks = read_jsonl(memlog)
    fixes = read_jsonl(fixlog)
    stats = read_jsonl(shimlog)

    def first(stage):
        for m in marks:
            if m.get("stage") == stage:
                return m
        return None

    imp, oe, he, ex = first("imported"), first("optimize_enter"), first("highs_enter"), first("exit")
    samples = [m for m in marks if m.get("stage") == "sample"]
    hwm_all = max([m.get("VmHWM", 0.0) for m in marks] + [0.0])
    if he is None:
        stage_reached = "optimize" if oe else ("build" if imp else "start")
    else:
        stage_reached = "solver"
    if ex is not None:
        stage_reached = "exit"
    row = {"exit": p.returncode, "killed": killed, "wall_s": round(wall, 3), "peak_rss_mb": round(peak_rss, 1),
           "peak_hwm_mb": round(hwm_all, 1), "stage_reached": stage_reached,
           "base_mb": imp.get("VmRSS") if imp else None,
           "build_hwm_mb": oe.get("VmHWM") if oe else None,
           "assembly_hwm_mb": he.get("VmHWM") if he else None,
           "vars": oe.get("vars") if oe else (samples[-1].get("vars") if samples else None),
           "constrs": oe.get("constrs") if oe else (samples[-1].get("constrs") if samples else None),
           "nnz": he.get("nnz") if he else None, "cols": he.get("n") if he else None,
           "rows": he.get("m") if he else None,
           "last_sample": samples[-1] if samples else None, "optimize_calls": len(stats),
           "objfix": [f for f in fixes][:5], "stderr_tail": err[-500:]}
    return row


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--limit", type=float, default=60.0)
    ap.add_argument("--cap-mb", type=float, default=3900.0)
    ap.add_argument("--max-bytes", type=int, default=20000000)
    ap.add_argument("--download-budget-mb", type=float, default=1500.0)
    ap.add_argument("--budget-min", type=float, default=220.0)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--first", nargs="*", default=[])
    ap.add_argument("--scratch", default="/tmp/memprobe")
    a = ap.parse_args(argv)
    t_job = time.time()
    out = os.path.join(a.out_dir, "memprobe")
    os.makedirs(out, exist_ok=True)
    repo, sha = fetch_repo(os.path.join(a.scratch, "repo"))
    sys.path.insert(0, os.path.join(repo, "kit"))
    import frontieror_hf as HF  # noqa: E402
    import harness as H  # noqa: E402
    rev = HF.revision()
    versions = {}
    from importlib.metadata import version as _dist_version
    for mod in ("highspy", "numpy"):
        try:
            versions[mod] = _dist_version(mod)
        except Exception as e:  # noqa: BLE001
            versions[mod] = "missing: %r" % (e,)
    base = {}
    if os.path.exists(os.path.join(HERE, "gpshim_base.json")):
        with open(os.path.join(HERE, "gpshim_base.json"), encoding="utf-8") as f:
            base = json.load(f)
    meta = {"repo": REPO, "sha": sha, "benchmark_revision": rev, "versions": versions, "gpshim_base": base,
            "python": sys.version, "cpu_count": os.cpu_count(), "limit": a.limit, "cap_mb": a.cap_mb,
            "max_bytes": a.max_bytes, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with open(os.path.join(out, "repo.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    print("meta", json.dumps(meta), flush=True)
    slugs = sorted(e["path"].split("/")[-1] for e in HF.tree("tasks", rev) if e.get("type") == "directory")
    if a.only:
        slugs = [s for s in slugs if s in set(a.only)]
    listings = {}

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

    plan, too_big = [], []
    for slug in slugs:
        try:
            s = files_of(slug).get("instance/large_instance_1.json")
        except Exception as e:  # noqa: BLE001
            print("listing failed", slug, repr(e)[:200], flush=True)
            continue
        if s is None:
            continue
        if s > a.max_bytes:
            too_big.append([slug, s])
        else:
            plan.append((0 if slug in a.first else 1, s, slug))
    plan.sort()
    rows_p = os.path.join(out, "rows.jsonl")
    done = {r["slug"]: r for r in read_jsonl(rows_p)}
    downloaded = 0.0
    skipped_budget, skipped_download = [], []
    for _, size, slug in plan:
        if slug in done:
            continue
        if (time.time() - t_job) / 60.0 + (a.limit + 60) / 60.0 > a.budget_min:
            skipped_budget.append(slug)
            continue
        sol_size = files_of(slug).get("gurobi_solution/large_solution_1.json") or 0
        if downloaded + (size + sol_size) / 1e6 > a.download_budget_mb:
            skipped_download.append(slug)
            continue
        row = {"slug": slug, "case": "large_1", "instance_bytes": size, "T": a.limit}
        try:
            d = os.path.join(a.scratch, "solvers", slug)
            if not os.path.isdir(d):
                os.makedirs(d)
                for name in SHIP:
                    shutil.copyfile(os.path.join(HERE, name),
                                    os.path.join(d, "solve.py" if name == "solve_probe.py" else name))
                shutil.copyfile(fetch(slug, "gurobi_code.py"), os.path.join(d, "gurobi_code.py"))
            ip = fetch(slug, "instance/large_instance_1.json")
            sp_ref = fetch(slug, "gurobi_solution/large_solution_1.json")
            checker = fetch(slug, "feasibility_check.py")
            downloaded += (size + sol_size) / 1e6
            work = os.path.join(a.scratch, "work", slug)
            os.makedirs(work, exist_ok=True)
            op = os.path.join(work, "large_1.solution.json")
            row.update(run_case(d, slug, ip, op, a.limit, a.cap_mb))
            ref = read_obj(sp_ref)[0] if sp_ref else None
            obj, wrote = read_obj(op)
            ss, declared = code_sense(os.path.join(d, "gurobi_code.py"))
            sense = SENSE_OVERRIDES.get(slug) or ss
            row.update(reference=ref, objective=obj, sense=sense, declared_senses=declared)
            if row["killed"] == "over_cap":
                row["status"] = "over_cap"
            elif not wrote:
                row["status"] = "overtime_no_output" if row["killed"] == "overtime" else (
                    "crash" if row["exit"] not in (0, "0") else "no_output")
            else:
                row.update(official(checker, ip, op, os.path.join(work, "large_1.result.json")))
                if row["wall_s"] > a.limit:
                    row["status"] = "overtime"
                elif row.get("official_feasible") is True:
                    row["status"] = "accepted"
                elif obj is None:
                    row["status"] = "no_solution"
                else:
                    row["status"] = "rejected"
            score = 0.0
            if row["status"] == "accepted" and obj is not None and sense in ("min", "max") and ref is not None:
                score = H.contest_score(obj, ref, sense)
            row["score"] = round(float(score), 6)
            # keep the shared data volume small: the big instance and reference files are not reused
            for pth in (ip, sp_ref):
                if pth and os.path.exists(pth) and os.path.getsize(pth) > 1500000:
                    os.remove(pth)
            shutil.rmtree(work, ignore_errors=True)
        except Exception as e:  # noqa: BLE001 - one task must not stop the run
            row["status"] = "harness_error"
            row["harness_error"] = repr(e)[:400]
            row.setdefault("score", 0.0)
        with open(rows_p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        done[slug] = row
        print("case", slug, size, row.get("status"), row.get("stage_reached"), row.get("peak_rss_mb"),
              row.get("vars"), row.get("constrs"), row.get("nnz"), row.get("score"), row.get("wall_s"), flush=True)

    rows = list(done.values())
    by_status = {}
    for r in rows:
        by_status.setdefault(r.get("status"), []).append(r["slug"])
    over = [r for r in rows if r.get("status") == "over_cap"]
    big = [r for r in rows if (r.get("peak_rss_mb") or 0) > 1024.0]
    before_solver = [r["slug"] for r in big if r.get("stage_reached") in ("start", "build", "optimize") or (
        r.get("assembly_hwm_mb") and r["assembly_hwm_mb"] >= 0.95 * (r.get("peak_hwm_mb") or 0))]
    per_item = []
    for r in rows:
        if r.get("build_hwm_mb") and r.get("base_mb") is not None and r.get("vars") is not None:
            k = (r["vars"] or 0) + (r["constrs"] or 0)
            if k >= 100000:
                per_item.append(round((r["build_hwm_mb"] - r["base_mb"]) * 1048576.0 / k, 1))
    per_item.sort()
    objfix_changed = sorted(set(r["slug"] for r in rows for f in (r.get("objfix") or []) if f.get("changed")))
    objfix_applicable = sorted(set(r["slug"] for r in rows if r.get("objfix")))
    summary = {"meta": meta, "planned": len(plan), "ran": len(rows), "too_big_not_run": too_big,
               "skipped_budget": skipped_budget, "skipped_download": skipped_download,
               "by_status": {k: sorted(v) for k, v in by_status.items()},
               "over_cap": sorted((r["slug"], r.get("stage_reached"), r.get("last_sample")) for r in over),
               "runs_over_1gb": len(big), "over_1gb_peak_before_solver": sorted(before_solver),
               "bytes_per_var_plus_constr_at_build_ge_100k": per_item,
               "median_bytes_per_var_plus_constr": per_item[len(per_item) // 2] if per_item else None,
               "objfix_applicable": objfix_applicable, "objfix_changed": objfix_changed,
               "accepted": len(by_status.get("accepted", [])),
               "mean_score": round(sum(r.get("score", 0.0) for r in rows) / len(rows), 6) if rows else None,
               "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "elapsed_min": round((time.time() - t_job) / 60.0, 2)}
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, default=str)
    lines = ["# memprobe: FrontierOR reference models through gpshim under a %.0f MB cap" % a.cap_mb, "",
             "Benchmark revision %s (Hugging Face frontieror/FrontierOR, CC BY 4.0); kit %s at %s; versions %s; "
             "gpshim base %s with gpshim_objfix 0.1.0; HiGHS only; large_instance_1, T = %g s. Made with AI agents "
             "working in MV2's name (MV2 of Munim, Inc.)." % (rev, REPO, sha, json.dumps(versions),
                                                                base.get("commit"), a.limit), "",
             "- Ran %d of %d planned; not run (instance over %d bytes): %d; skipped for time: %d; for download "
             "budget: %d" % (len(rows), len(plan), a.max_bytes, len(too_big), len(skipped_budget),
                             len(skipped_download)),
             "- By status: %s" % json.dumps({k: len(v) for k, v in by_status.items()}),
             "- Median Python-side MB cost per (variable + constraint) at the first optimize(), models with at "
             "least 100k: %s bytes" % summary["median_bytes_per_var_plus_constr"],
             "- objfix applicable: %d; changed ObjVal: %s" % (len(objfix_applicable), ", ".join(objfix_changed)),
             "", "| task | MB in file | status | stage | peak RSS MB | build MB | assembly MB | vars | constrs | "
                 "nnz | score |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: -(r.get("peak_rss_mb") or 0)):
        lines.append("| %s | %.2f | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["slug"], r.get("instance_bytes", 0) / 1e6, r.get("status"), r.get("stage_reached"),
            r.get("peak_rss_mb"), r.get("build_hwm_mb"), r.get("assembly_hwm_mb"), r.get("vars"),
            r.get("constrs"), r.get("nnz"), r.get("score")))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", json.dumps({k: summary[k] for k in ("planned", "ran", "accepted")}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

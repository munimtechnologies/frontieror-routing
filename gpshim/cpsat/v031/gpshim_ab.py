"""gpshim_ab: HiGHS vs OR-Tools CP-SAT on FrontierOR's own reference models, under the contest's rules.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python gpshim_ab.py --data-dir /data/hf --out-dir /out [--tiny-limit 20] [--large-limit 60]
                      [--large-max-bytes 1500000] [--budget-min 200] [--arm3-max 15] [--only slug ...]
                      [--only-file candidates.txt]

For every selected task of the public FrontierOR benchmark (Hugging Face frontieror/FrontierOR, CC BY 4.0) at one
pinned revision, the task's unchanged gurobi_code.py runs the contest way (python solve.py --problem --instance
--output --time-limit T) with gpshim (gurobipy stand-in, 0.2.0) and gpshim_cpsat (0.3.1, CP-SAT in a worker process)
in the folder:
1. tiny instance, T = --tiny-limit, backend cpsat (2 workers). The model is "CP-SAT eligible" when gpshim logged at
   least one optimize() solved by CP-SAT; otherwise the logged reason is kept (e.g. continuous columns).
   Eligible tasks also run tiny on HiGHS.
2. large_instance_1 (file <= --large-max-bytes), eligible tasks only, smallest first, while the budget lasts:
   arm "highs", arm "cpsat2" (2 workers), and for the first --arm3-max tasks arm "cpsat8" (8 workers on the same
   2 CPUs), all with T = --large-limit.
Every output is judged by the task's official feasibility_check.py; score = contest score against the stored Gurobi
solution (min(2, ref/obj) minimising, obj/ref maximising) when accepted and on time, else 0.
Writes OUT/gpshim_ab/{rows.jsonl, summary.json, results.md, repo.json}.
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
ARMS = {"highs": {"MV2_GPSHIM_BACKEND": "highs"},
        "cpsat2": {"MV2_GPSHIM_BACKEND": "cpsat", "MV2_GPSHIM_CPSAT_WORKERS": "2"},
        "cpsat8": {"MV2_GPSHIM_BACKEND": "cpsat", "MV2_GPSHIM_CPSAT_WORKERS": "8"}}
SHIP = ("gp_solve.py", "gpshim.py", "gpshim_cpsat.py", "gpshim_cpsat_worker.py")


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


def err_kind(stderr):
    lines = [x.strip() for x in (stderr or "").splitlines() if x.strip()]
    for line in reversed(lines):
        if re.match(r"^[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt)\b", line):
            return line[:300]
    return lines[-1][:300] if lines else ""


def run_case(folder, slug, ip, op, T, arm, mem_mb):
    log = op + ".shim.jsonl"
    for p in (op, log):
        if os.path.exists(p):
            os.remove(p)
    env = dict(os.environ)
    for k in ("MV2_GPSHIM_BACKEND", "MV2_GPSHIM_CPSAT_WORKERS", "MV2_GPSHIM_DEADLINE"):
        env.pop(k, None)
    env.update(ARMS[arm])
    env["MV2_GPSHIM_CPSAT_MEM_MB"] = str(mem_mb)
    env["MV2_GPSHIM_LOG"] = log
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
    backends = sorted(set(str(s.get("backend")) for s in stats))
    notes = [str(s.get("note") or "") for s in stats]
    skip = sorted(set(n.split("cpsat_skip: ", 1)[1][:160] for n in notes if "cpsat_skip: " in n))
    return {"exit": code, "wall_s": round(wall, 3), "stderr_tail": err[-600:], "err_kind": err_kind(err),
            "optimize_calls": len(stats), "backends": backends, "cpsat_skip": skip, "shim": stats[-2:]}


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
            out.update(official_feasible=r.get("feasible"), official_violations=str(r.get("violations"))[:300])
        except ValueError as e:
            out["checker_error"] = repr(e)[:200]
    return out


# Senses checked by hand against the task's solution_schema.json (used before anything else).
# furini2017: "Minimum number of distinct colors used ..." (its Gurobi solves include a maximising clique bound).
SENSE_OVERRIDES = {"furini2017": "min"}


def code_sense(path):
    """The optimisation sense declared in the task's gurobi_code.py, when every declaration agrees.

    v1 took the sense of gpshim's last optimize() call, which is wrong when a reference model also runs an auxiliary
    solve: furini2017 minimises colours, but one of its solves maximises (a clique bound) and v1 scored it as a
    maximisation. Returns ('min' | 'max' | None, list of declared senses). None means mixed or none found: the shim's
    sense is used then and the task is flagged for a hand check.
    """
    if not path or not os.path.exists(path):
        return None, []
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None, []
    found = re.findall(r"GRB\.(MINIMIZE|MAXIMIZE)\b", text)
    found += ["MAXIMIZE" if v.strip() == "-1" else "MINIMIZE"
              for v in re.findall(r"ModelSense\s*=\s*(-?1)\b", text)]
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--tiny-limit", type=float, default=20.0)
    ap.add_argument("--large-limit", type=float, default=60.0)
    ap.add_argument("--large-max-bytes", type=int, default=1500000)
    ap.add_argument("--budget-min", type=float, default=200.0)
    ap.add_argument("--arm3-max", type=int, default=15)
    ap.add_argument("--mem-mb", type=int, default=1200)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--only-file", default=None)
    ap.add_argument("--scratch", default="/tmp/gpshim_ab")
    a = ap.parse_args(argv)
    t_job = time.time()
    out = os.path.join(a.out_dir, "gpshim_ab")
    os.makedirs(out, exist_ok=True)
    repo, sha = fetch_repo(os.path.join(a.scratch, "repo"))
    sys.path.insert(0, os.path.join(repo, "kit"))
    import frontieror_hf as HF  # noqa: E402
    import harness as H  # noqa: E402
    rev = HF.revision()
    versions = {}
    try:
        from importlib.metadata import version as _dist_version
    except ImportError:  # pragma: no cover
        _dist_version = None
    for mod in ("highspy", "ortools", "numpy"):  # distribution metadata only: never import ortools here
        try:
            versions[mod] = _dist_version(mod) if _dist_version else "unknown"
        except Exception as e:  # noqa: BLE001
            versions[mod] = "missing: %r" % (e,)
    base = {}
    if os.path.exists(os.path.join(HERE, "gpshim_base.json")):
        with open(os.path.join(HERE, "gpshim_base.json"), encoding="utf-8") as f:
            base = json.load(f)
    meta = {"repo": REPO, "sha": sha, "benchmark_revision": rev, "versions": versions, "gpshim_base": base,
            "gpshim_cpsat": "0.3.1", "python": sys.version, "cpu_count": os.cpu_count(),
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tiny_limit": a.tiny_limit,
            "large_limit": a.large_limit, "large_max_bytes": a.large_max_bytes, "arm3_max": a.arm3_max,
            "cpsat_mem_mb": a.mem_mb}
    with open(os.path.join(out, "repo.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    print("meta", json.dumps(meta), flush=True)
    slugs = sorted(e["path"].split("/")[-1] for e in HF.tree("tasks", rev) if e.get("type") == "directory")
    only = list(a.only or [])
    if a.only_file:
        with open(a.only_file, encoding="utf-8") as f:
            only += [x.strip() for x in f if x.strip() and not x.startswith("#")]
    if only:
        missing = sorted(set(only) - set(slugs))
        if missing:
            print("selected slugs not in the benchmark:", missing, flush=True)
        slugs = [s for s in slugs if s in set(only)]
    meta["selected_tasks"] = len(slugs)
    rows_p = os.path.join(out, "rows.jsonl")
    done = {}
    if os.path.exists(rows_p):
        with open(rows_p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    done[(r["slug"], r["case"], r["arm"])] = r
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

    def folder(slug):
        d = os.path.join(a.scratch, "solvers", slug)
        if not os.path.isdir(d):
            os.makedirs(d)
            for name in SHIP:
                shutil.copyfile(os.path.join(HERE, name), os.path.join(d, "solve.py" if name == "gp_solve.py" else name))
            shutil.copyfile(fetch(slug, "gurobi_code.py"), os.path.join(d, "gurobi_code.py"))
        return d

    def one(slug, case, ifile, sfile, T, arm):
        key = (slug, case, arm)
        if key in done:
            return done[key]
        row = {"slug": slug, "case": case, "arm": arm, "T": T}
        try:
            d = folder(slug)
            ip = fetch(slug, "instance/" + ifile)
            sp_ref = fetch(slug, "gurobi_solution/" + sfile)
            checker = fetch(slug, "feasibility_check.py")
            if ip is None or checker is None:
                row["status"] = "missing_files"
            else:
                work = os.path.join(a.scratch, "work", slug)
                os.makedirs(work, exist_ok=True)
                op = os.path.join(work, "%s.%s.solution.json" % (case, arm))
                row.update(run_case(d, slug, ip, op, T, arm, a.mem_mb))
                ref = read_obj(sp_ref)[0] if sp_ref else None
                row["reference"] = ref
                obj, wrote = read_obj(op)
                row["objective"] = obj
                shim_sense = row["shim"][-1].get("sense") if row.get("shim") else None
                ss, declared = code_sense(os.path.join(d, "gurobi_code.py"))
                sense = SENSE_OVERRIDES.get(slug) or ss or shim_sense
                row["sense"], row["code_sense"], row["shim_sense"] = sense, ss, shim_sense
                row["declared_senses"] = declared
                if not wrote:
                    row["status"] = "overtime_no_output" if row["exit"] == "killed" else (
                        "crash" if row["exit"] not in (0, "0") else "no_output")
                else:
                    row.update(official(checker, ip, op, os.path.join(work, "%s.%s.result.json" % (case, arm))))
                    if row["wall_s"] > T:
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
        except Exception as e:  # noqa: BLE001 - one task must not stop the run
            row["status"] = "harness_error"
            row["harness_error"] = repr(e)[:400]
            row.setdefault("score", 0.0)
        with open(rows_p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        done[key] = row
        print("case", slug, case, arm, row.get("status"), row.get("objective"), row.get("reference"),
              row.get("score"), row.get("wall_s"), row.get("backends"), (row.get("err_kind") or "")[:100], flush=True)
        return row

    def eligible(r):
        return "cpsat" in (r.get("backends") or [])

    # stage 1: tiny, CP-SAT first; HiGHS too where CP-SAT actually solved the model
    elig = []
    for slug in slugs:
        r = one(slug, "tiny", "tiny_instance.json", "tiny_solution.json", a.tiny_limit, "cpsat2")
        if eligible(r):
            elig.append(slug)
            one(slug, "tiny", "tiny_instance.json", "tiny_solution.json", a.tiny_limit, "highs")
    # stage 2: large_instance_1 of eligible tasks, smallest first, paired arms
    sizes = []
    for slug in elig:
        try:
            s = files_of(slug).get("instance/large_instance_1.json")
        except Exception:  # noqa: BLE001
            s = None
        if s is not None and s <= a.large_max_bytes:
            sizes.append((s, slug))
    sizes.sort()
    skipped_budget = []
    for k, (s, slug) in enumerate(sizes):
        arms = ["highs", "cpsat2"] + (["cpsat8"] if k < a.arm3_max else [])
        need = len(arms) * (a.large_limit + 25) / 60.0
        if (time.time() - t_job) / 60.0 + need > a.budget_min:
            skipped_budget.append(slug)
            continue
        for arm in arms:
            one(slug, "large_1", "large_instance_1.json", "large_solution_1.json", a.large_limit, arm)

    # summary
    rows = list(done.values())
    tiny_c = [r for r in rows if r["case"] == "tiny" and r["arm"] == "cpsat2"]
    reasons = {}
    for r in tiny_c:
        if not eligible(r):
            k = "; ".join(re.sub(r"\d+", "N", x) for x in (r.get("cpsat_skip") or [])) or (
                "no optimize() logged: " + re.sub(r"\d+", "N", (r.get("err_kind") or r.get("status") or "")[:100]))
            reasons.setdefault(k, []).append(r["slug"])

    def paired(case, a1, a2):
        by = {}
        for r in rows:
            if r["case"] == case and r["arm"] in (a1, a2):
                by.setdefault(r["slug"], {})[r["arm"]] = r
        pairs = [(sl, v[a1], v[a2]) for sl, v in sorted(by.items()) if a1 in v and a2 in v]
        win = [sl for sl, x, y in pairs if y["score"] > x["score"] + 1e-3]
        loss = [sl for sl, x, y in pairs if y["score"] < x["score"] - 1e-3]
        n = len(pairs)
        return {"pairs": n, "%s_better" % a2: win, "%s_better" % a1: loss, "ties": n - len(win) - len(loss),
                "mean_%s" % a1: round(sum(x["score"] for _, x, _ in pairs) / n, 6) if n else None,
                "mean_%s" % a2: round(sum(y["score"] for _, _, y in pairs) / n, 6) if n else None,
                "accepted_%s" % a1: sum(1 for _, x, _ in pairs if x.get("status") == "accepted"),
                "accepted_%s" % a2: sum(1 for _, _, y in pairs if y.get("status") == "accepted"),
                "best_of_both_mean": round(sum(max(x["score"], y["score"]) for _, x, y in pairs) / n, 6)
                if n else None}

    summary = {"meta": meta, "tasks": len(slugs), "tiny_cpsat_runs": len(tiny_c), "cpsat_eligible": len(elig),
               "eligible_tasks": elig, "not_eligible_reasons": sorted(([k, len(v), v] for k, v in
                                                                      reasons.items()), key=lambda x: -x[1])[:40],
               "large_eligible": len(sizes), "skipped_for_budget": skipped_budget,
               "sense_mixed_in_code_check_by_hand": sorted(set(r["slug"] for r in rows if r.get("shim") and
                                                               not r.get("code_sense"))),
               "sense_code_vs_last_solve_differ": sorted(set(r["slug"] for r in rows if r.get("code_sense") and
                                                             r.get("shim_sense") and
                                                             r["code_sense"] != r["shim_sense"])),
               "tiny_highs_vs_cpsat2": paired("tiny", "highs", "cpsat2"),
               "large_highs_vs_cpsat2": paired("large_1", "highs", "cpsat2"),
               "large_cpsat2_vs_cpsat8": paired("large_1", "cpsat2", "cpsat8"),
               "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "elapsed_min": round((time.time() - t_job) / 60.0, 2)}
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    lines = ["# gpshim A/B: HiGHS vs CP-SAT on FrontierOR's reference models", "",
             "Benchmark revision %s (Hugging Face frontieror/FrontierOR, CC BY 4.0); kit from %s at %s; versions %s; "
             "gpshim base %s; gpshim_cpsat 0.3.1 (CP-SAT in a worker process). Each task's own gurobi_code.py ran "
             "unchanged, the contest way, and the official feasibility_check.py judged every output. Made with AI "
             "agents working in MV2's name (MV2 of Munim, Inc.)." % (rev, REPO, sha, json.dumps(versions),
                                                                     base.get("commit")), "",
             "- Tasks selected: %d; tiny runs on CP-SAT: %d; CP-SAT eligible (all-integer model actually solved by "
             "CP-SAT): %d" % (len(slugs), len(tiny_c), len(elig)),
             "- large_instance_1 eligible (<= %d bytes): %d; skipped for budget: %d" % (
                 a.large_max_bytes, len(sizes), len(skipped_budget)), ""]
    for name in ("tiny_highs_vs_cpsat2", "large_highs_vs_cpsat2", "large_cpsat2_vs_cpsat8"):
        lines.append("## %s" % name)
        lines.append("")
        lines.append("```")
        lines.append(json.dumps(summary[name], indent=1))
        lines.append("```")
        lines.append("")
    lines += ["## Why models stayed on HiGHS (tiny)", ""]
    for k, cnt, sl in summary["not_eligible_reasons"][:25]:
        lines.append("- %d: `%s` (%s)" % (cnt, k.replace("`", "'"), ", ".join(sl)))
    lines += ["", "## Large instance, per task", "", "| task | highs | cpsat2 | cpsat8 |", "|---|---|---|---|"]
    by = {}
    for r in rows:
        if r["case"] == "large_1":
            by.setdefault(r["slug"], {})[r["arm"]] = r
    for sl in sorted(by):
        cells = []
        for arm in ("highs", "cpsat2", "cpsat8"):
            r = by[sl].get(arm)
            cells.append("" if r is None else ("%.4f" % r["score"] if r.get("status") == "accepted"
                                                else "0 (%s)" % r.get("status")))
        lines.append("| %s | %s |" % (sl, " | ".join(cells)))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", json.dumps({k: summary[k] for k in ("cpsat_eligible", "large_eligible")}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

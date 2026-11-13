"""pecin_real: MV2's pecin2017 (VRPTW) solver v0.1.1 on the public FrontierOR instances, with the official checker.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python pecin_real.py --hf-dir /data/hf --out-dir /out [--only v011-60s ...]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded) for its kit
   (frontieror_real, harness, frontieror_hf).
2. Runs this folder's solve.py (with frontier_runtime.py next to it) the contest way on the tiny + 5 large public
   instances (Hugging Face frontieror/FrontierOR, CC BY 4.0): 60 s, 10 s, 60 s with seed 7, and 300 s. Every output
   is judged by the official feasibility_check.py and by our pecin_check.py; disagreements are recorded.
   Reference = the stored Gurobi objective; score = min(2, Gurobi / ours).
3. Records the stored Gurobi answers' facts (status, runtime, gap, bound if present, number of routes) and whether our
   objective is below a stored Gurobi bound (that would mean a modelling difference, never a win).
Writes OUT/pecin2017/<variant>/..., OUT/pecin2017/summary.json, results.md.
"""
import argparse
import importlib.util
import io
import json
import os
import shutil
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "munimtechnologies/frontieror-routing"
UA = "MV2-of-Munim-Inc FrontierOR pecin2017 (mv2@munimtech.com)"
SLUG = "pecin2017"
VARIANTS = [("v011-60s", 60.0, {}), ("v011-10s", 10.0, {}), ("v011-seed7-60s", 60.0, {"MV2_PECIN_SEED": "7"}),
            ("v011-300s", 300.0, {})]
NAMES = [("tiny", "tiny_instance.json", "tiny_solution.json")] + [
    ("large_%d" % k, "large_instance_%d.json" % k, "large_solution_%d.json" % k) for k in range(1, 6)]


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


def size_info(inst):
    pp = inst["problem_parameters"]
    nodes = [v for v in inst["nodes"] if v.get("type", "customer") == "customer"]
    widths = [float(v["time_window_close"]) - float(v["time_window_open"]) for v in nodes]
    return {"n_customers": pp.get("n_customers"), "capacity": pp.get("vehicle_capacity"),
            "horizon": pp.get("planning_horizon"),
            "total_demand": sum(float(v.get("demand", 0) or 0) for v in nodes),
            "mean_window": round(sum(widths) / len(widths), 3) if widths else None}


def gurobi_facts(hf_dir, P):
    tdir = os.path.join(hf_dir, "tasks", SLUG)
    out = {}
    for name, ifile, sfile in NAMES:
        try:
            with open(os.path.join(tdir, "instance", ifile), encoding="utf-8") as f:
                inst = json.load(f)
            with open(os.path.join(tdir, "gurobi_solution", sfile), encoding="utf-8") as f:
                sol = json.load(f)
            r = P.check(inst, sol)
            keep = {k: v for k, v in sol.items() if k != "routes" and not isinstance(v, (list, dict))}
            keep.update(routes=len(sol.get("routes") or []), ours_ok=r["feasible"], ours_reason=r["reason"],
                        ours_objective=r["objective"])
            out[name] = keep
        except Exception as e:  # noqa: BLE001
            out[name] = {"error": repr(e)[:200]}
    return out


def bound_of(g):
    for k in ("best_bound", "objective_bound", "ObjBound", "bound"):
        if isinstance(g.get(k), (int, float)):
            return float(g[k])
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--scratch", default="/tmp/mv2-pecin")
    a = ap.parse_args(argv)
    out = os.path.join(a.out_dir, SLUG)
    os.makedirs(out, exist_ok=True)
    repo, sha = fetch_repo(os.path.join(a.scratch, "repo"))
    print("repo", REPO, sha, flush=True)
    sys.path.insert(0, os.path.join(repo, "kit"))
    import frontieror_real as FR  # noqa: E402
    sdir = os.path.join(a.scratch, "solver")
    if os.path.exists(sdir):
        shutil.rmtree(sdir)
    os.makedirs(sdir)
    for fn in ("solve.py", "frontier_runtime.py"):
        shutil.copyfile(os.path.join(HERE, fn), os.path.join(sdir, fn))
    solve_py = os.path.join(sdir, "solve.py")
    P = _module(os.path.join(HERE, "pecin_check.py"), "mv2_pecin_check")
    sys.path.insert(0, HERE)
    S = _module(os.path.join(HERE, "solve.py"), "mv2_pecin_solve")
    os.environ["MV2_PECIN_LOG"] = "1"
    summary = {"repo_sha": sha, "solver_version": S.__version__, "pyvrp": S.pyvrp_version(), "python": sys.version,
               "cpu_count": os.cpu_count(), "variants": {}, "checker_disagreements": []}
    try:
        summary["gurobi_facts"] = gurobi_facts(a.hf_dir, P)
    except Exception as e:  # noqa: BLE001
        summary["gurobi_facts"] = {"error": repr(e)[:300]}
    gf = summary["gurobi_facts"] if isinstance(summary["gurobi_facts"], dict) else {}
    print("gurobi_facts", json.dumps(gf, default=str)[:2500], flush=True)
    for name, tl, env in VARIANTS:
        if a.only and name not in a.only:
            continue
        vout = os.path.join(out, name)
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            FR.run_task(SLUG, solve_py, P.check, "min", a.hf_dir, vout, tl, size_info=size_info,
                        title="pecin2017 (VRPTW) solver v%s, %s" % (S.__version__, name))
        except Exception as e:  # noqa: BLE001
            summary["variants"][name] = {"error": repr(e)[:500]}
            print("variant failed", name, repr(e), flush=True)
            continue
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        with open(os.path.join(vout, "rows.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        logs = {}
        for r in rows:
            lp = os.path.join(vout, "work", r["name"] + ".solution.json.log.json")
            if os.path.exists(lp):
                with open(lp, encoding="utf-8") as f:
                    logs[r["name"]] = json.load(f)
            if r.get("official_feasible") is not None and r.get("ours_feasible") is not None and \
                    bool(r["official_feasible"]) != bool(r["ours_feasible"]):
                summary["checker_disagreements"].append({"variant": name, "case": r["name"],
                                                         "official": r["official_feasible"],
                                                         "ours": r["ours_feasible"]})
            if r.get("gurobi_official_feasible") is not None and r.get("gurobi_ours_feasible") is not None and \
                    bool(r["gurobi_official_feasible"]) != bool(r["gurobi_ours_feasible"]):
                summary["checker_disagreements"].append({"variant": name, "case": r["name"] + " (gurobi file)",
                                                         "official": r["gurobi_official_feasible"],
                                                         "ours": r["gurobi_ours_feasible"],
                                                         "reason": r.get("gurobi_ours_reason")})
        below = {}
        for r in rows:
            bb = bound_of(gf.get(r["name"]) or {})
            if bb is not None and isinstance(r.get("objective"), (int, float)):
                below[r["name"]] = r["objective"] < bb - 1e-6 * max(1.0, abs(bb))
        large = [r for r in rows if r["name"].startswith("large")]
        summary["variants"][name] = {
            "time_limit": tl, "cases": len(rows),
            "official_feasible": sum(1 for r in rows if r.get("official_feasible") is True),
            "official_rejected": {r["name"]: str(r.get("official_violations"))[:300] for r in rows
                                  if r.get("official_feasible") is False},
            "status": {r["name"]: r.get("status") for r in rows},
            "objective": {r["name"]: r.get("objective") for r in rows},
            "reference": {r["name"]: r.get("reference") for r in rows},
            "score": {r["name"]: r.get("score") for r in rows},
            "gap_pct": {r["name"]: r.get("gap_pct") for r in rows},
            "below_gurobi_bound": below,
            "large_mean_score": round(sum(r.get("score") or 0 for r in large) / len(large), 6) if large else None,
            "large_strictly_better": sum(1 for r in large if r.get("status") == "ok" and
                                         (r.get("gap_pct") if r.get("gap_pct") is not None else 0) < -1e-6),
            "wall_s": {r["name"]: r.get("wall_s") for r in rows},
            "size": {r["name"]: {k: r.get(k) for k in ("n_customers", "capacity", "horizon", "total_demand",
                                                       "mean_window")} for r in rows},
            "solver_log": logs,
        }
        with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1, default=str)
        v = summary["variants"][name]
        print("variant", name, json.dumps({k: v[k] for k in ("official_feasible", "objective", "reference",
                                                              "score", "large_mean_score", "wall_s")},
                                          default=str)[:2500], flush=True)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, default=str)
    lines = ["# pecin2017 (VRPTW) solver v%s on the public FrontierOR instances, official checker" % S.__version__, "",
             "Repository %s at %s (kit); pyvrp %s. FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY "
             "4.0). score = min(2, Gurobi's stored objective / ours); gap = 100 * (ours - Gurobi) / Gurobi, negative = "
             "better than Gurobi. Made with AI agents working in MV2's name (MV2 of Munim, Inc.)."
             % (REPO, sha, summary["pyvrp"]), "",
             "| variant | official accepts | mean score, 5 large | large better than Gurobi | per instance: ours / "
             "Gurobi |", "|---|---|---|---|---|"]
    for name, v in summary["variants"].items():
        if "error" in v:
            lines.append("| %s | error: %s | | | |" % (name, v["error"][:120]))
            continue
        per = "; ".join("%s %s / %s" % (k, None if v["objective"][k] is None else round(v["objective"][k], 3),
                                        v["reference"][k]) for k in sorted(v["objective"]))
        lines.append("| %s | %d/%d | %s | %d | %s |" % (name, v["official_feasible"], v["cases"],
                                                        v["large_mean_score"], v["large_strictly_better"], per))
    lines += ["", "Checker disagreements (ours vs official): %d" % len(summary["checker_disagreements"]), "",
              "## Stored Gurobi answers (scalar fields of the solution files)", "", "```",
              json.dumps(gf, indent=1, default=str)[:6000], "```"]
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

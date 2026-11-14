"""nagy_real: MV2's two VRPDDP solvers on the real public FrontierOR nagy2015 instances, official checker.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python nagy_real.py --hf-dir /data/hf --out-dir /out [--only sisr-60s]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded) for its kit
   (frontieror_hf, harness, frontieror_real) and for vrpddp/nagy2015/solve.py (v0.2.0, PyVRP portfolio).
2. Copies each solver into its own contest-style folder and runs it the contest way (python solve.py --problem
   nagy2015 --instance ... --output ... --time-limit T) on the tiny + 5 large public instances (Hugging Face
   frontieror/FrontierOR, CC BY 4.0), in three variants: v0.2.0 'auto' 60 s, this folder's SISR engine 60 s and 10 s.
3. Each output is judged by the official feasibility_check.py (run as a program by the kit) and by solve.verify(), our
   mirror of it. Reference = the stored Gurobi solution's objective_value; contest-style score = min(2, ref / ours).
4. Also records each stored Gurobi solution's status, MIP gap, run time and number of routes, and, per output, how
   many arcs go from a customer's pickup node straight to its own delivery node (the checker forbids them).
Writes OUT/nagy/<variant>/{rows.jsonl, results.md, ...}, OUT/nagy/summary.json, OUT/nagy/results.md.
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
UA = "MV2-of-Munim-Inc FrontierOR nagy2015 (mv2@munimtech.com)"
SLUG = "nagy2015"
# (name, time limit, which solver): "repo" = vrpddp/nagy2015/solve.py v0.2.0 from the downloaded repository (default
# engine 'auto': PyVRP portfolio + numpy search); "sisr" = this folder's standard-library SISR engine.
VARIANTS = [("v020-auto-60s", 60.0, "repo"), ("sisr-60s", 60.0, "sisr"), ("sisr-10s", 10.0, "sisr")]
REPO_SOLVER = "vrpddp/nagy2015/solve.py"
CASE_FILES = [("tiny", "tiny_solution.json")] + [("large_%d" % k, "large_solution_%d.json" % k) for k in range(1, 6)]


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
    custs = inst.get("customers", [])
    C = inst.get("vehicle_capacity") or 1
    td = sum(c.get("delivery_demand", 0) or 0 for c in custs)
    tp = sum(c.get("pickup_demand", 0) or 0 for c in custs)
    return {"n": inst.get("num_customers"), "capacity": inst.get("vehicle_capacity"), "total_delivery": td,
            "total_pickup": tp, "min_vehicles": -(-max(td, tp) // C) if isinstance(C, int) else max(td, tp) / C}


def pkg_version(name):
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:  # noqa: BLE001
        return None


def pyvrp_version():
    return pkg_version("pyvrp")


def back_to_line_arcs(inst, sol):
    """Number of arcs n+i -> i (a customer's pickup node straight to its own delivery node) in a solution."""
    try:
        n = int(inst["num_customers"])
        return sum(1 for r in sol.get("routes") or [] for a, b in zip(r, r[1:]) if 1 <= b <= n and a == b + n)
    except Exception:  # noqa: BLE001
        return None


def arcs_in_output(hf_dir, vout, name):
    ifile = "tiny_instance.json" if name == "tiny" else "large_instance_%s.json" % name.split("_")[-1]
    try:
        with open(os.path.join(hf_dir, "tasks", SLUG, "instance", ifile), encoding="utf-8") as f:
            inst = json.load(f)
        with open(os.path.join(vout, "work", name + ".solution.json"), encoding="utf-8") as f:
            sol = json.load(f)
    except Exception:  # noqa: BLE001 - no output
        return None
    return back_to_line_arcs(inst, sol)


def gurobi_stats(gsol):
    if not gsol:
        return None
    return {k: gsol.get(k) for k in ("objective_value", "status", "mip_gap", "solve_time", "runtime", "num_routes")}


def solver_log(vout, name):
    p = os.path.join(vout, "work", name + ".solution.json.log.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        return {"unreadable": repr(e)[:200]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--scratch", default="/tmp/mv2-nagy")
    a = ap.parse_args(argv)
    out = os.path.join(a.out_dir, "nagy")
    os.makedirs(out, exist_ok=True)
    repo, sha = fetch_repo(os.path.join(a.scratch, "repo"))
    print("repo", REPO, sha, flush=True)
    sys.path.insert(0, os.path.join(repo, "kit"))
    import frontieror_real as FR  # noqa: E402
    solvers = {}
    for kind, src in (("sisr", os.path.join(HERE, "solve.py")), ("repo", os.path.join(repo, REPO_SOLVER))):
        sdir = os.path.join(a.scratch, "solver-" + kind)
        if os.path.exists(sdir):
            shutil.rmtree(sdir)
        os.makedirs(sdir)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(sdir, "solve.py"))
            solvers[kind] = os.path.join(sdir, "solve.py")
    S = _module(os.path.join(HERE, "solve.py"), "mv2_nagy_solve")
    os.environ["MV2_NAGY_LOG"] = "1"
    repo_version = None
    if "repo" in solvers:
        with open(solvers["repo"], encoding="utf-8") as f:
            for line in f:
                if line.startswith("VERSION"):
                    repo_version = line.split("=", 1)[1].strip().strip("\"'")
                    break

    def chk(inst, sol):
        r = S.verify(inst, sol)
        return {"feasible": r["feasible"], "objective": r["objective"], "reason": r["reason"]}

    summary = {"repo_sha": sha, "sisr_version": S.VERSION, "repo_solver": REPO_SOLVER, "repo_solver_version":
               repo_version, "python": sys.version, "cpu_count": os.cpu_count(), "pyvrp": pyvrp_version(),
               "numpy": pkg_version("numpy"), "variants": {}, "gurobi": {}}
    for name, tl, kind in VARIANTS:
        if a.only and name not in a.only:
            continue
        vout = os.path.join(out, name)
        if kind not in solvers:
            summary["variants"][name] = {"error": "solver missing: %s" % kind}
            continue
        try:
            tally = FR.run_task(SLUG, solvers[kind], chk, "min", a.hf_dir, vout, tl, size_info=size_info,
                                title="nagy2015 (VRP with divisible deliveries and pickups), %s solver v%s, %ss"
                                      % (kind, S.VERSION if kind == "sisr" else repo_version, int(tl)))
        except Exception as e:  # noqa: BLE001 - record and go on
            summary["variants"][name] = {"error": repr(e)[:500]}
            print("variant failed", name, repr(e), flush=True)
            continue
        with open(os.path.join(vout, "rows.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        large = [r for r in rows if r["name"].startswith("large")]
        summary["variants"][name] = {
            "time_limit": tl, "solver": kind, "revision": tally.get("revision"), "cases": len(rows),
            "official_feasible": sum(1 for r in rows if r.get("official_feasible") is True),
            "ours_agree_official": sum(1 for r in rows if r.get("official_feasible") is not None
                                       and bool(r.get("official_feasible")) == bool(r.get("ours_feasible"))),
            "official_rejected": {r["name"]: str(r.get("official_violations"))[:300] for r in rows
                                  if r.get("official_feasible") is False},
            "status": {r["name"]: r.get("status") for r in rows},
            "objective": {r["name"]: r.get("objective") for r in rows},
            "reference": {r["name"]: r.get("reference") for r in rows},
            "score": {r["name"]: r.get("score") for r in rows},
            "gap_pct": {r["name"]: r.get("gap_pct") for r in rows},
            "large_mean_score": tally.get("large_mean_score"),
            "large_strictly_better": sum(1 for r in large if r.get("status") == "ok"
                                         and r.get("gap_pct", 0) < -1e-6),
            "wall_s": {r["name"]: r.get("wall_s") for r in rows},
            "gurobi_official_feasible": {r["name"]: r.get("gurobi_official_feasible") for r in rows},
            "gurobi_ours_feasible": {r["name"]: r.get("gurobi_ours_feasible") for r in rows},
            "size": {r["name"]: {k: r.get(k) for k in ("n", "capacity", "total_delivery", "total_pickup",
                                                       "min_vehicles")} for r in rows},
            "solver_log": {r["name"]: solver_log(vout, r["name"]) for r in rows},
            "back_to_line_arcs": {r["name"]: arcs_in_output(a.hf_dir, vout, r["name"]) for r in rows},
        }
        with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1, default=str)
        print("variant", name, json.dumps(summary["variants"][name], default=str)[:2000], flush=True)
    tdir = os.path.join(a.hf_dir, "tasks", SLUG)
    for name, sfile in CASE_FILES:
        try:
            with open(os.path.join(tdir, "gurobi_solution", sfile), encoding="utf-8") as f:
                summary["gurobi"][name] = gurobi_stats(json.load(f))
        except Exception as e:  # noqa: BLE001
            summary["gurobi"][name] = {"error": repr(e)[:200]}
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, default=str)
    lines = ["# MV2's nagy2015 VRPDDP solvers (%s v%s, SISR engine v%s) on the public FrontierOR instances, official "
             "checker" % (REPO_SOLVER, repo_version, S.VERSION),
             "", "Repository %s at %s (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). "
             "score = min(2, Gurobi's stored objective / ours) (the contest's rule for a minimised positive "
             "objective, here against the stored Gurobi answer, not the contest's frozen reference); gap = 100 * "
             "(ours - Gurobi) / Gurobi, negative = better. PyVRP installed: %s. Made with AI agents working in MV2's "
             "name (MV2 of Munim, Inc.)." % (REPO, sha, summary["pyvrp"]), "",
             "| variant | official accepts | mean score, 5 large | large better than Gurobi | per instance gap (%) |",
             "|---|---|---|---|---|"]
    for name, v in summary["variants"].items():
        if "error" in v:
            lines.append("| %s | error: %s | | | |" % (name, v["error"][:120]))
            continue
        per = ", ".join("%s %s" % (k, v["gap_pct"][k]) for k in sorted(v["gap_pct"]))
        lines.append("| %s | %d/%d | %s | %d | %s |" % (name, v["official_feasible"], v["cases"],
                                                       v["large_mean_score"], v["large_strictly_better"], per))
    lines += ["", "Stored Gurobi solutions (status, MIP gap, time, routes):", ""]
    for name, g in summary["gurobi"].items():
        lines.append("- %s: %s" % (name, json.dumps(g)))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

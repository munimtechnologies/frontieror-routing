"""desaulniers_real: MV2's desaulniers2010 (SDVRPTW) solver v0.1.0 on the public FrontierOR instances, official checker.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python desaulniers_real.py --hf-dir /data/hf --out-dir /out [--only v010-60s ...]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded) for its kit
   (frontieror_hf, harness, frontieror_real).
2. Runs this folder's solve.py the contest way (python solve.py --problem desaulniers2010 --instance ... --output ...
   --time-limit T) on desaulniers2010's tiny + 5 large public instances (Hugging Face frontieror/FrontierOR,
   CC BY 4.0): with PyVRP at 60 s and 10 s, and without PyVRP at 60 s.
3. Every output is judged by the official feasibility_check.py (as a program, by the kit, and its contract check +
   check_feasibility() inside our checker function, whose objective is the official recomputation). Our verify() runs
   too and every disagreement is recorded. Reference = the stored Gurobi solution's objective_value; score =
   min(2, Gurobi / ours).
4. Instance facts: n, Q, demand / Q statistics, window widths, and how many customers our final solutions split.
Writes OUT/desaulniers2010/<variant>/..., OUT/desaulniers2010/summary.json, results.md, facts.md.
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
UA = "MV2-of-Munim-Inc FrontierOR desaulniers2010 (mv2@munimtech.com)"
SLUG = "desaulniers2010"
VARIANTS = [("v010-60s", 60.0, {}), ("v010-10s", 10.0, {}), ("v010-nopyvrp-60s", 60.0, {"MV2_DESAUL_NOPYVRP": "1"})]


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
    Q = inst["vehicle_capacity"]
    d = [c["demand"] for c in inst["customers"]]
    w = [c["time_window"][1] - c["time_window"][0] for c in inst["customers"]]
    return {"n": inst["num_customers"], "Q": Q, "demand_sum": sum(d),
            "lb_vehicles": -(-sum(d) // Q) if isinstance(Q, int) else None,
            "d_over_Q_mean": round(sum(d) / len(d) / Q, 3) if d else None,
            "d_over_half_Q": sum(1 for x in d if x > Q / 2.0),
            "d_over_Q": sum(1 for x in d if x > Q),
            "tw_mean": round(sum(w) / len(w), 1) if w else None,
            "depot_tw": inst["depot"]["time_window"],
            "svc": sorted({c.get("service_time", 0) for c in inst["customers"]})[:4]}


DISAGREE = []


def make_checker(hf_dir, solver_mod):
    cache = {}

    def chk(inst, sol):
        try:
            if "off" not in cache:
                cache["off"] = _module(os.path.join(hf_dir, "tasks", SLUG, "feasibility_check.py"), "desaul_official")
            off = cache["off"]
            contract = off._frontieror_validate_solution_contract(sol)
            r = contract if contract is not None else off.check_feasibility(inst, sol)
            pb = solver_mod.Problem(inst)
            routes = []
            for x in sol.get("routes") or []:
                seq = list(x["route"])
                if len(seq) >= 2 and seq[0] == 0 and seq[-1] == pb.sink:
                    seq = seq[1:-1]
                routes.append(solver_mod.Route(seq, {int(k): v for k, v in (x.get("deliveries") or {}).items()}))
            obj = solver_mod.total_cost(pb, routes)
            ours, why = solver_mod.verify(pb, routes)
            o = bool(r.get("feasible"))
            if ours != o:
                DISAGREE.append({"official": o, "ours": ours, "why": why, "violated": r.get("violated_constraints"),
                                 "violations": str(r.get("violations"))[:300]})
            return {"feasible": o, "objective": obj,
                    "reason": "violated %s; ours %s %s" % (r.get("violated_constraints"), ours, why)}
        except Exception as e:  # noqa: BLE001 - a crash is a rejection, recorded
            return {"feasible": False, "objective": None, "reason": "checker error %r" % (e,)}
    return chk


def solver_log(vout, name):
    p = os.path.join(vout, "work", name + ".solution.json.log.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            lg = json.load(f)
        ev = lg.get("events") or []
        lg["events"] = ev[:3] + ev[-6:] if len(ev) > 9 else ev
        lg.pop("verify_fail", None) if not lg.get("verify_fail") else None
        return lg
    except Exception as e:  # noqa: BLE001
        return {"unreadable": repr(e)[:200]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--scratch", default="/tmp/mv2-desaul")
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
    shutil.copyfile(os.path.join(HERE, "solve.py"), os.path.join(sdir, "solve.py"))
    solve_py = os.path.join(sdir, "solve.py")
    solver_mod = _module(os.path.join(HERE, "solve.py"), "mv2_desaul_solve")
    os.environ["MV2_DESAUL_LOG"] = "1"
    chk = make_checker(a.hf_dir, solver_mod)
    try:
        import pyvrp  # noqa: F401
        have_pyvrp = True
    except Exception:  # noqa: BLE001
        have_pyvrp = False
    summary = {"repo_sha": sha, "solver_version": solver_mod.VERSION, "python": sys.version,
               "cpu_count": os.cpu_count(), "pyvrp_importable": have_pyvrp, "variants": {}}
    for name, tl, env in VARIANTS:
        if a.only and name not in a.only:
            continue
        vout = os.path.join(out, name)
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            tally = FR.run_task(SLUG, solve_py, chk, "min", a.hf_dir, vout, tl, size_info=size_info,
                                title="desaulniers2010 (SDVRPTW) solver v%s, %s" % (solver_mod.VERSION, name))
        except Exception as e:  # noqa: BLE001 - record and go on
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
        large = [r for r in rows if r["name"].startswith("large")]
        logs = {r["name"]: solver_log(vout, r["name"]) for r in rows}
        summary["variants"][name] = {
            "time_limit": tl, "revision": tally.get("revision"), "cases": len(rows),
            "official_feasible": sum(1 for r in rows if r.get("official_feasible") is True),
            "official_rejected": {r["name"]: str(r.get("official_violations"))[:300] for r in rows
                                  if r.get("official_feasible") is False},
            "status": {r["name"]: r.get("status") for r in rows},
            "objective": {r["name"]: r.get("objective") for r in rows},
            "reference": {r["name"]: r.get("reference") for r in rows},
            "score": {r["name"]: r.get("score") for r in rows},
            "gap_pct": {r["name"]: r.get("gap_pct") for r in rows},
            "large_mean_score": round(sum(r["score"] for r in large) / len(large), 6) if large else None,
            "large_strictly_better": sum(1 for r in large if r.get("status") == "ok" and r.get("gap_pct", 0) < -1e-6),
            "large_score_2": sum(1 for r in large if r.get("score", 0) >= 2.0 - 1e-9),
            "wall_s": {r["name"]: r.get("wall_s") for r in rows},
            "gurobi_official_feasible": {r["name"]: r.get("gurobi_official_feasible") for r in rows},
            "gurobi_log": {r["name"]: r.get("gurobi_log") for r in rows},
            "size": {r["name"]: {k: r.get(k) for k in ("n", "Q", "demand_sum", "lb_vehicles", "d_over_Q_mean",
                                                       "d_over_half_Q", "d_over_Q", "tw_mean", "depot_tw", "svc")}
                     for r in rows},
            "unsplit_best": {k: (v or {}).get("unsplit_best") for k, v in logs.items()},
            "split_customers": {k: (v or {}).get("split_customers") for k, v in logs.items()},
            "final_routes": {k: (v or {}).get("final_routes") for k, v in logs.items()},
            "pyvrp_used": {k: (v or {}).get("pyvrp_used") for k, v in logs.items()},
            "solver_log": logs,
        }
        summary["checker_disagreements"] = list(DISAGREE)
        with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1, default=str)
        print("variant", name, json.dumps({k: v for k, v in summary["variants"][name].items()
                                           if k != "solver_log"}, default=str)[:2500], flush=True)
    summary["checker_disagreements"] = list(DISAGREE)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, default=str)
    lines = ["# desaulniers2010 (SDVRPTW) solver v%s on the public FrontierOR instances, official checker"
             % solver_mod.VERSION, "",
             "Repository %s at %s (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). "
             "score = min(2, Gurobi's stored objective / ours); gap = 100 * (ours - Gurobi) / Gurobi, negative = "
             "better than Gurobi. 'unsplit' = best cost before the split-delivery step. Made with AI agents working "
             "in MV2's name (MV2 of Munim, Inc.)." % (REPO, sha), "",
             "| variant | official accepts | mean score, 5 large | large better than Gurobi | per instance: ours / "
             "unsplit / Gurobi (split customers) |", "|---|---|---|---|---|"]
    for name, v in summary["variants"].items():
        if "error" in v:
            lines.append("| %s | error: %s | | | |" % (name, v["error"][:120]))
            continue
        per = "; ".join("%s %s / %s / %s (%s)" % (
            k, None if v["objective"][k] is None else round(v["objective"][k], 1),
            None if v["unsplit_best"].get(k) is None else round(v["unsplit_best"][k], 1),
            v["reference"][k], v["split_customers"].get(k)) for k in sorted(v["objective"]))
        lines.append("| %s | %d/%d | %s | %d | %s |" % (name, v["official_feasible"], v["cases"],
                                                        v["large_mean_score"], v["large_strictly_better"], per))
    lines += ["", "Checker disagreements (ours vs official): %d" % len(DISAGREE)]
    first = next((v for v in summary["variants"].values() if "size" in v), None)
    if first:
        lines += ["", "## Instance facts", "", "| instance | n | Q | demand sum | capacity bound | mean d/Q | "
                  "d > Q/2 | d > Q | mean window | depot window | service |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for k in sorted(first["size"]):
            s = first["size"][k]
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                k, s["n"], s["Q"], s["demand_sum"], s["lb_vehicles"], s["d_over_Q_mean"], s["d_over_half_Q"],
                s["d_over_Q"], s["tw_mean"], s["depot_tw"], s["svc"]))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

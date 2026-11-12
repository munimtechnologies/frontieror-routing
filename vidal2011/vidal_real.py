"""vidal_real: MV2's vidal2011 (MDPVRP) solver v0.1.0 on the public FrontierOR instances, official checker.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python vidal_real.py --hf-dir /data/hf --out-dir /out [--only v010-60s ...]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded) for its kit
   (frontieror_hf, harness, frontieror_real).
2. Runs this folder's solve.py the contest way (python solve.py --problem vidal2011 --instance ... --output ...
   --time-limit T) on vidal2011's tiny + 5 large public instances (Hugging Face frontieror/FrontierOR, CC BY 4.0)
   at 60 s, 10 s and 300 s, and at 60 s with one worker (no forked second seed).
3. Every output is judged by the official feasibility_check.py (as a program, by the kit, and its contract check +
   check_feasibility() inside our checker function). Our verify() runs too and every disagreement is recorded.
   Reference = the stored Gurobi solution's objective_value; score = min(2, Gurobi / ours).
4. Instance facts: n, d, t, m, Q, T, visits, patterns per customer, and how full the fleet must be.
Writes OUT/vidal2011/<variant>/..., OUT/vidal2011/summary.json, results.md.
"""
import argparse
import importlib.util
import io
import json
import math
import os
import shutil
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "munimtechnologies/frontieror-routing"
UA = "MV2-of-Munim-Inc FrontierOR vidal2011 (mv2@munimtech.com)"
SLUG = "vidal2011"
VARIANTS = [("v010-60s", 60.0, {}), ("v010-10s", 10.0, {}), ("v010-300s", 300.0, {}),
            ("v010-1w-60s", 60.0, {"MV2_VIDAL_WORKERS": "1"})]


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
    cs = inst["customers"]
    Q = inst["vehicle_capacity"]
    d, t, m = inst["d"], inst["t"], inst["m"]
    visits = sum(int(c["frequency"]) for c in cs)
    load = sum(c["demand"] * int(c["frequency"]) for c in cs)
    npat = [len(c["pattern_list"]) for c in cs]
    return {"n": inst["n"], "d": d, "t": t, "m": m, "Q": Q, "T": inst["route_duration_limit"],
            "visits": visits, "patterns_mean": round(sum(npat) / max(1, len(npat)), 2),
            "patterns_max": max(npat) if npat else None,
            "lb_routes": int(math.ceil(load / float(Q))) if Q else None, "route_slots": d * t * m,
            "fleet_load_share": round(load / float(d * t * m * Q), 3) if Q else None,
            "has_p_key": "p" in inst}


DISAGREE = []


def make_checker(hf_dir, solver_mod):
    cache = {}

    def chk(inst, sol):
        try:
            if "off" not in cache:
                cache["off"] = _module(os.path.join(hf_dir, "tasks", SLUG, "feasibility_check.py"), "vidal_official")
            off = cache["off"]
            contract = off._frontieror_validate_solution_contract(sol)
            r = contract if contract is not None else off.check_feasibility(inst, sol)
            pb = solver_mod.Problem(inst)
            ours, why, cost = solver_mod.verify(pb, sol)
            if cost is None:  # still report the official recomputation basis: sum of route costs
                cost = 0.0
                for x in sol.get("routes") or []:
                    cost += pb.route_eval(x["depot"], [pb.d + c for c in x["customers"]])[0]
            o = bool(r.get("feasible"))
            if ours != o:
                DISAGREE.append({"official": o, "ours": ours, "why": why, "violated": r.get("violated_constraints"),
                                 "violations": str(r.get("violations"))[:300]})
            return {"feasible": o, "objective": cost,
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
        lg["events_count"] = len(ev)
        lg["events"] = ev[:3] + ev[-6:] if len(ev) > 9 else ev
        return lg
    except Exception as e:  # noqa: BLE001
        return {"unreadable": repr(e)[:200]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--scratch", default="/tmp/mv2-vidal")
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
    solver_mod = _module(os.path.join(HERE, "solve.py"), "mv2_vidal_solve")
    os.environ["MV2_VIDAL_LOG"] = "1"
    chk = make_checker(a.hf_dir, solver_mod)
    summary = {"repo_sha": sha, "solver_version": solver_mod.VERSION, "python": sys.version,
               "cpu_count": os.cpu_count(), "variants": {}}
    for name, tl, env in VARIANTS:
        if a.only and name not in a.only:
            continue
        vout = os.path.join(out, name)
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            tally = FR.run_task(SLUG, solve_py, chk, "min", a.hf_dir, vout, tl, size_info=size_info,
                                title="vidal2011 (MDPVRP) solver v%s, %s" % (solver_mod.VERSION, name))
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
            "gurobi_ours_feasible": {r["name"]: r.get("gurobi_ours_feasible") for r in rows},
            "gurobi_log": {r["name"]: r.get("gurobi_log") for r in rows},
            "size": {r["name"]: {k: r.get(k) for k in ("n", "d", "t", "m", "Q", "T", "visits", "patterns_mean",
                                                       "patterns_max", "lb_routes", "route_slots",
                                                       "fleet_load_share", "has_p_key")} for r in rows},
            "construction": {k: (v or {}).get("construction") for k, v in logs.items()},
            "best_source": {k: (v or {}).get("best_source") for k, v in logs.items()},
            "iterations": {k: ((v or {}).get("search") or {}).get("iterations") for k, v in logs.items()},
            "child": {k: (v or {}).get("child") for k, v in logs.items()},
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
    lines = ["# vidal2011 (MDPVRP) solver v%s on the public FrontierOR instances, official checker"
             % solver_mod.VERSION, "",
             "Repository %s at %s (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). "
             "score = min(2, Gurobi's stored objective / ours); gap = 100 * (ours - Gurobi) / Gurobi, negative = "
             "better than Gurobi. Made with AI agents working in MV2's name (MV2 of Munim, Inc.)." % (REPO, sha), "",
             "| variant | official accepts | mean score, 5 large | large better than Gurobi | per instance: ours / "
             "Gurobi |", "|---|---|---|---|---|"]
    for name, v in summary["variants"].items():
        if "error" in v:
            lines.append("| %s | error: %s | | | |" % (name, v["error"][:120]))
            continue
        per = "; ".join("%s %s / %s" % (k, None if v["objective"][k] is None else round(v["objective"][k], 2),
                                        None if v["reference"][k] is None else round(v["reference"][k], 2))
                        for k in sorted(v["objective"]))
        lines.append("| %s | %d/%d | %s | %d | %s |" % (name, v["official_feasible"], v["cases"],
                                                        v["large_mean_score"], v["large_strictly_better"], per))
    lines += ["", "Checker disagreements (ours vs official): %d" % len(DISAGREE)]
    first = next((v for v in summary["variants"].values() if "size" in v), None)
    if first:
        lines += ["", "## Instance facts", "", "| instance | n | d | t | m | Q | T | visits | patterns (mean/max) | "
                  "route lower bound | route slots | fleet load share |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for k in sorted(first["size"]):
            s = first["size"][k]
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s/%s | %s | %s | %s |" % (
                k, s["n"], s["d"], s["t"], s["m"], s["Q"], s["T"], s["visits"], s["patterns_mean"],
                s["patterns_max"], s["lb_routes"], s["route_slots"], s["fleet_load_share"]))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

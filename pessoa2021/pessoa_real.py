"""pessoa_real: MV2's pessoa2021 (robust CVRP) solver on the public FrontierOR instances, official checker.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python pessoa_real.py --hf-dir /data/hf --out-dir /out [--only v010-60s ...]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded) for its kit
   (frontieror_hf, harness, frontieror_real).
2. Runs this folder's solve.py the contest way (python solve.py --problem pessoa2021 --instance ... --output ...
   --time-limit T) on the tiny + 5 large public instances (Hugging Face frontieror/FrontierOR, CC BY 4.0): 60 s,
   10 s, 60 s with one worker (no forked second search), 60 s with another seed, and 300 s.
3. Every output is judged by the official feasibility_check.py (run as a program by the kit); our verify() runs too
   and every disagreement is recorded. Reference = the stored Gurobi solution's objective_value;
   score = min(2, Gurobi / ours).
4. Records instance facts: customers, vehicles, capacity, Gamma, symmetric costs, and how tight the capacity is
   (sum of nominal demands / (m C); sum of nominal + deviation / (m C)); and, for the stored Gurobi answer, its
   route count and largest worst-case load.
Writes OUT/pessoa2021/<variant>/..., OUT/pessoa2021/summary.json, results.md.
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
UA = "MV2-of-Munim-Inc FrontierOR pessoa2021 (mv2@munimtech.com)"
SLUG = "pessoa2021"
VARIANTS = [("v010-60s", 60.0, {}), ("v010-10s", 10.0, {}), ("v010-1w-60s", 60.0, {"MV2_RCVRP_WORKERS": "1"}),
            ("v010-seed7-60s", 60.0, {"MV2_RCVRP_SEED": "7"}), ("v010-300s", 300.0, {})]


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


def make_size_info(solver_mod):
    def size_info(inst):
        pb = solver_mod.Problem(inst)
        nom = sum(pb.bar[1:])
        rob = sum(pb.bar[i] + pb.hat[i] for i in range(1, pb.n + 1))
        cap = float(pb.m * pb.C) if pb.m * pb.C else 1.0
        return {"n": pb.n, "m": pb.m, "C": pb.C, "Gamma": pb.G, "symmetric": pb.sym,
                "tight_nominal": round(nom / cap, 4), "tight_full_deviation": round(rob / cap, 4),
                "max_dist": pb.maxd}
    return size_info


DISAGREE = []


def make_checker(solver_mod):
    cache = {}

    def chk(inst, sol):
        try:
            key = id(inst)
            if key not in cache or cache[key][0] is not inst:
                cache.clear()
                cache[key] = (inst, solver_mod.Problem(inst))  # holding inst keeps its id unique while cached
            pb = cache[key][1]
            ok, why, obj = solver_mod.verify(pb, sol)
            return {"feasible": ok, "objective": obj, "reason": why}
        except Exception as e:  # noqa: BLE001 - a crash is a rejection, recorded
            return {"feasible": False, "objective": None, "reason": "checker error %r" % (e,)}
    return chk


def gurobi_facts(hf_dir, solver_mod):
    """Route count and largest worst-case load of each stored Gurobi answer."""
    tdir = os.path.join(hf_dir, "tasks", SLUG)
    out = {}
    names = [("tiny", "tiny_instance.json", "tiny_solution.json")] + [
        ("large_%d" % k, "large_instance_%d.json" % k, "large_solution_%d.json" % k) for k in range(1, 6)]
    for name, ifile, sfile in names:
        try:
            with open(os.path.join(tdir, "instance", ifile), encoding="utf-8") as f:
                inst = json.load(f)
            with open(os.path.join(tdir, "gurobi_solution", sfile), encoding="utf-8") as f:
                sol = json.load(f)
            pb = solver_mod.Problem(inst)
            loads = [pb.worst_case(r["customers"]) for r in sol.get("routes", [])]
            out[name] = {"routes": len(sol.get("routes", [])), "nonempty": sum(1 for r in sol.get("routes", [])
                                                                              if r.get("customers")),
                         "max_load": max(loads) if loads else None, "C": pb.C, "status": sol.get("status"),
                         "runtime": sol.get("runtime"), "objective_value": sol.get("objective_value")}
        except Exception as e:  # noqa: BLE001
            out[name] = {"error": repr(e)[:200]}
    return out


def empty_route_probe(FR, hf_dir, scratch):
    """Does the official checker accept an answer that pads the m routes with empty ones?

    The problem text asks for one route per vehicle and the Gurobi model sends exactly m vehicles out of the depot,
    each to a customer; the checker counts len(routes) and skips the capacity test for an empty route. A synthetic
    6-customer, 3-vehicle instance with a large capacity is judged twice: all customers on one route plus two empty
    routes (cheaper, as costs are Euclidean), and three non-empty routes. Recorded only; our solver never pads."""
    import math
    pts = [(0, 0), (10, 0), (20, 0), (30, 0), (0, 10), (0, 20), (0, 30)]
    D = [[int(round(math.hypot(a[0] - b[0], a[1] - b[1]))) for b in pts] for a in pts]
    inst = {"num_customers": 6, "num_vehicles": 3, "vehicle_capacity": 1000, "uncertainty_set": {"Gamma": 1},
            "depot": {"id": 0, "x": 0, "y": 0},
            "customers": [{"id": i, "x": pts[i][0], "y": pts[i][1], "nominal_demand": 5, "demand_deviation": 2}
                          for i in range(1, 7)], "distance_matrix": D}

    def cost(seq):
        prev, c = 0, 0
        for v in seq:
            c += D[prev][v]
            prev = v
        return c + D[prev][0]
    padded = [[1, 2, 3, 6, 5, 4], [], []]
    full = [[1, 2, 3], [4, 5], [6]]
    os.makedirs(scratch, exist_ok=True)
    ip = os.path.join(scratch, "probe_instance.json")
    with open(ip, "w", encoding="utf-8") as f:
        json.dump(inst, f)
    checker_py = os.path.join(hf_dir, "tasks", SLUG, "feasibility_check.py")
    out = {}
    for name, routes in (("padded_with_2_empty_routes", padded), ("three_nonempty_routes", full)):
        sol = {"objective_value": float(sum(cost(r) for r in routes)), "status": "feasible",
               "routes": [{"customers": r, "cost": cost(r), "worst_case_demand": 5 * len(r) + (2 if r else 0)}
                          for r in routes]}
        sp = os.path.join(scratch, "probe_%s.json" % name)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(sol, f)
        try:
            o = FR.official(checker_py, ip, sp, os.path.join(scratch, "probe_%s.result.json" % name))
        except Exception as e:  # noqa: BLE001
            o = {"error": repr(e)[:200]}
        o["objective_value"] = sol["objective_value"]
        out[name] = o
    return out


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
    ap.add_argument("--scratch", default="/tmp/mv2-rcvrp")
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
    solver_mod = _module(os.path.join(HERE, "solve.py"), "mv2_rcvrp_solve")
    os.environ["MV2_RCVRP_LOG"] = "1"
    chk = make_checker(solver_mod)
    size_info = make_size_info(solver_mod)
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
                                title="pessoa2021 (robust CVRP) solver v%s, %s" % (solver_mod.VERSION, name))
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
        if "gurobi_facts" not in summary:
            summary["gurobi_facts"] = gurobi_facts(a.hf_dir, solver_mod)
            try:
                summary["empty_route_probe"] = empty_route_probe(FR, a.hf_dir, os.path.join(a.scratch, "probe"))
            except Exception as e:  # noqa: BLE001
                summary["empty_route_probe"] = {"error": repr(e)[:300]}
            print("empty_route_probe", json.dumps(summary["empty_route_probe"], default=str)[:1500], flush=True)
        with open(os.path.join(vout, "rows.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        for r in rows:
            if r.get("official_feasible") is not None and r.get("ours_feasible") is not None and \
                    bool(r["official_feasible"]) != bool(r["ours_feasible"]):
                DISAGREE.append({"variant": name, "case": r["name"], "official": r["official_feasible"],
                                 "ours": r["ours_feasible"], "violations": str(r.get("official_violations"))[:300]})
            if r.get("gurobi_official_feasible") is not None and r.get("gurobi_ours_feasible") is not None and \
                    bool(r["gurobi_official_feasible"]) != bool(r["gurobi_ours_feasible"]):
                DISAGREE.append({"variant": name, "case": r["name"] + " (gurobi file)",
                                 "official": r["gurobi_official_feasible"], "ours": r["gurobi_ours_feasible"],
                                 "reason": r.get("gurobi_ours_reason")})
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
            "large_matched_or_better": sum(1 for r in large if r.get("status") == "ok" and
                                           r.get("gap_pct", 99) <= 1e-6),
            "wall_s": {r["name"]: r.get("wall_s") for r in rows},
            "gurobi_official_feasible": {r["name"]: r.get("gurobi_official_feasible") for r in rows},
            "gurobi_ours_feasible": {r["name"]: r.get("gurobi_ours_feasible") for r in rows},
            "gurobi_log": {r["name"]: r.get("gurobi_log") for r in rows},
            "size": {r["name"]: {k: r.get(k) for k in ("n", "m", "C", "Gamma", "symmetric", "tight_nominal",
                                                       "tight_full_deviation", "max_dist")} for r in rows},
            "construction": {k: (v or {}).get("parent", {}).get("construction") for k, v in logs.items()},
            "construction_feasible": {k: (v or {}).get("parent", {}).get("construction_feasible")
                                      for k, v in logs.items()},
            "best_source": {k: (v or {}).get("best_source") for k, v in logs.items()},
            "iterations_parent": {k: (v or {}).get("parent", {}).get("iterations") for k, v in logs.items()},
            "iterations_child": {k: ((v or {}).get("child") or {}).get("iterations") for k, v in logs.items()},
            "load_s": {k: (v or {}).get("load_s") for k, v in logs.items()},
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
    lines = ["# pessoa2021 (robust CVRP) solver v%s on the public FrontierOR instances, official checker"
             % solver_mod.VERSION, "",
             "Repository %s at %s (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). "
             "score = min(2, Gurobi's stored objective / ours); gap = 100 * (ours - Gurobi) / Gurobi, negative = "
             "better than Gurobi. Made with AI agents working in MV2's name (MV2 of Munim, Inc.)." % (REPO, sha), "",
             "| variant | official accepts | mean score, 5 large | large better than Gurobi | large matched or better "
             "| per instance: ours / Gurobi |", "|---|---|---|---|---|---|"]
    for name, v in summary["variants"].items():
        if "error" in v:
            lines.append("| %s | error: %s | | | | |" % (name, v["error"][:120]))
            continue
        per = "; ".join("%s %s / %s" % (k, v["objective"][k], v["reference"][k]) for k in sorted(v["objective"]))
        lines.append("| %s | %d/%d | %s | %d | %d | %s |" % (name, v["official_feasible"], v["cases"],
                                                             v["large_mean_score"], v["large_strictly_better"],
                                                             v["large_matched_or_better"], per))
    lines += ["", "Checker disagreements (ours vs official): %d" % len(DISAGREE)]
    first = next((v for v in summary["variants"].values() if "size" in v), None)
    if first:
        lines += ["", "## Instance facts", "",
                  "| instance | customers | vehicles | capacity | Gamma | symmetric | nominal / (m C) "
                  "| nominal + deviation / (m C) | Gurobi status, runtime s |", "|---|---|---|---|---|---|---|---|---|"]
        gf = summary.get("gurobi_facts", {})
        for k in sorted(first["size"]):
            s = first["size"][k]
            g = gf.get(k, {})
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s, %s |" % (
                k, s.get("n"), s.get("m"), s.get("C"), s.get("Gamma"), s.get("symmetric"), s.get("tight_nominal"),
                s.get("tight_full_deviation"), g.get("status"), g.get("runtime")))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""bode_real: MV2's bode2012 (capacitated arc routing) solver on the public FrontierOR instances, official checker.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python bode_real.py --hf-dir /data/hf --out-dir /out [--only v010-60s ...]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded) for its kit
   (frontieror_hf, harness, frontieror_real).
2. Runs this folder's solve.py the contest way (python solve.py --problem bode2012 --instance ... --output ...
   --time-limit T) on the tiny + 5 large public instances (Hugging Face frontieror/FrontierOR, CC BY 4.0): 60 s,
   10 s, 60 s with one worker (no forked second search) and 60 s with another seed.
3. Every output is judged by the official feasibility_check.py (run as a program by the kit); our verify() runs too
   and every disagreement is recorded. Reference = the stored Gurobi solution's objective_value;
   score = min(2, Gurobi / ours).
4. Records instance facts (nodes, edges, required edges, vehicles, capacity, total demand / (K Q), the constant
   service-cost part) and, for each stored Gurobi answer, its working-vehicle count, status and runtime.
5. fleet_probe: does the official checker count vehicles? A synthetic 2-edge path with ONE vehicle whose capacity
   holds one edge is judged with an answer that uses two working vehicles. Recorded only; our solver never uses more
   vehicles than the fleet has.
Writes OUT/bode2012/<variant>/..., OUT/bode2012/summary.json, results.md.
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
UA = "MV2-of-Munim-Inc FrontierOR bode2012 (mv2@munimtech.com)"
SLUG = "bode2012"
VARIANTS = [("v010-60s", 60.0, {}), ("v010-10s", 10.0, {}), ("v010-1w-60s", 60.0, {"MV2_CARP_WORKERS": "1"}),
            ("v010-seed7-60s", 60.0, {"MV2_CARP_SEED": "7"})]


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
        tot = sum(pb.dem)
        cap = float(pb.K * pb.Q) if pb.K * pb.Q else 1.0
        return {"nodes": pb.N, "edges": len(pb.edges), "required": pb.R, "K": pb.K, "Q": pb.Q,
                "tight": round(tot / cap, 4), "service_total": pb.service_total}
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
            ok, why, obj = solver_mod.verify(pb, sol, strict_fleet=False)
            return {"feasible": ok, "objective": obj, "reason": why}
        except Exception as e:  # noqa: BLE001 - a crash is a rejection, recorded
            return {"feasible": False, "objective": None, "reason": "checker error %r" % (e,)}
    return chk


def gurobi_facts(hf_dir, solver_mod):
    """Working-vehicle count, status and runtime of each stored Gurobi answer; whether it keeps to the fleet."""
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
            rts = sol.get("routes") or []
            busy = sum(1 for r in rts if r.get("serviced_edges"))
            ok, why, obj = solver_mod.verify(pb, sol, strict_fleet=True)
            out[name] = {"routes": len(rts), "working_vehicles": busy, "K": pb.K,
                         "deadhead": (None if sol.get("objective_value") is None
                                      else sol["objective_value"] - pb.service_total),
                         "status": sol.get("status_str", sol.get("status")), "runtime": sol.get("runtime"),
                         "objective_value": sol.get("objective_value"), "ours_strict_ok": ok, "ours_reason": why}
        except Exception as e:  # noqa: BLE001
            out[name] = {"error": repr(e)[:200]}
    return out


def fleet_probe(FR, hf_dir, scratch):
    """Two required edges in a path 0-1-2, one vehicle that can carry one of them. Answer A uses two working
    vehicles (each feasible on its own); answer B is the honest single-vehicle answer (over capacity)."""
    inst = {"graph": {"num_nodes": 3, "num_edges": 2, "type": "undirected"}, "depot": 0,
            "fleet": {"num_vehicles": 1, "vehicle_capacity": 5, "type": "homogeneous"},
            "num_required_edges": 2, "total_demand": 10,
            "edges": [{"edge_id": 0, "endpoints": [0, 1], "cost": 3, "is_required": True, "demand": 5,
                       "service_cost": 3},
                      {"edge_id": 1, "endpoints": [1, 2], "cost": 4, "is_required": True, "demand": 5,
                       "service_cost": 4}]}
    two = {"objective_value": float(3 + 3 + 3 * 2 + 4 + 4), "routes": [
        {"vehicle": 0, "serviced_edges": [0], "deadheaded_edges": [{"edge_id": 0, "times": 1}]},
        {"vehicle": 1, "serviced_edges": [1], "deadheaded_edges": [{"edge_id": 0, "times": 2},
                                                                   {"edge_id": 1, "times": 1}]}]}
    one = {"objective_value": float(3 + 4 + 4 + 3), "routes": [
        {"vehicle": 0, "serviced_edges": [0, 1], "deadheaded_edges": [{"edge_id": 0, "times": 1},
                                                                      {"edge_id": 1, "times": 1}]}]}
    os.makedirs(scratch, exist_ok=True)
    ip = os.path.join(scratch, "probe_instance.json")
    with open(ip, "w", encoding="utf-8") as f:
        json.dump(inst, f)
    checker_py = os.path.join(hf_dir, "tasks", SLUG, "feasibility_check.py")
    out = {}
    for name, sol in (("two_working_vehicles_fleet_of_one", two), ("one_vehicle_over_capacity", one)):
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
    ap.add_argument("--scratch", default="/tmp/mv2-carp")
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
    solver_mod = _module(os.path.join(HERE, "solve.py"), "mv2_carp_solve")
    os.environ["MV2_CARP_LOG"] = "1"
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
                                title="bode2012 (capacitated arc routing) solver v%s, %s" % (solver_mod.VERSION, name))
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
                summary["fleet_probe"] = fleet_probe(FR, a.hf_dir, os.path.join(a.scratch, "probe"))
            except Exception as e:  # noqa: BLE001
                summary["fleet_probe"] = {"error": repr(e)[:300]}
            print("fleet_probe", json.dumps(summary["fleet_probe"], default=str)[:1500], flush=True)
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
            "size": {r["name"]: {k: r.get(k) for k in ("nodes", "edges", "required", "K", "Q", "tight",
                                                       "service_total")} for r in rows},
            "construction": {k: (v or {}).get("parent", {}).get("construction") for k, v in logs.items()},
            "construction_feasible": {k: (v or {}).get("parent", {}).get("construction_feasible")
                                      for k, v in logs.items()},
            "best_source": {k: (v or {}).get("best_source") for k, v in logs.items()},
            "iterations_parent": {k: (v or {}).get("parent", {}).get("iterations") for k, v in logs.items()},
            "iterations_child": {k: ((v or {}).get("child") or {}).get("iterations") for k, v in logs.items()},
            "first_event": {k: ((v or {}).get("parent", {}).get("events") or [None])[0] for k, v in logs.items()},
            "last_event": {k: ((v or {}).get("parent", {}).get("events") or [None])[-1] for k, v in logs.items()},
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
    lines = ["# bode2012 (capacitated arc routing) solver v%s on the public FrontierOR instances, official checker"
             % solver_mod.VERSION, "",
             "Repository %s at %s (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). "
             "score = min(2, Gurobi's stored objective / ours); gap = 100 * (ours - Gurobi) / Gurobi, negative = "
             "better than Gurobi. Objectives include the constant service-cost part. Made with AI agents working "
             "in MV2's name (MV2 of Munim, Inc.)." % (REPO, sha), "",
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
                  "| instance | nodes | edges | required | vehicles | capacity | demand / (K Q) | service part "
                  "| Gurobi working vehicles, status, runtime s |", "|---|---|---|---|---|---|---|---|---|"]
        gf = summary.get("gurobi_facts", {})
        for k in sorted(first["size"]):
            s = first["size"][k]
            g = gf.get(k, {})
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s, %s, %s |" % (
                k, s.get("nodes"), s.get("edges"), s.get("required"), s.get("K"), s.get("Q"), s.get("tight"),
                s.get("service_total"), g.get("working_vehicles"), g.get("status"), g.get("runtime")))
    fp = summary.get("fleet_probe") or {}
    if fp:
        lines += ["", "## Fleet probe (official checker, synthetic instance, recorded only)", ""]
        for k, v in fp.items():
            lines.append("- %s: feasible=%s, objective %s" % (k, v.get("feasible"), v.get("objective_value")))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

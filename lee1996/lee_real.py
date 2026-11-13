"""lee_real: MV2's lee1996 (Steiner tree-star) solver on the public FrontierOR instances, plus three checker probes.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python lee_real.py --hf-dir /data/hf --out-dir /out [--only v010-60s ...]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded) for its kit.
2. Runs this folder's solve.py the contest way on the tiny + 5 large public instances (Hugging Face
   frontieror/FrontierOR, CC BY 4.0): 60 s, 10 s, and 60 s with another seed. Every output is judged by the official
   feasibility_check.py and by our verify(); disagreements are recorded. Reference = the stored Gurobi objective;
   score = min(2, Gurobi / ours).
3. Records the stored Gurobi answers' facts (status, runtime, MIP gap, best bound, number of active hubs) and
   whether our objective is below Gurobi's proven bound (that would mean a modelling difference, not a win).
4. Checker probes (tests of the official checker, never entries, never written as a solution): from our own 60 s
   solution of each instance with at least 3 active hubs, the most expensive tree edge (j, k) is
   (a) "selfloop": replaced by the self-loop [j, j], objective restated to the recomputed cost;
   (b) "dropedge": removed, objective restated (one edge too few, so it must be rejected);
   (c) "objlow": unchanged, but objective_value reported 0.05% below the true cost (inside the checker's 0.1%
       tolerance).
   The official verdict on each is recorded in probes.md.
Writes OUT/lee1996/<variant>/..., OUT/lee1996/summary.json, results.md, probes.md, probes.jsonl.
"""
import argparse
import copy
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "munimtechnologies/frontieror-routing"
UA = "MV2-of-Munim-Inc FrontierOR lee1996 (mv2@munimtech.com)"
SLUG = "lee1996"
VARIANTS = [("v010-60s", 60.0, {}), ("v010-10s", 10.0, {}), ("v010-seed7-60s", 60.0, {"MV2_LEE_SEED": "7"})]
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


def make_checker(L):
    cache = {}

    def chk(inst, sol):
        try:
            key = id(inst)
            if key not in cache or cache[key][0] is not inst:
                cache.clear()
                cache[key] = (inst, L.Problem(inst))
            ok, why, obj = L.verify(cache[key][1], sol)
            return {"feasible": ok, "objective": obj, "reason": why}
        except Exception as e:  # noqa: BLE001
            return {"feasible": False, "objective": None, "reason": "checker error %r" % (e,)}
    return chk


def size_info(inst):
    return {"m": inst["target_nodes"]["count"], "n": inst["steiner_nodes"]["count"],
            "weight_range": [min(inst["steiner_nodes"]["node_weights"]), max(inst["steiner_nodes"]["node_weights"])]}


def gurobi_facts(hf_dir, L):
    tdir = os.path.join(hf_dir, "tasks", SLUG)
    out = {}
    for name, ifile, sfile in NAMES:
        try:
            with open(os.path.join(tdir, "instance", ifile), encoding="utf-8") as f:
                inst = json.load(f)
            with open(os.path.join(tdir, "gurobi_solution", sfile), encoding="utf-8") as f:
                sol = json.load(f)
            ok, why, obj = L.verify(L.Problem(inst), sol)
            out[name] = {"status": sol.get("status_name", sol.get("solver_status")),
                         "runtime": sol.get("runtime_seconds", sol.get("runtime")),
                         "objective_value": sol.get("objective_value"), "best_bound": sol.get("best_bound"),
                         "mip_gap": sol.get("mip_gap"), "active": len(sol.get("active_steiner_nodes") or []),
                         "ours_ok": ok, "ours_reason": why, "ours_objective": obj}
        except Exception as e:  # noqa: BLE001
            out[name] = {"error": repr(e)[:200]}
    return out


def official(checker_py, ip, sp, rp):
    p = subprocess.run([sys.executable, checker_py, "--instance_path", ip, "--solution_path", sp, "--result_path",
                        rp], capture_output=True, text=True, timeout=600, cwd=os.path.dirname(rp))
    out = {"exit": p.returncode}
    if os.path.exists(rp):
        with open(rp, encoding="utf-8") as f:
            r = json.load(f)
        out.update(feasible=r.get("feasible"), violated=r.get("violated_constraints"),
                   violations=str(r.get("violations"))[:300])
    return out


def probes(hf_dir, L, vout, pout):
    """Official verdicts on three altered copies of our own solutions. Tests of the checker; never entries."""
    tdir = os.path.join(hf_dir, "tasks", SLUG)
    checker_py = os.path.join(tdir, "feasibility_check.py")
    os.makedirs(pout, exist_ok=True)
    rows = []
    for name, ifile, _ in NAMES:
        sp = os.path.join(vout, "work", name + ".solution.json")
        ip = os.path.join(tdir, "instance", ifile)
        if not os.path.exists(sp):
            rows.append({"name": name, "skipped": "no solution"})
            continue
        with open(ip, encoding="utf-8") as f:
            pb = L.Problem(json.load(f))
        with open(sp, encoding="utf-8") as f:
            base = json.load(f)
        ok, why, true_obj = L.verify(pb, base)
        if not ok or len(base["active_steiner_nodes"]) < 3:
            rows.append({"name": name, "skipped": "base not verified or fewer than 3 active hubs", "reason": why})
            continue
        e = max(base["steiner_tree_edges"], key=lambda ed: pb.d[min(ed)][max(ed)])
        j, k = min(e), max(e)
        saved = pb.d[j][k]
        kinds = {}
        p1 = copy.deepcopy(base)
        p1["steiner_tree_edges"] = [x for x in p1["steiner_tree_edges"] if sorted(x) != [j, k]] + [[j, j]]
        p1["objective_value"] = true_obj - saved + pb.d[j][j]  # the checker prices the loop at d[j][j]
        kinds["selfloop"] = p1
        p2 = copy.deepcopy(base)
        p2["steiner_tree_edges"] = [x for x in p2["steiner_tree_edges"] if sorted(x) != [j, k]]
        p2["objective_value"] = true_obj - saved
        kinds["dropedge"] = p2
        p3 = copy.deepcopy(base)
        p3["objective_value"] = true_obj * (1 - 0.0005)
        kinds["objlow"] = p3
        for kind, sol in kinds.items():
            pp = os.path.join(pout, "%s.%s.probe.json" % (name, kind))
            with open(pp, "w", encoding="utf-8") as f:
                json.dump(sol, f)
            o = official(checker_py, ip, pp, os.path.join(pout, "%s.%s.result.json" % (name, kind)))
            rows.append({"name": name, "kind": kind, "active": len(sol["active_steiner_nodes"]),
                         "edges": len(sol["steiner_tree_edges"]), "removed_edge": [j, k],
                         "removed_edge_cost": saved, "true_objective_of_base": true_obj,
                         "reported": sol["objective_value"], "ours_verdict": L.verify(pb, sol)[0],
                         "official_feasible": o.get("feasible"), "official_violated": o.get("violated"),
                         "official_exit": o.get("exit")})
    with open(os.path.join(pout, "probes.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--scratch", default="/tmp/mv2-lee")
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
    L = _module(os.path.join(HERE, "solve.py"), "mv2_lee_solve")
    os.environ["MV2_LEE_LOG"] = "1"
    chk = make_checker(L)
    summary = {"repo_sha": sha, "solver_version": L.VERSION, "python": sys.version, "cpu_count": os.cpu_count(),
               "variants": {}, "checker_disagreements": []}
    try:
        summary["gurobi_facts"] = gurobi_facts(a.hf_dir, L)
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
            FR.run_task(SLUG, solve_py, chk, "min", a.hf_dir, vout, tl, size_info=size_info,
                        title="lee1996 (Steiner tree-star) solver v%s, %s" % (L.VERSION, name))
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
            bb = (gf.get(r["name"]) or {}).get("best_bound")
            if isinstance(bb, (int, float)) and isinstance(r.get("objective"), (int, float)):
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
            "large_mean_score": round(sum(r["score"] for r in large) / len(large), 6) if large else None,
            "large_within_1e-6": sum(1 for r in large if r.get("status") == "ok" and
                                     abs(r.get("gap_pct", 99)) <= 1e-4),
            "wall_s": {r["name"]: r.get("wall_s") for r in rows},
            "size": {r["name"]: {k: r.get(k) for k in ("m", "n", "weight_range")} for r in rows},
            "best_found_s": {k: v.get("best_found_s") for k, v in logs.items()},
            "first_write_s": {k: v.get("first_write_s") for k, v in logs.items()},
            "active": {k: v.get("active") for k, v in logs.items()},
            "ils_iters": {k: v.get("ils_iters") for k, v in logs.items()},
            "evals": {k: v.get("evals") for k, v in logs.items()},
            "verify_failures": {k: v.get("verify_failures") for k, v in logs.items()},
        }
        with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1, default=str)
        print("variant", name, json.dumps(summary["variants"][name], default=str)[:2500], flush=True)
    prows = []
    v60 = os.path.join(out, "v010-60s")
    if os.path.isdir(v60):
        try:
            prows = probes(a.hf_dir, L, v60, os.path.join(out, "probes"))
        except Exception as e:  # noqa: BLE001
            prows = [{"error": repr(e)[:300]}]
    summary["probes"] = prows
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, default=str)
    lines = ["# lee1996 (Steiner tree-star) solver v%s on the public FrontierOR instances, official checker"
             % L.VERSION, "",
             "Repository %s at %s (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). "
             "score = min(2, Gurobi's stored objective / ours); gap = 100 * (ours - Gurobi) / Gurobi. Made with AI "
             "agents working in MV2's name (MV2 of Munim, Inc.)." % (REPO, sha), "",
             "| variant | official accepts | mean score, 5 large | large equal to Gurobi (1e-6) | per instance: ours / "
             "Gurobi |", "|---|---|---|---|---|"]
    for name, v in summary["variants"].items():
        if "error" in v:
            lines.append("| %s | error: %s | | | |" % (name, v["error"][:120]))
            continue
        per = "; ".join("%s %s / %s" % (k, v["objective"][k], v["reference"][k]) for k in sorted(v["objective"]))
        lines.append("| %s | %d/%d | %s | %d | %s |" % (name, v["official_feasible"], v["cases"],
                                                        v["large_mean_score"], v["large_within_1e-6"], per))
    lines += ["", "Checker disagreements (ours vs official): %d" % len(summary["checker_disagreements"]), "",
              "## Stored Gurobi answers", "", "| instance | status | runtime s | objective | best bound | MIP gap "
              "| active hubs | our verify() |", "|---|---|---|---|---|---|---|---|"]
    for name, _, _ in NAMES:
        g = gf.get(name, {})
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (name, g.get("status"), g.get("runtime"),
                                                                    g.get("objective_value"), g.get("best_bound"),
                                                                    g.get("mip_gap"), g.get("active"),
                                                                    g.get("ours_ok")))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    pl = ["# lee1996: three probes of the official checker", "",
          "Altered copies of our own 60 s solutions, run through the official feasibility_check.py. These test the "
          "checker; none is an entry or a solution. selfloop = the most expensive tree edge replaced by a self-loop "
          "on one of its ends (the active hubs are then a forest, not a tree); dropedge = that edge removed; objlow = "
          "objective_value reported 0.05% below the true cost. Made with AI agents working in MV2's name (MV2 of "
          "Munim, Inc.).", "",
          "| instance | probe | active hubs | edges | official feasible | official violated | our verify() |",
          "|---|---|---|---|---|---|---|"]
    for r in prows:
        if "kind" in r:
            pl.append("| %s | %s | %s | %s | %s | %s | %s |" % (r["name"], r["kind"], r["active"], r["edges"],
                                                               r["official_feasible"], r["official_violated"],
                                                               r["ours_verdict"]))
        else:
            pl.append("| %s | skipped | | | | | %s |" % (r.get("name"), r.get("skipped") or r.get("error")))
    with open(os.path.join(out, "probes.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(pl) + "\n")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

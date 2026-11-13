"""arch_real: MV2's archetti2007 (inventory routing, order-up-to) solver on the public FrontierOR instances.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python arch_real.py --hf-dir /data/hf --out-dir /out [--only v010-60s ...]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded) for its kit.
2. Runs this folder's solve.py the contest way on the tiny + 5 large public instances (Hugging Face
   frontieror/FrontierOR, CC BY 4.0): 60 s, 10 s, 60 s with one worker and 60 s with another seed.
3. Every output is judged by the official feasibility_check.py; our verify() runs too and every disagreement is
   recorded. Reference = the stored Gurobi objective; score = min(2, Gurobi / ours).
4. Records instance facts (n, H, capacity / total demand, supplier stock / total demand, holding-cost ranges,
   U / r ratios, starting stock, number of visit patterns, whether delivering only when a stockout is otherwise
   unavoidable fits the capacity) and the stored Gurobi answers' facts (status, runtime, MIP gap, the lower bound
   that gap implies, our verdict). Our objective below a proven Gurobi bound would mean a modelling difference.
Writes OUT/archetti2007/<variant>/..., OUT/archetti2007/summary.json, results.md.
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
UA = "MV2-of-Munim-Inc FrontierOR archetti2007 (mv2@munimtech.com)"
SLUG = "archetti2007"
VARIANTS = [("v010-60s", 60.0, {}), ("v010-10s", 10.0, {}), ("v010-1w-60s", 60.0, {"MV2_IRP_WORKERS": "1"}),
            ("v010-seed7-60s", 60.0, {"MV2_IRP_SEED": "7"})]


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


def jit_plan_fits(pb):
    """Deliver only when the next period would otherwise stock out (latest possible visits)."""
    q = [0] * pb.H
    for s in range(1, pb.n + 1):
        inv = pb.I0[s]
        for t in range(pb.H):
            if inv - pb.r[s] < 0:
                q[t] += pb.U[s] - inv
                inv = pb.U[s]
            inv -= pb.r[s]
    return {"fits": all(v == 0 for v in [max(0, q[t] - pb.C) for t in range(pb.H)]) and
            all(sum(q[:t + 1]) <= pb.SC[t] for t in range(pb.H)), "loads": q}


def make_size_info(solver_mod):
    def size_info(inst):
        pb = solver_mod.Problem(inst)
        sr = sum(pb.r[1:]) or 1
        counts = [len(P) for P in pb.pats[1:]]
        return {"n": pb.n, "H": pb.H, "C": pb.C, "C_over_sum_r": round(pb.C / float(sr), 4),
                "B0_over_sum_r": round(pb.B0 / float(sr), 4), "r0_over_sum_r": round(pb.r0 / float(sr), 4),
                "h0": pb.h0, "h_range": [min(pb.h[1:]), max(pb.h[1:])] if pb.n else None,
                "U_over_r": sorted({round(pb.U[s] / float(pb.r[s]), 3) for s in range(1, pb.n + 1) if pb.r[s]}),
                "I0_is_U_minus_r": all(pb.I0[s] == pb.U[s] - pb.r[s] for s in range(1, pb.n + 1)),
                "patterns_total": sum(counts), "patterns_max": max(counts) if counts else 0,
                "jit": jit_plan_fits(pb)}
    return size_info


DISAGREE = []


def make_checker(solver_mod):
    cache = {}

    def chk(inst, sol):
        try:
            key = id(inst)
            if key not in cache or cache[key][0] is not inst:
                cache.clear()
                cache[key] = (inst, solver_mod.Problem(inst))
            pb = cache[key][1]
            ok, why, obj = solver_mod.verify(pb, sol)
            return {"feasible": ok, "objective": obj, "reason": why}
        except Exception as e:  # noqa: BLE001
            return {"feasible": False, "objective": None, "reason": "checker error %r" % (e,)}
    return chk


def gurobi_facts(hf_dir, solver_mod):
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
            ok, why, obj = solver_mod.verify(pb, sol)
            ov = sol.get("objective_value")
            gap = sol.get("mip_gap")
            bound = None
            if isinstance(ov, (int, float)) and isinstance(gap, (int, float)):
                bound = ov - gap * abs(ov)
            routes = sol.get("routes") or {}
            out[name] = {"status": sol.get("status_str", sol.get("status")), "runtime": sol.get("runtime"),
                         "objective_value": ov, "mip_gap": gap, "lower_bound": bound,
                         "visits": sum(len(v) for v in (sol.get("deliveries") or {}).values()),
                         "periods_with_route": len(routes),
                         "ours_ok": ok, "ours_reason": why, "ours_objective": obj}
        except Exception as e:  # noqa: BLE001
            out[name] = {"error": repr(e)[:200]}
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
    ap.add_argument("--scratch", default="/tmp/mv2-irp")
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
    solver_mod = _module(os.path.join(HERE, "solve.py"), "mv2_irp_solve")
    os.environ["MV2_IRP_LOG"] = "1"
    chk = make_checker(solver_mod)
    size_info = make_size_info(solver_mod)
    summary = {"repo_sha": sha, "solver_version": solver_mod.VERSION, "python": sys.version,
               "cpu_count": os.cpu_count(), "variants": {}}
    try:
        summary["gurobi_facts"] = gurobi_facts(a.hf_dir, solver_mod)
    except Exception as e:  # noqa: BLE001
        summary["gurobi_facts"] = {"error": repr(e)[:300]}
    print("gurobi_facts", json.dumps(summary["gurobi_facts"], default=str)[:2500], flush=True)
    gf = summary["gurobi_facts"]
    for name, tl, env in VARIANTS:
        if a.only and name not in a.only:
            continue
        vout = os.path.join(out, name)
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            tally = FR.run_task(SLUG, solve_py, chk, "min", a.hf_dir, vout, tl, size_info=size_info,
                                title="archetti2007 (inventory routing, order-up-to) solver v%s, %s"
                                % (solver_mod.VERSION, name))
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
        below = {}
        for r in rows:
            g = gf.get(r["name"], {}) if isinstance(gf, dict) else {}
            lb = g.get("lower_bound")
            if g.get("status") == "OPTIMAL" and isinstance(g.get("objective_value"), (int, float)):
                lb = g["objective_value"] * (1 - 1e-4) if lb is None else lb
            if isinstance(lb, (int, float)) and isinstance(r.get("objective"), (int, float)):
                below[r["name"]] = r["objective"] < lb - 1e-6
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
            "below_gurobi_bound": below,
            "large_mean_score": round(sum(r["score"] for r in large) / len(large), 6) if large else None,
            "large_strictly_better": sum(1 for r in large if r.get("status") == "ok" and r.get("gap_pct", 0) < -1e-6),
            "large_within_1pct": sum(1 for r in large if r.get("status") == "ok" and r.get("gap_pct", 99) <= 1.0),
            "wall_s": {r["name"]: r.get("wall_s") for r in rows},
            "gurobi_official_feasible": {r["name"]: r.get("gurobi_official_feasible") for r in rows},
            "gurobi_ours_feasible": {r["name"]: r.get("gurobi_ours_feasible") for r in rows},
            "gurobi_log": {r["name"]: r.get("gurobi_log") for r in rows},
            "size": {r["name"]: {k: r.get(k) for k in ("n", "H", "C", "C_over_sum_r", "B0_over_sum_r",
                                                       "r0_over_sum_r", "h0", "h_range", "U_over_r",
                                                       "I0_is_U_minus_r", "patterns_total", "patterns_max",
                                                       "jit")} for r in rows},
            "first_feasible_s": {k: ((v or {}).get("parent") or {}).get("first_feasible_s") for k, v in logs.items()},
            "initial_viol": {k: ((v or {}).get("parent") or {}).get("initial_viol") for k, v in logs.items()},
            "repair_viol": {k: ((v or {}).get("parent") or {}).get("repair_viol") for k, v in logs.items()},
            "best_source": {k: (v or {}).get("best_source") for k, v in logs.items()},
            "iterations_parent": {k: ((v or {}).get("parent") or {}).get("iterations") for k, v in logs.items()},
            "iterations_child": {k: ((v or {}).get("child") or {}).get("iterations") for k, v in logs.items()},
            "verify_failures": {k: (v or {}).get("verify_failures") for k, v in logs.items()},
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
    lines = ["# archetti2007 (inventory routing, order-up-to) solver v%s on the public FrontierOR instances, "
             "official checker" % solver_mod.VERSION, "",
             "Repository %s at %s (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). "
             "score = min(2, Gurobi's stored objective / ours); gap = 100 * (ours - Gurobi) / Gurobi. Made with AI "
             "agents working in MV2's name (MV2 of Munim, Inc.)." % (REPO, sha), "",
             "| variant | official accepts | mean score, 5 large | large better than Gurobi | large within 1% "
             "| per instance: ours / Gurobi |", "|---|---|---|---|---|---|"]
    for name, v in summary["variants"].items():
        if "error" in v:
            lines.append("| %s | error: %s | | | | |" % (name, v["error"][:120]))
            continue
        per = "; ".join("%s %s / %s" % (k, v["objective"][k], v["reference"][k]) for k in sorted(v["objective"]))
        lines.append("| %s | %d/%d | %s | %d | %d | %s |" % (name, v["official_feasible"], v["cases"],
                                                             v["large_mean_score"], v["large_strictly_better"],
                                                             v["large_within_1pct"], per))
    lines += ["", "Checker disagreements (ours vs official): %d" % len(DISAGREE)]
    first = next((v for v in summary["variants"].values() if "size" in v), None)
    if first and isinstance(gf, dict):
        lines += ["", "## Instance facts and the stored Gurobi answers", "",
                  "| instance | n | H | C / sum r | B0 / sum r | latest-delivery plan fits | Gurobi status, runtime s, "
                  "MIP gap | Gurobi lower bound |", "|---|---|---|---|---|---|---|---|"]
        for k in sorted(first["size"]):
            s = first["size"][k]
            g = gf.get(k, {})
            lines.append("| %s | %s | %s | %s | %s | %s | %s, %s, %s | %s |" % (
                k, s.get("n"), s.get("H"), s.get("C_over_sum_r"), s.get("B0_over_sum_r"),
                (s.get("jit") or {}).get("fits"), g.get("status"), g.get("runtime"), g.get("mip_gap"),
                g.get("lower_bound")))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

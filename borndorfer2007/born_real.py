"""born_real: MV2's borndorfer2007 (line planning) solver on the real public FrontierOR instances, official checker.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python born_real.py --hf-dir /data/hf --out-dir /out [--only v010-60s]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded) for its kit
   (frontieror_hf, harness, frontieror_real).
2. Runs this folder's solve.py the contest way (python solve.py --problem borndorfer2007 --instance ... --output ...
   --time-limit T) on the tiny + 5 large public instances (Hugging Face frontieror/FrontierOR, CC BY 4.0): seed 1 at
   60 s and at 10 s.
3. Each output is judged by the official feasibility_check.py (run as a program by the kit) and by solve.verify()
   with the checker's own tolerances. Reference = the stored Gurobi solution's objective_value; contest-style score
   = min(2, ref / ours).
4. For our answers and Gurobi's: lines, mean and longest line (edges), fixed cost, operating cost, passenger travel
   time, lines that break the model's line rules; Gurobi's stored status and MIP gap; each instance's size.
Writes OUT/born/<variant>/{rows.jsonl, results.md, ...}, OUT/born/summary.json, OUT/born/results.md.
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
UA = "MV2-of-Munim-Inc FrontierOR borndorfer2007 (mv2@munimtech.com)"
SLUG = "borndorfer2007"
VARIANTS = [("v010-60s", 60.0, 1), ("v010-10s", 10.0, 1)]
CASE_FILES = [("tiny", "tiny_instance.json", "tiny_solution.json")] + [
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


S = _module(os.path.join(HERE, "solve.py"), "mv2_borndorfer2007_solve_real")


def size_info(inst):
    try:
        P = S.Problem(inst)
        gp = inst.get("global_parameters") or {}
        return {"nodes": P.n, "edges": P.E, "coverable_edges": P.coverable, "prep_s": P.prep_s,
                "od_pairs": len(P.od), "origins": len(P.origins), "od_dupes": P.od_dupes,
                "total_demand": sum(P.od.values()), "lambda": P.lam, "max_line_length_edges": P.L,
                "F": P.F, "num_od_nodes": (inst.get("network") or {}).get("num_od_nodes"),
                "modes": [{"name": P.mname[i], "kappa": P.kappa[i], "fixed_cost": P.Cf[i],
                           "terminals": len(P.term[i]), "edges": len(P.medges[i])} for i in range(P.M)],
                "global_fixed_cost_per_line": gp.get("fixed_cost_per_line"),
                "global_operating_cost_per_edge": gp.get("operating_cost_per_edge")}
    except Exception as e:  # noqa: BLE001
        return {"size_error": repr(e)[:200]}


def solver_log(vout, name):
    p = os.path.join(vout, "work", name + ".solution.json.log.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        return {"unreadable": repr(e)[:200]}


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--scratch", default="/tmp/mv2-born")
    a = ap.parse_args(argv)
    out = os.path.join(a.out_dir, "born")
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
    solver = os.path.join(sdir, "solve.py")
    os.environ["MV2_BORN_LOG"] = "1"

    def chk(inst, sol):
        r = S.verify(inst, sol, loose=True)
        return {"feasible": r["feasible"], "objective": r["objective"], "reason": r["reason"]}

    summary = {"repo_sha": sha, "version": S.VERSION, "python": sys.version, "cpu_count": os.cpu_count(),
               "variants": {}, "gurobi": {}}
    tdir = os.path.join(a.hf_dir, "tasks", SLUG)
    for name, tl, seed in VARIANTS:
        if a.only and name not in a.only:
            continue
        os.environ["MV2_BORN_SEED"] = str(seed)
        vout = os.path.join(out, name)
        try:
            tally = FR.run_task(SLUG, solver, chk, "min", a.hf_dir, vout, tl, size_info=size_info,
                                title="borndorfer2007 (line planning in public transport), MV2 solver v%s, %ss, "
                                      "seed %d" % (S.VERSION, int(tl), seed))
        except Exception as e:  # noqa: BLE001 - record and go on
            summary["variants"][name] = {"error": repr(e)[:500], "seed": seed}
            print("variant failed", name, repr(e), flush=True)
            continue
        with open(os.path.join(vout, "rows.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        large = [r for r in rows if r["name"].startswith("large")]
        prt = {}
        for cname, ifile, _ in CASE_FILES:
            inst = load(os.path.join(tdir, "instance", ifile))
            sol = load(os.path.join(vout, "work", cname + ".solution.json"))
            prt[cname] = S.parts(S.Problem(inst), sol) if inst and sol else None
            if inst and sol:
                prt[cname]["strict_verdict"] = S.verify(inst, sol)["feasible"]
        summary["variants"][name] = {
            "time_limit": tl, "seed": seed, "revision": tally.get("revision"), "cases": len(rows),
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
                                         and (r.get("gap_pct") or 0) < -1e-6),
            "wall_s": {r["name"]: r.get("wall_s") for r in rows},
            "gurobi_official_feasible": {r["name"]: r.get("gurobi_official_feasible") for r in rows},
            "gurobi_ours_feasible": {r["name"]: r.get("gurobi_ours_feasible") for r in rows},
            "parts": prt,
            "solver_log": {r["name"]: solver_log(vout, r["name"]) for r in rows},
        }
        with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1, default=str)
        print("variant", name, json.dumps(summary["variants"][name], default=str)[:2000], flush=True)
    for cname, ifile, sfile in CASE_FILES:
        inst = load(os.path.join(tdir, "instance", ifile))
        g = load(os.path.join(tdir, "gurobi_solution", sfile))
        if g is None:
            summary["gurobi"][cname] = {"error": "missing"}
            continue
        row = {k: g.get(k) for k in ("objective_value", "status", "mip_gap", "solve_time_seconds", "runtime")}
        if inst:
            P = S.Problem(inst)
            row.update(S.parts(P, g))
            row["size"] = size_info(inst)
            v = S.verify(inst, g, P, loose=True)
            row["ours_loose_verdict"] = [v["feasible"], v["reason"][:200]]
            v2 = S.verify(inst, g, P)
            row["ours_strict_verdict"] = [v2["feasible"], v2["reason"][:200]]
        summary["gurobi"][cname] = row
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, default=str)
    lines = ["# MV2's borndorfer2007 (line planning) solver v%s on the public FrontierOR instances, official checker"
             % S.VERSION, "",
             "Repository %s at %s (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). "
             "score = min(2, Gurobi's stored objective / ours) (the contest's rule for a minimised positive "
             "objective, here against the stored Gurobi answer, not the contest's frozen reference); gap = 100 * "
             "(ours - Gurobi) / Gurobi, negative = better. Made with AI agents working in MV2's name (MV2 of Munim, "
             "Inc.)." % (REPO, sha), "",
             "| variant | official accepts | mean score, 5 large | large better than Gurobi | per instance gap (%) |",
             "|---|---|---|---|---|"]
    for name, v in summary["variants"].items():
        if "error" in v:
            lines.append("| %s | error: %s | | | |" % (name, v["error"][:120]))
            continue
        per = ", ".join("%s %s" % (k, v["gap_pct"][k]) for k in sorted(v["gap_pct"]))
        lines.append("| %s | %d/%d | %s | %d | %s |" % (name, v["official_feasible"], v["cases"],
                                                       v["large_mean_score"], v["large_strictly_better"], per))
    lines += ["", "Line plans (lines; mean and longest line in edges; fixed cost; operating cost; travel time; "
                  "line-rule breaches) and Gurobi's stored status:", ""]
    keys = ("lines", "mean_line_edges", "max_line_edges", "fixed_cost", "operating_cost", "travel_time",
            "line_rule_breaches")
    for cname, _, _ in CASE_FILES:
        g = summary["gurobi"].get(cname) or {}
        gshort = {k: g.get(k) for k in ("objective_value", "status", "mip_gap") + keys}
        ours = {n: {k: ((v.get("parts") or {}).get(cname) or {}).get(k) for k in keys}
                for n, v in summary["variants"].items() if "error" not in v}
        lines.append("- %s: Gurobi %s; ours %s" % (cname, json.dumps(gshort), json.dumps(ours)))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

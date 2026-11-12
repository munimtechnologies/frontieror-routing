"""guo_real: MV2's guo2021 solver v0.1.0 on the real public FrontierOR instances, judged by the official checker.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python guo_real.py --hf-dir /data/hf --out-dir /out [--only guo-v010-60s]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded) for its kit
   (frontieror_hf, harness, frontieror_real).
2. Copies this folder's solve.py into a contest-style folder /tmp/mv2-guo/solver/ and runs it the contest way
   (python solve.py --problem guo2021 --instance ... --output ... --time-limit T) on guo2021's tiny + 5 large public
   instances (Hugging Face frontieror/FrontierOR, CC BY 4.0), at 60 s and at 10 s.
3. Each output is judged by the official feasibility_check.py (run as a program by the kit, and its
   check_feasibility() for our checker, whose objective is the checker's own recomputation, see solve.py). The
   reference is the stored Gurobi solution's objective_value (Gurobi hit its time limit on all five large instances
   when the benchmark selected its hard set). Because the objective is usually negative here, the kit's ratio score
   is not meaningful; the report gives gap_pct = 100 * (ours - Gurobi) / |Gurobi| (negative = better than Gurobi).
Writes OUT/guo2021/<variant>/{rows.jsonl, results.md, ...}, OUT/guo2021/summary.json, OUT/guo2021/results.md.
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
UA = "MV2-of-Munim-Inc FrontierOR guo2021 (mv2@munimtech.com)"
SLUG = "guo2021"
VARIANTS = [("guo-v010-60s", 60.0), ("guo-v010-10s", 10.0)]


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
    pts = inst.get("patients", [])
    bs = [dd["B_hd"] for h in inst.get("hospitals", []) for dd in h["days"]]
    sc = inst.get("scenarios", [])
    durs = [v for s in sc for v in s["surgery_durations_minutes"]]
    return {"patients": inst.get("num_patients"), "mandatory": sum(1 for p in pts if p.get("is_mandatory")),
            "hospitals": inst.get("num_hospitals"), "days": inst.get("num_days"),
            "ors": inst.get("num_ors_per_hospital"), "scenarios": inst.get("num_scenarios", len(sc)),
            "B_min": min(bs) if bs else None, "B_max": max(bs) if bs else None,
            "dur_mean": round(sum(durs) / len(durs), 2) if durs else None}


def make_checker(hf_dir, solver_mod):
    cache = {}

    def chk(inst, sol):
        try:
            if "off" not in cache:
                cache["off"] = _module(os.path.join(hf_dir, "tasks", SLUG, "feasibility_check.py"), "guo_official")
            r = cache["off"].check_feasibility(inst, sol)
            obj = solver_mod.checker_objective(inst, sol)
            return {"feasible": bool(r.get("feasible")), "objective": obj,
                    "reason": "violated %s" % (r.get("violated_constraints"),)}
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
        lg["events"] = ev[:3] + ev[-5:] if len(ev) > 8 else ev
        return lg
    except Exception as e:  # noqa: BLE001
        return {"unreadable": repr(e)[:200]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--scratch", default="/tmp/mv2-guo")
    a = ap.parse_args(argv)
    out = os.path.join(a.out_dir, "guo2021")
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
    solver_mod = _module(os.path.join(HERE, "solve.py"), "mv2_guo_solve")
    os.environ["MV2_GUO_LOG"] = "1"
    chk = make_checker(a.hf_dir, solver_mod)
    summary = {"repo_sha": sha, "solver_version": solver_mod.VERSION, "python": sys.version,
               "cpu_count": os.cpu_count(), "variants": {}}
    for name, tl in VARIANTS:
        if a.only and name not in a.only:
            continue
        vout = os.path.join(out, name)
        try:
            tally = FR.run_task(SLUG, solve_py, chk, "min", a.hf_dir, vout, tl, size_info=size_info,
                                title="guo2021 (stochastic distributed OR scheduling) solver v%s, %ss"
                                % (solver_mod.VERSION, int(tl)))
        except Exception as e:  # noqa: BLE001 - record and go on
            summary["variants"][name] = {"error": repr(e)[:500]}
            print("variant failed", name, repr(e), flush=True)
            continue
        with open(os.path.join(vout, "rows.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        large = [r for r in rows if r["name"].startswith("large")]
        gaps = [r.get("gap_pct") for r in large if r.get("status") == "ok" and r.get("official_feasible") is True
                and r.get("gap_pct") is not None]
        summary["variants"][name] = {
            "time_limit": tl, "revision": tally.get("revision"), "cases": len(rows),
            "official_feasible": sum(1 for r in rows if r.get("official_feasible") is True),
            "official_rejected": {r["name"]: str(r.get("official_violations"))[:300] for r in rows
                                  if r.get("official_feasible") is False},
            "status": {r["name"]: r.get("status") for r in rows},
            "objective": {r["name"]: r.get("objective") for r in rows},
            "reference": {r["name"]: r.get("reference") for r in rows},
            "gap_pct": {r["name"]: r.get("gap_pct") for r in rows},
            "large_mean_gap_pct": round(sum(gaps) / len(gaps), 4) if len(gaps) == len(large) and large else None,
            "large_strictly_better": sum(1 for g in gaps if g < -1e-6),
            "wall_s": {r["name"]: r.get("wall_s") for r in rows},
            "gurobi_official_feasible": {r["name"]: r.get("gurobi_official_feasible") for r in rows},
            "size": {r["name"]: {k: r.get(k) for k in ("patients", "mandatory", "hospitals", "days", "ors",
                                                       "scenarios", "B_min", "B_max", "dur_mean")} for r in rows},
            "solver_log": {r["name"]: solver_log(vout, r["name"]) for r in rows},
        }
        with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1, default=str)
        print("variant", name, json.dumps(summary["variants"][name], default=str)[:2000], flush=True)
    lines = ["# guo2021 solver v%s on the public FrontierOR instances, official checker" % solver_mod.VERSION, "",
             "Repository %s at %s (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). "
             "gap = 100 * (ours - Gurobi's stored objective) / |Gurobi|; negative = better than Gurobi. Made with AI "
             "agents working in MV2's name (MV2 of Munim, Inc.)." % (REPO, sha), "",
             "| variant | official accepts | mean gap, 5 large (%) | large better than Gurobi | per instance gap (%) |",
             "|---|---|---|---|---|"]
    for name, v in summary["variants"].items():
        if "error" in v:
            lines.append("| %s | error: %s | | | |" % (name, v["error"][:120]))
            continue
        per = ", ".join("%s %s" % (k, v["gap_pct"][k]) for k in sorted(v["gap_pct"]))
        lines.append("| %s | %d/%d | %s | %d | %s |" % (name, v["official_feasible"], v["cases"],
                                                       v["large_mean_gap_pct"], v["large_strictly_better"], per))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

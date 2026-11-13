"""martin_real: MV2's berth solver v0.1.0 on the real public FrontierOR martin-iradi2024 instances, official checker.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python martin_real.py --hf-dir /data/hf --out-dir /out [--only berth-v010-60s]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded) for its kit
   (frontieror_hf, harness, frontieror_real).
2. Copies this folder's solve.py into a contest-style folder and runs it the contest way (python solve.py --problem
   martin-iradi2024 --instance ... --output ... --time-limit T) on the tiny + 5 large public instances (Hugging Face
   frontieror/FrontierOR, CC BY 4.0), in three variants: 60 s with the description's first-call rule (default),
   60 s with the stored Gurobi model's stricter first-call rule (arrival = earliest start), and 10 s default.
3. Each output is judged by the official feasibility_check.py (run as a program by the kit) and by solve.verify(), our
   mirror of it. Reference = the stored Gurobi solution's objective_value; contest score = min(2, ref / ours).
4. Also records, for each stored Gurobi solution, how many first calls have arrival = earliest start and the waiting
   cost it pays at first calls (the part of its objective the description's rule would not charge).
Writes OUT/berth/<variant>/{rows.jsonl, results.md, ...}, OUT/berth/summary.json, OUT/berth/results.md.
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
UA = "MV2-of-Munim-Inc FrontierOR martin-iradi2024 (mv2@munimtech.com)"
SLUG = "martin-iradi2024"
VARIANTS = [("berth-v010-60s", 60.0, "desc"), ("berth-v010-60s-est", 60.0, "est"), ("berth-v010-10s", 10.0, "desc")]
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


def size_info(inst):
    ships = inst.get("ships", [])
    return {"ships": len(ships), "calls": sum(len(s.get("port_visits", [])) for s in ships),
            "ports": len(inst.get("ports", [])), "speeds": len(inst.get("speeds_knots", [])),
            "external": sum(len(e.get("ships", [])) for e in inst.get("external_ships", [])),
            "quay_min": min((p["quay_length_meters"] for p in inst.get("ports", [])), default=None),
            "costs": inst.get("cost_parameters"), "beta": inst.get("handling_time_deviation_factor_beta_per_meter")}


def gurobi_first_calls(inst, gsol):
    """How the stored Gurobi solution treats first calls: count with arrival = EST, and first-call waiting cost."""
    if not gsol or not gsol.get("ships"):
        return None
    I = (inst.get("cost_parameters") or {}).get("waiting_cost_usd_per_hour", 0)
    est = {s["id"]: min(s["port_visits"], key=lambda p: p["port_call_index"])["earliest_start_time_hours"]
           for s in inst["ships"] if s.get("port_visits")}
    n = same = 0
    wait_cost = 0.0
    for s in gsol["ships"]:
        pvs = s.get("port_visits") or []
        if not pvs:
            continue
        first = min(pvs, key=lambda p: p["port_call_index"])
        n += 1
        if abs(first.get("arrival_time", -1) - est.get(s["ship_id"], -2)) <= 1e-6:
            same += 1
        wait_cost += I * (first.get("start_time", 0.0) - first.get("arrival_time", 0.0))
    obj = gsol.get("objective_value")
    return {"first_calls": n, "arrival_eq_est": same, "first_call_waiting_cost": round(wait_cost, 4),
            "share_of_objective": round(wait_cost / obj, 6) if obj else None}


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
    ap.add_argument("--scratch", default="/tmp/mv2-berth")
    a = ap.parse_args(argv)
    out = os.path.join(a.out_dir, "berth")
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
    S = _module(os.path.join(HERE, "solve.py"), "mv2_berth_solve")
    os.environ["MV2_BERTH_LOG"] = "1"

    def chk(inst, sol):
        r = S.verify(inst, sol)
        return {"feasible": r["feasible"], "objective": r["objective"], "reason": r["reason"]}

    summary = {"repo_sha": sha, "solver_version": S.VERSION, "python": sys.version, "cpu_count": os.cpu_count(),
               "variants": {}, "gurobi_first_calls": {}}
    for name, tl, mode in VARIANTS:
        if a.only and name not in a.only:
            continue
        os.environ["MV2_BERTH_FIRST_ARRIVAL"] = mode
        vout = os.path.join(out, name)
        try:
            tally = FR.run_task(SLUG, solve_py, chk, "min", a.hf_dir, vout, tl, size_info=size_info,
                                title="martin-iradi2024 (multi-port berth allocation + speeds) solver v%s, %ss, "
                                      "first call '%s'" % (S.VERSION, int(tl), mode))
        except Exception as e:  # noqa: BLE001 - record and go on
            summary["variants"][name] = {"error": repr(e)[:500]}
            print("variant failed", name, repr(e), flush=True)
            continue
        with open(os.path.join(vout, "rows.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        large = [r for r in rows if r["name"].startswith("large")]
        summary["variants"][name] = {
            "time_limit": tl, "first_arrival": mode, "revision": tally.get("revision"), "cases": len(rows),
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
            "size": {r["name"]: {k: r.get(k) for k in ("ships", "calls", "ports", "speeds", "external", "quay_min",
                                                       "costs", "beta")} for r in rows},
            "solver_log": {r["name"]: solver_log(vout, r["name"]) for r in rows},
        }
        with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1, default=str)
        print("variant", name, json.dumps(summary["variants"][name], default=str)[:2000], flush=True)
    tdir = os.path.join(a.hf_dir, "tasks", SLUG)
    for name, ifile, sfile in CASE_FILES:
        try:
            with open(os.path.join(tdir, "instance", ifile), encoding="utf-8") as f:
                inst = json.load(f)
            with open(os.path.join(tdir, "gurobi_solution", sfile), encoding="utf-8") as f:
                gsol = json.load(f)
            summary["gurobi_first_calls"][name] = gurobi_first_calls(inst, gsol)
        except Exception as e:  # noqa: BLE001
            summary["gurobi_first_calls"][name] = {"error": repr(e)[:200]}
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, default=str)
    lines = ["# martin-iradi2024 berth solver v%s on the public FrontierOR instances, official checker" % S.VERSION,
             "", "Repository %s at %s (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). "
             "score = min(2, Gurobi's stored objective / ours) (the contest's rule for a minimised positive "
             "objective, here against the stored Gurobi answer, not the contest's frozen reference); gap = 100 * "
             "(ours - Gurobi) / Gurobi, negative = better. Made with AI agents working in MV2's name (MV2 of "
             "Munim, Inc.)." % (REPO, sha), "",
             "| variant | official accepts | mean score, 5 large | large better than Gurobi | per instance gap (%) |",
             "|---|---|---|---|---|"]
    for name, v in summary["variants"].items():
        if "error" in v:
            lines.append("| %s | error: %s | | | |" % (name, v["error"][:120]))
            continue
        per = ", ".join("%s %s" % (k, v["gap_pct"][k]) for k in sorted(v["gap_pct"]))
        lines.append("| %s | %d/%d | %s | %d | %s |" % (name, v["official_feasible"], v["cases"],
                                                       v["large_mean_score"], v["large_strictly_better"], per))
    lines += ["", "Stored Gurobi solutions, first calls (arrival = earliest start; waiting cost paid there):", ""]
    for name, g in summary["gurobi_first_calls"].items():
        lines.append("- %s: %s" % (name, json.dumps(g)))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

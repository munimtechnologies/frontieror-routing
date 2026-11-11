"""practice_real: MV2's FrontierOR practice solvers (op, vrpddp, darp, spp) on their real public instances, judged by
the official checkers, before and after the output fixes found by reading those checkers.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python practice_real.py --hf-dir /data/hf --out-dir /out [--time-limit 60] [--only darp-v3 spp-v030]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded) and builds
   one contest-style folder per solver version under /tmp/solvers (each folder holds everything it imports):
     op-v1      fischetti1998  op/fischetti1998/solve.py                       (as published)
     nagy-v2    nagy2015       vrpddp/nagy2015/solve.py                        (as published)
     nagy-v3    nagy2015       postfix/nagy2015/solve.py + v2 as nagy_core.py  (this run)
     darp-v2    cordeau2006    darp/cordeau2006/solve.py                       (as published, v0.2.0)
     darp-v3    cordeau2006    postfix/cordeau2006/solve.py + v0.2.0 as darp_core.py (this run, v0.3.0)
     spp-v020   hoffman1993    spp/hoffman1993/solve.py + kit/frontier_runtime.py     (as published)
     spp-v030   hoffman1993    spp/hoffman1993/solve.py of this run + kit/frontier_runtime.py
2. For each version runs kit/frontieror_real.run_task on the task's tiny + 5 large public instances of the FrontierOR
   benchmark (Hugging Face frontieror/FrontierOR, CC BY 4.0), 60 s each, the contest way. Each output is judged by
   our own checker (the published *_eval.py one, or spp_check below) AND by the official feasibility_check.py.
3. official_score = contest score (min(2, ref/obj) or min(2, obj/ref), ref = stored Gurobi objective) when the
   official checker accepts the file and the run finished in time, else 0. This is the number the contest would use
   (on its private instances).
Writes OUT/practice/<version>/{rows.jsonl, results.json, results.md, manifest.json}, OUT/practice/summary.json,
OUT/practice/results.md and OUT/practice/repo.json.
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
UA = "MV2-of-Munim-Inc FrontierOR practice (mv2@munimtech.com)"

VARIANTS = [
    # name, slug, sense, title
    ("spp-v030", "hoffman1993", "min", "hoffman1993 (set partitioning) solver v0.3.0"),
    ("spp-v020", "hoffman1993", "min", "hoffman1993 (set partitioning) solver v0.2.0"),
    ("darp-v3", "cordeau2006", "min", "cordeau2006 (dial-a-ride) solver v0.3.0"),
    ("darp-v2", "cordeau2006", "min", "cordeau2006 (dial-a-ride) solver v0.2.0"),
    ("nagy-v3", "nagy2015", "min", "nagy2015 (VRPDDP) solver v3"),
    ("nagy-v2", "nagy2015", "min", "nagy2015 (VRPDDP) solver v2"),
    ("op-v1", "fischetti1998", "max", "fischetti1998 (orienteering) solver v1"),
]


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


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


def assemble(repo, root):
    """Build /tmp/solvers/<variant>/solve.py (+ what it imports). Returns {variant: solve.py path}."""
    if os.path.exists(root):
        shutil.rmtree(root)
    rt = os.path.join(repo, "kit", "frontier_runtime.py")
    out = {}

    def folder(name):
        d = os.path.join(root, name)
        os.makedirs(d, exist_ok=True)
        out[name] = os.path.join(d, "solve.py")
        return d

    d = folder("op-v1")
    _copy(os.path.join(repo, "op", "fischetti1998", "solve.py"), os.path.join(d, "solve.py"))
    d = folder("nagy-v2")
    _copy(os.path.join(repo, "vrpddp", "nagy2015", "solve.py"), os.path.join(d, "solve.py"))
    d = folder("nagy-v3")
    _copy(os.path.join(HERE, "postfix", "nagy2015", "solve.py"), os.path.join(d, "solve.py"))
    _copy(os.path.join(repo, "vrpddp", "nagy2015", "solve.py"), os.path.join(d, "nagy_core.py"))
    d = folder("darp-v2")
    _copy(os.path.join(repo, "darp", "cordeau2006", "solve.py"), os.path.join(d, "solve.py"))
    d = folder("darp-v3")
    _copy(os.path.join(HERE, "postfix", "cordeau2006", "solve.py"), os.path.join(d, "solve.py"))
    _copy(os.path.join(repo, "darp", "cordeau2006", "solve.py"), os.path.join(d, "darp_core.py"))
    d = folder("spp-v020")
    _copy(os.path.join(repo, "spp", "hoffman1993", "solve.py"), os.path.join(d, "solve.py"))
    _copy(rt, os.path.join(d, "frontier_runtime.py"))
    d = folder("spp-v030")
    _copy(os.path.join(HERE, "spp", "hoffman1993", "solve.py"), os.path.join(d, "solve.py"))
    _copy(rt, os.path.join(d, "frontier_runtime.py"))
    return out


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ our checkers
def spp_check(inst, sol, tol=1e-6):
    """hoffman1993, read as the official checker reads the instance: 0-based legs, the first num_cols columns, row
    indices outside [0, num_rows) ignored, cost beyond cost_vector = 0. The solution is read from variable_values."""
    m = int(inst["dimensions"]["num_rows"])
    n = int(inst["dimensions"]["num_cols"])
    cols = inst["constraint_matrix_A"]["columns"]
    cost = inst.get("cost_vector") or []
    for key in ("objective_value", "selected_rotations", "variable_values"):
        if key not in sol or sol[key] is None:
            return {"feasible": False, "objective": None, "reason": "missing " + key}
    if not sol["selected_rotations"]:
        return {"feasible": False, "objective": None, "reason": "empty selected_rotations"}
    x = {}
    for k, v in sol["variable_values"].items():
        j = int(k)
        if 0 <= j < n:
            x[j] = float(v)
    if any(min(abs(v), abs(v - 1.0)) > 1e-5 for v in x.values()):
        return {"feasible": False, "objective": None, "reason": "non-binary value"}
    chosen = [j for j, v in x.items() if v > 0.5]
    sel = sol["selected_rotations"]
    if any((not isinstance(r, int)) or r < 0 or r >= n for r in sel) or len(set(sel)) != len(sel):
        return {"feasible": False, "objective": None, "reason": "bad selected_rotations"}
    cover = [0] * m
    for j in chosen:
        for i in (cols[j] if j < len(cols) else []):
            if 0 <= int(i) < m:
                cover[int(i)] += 1
    if any(c != 1 for c in cover):
        return {"feasible": False, "objective": None,
                "reason": "%d legs not covered exactly once" % sum(1 for c in cover if c != 1)}
    if inst.get("has_base_constraints", False) and inst.get("base_constraints") is not None:
        bc = inst["base_constraints"]
        for b in range(int(bc["num_constraints"])):
            row = bc["D_matrix"]["rows"][b]
            s = sum(float(row[j]) for j in chosen)
            if s < float(bc["lower_bounds_d1"][b]) - tol or s > float(bc["upper_bounds_d2"][b]) + tol:
                return {"feasible": False, "objective": None, "reason": "base constraint %d" % b}
    obj = float(sum(float(cost[j]) for j in chosen if j < len(cost)))
    return {"feasible": True, "objective": obj, "reason": "ok"}


def checkers(repo):
    op = _module(os.path.join(repo, "op", "op_eval.py"), "mv2_op_eval")
    nagy = _module(os.path.join(repo, "vrpddp", "nagy_eval.py"), "mv2_nagy_eval")
    darp = _module(os.path.join(repo, "darp", "darp_eval.py"), "mv2_darp_eval")

    def wrap(fn):
        def chk(inst, sol):
            try:
                r = fn(inst, sol)
            except Exception as e:  # noqa: BLE001 - a crash in our checker is a rejection, recorded
                return {"feasible": False, "objective": None, "reason": "our checker error %r" % (e,)}
            return {"feasible": bool(r[0]), "objective": r[2], "reason": r[1]}
        return chk

    def safe_spp(inst, sol):
        try:
            return spp_check(inst, sol)
        except Exception as e:  # noqa: BLE001
            return {"feasible": False, "objective": None, "reason": "our checker error %r" % (e,)}

    return {
        "fischetti1998": wrap(op.check_solution),
        "nagy2015": wrap(nagy.check),
        "cordeau2006": wrap(lambda i, s: darp.check(i, s, 0)),
        "hoffman1993": safe_spp,
    }


def size_info(slug):
    def f(inst):
        if slug == "hoffman1993":
            d = inst["dimensions"]
            cols = inst["constraint_matrix_A"]["columns"]
            m = int(d["num_rows"])
            return {"rows": m, "cols": int(d["num_cols"]), "listed_columns": len(cols),
                    "out_of_range_indices": sum(1 for c in cols[:int(d["num_cols"])] for i in c
                                                if not 0 <= int(i) < m),
                    "has_base": bool(inst.get("has_base_constraints"))}
        if slug == "cordeau2006":
            users = {int(r["user_id"]) for r in inst["nodes"] if r.get("node_type") == "pickup" and "user_id" in r}
            pick = [int(r["node_id"]) for r in inst["nodes"] if r.get("node_type") == "pickup"]
            return {"users": inst["num_users"], "vehicles": inst["num_vehicles"],
                    "user_id_min": min(users) if users else None,
                    "user_id_equals_pickup_node": all(
                        int(r.get("user_id", -1)) == int(r["node_id"]) for r in inst["nodes"]
                        if r.get("node_type") == "pickup"),
                    "pickups_are_1_to_n": sorted(pick) == list(range(1, int(inst["num_users"]) + 1))}
        if slug == "nagy2015":
            return {"customers": inst["num_customers"], "capacity": inst["vehicle_capacity"]}
        if slug == "fischetti1998":
            return {"n": inst["n"], "t0": inst["t0"]}
        return {}
    return f


def official_score(row, sense, H):
    if row.get("official_feasible") is not True or row.get("status") in ("overtime", "no_output"):
        return 0.0
    stated = row.get("stated")
    if not isinstance(stated, (int, float)):
        return 0.0
    return round(H.contest_score(float(stated), row.get("reference"), sense), 6)


def vehicles_used(row_path):
    """For darp rows: how many listed routes visit at least one request (from the saved solution)."""
    try:
        with open(row_path, encoding="utf-8") as f:
            sol = json.load(f)
        r = sol.get("routes") or {}
        return {"routes_listed": len(r), "routes_used": sum(1 for v in r.values() if len(v) > 2)}
    except Exception:  # noqa: BLE001
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--scratch", default="/tmp/mv2-practice")
    a = ap.parse_args(argv)
    out = os.path.join(a.out_dir, "practice")
    os.makedirs(out, exist_ok=True)
    repo, sha = fetch_repo(os.path.join(a.scratch, "repo"))
    with open(os.path.join(out, "repo.json"), "w", encoding="utf-8") as f:
        json.dump({"repo": REPO, "sha": sha, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f)
    print("repo", REPO, sha, flush=True)
    sys.path.insert(0, os.path.join(repo, "kit"))
    import frontieror_real as FR  # noqa: E402
    import harness as H  # noqa: E402
    solvers = assemble(repo, os.path.join(a.scratch, "solvers"))
    chk = checkers(repo)
    summary = {"repo_sha": sha, "time_limit": a.time_limit, "variants": {}}
    for name, slug, sense, title in VARIANTS:
        if a.only and name not in a.only:
            continue
        vout = os.path.join(out, name)
        try:
            tally = FR.run_task(slug, solvers[name], chk[slug], sense, a.hf_dir, vout, a.time_limit,
                                size_info=size_info(slug), title=title)
        except Exception as e:  # noqa: BLE001 - record and go on with the next version
            summary["variants"][name] = {"slug": slug, "error": repr(e)[:500]}
            print("variant failed", name, repr(e), flush=True)
            continue
        rows = []
        with open(os.path.join(vout, "rows.jsonl"), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    r["official_score"] = official_score(r, sense, H)
                    if slug == "cordeau2006":
                        r.update(vehicles_used(os.path.join(vout, "work", r["name"] + ".solution.json")))
                    rows.append(r)
        with open(os.path.join(vout, "rows_scored.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")
        large = [r for r in rows if r["name"].startswith("large")]
        summary["variants"][name] = {
            "slug": slug, "sense": sense, "cases": len(rows),
            "official_feasible": sum(1 for r in rows if r.get("official_feasible") is True),
            "official_rejected": [r["name"] for r in rows if r.get("official_feasible") is False],
            "official_violated": {r["name"]: r.get("official_violated") for r in rows
                                  if r.get("official_feasible") is False},
            "official_violations": {r["name"]: str(r.get("official_violations"))[:300] for r in rows
                                    if r.get("official_feasible") is False},
            "no_output_or_overtime": [r["name"] for r in rows if r.get("status") in ("no_output", "overtime")],
            "ours_status": {r["name"]: r.get("status") for r in rows},
            "official_score_large_mean": round(sum(r["official_score"] for r in large) / len(large), 6)
            if large else None,
            "official_score_all": {r["name"]: r["official_score"] for r in rows},
            "gurobi_official_feasible": sum(1 for r in rows if r.get("gurobi_official_feasible") is True),
            "checkers_agree": tally.get("checkers_agree"), "checker_comparisons": tally.get("checker_comparisons"),
            "max_wall_s": tally.get("max_wall_s"), "revision": tally.get("revision"),
            "size": {r["name"]: {k: r.get(k) for k in ("rows", "cols", "listed_columns", "out_of_range_indices",
                                                       "users", "vehicles", "user_id_min",
                                                       "user_id_equals_pickup_node", "pickups_are_1_to_n",
                                                       "customers", "n", "routes_listed", "routes_used")
                                 if r.get(k) is not None} for r in rows},
        }
        with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1)
        print("variant", name, json.dumps(summary["variants"][name])[:1500], flush=True)
    lines = ["# MV2's FrontierOR practice solvers on the real public instances, official checkers", "",
             "Repository %s at %s; %ss per instance; official_score = contest score vs the stored Gurobi objective "
             "when the official feasibility_check.py accepts the file, else 0. FrontierOR benchmark: Hugging Face "
             "frontieror/FrontierOR (CC BY 4.0). Made with AI agents working in MV2's name (MV2 of Munim, Inc.)."
             % (REPO, sha, a.time_limit), "",
             "| version | task | official accepts | rejected | mean official score (5 large) | Gurobi refs accepted |",
             "|---|---|---|---|---|---|"]
    for name, v in summary["variants"].items():
        if "error" in v:
            lines.append("| %s | %s | error: %s | | | |" % (name, v["slug"], v["error"][:120]))
            continue
        lines.append("| %s | %s | %d/%d | %s | %s | %d |" % (name, v["slug"], v["official_feasible"], v["cases"],
                                                         ", ".join(v["official_rejected"]) or "-",
                                                         v["official_score_large_mean"],
                                                         v["gurobi_official_feasible"]))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", json.dumps({k: (v.get("official_feasible"), v.get("official_score_large_mean"))
                              for k, v in summary["variants"].items()}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

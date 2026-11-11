"""spp_v040: MV2's hoffman1993 (set partitioning) solver v0.4.0 on the real public FrontierOR instances, official checker,
in three phase-2 variants; and the contest-style submission folders for the four practice tasks his solvers pass.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python spp_v040.py --hf-dir /data/hf --out-dir /out [--time-limit 60] [--only spp-v040]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded).
2. Builds /tmp/mv2-spp040/solvers/<variant>/ = this folder's spp/hoffman1993/solve.py + the repo's
   kit/frontier_runtime.py (+ spp_config.json for the non-default variants):
     spp-v040        phase 2 = CP-SAT hinted with the search's incumbent (the default, what a submission runs)
     spp-v040-highs  phase 2 = HiGHS on the columns the Lagrangian filter keeps
     spp-v040-dfs    no phase 2: the exact-cover search gets all the time after the LP
3. Runs each on hoffman1993's tiny + 5 large public instances with the repo's kit/frontieror_real.run_task (60 s, the
   contest way), judged by practice/practice_real.spp_check and the official feasibility_check.py. official_score =
   min(2, ref/obj) vs the stored Gurobi objective when the official checker accepts the file and the run finished in
   time, else 0.
4. Assembles OUT/submission/<slug>/ (one folder per task, as the contest's archive wants) from the repo's own files:
     cordeau2006   practice/postfix/cordeau2006/solve.py + darp/cordeau2006/solve.py as darp_core.py
     nagy2015      practice/postfix/nagy2015/solve.py + vrpddp/nagy2015/solve.py as nagy_core.py
     fischetti1998 op/fischetti1998/solve.py
     hoffman1993   spp/hoffman1993/solve.py of THIS folder (v0.4.0) + kit/frontier_runtime.py
   byte-compiles every file, zips the four folders and records the archive size (the contest limit is 4 MB).
Writes OUT/spp040/<variant>/{rows.jsonl, rows_scored.jsonl, results.md, ...}, OUT/spp040/summary.json,
OUT/spp040/results.md, OUT/spp040/repo.json, OUT/submission/** and OUT/submission/manifest.json.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
import py_compile
import shutil
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "munimtechnologies/frontieror-routing"
UA = "MV2-of-Munim-Inc FrontierOR practice (mv2@munimtech.com)"
VARIANTS = [  # log_file only makes the solver also write <output>.log.json, so the run can be graded
    ("spp-v040", {"log_file": True}, "hoffman1993 (set partitioning) solver v0.4.0, phase 2 CP-SAT (default)"),
    ("spp-v040-highs", {"phase2": "highs", "log_file": True}, "hoffman1993 solver v0.4.0, phase 2 HiGHS"),
    ("spp-v040-dfs", {"phase2": "dfs", "log_file": True}, "hoffman1993 solver v0.4.0, exact-cover search only"),
]


def solver_logs(vout, names):
    """The <output>.log.json files the solver wrote (if the harness used work/<name>.solution.json as output)."""
    got = {}
    work = os.path.join(vout, "work")
    for name in names:
        hits = []
        if os.path.isdir(work):
            hits = [f for f in os.listdir(work) if f.startswith(name + ".") and f.endswith(".log.json")]
        for f in sorted(hits)[:1]:
            try:
                with open(os.path.join(work, f), encoding="utf-8") as fh:
                    got[name] = json.load(fh)
            except Exception as e:  # noqa: BLE001
                got[name] = {"unreadable": repr(e)[:200]}
    return got
SUBMISSION = [
    # slug, [(repo path or "HERE:<path>", file name in the folder)]
    ("cordeau2006", [("practice/postfix/cordeau2006/solve.py", "solve.py"),
                     ("darp/cordeau2006/solve.py", "darp_core.py")]),
    ("nagy2015", [("practice/postfix/nagy2015/solve.py", "solve.py"),
                  ("vrpddp/nagy2015/solve.py", "nagy_core.py")]),
    ("fischetti1998", [("op/fischetti1998/solve.py", "solve.py")]),
    ("hoffman1993", [("HERE:spp/hoffman1993/solve.py", "solve.py"),
                     ("kit/frontier_runtime.py", "frontier_runtime.py")]),
]
ARCHIVE_LIMIT = 4 * 1024 * 1024


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


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


def source(repo, path):
    return os.path.join(HERE, path[5:]) if path.startswith("HERE:") else os.path.join(repo, *path.split("/"))


def build_variants(repo, root):
    if os.path.exists(root):
        shutil.rmtree(root)
    out = {}
    for name, cfg, _title in VARIANTS:
        d = os.path.join(root, name)
        _copy(os.path.join(HERE, "spp", "hoffman1993", "solve.py"), os.path.join(d, "solve.py"))
        _copy(os.path.join(repo, "kit", "frontier_runtime.py"), os.path.join(d, "frontier_runtime.py"))
        if cfg is not None:
            with open(os.path.join(d, "spp_config.json"), "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        out[name] = os.path.join(d, "solve.py")
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def assemble_submission(repo, out_dir):
    """OUT/submission/<slug>/..., byte-compiled; returns the manifest."""
    sub = os.path.join(out_dir, "submission")
    if os.path.exists(sub):
        shutil.rmtree(sub)
    man = {"folders": {}, "errors": []}
    for slug, files in SUBMISSION:
        entry = []
        for src, name in files:
            p = source(repo, src)
            dst = os.path.join(sub, slug, name)
            if not os.path.exists(p):
                man["errors"].append("%s: missing %s" % (slug, src))
                continue
            _copy(p, dst)
            try:
                py_compile.compile(dst, cfile=os.path.join("/tmp", "mv2-pyc", slug, name + "c"), doraise=True)
                ok = True
            except py_compile.PyCompileError as e:
                ok = False
                man["errors"].append("%s/%s: %s" % (slug, name, str(e)[:200]))
            entry.append({"file": name, "from": src, "bytes": os.path.getsize(dst), "sha256": sha256(dst),
                          "compiles": ok})
        man["folders"][slug] = entry
    zpath = os.path.join(out_dir, "submission.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for slug, _files in SUBMISSION:
            for name in sorted(os.listdir(os.path.join(sub, slug))) if os.path.isdir(os.path.join(sub, slug)) else []:
                z.write(os.path.join(sub, slug, name), "%s/%s" % (slug, name))
    man["archive_bytes"] = os.path.getsize(zpath)
    man["archive_within_4mb"] = man["archive_bytes"] <= ARCHIVE_LIMIT
    with open(os.path.join(sub, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1)
    return man


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--scratch", default="/tmp/mv2-spp040")
    a = ap.parse_args(argv)
    out = os.path.join(a.out_dir, "spp040")
    os.makedirs(out, exist_ok=True)
    repo, sha = fetch_repo(os.path.join(a.scratch, "repo"))
    with open(os.path.join(out, "repo.json"), "w", encoding="utf-8") as f:
        json.dump({"repo": REPO, "sha": sha, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f)
    print("repo", REPO, sha, flush=True)
    man = assemble_submission(repo, a.out_dir)
    print("submission", json.dumps({k: man[k] for k in ("archive_bytes", "archive_within_4mb", "errors")}),
          flush=True)
    sys.path.insert(0, os.path.join(repo, "kit"))
    import frontieror_real as FR  # noqa: E402
    import harness as H  # noqa: E402
    PR = _module(os.path.join(repo, "practice", "practice_real.py"), "mv2_practice_real")
    solvers = build_variants(repo, os.path.join(a.scratch, "solvers"))
    summary = {"repo_sha": sha, "time_limit": a.time_limit, "submission": man, "variants": {}}
    for name, _cfg, title in VARIANTS:
        if a.only and name not in a.only:
            continue
        vout = os.path.join(out, name)
        try:
            tally = FR.run_task("hoffman1993", solvers[name], PR.spp_check, "min", a.hf_dir, vout, a.time_limit,
                                size_info=PR.size_info("hoffman1993"), title=title)
        except Exception as e:  # noqa: BLE001 - record and go on with the next variant
            summary["variants"][name] = {"error": repr(e)[:500]}
            print("variant failed", name, repr(e), flush=True)
            continue
        rows = []
        with open(os.path.join(vout, "rows.jsonl"), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    r["official_score"] = PR.official_score(r, "min", H)
                    rows.append(r)
        with open(os.path.join(vout, "rows_scored.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")
        large = [r for r in rows if r["name"].startswith("large")]
        summary["variants"][name] = {
            "cases": len(rows),
            "official_feasible": sum(1 for r in rows if r.get("official_feasible") is True),
            "official_rejected": [r["name"] for r in rows if r.get("official_feasible") is False],
            "official_violations": {r["name"]: str(r.get("official_violations"))[:300] for r in rows
                                    if r.get("official_feasible") is False},
            "no_output_or_overtime": [r["name"] for r in rows if r.get("status") in ("no_output", "overtime")],
            "official_score_large_mean": round(sum(r["official_score"] for r in large) / len(large), 6)
            if large else None,
            "official_score_all": {r["name"]: r["official_score"] for r in rows},
            "objective": {r["name"]: r.get("objective") for r in rows},
            "reference": {r["name"]: r.get("reference") for r in rows},
            "wall_s": {r["name"]: r.get("wall_s") for r in rows},
            "solver_log": {r["name"]: str(r.get("stderr_tail") or "")[-700:] for r in rows},
            "solver_log_file": solver_logs(vout, [r["name"] for r in rows]),
            "checkers_agree": tally.get("checkers_agree"), "checker_comparisons": tally.get("checker_comparisons"),
            "max_wall_s": tally.get("max_wall_s"),
        }
        with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1)
        print("variant", name, json.dumps(summary["variants"][name])[:1500], flush=True)
    lines = ["# hoffman1993 (set partitioning) v0.4.0 on the public FrontierOR instances, official checker", "",
             "Repository %s at %s; %ss per instance; official_score = min(2, Gurobi objective / ours) when the "
             "official feasibility_check.py accepts the file and the run finished in time, else 0. v0.3.0 scored "
             "0.273929 (3 of 5 large instances with no output). FrontierOR benchmark: Hugging Face "
             "frontieror/FrontierOR (CC BY 4.0). Made with AI agents working in MV2's name (MV2 of Munim, Inc.)."
             % (REPO, sha, a.time_limit), "",
             "| variant | official accepts | no output / overtime | mean official score (5 large) | per instance |",
             "|---|---|---|---|---|"]
    for name, v in summary["variants"].items():
        if "error" in v:
            lines.append("| %s | error: %s | | | |" % (name, v["error"][:120]))
            continue
        per = ", ".join("%s %s" % (k, v["official_score_all"][k]) for k in sorted(v["official_score_all"]))
        lines.append("| %s | %d/%d | %s | %s | %s |" % (name, v["official_feasible"], v["cases"],
                                                       ", ".join(v["no_output_or_overtime"]) or "-",
                                                       v["official_score_large_mean"], per))
    lines += ["", "Submission folders: %d bytes zipped (limit 4 MB: %s); errors: %s"
              % (man["archive_bytes"], man["archive_within_4mb"], man["errors"] or "none")]
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", json.dumps({k: (v.get("official_feasible"), v.get("official_score_large_mean"))
                              for k, v in summary["variants"].items()}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

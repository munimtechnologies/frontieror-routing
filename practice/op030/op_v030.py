"""op_v030: MV2's fischetti1998 (orienteering) solver v0.3.0 on the real public FrontierOR instances, official checker,
in three variants, against the published v1, on the same machine in the same job.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python op_v030.py --hf-dir /data/hf --out-dir /out [--time-limit 60] [--only op-v030]

1. Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main (sha recorded).
2. Builds /tmp/mv2-op030/solvers/<variant>/ (one contest-style folder each):
     op-v030          this folder's op/fischetti1998/solve.py + the repo's op/fischetti1998/solve.py (published v1)
                      as op_core.py; parallel: v1 search + OR-Tools guided local search on the second CPU (default)
     op-v030-ortools  same files, op_config.json {"mode": "ortools"}: OR-Tools only, one process
     op-v030-ops      same files, op_config.json {"extra_ops": true}: parallel, two more OR-Tools neighbourhoods
     op-v020          the repo's op/fischetti1998/solve.py as published (baseline)
   (the v0.3.0 variants also get "log_file": true, so each run leaves <output>.log.json for grading)
3. Runs each on fischetti1998's tiny + 5 large public instances with the repo's kit/frontieror_real.run_task (60 s,
   the contest way), judged by the repo's op/op_eval.py and the official feasibility_check.py. official_score =
   min(2, ours / Gurobi) when the official checker accepts the file and the run finished in time, else 0.
Writes OUT/op030/<variant>/{rows.jsonl, rows_scored.jsonl, results.md, ...}, OUT/op030/summary.json,
OUT/op030/results.md, OUT/op030/repo.json.
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
SLUG = "fischetti1998"
VARIANTS = [
    ("op-v030", {"log_file": True},
     "fischetti1998 (orienteering) solver v0.3.0, v1 search + OR-Tools GLS in parallel (default)"),
    ("op-v030-ortools", {"mode": "ortools", "log_file": True}, "fischetti1998 solver v0.3.0, OR-Tools GLS only"),
    ("op-v030-ops", {"extra_ops": True, "log_file": True},
     "fischetti1998 solver v0.3.0, parallel, extra OR-Tools neighbourhoods"),
    ("op-v1", None, "fischetti1998 solver v1 as published (baseline)"),
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


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


def build_variants(repo, root):
    if os.path.exists(root):
        shutil.rmtree(root)
    v1 = os.path.join(repo, "op", "fischetti1998", "solve.py")
    out = {}
    for name, cfg, _title in VARIANTS:
        d = os.path.join(root, name)
        if cfg is None:
            _copy(v1, os.path.join(d, "solve.py"))
        else:
            _copy(os.path.join(HERE, "op", "fischetti1998", "solve.py"), os.path.join(d, "solve.py"))
            _copy(v1, os.path.join(d, "op_core.py"))
            with open(os.path.join(d, "op_config.json"), "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        out[name] = os.path.join(d, "solve.py")
    return out


def solver_logs(vout, names):
    """The <output>.log.json files the solver wrote (the harness's output is work/<name>.solution.json)."""
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--scratch", default="/tmp/mv2-op030")
    a = ap.parse_args(argv)
    out = os.path.join(a.out_dir, "op030")
    os.makedirs(out, exist_ok=True)
    repo, sha = fetch_repo(os.path.join(a.scratch, "repo"))
    with open(os.path.join(out, "repo.json"), "w", encoding="utf-8") as f:
        json.dump({"repo": REPO, "sha": sha, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f)
    print("repo", REPO, sha, flush=True)
    try:
        import ortools  # noqa: F401
        ort_version = getattr(ortools, "__version__", "?")
    except Exception as e:  # noqa: BLE001
        ort_version = "missing: %r" % (e,)
    print("ortools", ort_version, flush=True)
    sys.path.insert(0, os.path.join(repo, "kit"))
    import frontieror_real as FR  # noqa: E402
    import harness as H  # noqa: E402
    PR = _module(os.path.join(repo, "practice", "practice_real.py"), "mv2_practice_real")
    chk = PR.checkers(repo)[SLUG]
    solvers = build_variants(repo, os.path.join(a.scratch, "solvers"))
    summary = {"repo_sha": sha, "time_limit": a.time_limit, "ortools": ort_version, "python": sys.version,
               "cpu_count": os.cpu_count(), "variants": {}}
    for name, _cfg, title in VARIANTS:
        if a.only and name not in a.only:
            continue
        vout = os.path.join(out, name)
        try:
            tally = FR.run_task(SLUG, solvers[name], chk, "max", a.hf_dir, vout, a.time_limit,
                                size_info=PR.size_info(SLUG), title=title)
        except Exception as e:  # noqa: BLE001 - record and go on with the next variant
            summary["variants"][name] = {"error": repr(e)[:500]}
            print("variant failed", name, repr(e), flush=True)
            continue
        rows = []
        with open(os.path.join(vout, "rows.jsonl"), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    r["official_score"] = PR.official_score(r, "max", H)
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
            "t0": {r["name"]: r.get("t0") for r in rows},
            "wall_s": {r["name"]: r.get("wall_s") for r in rows},
            "solver_log": {r["name"]: str(r.get("stderr_tail") or "")[-700:] for r in rows},
            "solver_log_file": solver_logs(vout, [r["name"] for r in rows]),
            "checkers_agree": tally.get("checkers_agree"), "checker_comparisons": tally.get("checker_comparisons"),
            "max_wall_s": tally.get("max_wall_s"),
        }
        with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1)
        print("variant", name, json.dumps(summary["variants"][name])[:1500], flush=True)
    lines = ["# fischetti1998 (orienteering) v0.3.0 on the public FrontierOR instances, official checker", "",
             "Repository %s at %s; %ss per instance; OR-Tools %s; %s CPUs. official_score = min(2, our prize / "
             "Gurobi's) when the official feasibility_check.py accepts the file and the run finished in time, else 0. "
             "v1 scored 0.893785 in the 11 Nov practice run. FrontierOR benchmark: Hugging Face "
             "frontieror/FrontierOR (CC BY 4.0). Made with AI agents working in MV2's name (MV2 of Munim, Inc.)."
             % (REPO, sha, a.time_limit, ort_version, os.cpu_count()), "",
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
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done", json.dumps({k: (v.get("official_feasible"), v.get("official_score_large_mean"))
                              for k, v in summary["variants"].items()}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

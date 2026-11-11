"""trace_census: re-run every FrontierOR task's official checker on its stored Gurobi solutions, with key tracing.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python census/trace_census.py --out-dir /out/census [--max-bytes 5000000] [--timeout 120] [--budget-min 200]
                                [--only slug ...]

For each task of the public FrontierOR benchmark (Hugging Face frontieror/FrontierOR, CC BY 4.0, one pinned
revision) and each of its six cases (tiny + large_1..5) whose instance and Gurobi solution are both at most
--max-bytes, this downloads feasibility_check.py, the instance, the stored Gurobi solution and the stored
gurobi_feasi_result into a scratch folder (deleted after each task), then runs the checker unchanged through
trace_run.py (every read of an absent key recorded, see there). If the traced run fails or times out, the plain
checker is run once more for the verdict. Rows go to rows.jsonl as each case finishes.

Outputs: rows.jsonl, by_task.json, summary.json, defaults.md (instance keys a checker read but the instance lacks),
verdicts.md (cases where today's checker disagrees with the stored gurobi_feasi_result), manifest.json.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(os.path.dirname(HERE), "kit")
for p in (KIT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import frontieror_hf as HF  # noqa: E402

CASES = [("tiny", "tiny_instance.json", "tiny_solution.json", "tiny_feasi_result.json")] + [
    ("large_%d" % k, "large_instance_%d.json" % k, "large_solution_%d.json" % k, "large_feasi_result_%d.json" % k)
    for k in range(1, 6)]
DEFAULT_KINDS = ("get", "setdefault")


def run_traced(checker, ip, sp, work, name, timeout):
    rp = os.path.join(work, name + ".traced.result.json")
    tp = os.path.join(work, name + ".trace.json")
    out = {"trace_status": None, "feasible": None, "violated": None, "violations": "", "events": []}
    t0 = time.monotonic()
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "trace_run.py"), "--checker", checker, "--instance", ip,
                        "--solution", sp, "--result", rp, "--trace", tp], capture_output=True, text=True,
                       timeout=timeout, cwd=work)
    except subprocess.TimeoutExpired:
        out["trace_status"] = "timeout"
    out["trace_seconds"] = round(time.monotonic() - t0, 3)
    if os.path.exists(tp):
        with open(tp, encoding="utf-8") as f:
            tr = json.load(f)
        out["trace_status"] = out["trace_status"] or tr.get("status")
        out["events"] = tr.get("events") or []
    elif out["trace_status"] is None:
        out["trace_status"] = "no-trace"
    if os.path.exists(rp):
        try:
            with open(rp, encoding="utf-8") as f:
                r = json.load(f)
            out.update(feasible=r.get("feasible"), violated=r.get("violated_constraints"),
                       violations=str(r.get("violations"))[:300])
        except ValueError:
            pass
    return out


def run_plain(checker, ip, sp, work, name, timeout):
    rp = os.path.join(work, name + ".plain.result.json")
    try:
        p = subprocess.run([sys.executable, checker, "--instance_path", ip, "--solution_path", sp, "--result_path",
                            rp], capture_output=True, text=True, timeout=timeout, cwd=work)
        code, err = p.returncode, p.stderr[-300:]
    except subprocess.TimeoutExpired:
        return {"plain_status": "timeout"}
    out = {"plain_status": "exit %s" % code, "plain_stderr": err}
    if os.path.exists(rp):
        try:
            with open(rp, encoding="utf-8") as f:
                r = json.load(f)
            out.update(feasible=r.get("feasible"), violated=r.get("violated_constraints"),
                       violations=str(r.get("violations"))[:300])
        except ValueError:
            pass
    return out


def stored_verdict(path):
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            r = json.load(f)
    except ValueError:
        return "unreadable", None
    return r.get("feasible"), r.get("violated_constraints")


def census_task(tid, rev, scratch, max_bytes, timeout, done, rows_p):
    files = HF.tree("tasks/" + tid, rev, recursive=True)
    size = {e["path"]: int(e.get("size") or 0) for e in files if e.get("type") == "file"}
    base = "tasks/" + tid + "/"
    tdir = os.path.join(scratch, tid)
    os.makedirs(tdir, exist_ok=True)
    checker_rel = base + "feasibility_check.py"
    if checker_rel not in size:
        return [{"task": tid, "name": "*", "status": "no_checker"}]
    checker = os.path.join(tdir, "feasibility_check.py")
    HF.download(checker_rel, rev, checker, expect_size=size[checker_rel])
    rows = []
    for name, ifile, sfile, ffile in CASES:
        if (tid, name) in done:
            continue
        ipath, spath, fpath = base + "instance/" + ifile, base + "gurobi_solution/" + sfile, \
            base + "gurobi_feasi_result/" + ffile
        row = {"task": tid, "name": name, "instance_bytes": size.get(ipath), "solution_bytes": size.get(spath)}
        if ipath not in size:
            row["status"] = "no_instance"
        elif spath not in size:
            row["status"] = "no_solution"
        elif size[ipath] > max_bytes or size[spath] > max_bytes:
            row["status"] = "too_big"
        else:
            ip = os.path.join(tdir, "instance", ifile)
            sp = os.path.join(tdir, "gurobi_solution", sfile)
            fp = os.path.join(tdir, "gurobi_feasi_result", ffile)
            HF.download(ipath, rev, ip, expect_size=size[ipath])
            HF.download(spath, rev, sp, expect_size=size[spath])
            if fpath in size:
                HF.download(fpath, rev, fp, expect_size=size[fpath])
            sf, sv = stored_verdict(fp)
            row.update(stored_feasible=sf, stored_violated=sv)
            work = os.path.join(tdir, "work")
            os.makedirs(work, exist_ok=True)
            tr = run_traced(checker, ip, sp, work, name, timeout)
            row.update({k: v for k, v in tr.items() if k != "events"})
            ev = tr["events"]
            row["instance_events"] = [e for e in ev if e["src"] == "instance"][:200]
            row["solution_events"] = [e for e in ev if e["src"] == "solution"][:100]
            row["other_events"] = len([e for e in ev if e["src"] not in ("instance", "solution")])
            row["verdict_from"] = "traced"
            if tr.get("feasible") is None:
                pl = run_plain(checker, ip, sp, work, name, max(timeout, 180))
                row.update(pl)
                row["verdict_from"] = "plain"
            if row.get("feasible") is None:
                row["status"] = "checker_failed"
            elif sf is None:
                row["status"] = "ran_no_stored_result"
            else:
                row["status"] = "ran"
            row["reproduced"] = (sf is not None and row.get("feasible") is not None and
                                 bool(sf) == bool(row.get("feasible")))
        with open(rows_p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        rows.append(row)
        print("census", tid, name, row["status"], row.get("feasible"), row.get("stored_feasible"),
              len(row.get("instance_events") or []), flush=True)
    shutil.rmtree(tdir, ignore_errors=True)
    return rows


def aggregate(rows, rev, out):
    by_task = {}
    for r in rows:
        t = by_task.setdefault(r["task"], {"cases": 0, "ran": 0, "reproduced": 0, "mismatch": [], "failed": [],
                                           "skipped": {}, "instance_keys": {}, "solution_keys": {}})
        t["cases"] += 1
        st = r.get("status")
        if st in ("ran", "ran_no_stored_result"):
            t["ran"] += 1
            if r.get("reproduced"):
                t["reproduced"] += 1
            elif st == "ran":
                t["mismatch"].append({"name": r["name"], "stored": r.get("stored_feasible"),
                                      "now": r.get("feasible"), "violated": r.get("violated"),
                                      "violations": r.get("violations")})
        elif st == "checker_failed":
            t["failed"].append({"name": r["name"], "trace_status": r.get("trace_status"),
                                "plain_status": r.get("plain_status")})
        else:
            t["skipped"][st] = t["skipped"].get(st, 0) + 1
        for side in ("instance", "solution"):
            for e in r.get(side + "_events") or []:
                k = "%s|%s" % (e["key"], e["kind"])
                agg = t[side + "_keys"].setdefault(k, {"key": e["key"], "kind": e["kind"], "defaults": [],
                                                       "cases": [], "contexts": [], "reads": 0})
                if e["default"] not in agg["defaults"]:
                    agg["defaults"].append(e["default"])
                if r["name"] not in agg["cases"]:
                    agg["cases"].append(r["name"])
                if e["context"] not in agg["contexts"] and len(agg["contexts"]) < 3:
                    agg["contexts"].append(e["context"])
                agg["reads"] += e["count"]
    ran = [r for r in rows if r.get("status") in ("ran", "ran_no_stored_result")]
    with_stored = [r for r in rows if r.get("status") == "ran"]
    tasks_default = sorted(t for t, v in by_task.items()
                           if any(a["kind"] in DEFAULT_KINDS for a in v["instance_keys"].values()))
    tasks_any = sorted(t for t, v in by_task.items() if v["instance_keys"])
    summary = {
        "revision": rev, "tasks": len(by_task), "cases": len(rows), "ran": len(ran),
        "with_stored_result": len(with_stored),
        "reproduced": sum(1 for r in with_stored if r.get("reproduced")),
        "mismatches": sum(1 for r in with_stored if not r.get("reproduced")),
        "checker_failed": sum(1 for r in rows if r.get("status") == "checker_failed"),
        "skipped": {s: sum(1 for r in rows if r.get("status") == s) for s in
                    sorted({r.get("status") for r in rows} - {"ran", "ran_no_stored_result", "checker_failed"})},
        "tasks_with_instance_default_reads": len(tasks_default),
        "tasks_with_instance_default_reads_list": tasks_default,
        "tasks_with_any_absent_instance_key_read": len(tasks_any),
        "he2020_instance_keys": sorted(by_task.get("he2020", {}).get("instance_keys", {}).keys()),
        "traced_timeouts": sum(1 for r in rows if r.get("trace_status") == "timeout"),
    }
    with open(os.path.join(out, "by_task.json"), "w", encoding="utf-8") as f:
        json.dump(by_task, f, indent=1, default=str)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    intro = ("Public FrontierOR benchmark (Hugging Face frontieror/FrontierOR, revision %s, CC BY 4.0). Each task's "
             "official feasibility_check.py was run unchanged on its stored Gurobi solutions; every read of a key "
             "that the instance JSON does not contain was recorded (trace_run.py). Made with AI agents working in "
             "MV2's name (MV2 of Munim, Inc.)." % rev)
    lines = ["# FrontierOR checker census: instance keys a checker reads but the instance lacks", "", intro, "",
             "```", json.dumps(summary, indent=1), "```", "",
             "Kinds: get / setdefault = the checker fell back to the default shown; in = a membership test came "
             "back false; getitem = d[key] raised KeyError (the checker may catch it). A default read is not a bug "
             "by itself: the triage of what each one changes is done by hand afterwards.", "",
             "| task | key | kind | default(s) | cases | reads | context (keys of the object read) |",
             "|---|---|---|---|---|---|---|"]
    for tid in sorted(by_task):
        for a in sorted(by_task[tid]["instance_keys"].values(), key=lambda a: (a["kind"], a["key"])):
            lines.append("| %s | %s | %s | %s | %d/%d | %d | %s |" % (
                tid, a["key"].replace("|", "/"), a["kind"], " / ".join(a["defaults"]).replace("|", "/")[:80],
                len(a["cases"]), by_task[tid]["ran"], a["reads"], (a["contexts"][0] if a["contexts"] else "")[:90]))
    with open(os.path.join(out, "defaults.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    vl = ["# FrontierOR checker census: today's checker vs the stored gurobi_feasi_result", "", intro, "",
          "| task | case | stored feasible | checker now | violated | violations (first 300 chars) |",
          "|---|---|---|---|---|---|"]
    for tid in sorted(by_task):
        for m in by_task[tid]["mismatch"]:
            vl.append("| %s | %s | %s | %s | %s | %s |" % (tid, m["name"], m["stored"], m["now"], m["violated"],
                                                           str(m["violations"]).replace("|", "/")[:300]))
        for m in by_task[tid]["failed"]:
            vl.append("| %s | %s | - | checker failed | %s | %s |" % (tid, m["name"], m["trace_status"],
                                                                      m["plain_status"]))
    with open(os.path.join(out, "verdicts.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(vl) + "\n")
    print("summary", json.dumps(summary), flush=True)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--scratch", default="/tmp/frontieror-census")
    ap.add_argument("--max-bytes", type=int, default=5000000)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--budget-min", type=float, default=200.0)
    ap.add_argument("--delay", type=float, default=0.2)
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args(argv)
    a.scratch = os.path.abspath(a.scratch)
    os.makedirs(a.out_dir, exist_ok=True)
    t0 = time.monotonic()
    rev = HF.revision()
    print("revision", rev, flush=True)
    tasks = sorted(e["path"].split("/")[-1] for e in HF.tree("tasks", rev) if e.get("type") == "directory")
    if a.only:
        tasks = [t for t in tasks if t in set(a.only)]
    rows_p = os.path.join(a.out_dir, "rows.jsonl")
    done = set()
    if os.path.exists(rows_p):
        with open(rows_p, encoding="utf-8") as f:
            done = {(r["task"], r["name"]) for r in (json.loads(x) for x in f if x.strip())}
    errors = []
    stopped_early = False
    for tid in tasks:
        if (time.monotonic() - t0) / 60.0 > a.budget_min:
            stopped_early = True
            break
        try:
            census_task(tid, rev, a.scratch, a.max_bytes, a.timeout, done, rows_p)
        except Exception as e:  # noqa: BLE001
            errors.append({"task": tid, "error": repr(e)[:300]})
            print("census-error", tid, repr(e)[:300], flush=True)
            shutil.rmtree(os.path.join(a.scratch, tid), ignore_errors=True)
        time.sleep(a.delay)
    with open(rows_p, encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    summary = aggregate(rows, rev, a.out_dir)
    with open(os.path.join(a.out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"revision": rev, "tasks_listed": len(tasks), "errors": errors, "stopped_early": stopped_early,
                   "max_bytes": a.max_bytes, "timeout_s": a.timeout,
                   "minutes": round((time.monotonic() - t0) / 60.0, 1)}, f, indent=1)
    return 0 if summary else 1


if __name__ == "__main__":
    sys.exit(main())

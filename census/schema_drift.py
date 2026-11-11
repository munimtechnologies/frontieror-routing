"""schema_drift: compare each FrontierOR task's documented instance format with its real instance files.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python census/schema_drift.py --out-dir /out/drift [--max-bytes 15000000] [--budget-min 150] [--only slug ...]

For every task of the public FrontierOR benchmark (Hugging Face frontieror/FrontierOR, CC BY 4.0) at one pinned
revision, this downloads instance_schema.json, feasibility_check.py and gurobi_code.py, and each of the six
instances (tiny + large_1..5) up to --max-bytes, into a scratch folder that is deleted after the task. It then walks
the schema and each instance side by side and records:
- extra:   a key present in an instance object whose schema documents that object but not that key;
- missing: a key the schema documents that the instance object does not have.
Lists are compared through their first five items. A schema object whose keys are all placeholders ("{...}" or
"<...>") is treated as a map. An object with more than 20 undocumented keys is recorded once, as a map.
Each finding's last key name is looked up as a quoted string in the official checker and in gurobi_code.py (a
mention, not proof of use). Every `.get("key", ...)` the checker makes on a variable named instance, inst, data or
instance_data is compared with each instance's top-level keys (`data` is sometimes the solution: triage by hand).

Outputs: rows.jsonl (one line per task, written as each task finishes), summary.json, drift.md, manifest.json.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(os.path.dirname(HERE), "kit")
for p in (KIT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import frontieror_hf as HF  # noqa: E402

CASES = ["tiny_instance.json"] + ["large_instance_%d.json" % k for k in range(1, 6)]
SAMPLE = 5
MANY = 20
TOP_KEYS_MAX = 300
PLACEHOLDER = re.compile(r"^\s*[{<].*[}>]\s*$")
GET_RE = re.compile(r"\b(?:instance|inst|data|instance_data)\.get\(\s*[\"']([^\"']+)[\"']")

# Keys whose presence the pre-registration asks about (DRIFT-PREREG.md, S4-S7), plus he2020 as a cross-check.
WATCH = {
    "cordeau2019": ["problem_types"],
    "vidal2011": ["p", "t"],
    "wei2020": ["conflicts", "edges"],
    "gangammanavar2020": ["seed"],
    "xie2019": ["random_seed"],
    "he2020": ["inconvenience_cost_factor_rho", "inconvenience_cost_function"],
}


def case_name(ifile):
    return ifile.replace("_instance", "").replace(".json", "")


def is_map_schema(node):
    return isinstance(node, dict) and len(node) > 0 and all(PLACEHOLDER.match(str(k)) for k in node)


def join(path, key):
    return "%s.%s" % (path, key) if path else str(key)


def walk(schema, inst, path, out):
    """Add documented-but-absent paths to out["missing"] and present-but-undocumented paths to out["extra"]."""
    if isinstance(schema, dict) and isinstance(inst, dict):
        if is_map_schema(schema):
            sub = next(iter(schema.values()))
            for v in list(inst.values())[:SAMPLE]:
                walk(sub, v, path + "{}", out)
            return
        for k in schema:
            if k in inst:
                walk(schema[k], inst[k], join(path, k), out)
            else:
                out["missing"].add(join(path, k))
        extra = [k for k in inst if k not in schema]
        if len(extra) > MANY:
            out["extra"].add(join(path, "{%d+ undocumented keys}" % MANY))
        else:
            for k in extra:
                out["extra"].add(join(path, k))
    elif isinstance(schema, list) and schema and isinstance(inst, list):
        for v in inst[:SAMPLE]:
            walk(schema[0], v, path + "[]", out)


def leaf(path):
    last = path.split(".")[-1]
    return re.sub(r"(\[\]|\{\})+$", "", last)


def mentions(text, key):
    if not text or not key:
        return False
    return re.search(r"[\"']%s[\"']" % re.escape(key), text) is not None


def drift_task(tid, rev, scratch, max_bytes):
    files = HF.tree("tasks/" + tid, rev, recursive=True)
    size = {e["path"]: int(e.get("size") or 0) for e in files if e.get("type") == "file"}
    base = "tasks/" + tid + "/"
    tdir = os.path.join(scratch, tid)
    os.makedirs(tdir, exist_ok=True)
    texts = {}
    for name in ("instance_schema.json", "feasibility_check.py", "gurobi_code.py"):
        rel = base + name
        if rel in size:
            dest = os.path.join(tdir, name)
            HF.download(rel, rev, dest, expect_size=size[rel])
            with open(dest, encoding="utf-8", errors="replace") as f:
                texts[name] = f.read()
    row = {"task": tid, "cases": [], "skipped": {}, "top_keys": {}, "get_absent": {}}
    schema = None
    try:
        schema = json.loads(texts.get("instance_schema.json") or "null")
    except ValueError:
        row["schema_error"] = "unreadable"
    if not isinstance(schema, (dict, list)):
        row["schema_error"] = row.get("schema_error") or "no schema object"
        schema = None
    checker = texts.get("feasibility_check.py", "")
    gcode = texts.get("gurobi_code.py", "")
    gets = sorted(set(GET_RE.findall(checker)))
    row["checker_get_keys"] = gets
    found = {"missing": {}, "extra": {}}
    for ifile in CASES:
        name = case_name(ifile)
        rel = base + "instance/" + ifile
        if rel not in size:
            row["skipped"][name] = "no_instance"
            continue
        if size[rel] > max_bytes:
            row["skipped"][name] = "too_big"
            continue
        ip = os.path.join(tdir, ifile)
        HF.download(rel, rev, ip, expect_size=size[rel])
        try:
            with open(ip, encoding="utf-8") as f:
                inst = json.load(f)
        except ValueError:
            row["skipped"][name] = "unreadable"
            os.remove(ip)
            continue
        os.remove(ip)
        row["cases"].append(name)
        if isinstance(inst, dict):
            row["top_keys"][name] = sorted(inst.keys())[:TOP_KEYS_MAX]
            for k in gets:
                if k not in inst:
                    row["get_absent"].setdefault(k, []).append(name)
        if schema is not None:
            out = {"missing": set(), "extra": set()}
            walk(schema, inst, "", out)
            for side in ("missing", "extra"):
                for pth in out[side]:
                    found[side].setdefault(pth, []).append(name)
        del inst
    for side in ("missing", "extra"):
        row[side + "_info"] = [{"path": pth, "cases": cs, "checker_mentions": mentions(checker, leaf(pth)),
                                "gurobi_mentions": mentions(gcode, leaf(pth))}
                               for pth, cs in sorted(found[side].items())]
    shutil.rmtree(tdir, ignore_errors=True)
    return row


def watch_presence(rows):
    by = {r["task"]: r for r in rows}
    res = {}
    for tid, keys in WATCH.items():
        r = by.get(tid)
        if not r:
            continue
        n = len(r["cases"])
        res[tid] = {k: "%d/%d" % (sum(1 for c in r["cases"] if k in r["top_keys"].get(c, [])), n) for k in keys}
    return res


def _md(s, n=120):
    return str(s).replace("|", "/").replace("\n", " ")[:n]


def aggregate(rows, rev, out):
    scanned = [r for r in rows if r["cases"]]
    skipped = {}
    for r in rows:
        for why in r["skipped"].values():
            skipped[why] = skipped.get(why, 0) + 1
    summary = {
        "revision": rev,
        "tasks": len(rows),
        "tasks_scanned": len(scanned),
        "tasks_all_six_scanned": sum(1 for r in rows if len(r["cases"]) == 6),
        "cases_scanned": sum(len(r["cases"]) for r in rows),
        "cases_skipped": skipped,
        "schema_errors": sorted(r["task"] for r in rows if r.get("schema_error")),
        "tasks_with_extra": sum(1 for r in scanned if r["extra_info"]),
        "tasks_with_extra_checker_mentions": sum(1 for r in scanned
                                                 if any(e["checker_mentions"] for e in r["extra_info"])),
        "tasks_with_missing": sum(1 for r in scanned if r["missing_info"]),
        "tasks_with_missing_checker_mentions": sum(1 for r in scanned
                                                   if any(e["checker_mentions"] for e in r["missing_info"])),
        "tasks_with_checker_get_absent": sorted(r["task"] for r in scanned if r["get_absent"]),
        "extra_paths": sum(len(r["extra_info"]) for r in rows),
        "missing_paths": sum(len(r["missing_info"]) for r in rows),
        "watch": watch_presence(rows),
    }
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    intro = ("Public FrontierOR benchmark (Hugging Face frontieror/FrontierOR, revision %s, CC BY 4.0). For each "
             "task, every instance file up to the size cap was compared with the task's instance_schema.json. "
             "'extra' = key in the instance that the schema does not document; 'missing' = documented key the "
             "instance lacks. 'checker' / 'gurobi' = the key name appears as a quoted string in the official "
             "feasibility_check.py / gurobi_code.py (a mention, not proof of use). Made with AI agents working in "
             "MV2's name (MV2 of Munim, Inc.)." % rev)
    lines = ["# FrontierOR schema drift: documented instance format vs the real instance files", "", intro, "",
             "```", json.dumps(summary, indent=1), "```", "",
             "## Findings", "",
             "| task | finding | path | cases | checker | gurobi |", "|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["task"]):
        for side in ("missing", "extra"):
            for e in r[side + "_info"]:
                lines.append("| %s | %s | `%s` | %d/%d | %s | %s |" % (
                    r["task"], side, _md(e["path"], 90), len(e["cases"]), len(r["cases"]),
                    "yes" if e["checker_mentions"] else "-", "yes" if e["gurobi_mentions"] else "-"))
    lines += ["", "## Checker .get() keys absent from the instance's top level", "",
              "`data` is sometimes the solution object, so each line is triaged by hand.", "",
              "| task | key | cases without it |", "|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["task"]):
        for k, cs in sorted(r["get_absent"].items()):
            lines.append("| %s | `%s` | %d/%d (%s) |" % (r["task"], _md(k, 60), len(cs), len(r["cases"]),
                                                       ", ".join(cs)))
    lines += ["", "## Skipped cases", "", "| task | skipped |", "|---|---|"]
    for r in sorted(rows, key=lambda r: r["task"]):
        if r["skipped"]:
            lines.append("| %s | %s |" % (r["task"], ", ".join("%s: %s" % kv for kv in sorted(r["skipped"].items()))))
    with open(os.path.join(out, "drift.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("summary", json.dumps(summary), flush=True)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--scratch", default="/tmp/frontieror-drift")
    ap.add_argument("--max-bytes", type=int, default=15000000)
    ap.add_argument("--budget-min", type=float, default=150.0)
    ap.add_argument("--delay", type=float, default=0.2)
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args(argv)
    scratch = os.path.abspath(a.scratch)
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
            done = {json.loads(x)["task"] for x in f if x.strip()}
    errors = []
    stopped_early = False
    for tid in tasks:
        if tid in done:
            continue
        if (time.monotonic() - t0) / 60.0 > a.budget_min:
            stopped_early = True
            break
        try:
            row = drift_task(tid, rev, scratch, a.max_bytes)
        except Exception as e:  # noqa: BLE001
            errors.append({"task": tid, "error": repr(e)[:300]})
            print("drift-error", tid, repr(e)[:300], flush=True)
            shutil.rmtree(os.path.join(scratch, tid), ignore_errors=True)
            continue
        with open(rows_p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print("drift", tid, "cases", len(row["cases"]), "extra", len(row["extra_info"]), "missing",
              len(row["missing_info"]), "get_absent", sorted(row["get_absent"]), flush=True)
        time.sleep(a.delay)
    rows = []
    if os.path.exists(rows_p):
        with open(rows_p, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
    summary = aggregate(rows, rev, a.out_dir)
    with open(os.path.join(a.out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"revision": rev, "tasks_listed": len(tasks), "errors": errors, "stopped_early": stopped_early,
                   "max_bytes": a.max_bytes, "minutes": round((time.monotonic() - t0) / 60.0, 1)}, f, indent=1)
    return 0 if summary else 1


if __name__ == "__main__":
    sys.exit(main())

"""refgap: how strong is each stored Gurobi reference in the public FrontierOR benchmark?

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

The FrontierOR Challenge scores a feasible answer against a reference objective, capped at 2. The public benchmark
(Hugging Face frontieror/FrontierOR, CC BY 4.0) stores, for every task and instance, the answer Gurobi had when it
stopped (usually at a one-hour limit). When Gurobi stopped far from its own bound, a fast heuristic can score far
above 1 (guo2021: mean 1.44 over 5 large instances in 60 s). This census reads every stored Gurobi solution's scalar
fields (objective, MIP gap, status, runtime, ...) and the benchmark's reference table, and works out for each case the
"ceiling": the contest score an answer would get if it reached Gurobi's own bound. A ceiling of 1 means Gurobi proved
its answer optimal; 2 means there may be room to reach the cap.

  python refgap.py --out-dir /out [--rev SHA] [--max-bytes 3000000] [--delay 0.35] [--only slug ...]

Standard library only. One request at a time, with a pause between requests and a named User-Agent.
"""
import argparse
import csv
import gzip
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://huggingface.co"
REPO = "frontieror/FrontierOR"
REV_DEFAULT = "ef42a2eac13595453f986d9df0b62e86e75ab596"
UA = "MV2-of-Munim-Inc FrontierOR reference census (mv2@munimtech.com)"
VERSION = "0.1.0"


# ----------------------------------------------------------------------------------------------- scoring (pure)

def num(v):
    """A finite float, or None."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def contest_score(ours, ref, sense):
    """The FrontierOR Challenge instance score (docs/main/scoring), capped at 2. sense is 'min' or 'max'."""
    if ours == ref:
        return 1.0
    better = ours < ref if sense == "min" else ours > ref
    if ref == 0 or ours == 0 or (ours > 0) != (ref > 0):
        return 2.0 if better else 0.0
    if ref > 0:
        s = ref / ours if sense == "min" else ours / ref
    else:
        s = ours / ref if sense == "min" else ref / ours
    return min(2.0, max(0.0, s))


def implied_bound(obj, gap, sense):
    """Gurobi's MIPGap is |bound - incumbent| / |incumbent|; the bound lies on the better side."""
    if obj is None or gap is None or gap < 0:
        return None
    d = gap * abs(obj)
    return obj - d if sense == "min" else obj + d


def ceiling(obj, gap, sense):
    b = implied_bound(obj, gap, sense)
    if b is None:
        return None
    return contest_score(b, obj, sense)


def sense_of(code_text):
    """'min' or 'max' from a gurobi_code.py text; None when it cannot tell."""
    if not code_text:
        return None
    t = code_text
    mx = len(re.findall(r"GRB\.MAXIMIZE|ModelSense\s*=\s*-1|sense\s*=\s*['\"]?max", t))
    mn = len(re.findall(r"GRB\.MINIMIZE|ModelSense\s*=\s*1\b|sense\s*=\s*['\"]?min", t))
    if mx and not mn:
        return "max"
    if mn and not mx:
        return "min"
    if not mx and not mn:
        return "min"  # Gurobi's default model sense
    return None


def case_name(filename):
    """'large_solution_3.json' -> 'large_3'; 'tiny_solution.json' -> 'tiny'; other names are kept without .json."""
    base = filename[:-5] if filename.endswith(".json") else filename
    m = re.match(r"^([a-z]+)_solution(?:_(\d+))?$", base)
    if not m:
        return base
    return m.group(1) + ("_" + m.group(2) if m.group(2) else "")


def scalars(sol):
    out = {}
    if not isinstance(sol, dict):
        return out
    for k, v in sol.items():
        if isinstance(v, (list, dict)):
            continue
        if isinstance(v, str):
            v = v[:200]
        out[str(k)] = v
    return out


GAP_KEYS = ("mip_gap", "MIPGap", "gap", "mipgap", "final_gap", "optimality_gap")
STATUS_KEYS = ("status", "Status", "solver_status", "gurobi_status", "termination")
RUNTIME_KEYS = ("runtime", "Runtime", "solve_time", "time", "runtime_s", "wall_time")
OBJ_KEYS = ("objective_value", "objective", "ObjVal", "obj")
BOUND_KEYS = ("obj_bound", "ObjBound", "best_bound", "bound", "objective_bound")
WANTED = set(GAP_KEYS + STATUS_KEYS + RUNTIME_KEYS + OBJ_KEYS + BOUND_KEYS)


def pick(d, keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def gap_from(fields, obj):
    """Gap from the stored fields: mip_gap if given, else from a stored bound, else 0 when the status says optimal."""
    for k in GAP_KEYS:
        g = num(fields.get(k))
        if g is not None:
            return g, k
    for k in BOUND_KEYS:
        b = num(fields.get(k))
        if b is not None and obj is not None and obj != 0:
            return abs(obj - b) / abs(obj), k
    st = pick(fields, STATUS_KEYS)
    if isinstance(st, str) and st.strip().upper() in ("OPTIMAL", "2"):
        return 0.0, "status"
    if isinstance(st, (int, float)) and not isinstance(st, bool) and int(st) == 2:
        return 0.0, "status"
    return None, None


# ----------------------------------------------------------------------------------------------- network

def get(url, tries=6, timeout=180):
    err = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), r.headers
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise
            err = e
            if e.code == 429:
                time.sleep(60.0)
                continue
        except Exception as e:  # noqa: BLE001 - retry network errors
            err = e
        time.sleep(3.0 * (k + 1))
    raise err


def q(path):
    return urllib.parse.quote(path, safe="/")


def _next_link(link):
    if not link:
        return None
    for part in link.split(","):
        if 'rel="next"' in part:
            return part[part.find("<") + 1:part.find(">")]
    return None


def tree(path, rev, recursive=False):
    url = "%s/api/datasets/%s/tree/%s/%s" % (BASE, REPO, rev, q(path))
    if recursive:
        url += "?recursive=true"
    out = []
    while url:
        body, hd = get(url)
        out.extend(json.loads(body.decode("utf-8")))
        url = _next_link(hd.get("Link"))
    return out


def fetch(path, rev):
    body, _ = get("%s/datasets/%s/resolve/%s/%s" % (BASE, REPO, rev, q(path)))
    return body


# ----------------------------------------------------------------------------------------------- census

def read_reference_table(rev, out_dir, log):
    """The benchmark's metadata/gurobi_references.csv.gz: header, column guesses and rows (as dicts)."""
    info = {"path": "metadata/gurobi_references.csv.gz"}
    try:
        raw = fetch(info["path"], rev)
    except Exception as e:  # noqa: BLE001
        info["error"] = repr(e)[:300]
        return info, []
    text = gzip.decompress(raw).decode("utf-8", errors="replace")
    info["bytes_gz"] = len(raw)
    info["bytes_csv"] = len(text)
    rows = list(csv.DictReader(io.StringIO(text)))
    info["rows"] = len(rows)
    info["header"] = list(rows[0].keys()) if rows else []
    info["first_rows"] = rows[:3]
    if len(text) <= 30000000:
        with open(os.path.join(out_dir, "gurobi_references.csv"), "w", encoding="utf-8", newline="") as f:
            f.write(text)
    log("reference table: %d rows, columns %s" % (len(rows), info["header"]))
    return info, rows


def table_index(rows):
    """{(task, case): row} using whatever task/instance columns the table has."""
    if not rows:
        return {}, {}
    hdr = list(rows[0].keys())
    low = {h.lower(): h for h in hdr}
    tcol = next((low[k] for k in ("paper_id", "task", "task_id", "slug", "problem") if k in low), None)
    icol = next((h for h in hdr if "instance" in h.lower()), None)
    cols = {"task": tcol, "instance": icol}
    idx = {}
    if tcol is None:
        return idx, cols
    for r in rows:
        inst = str(r.get(icol, "")) if icol else ""
        idx[(r[tcol], table_case(inst))] = r
    return idx, cols


def table_case(inst):
    """'large_instance_3.json' / 'large_3' / 'tasks/x/instance/large_instance_3.json' -> 'large_3'; tiny -> 'tiny'."""
    s = inst.lower().split("/")[-1]
    if "tiny" in s:
        return "tiny"
    if "large" in s:
        d = re.findall(r"\d+", s)
        return "large_" + d[-1] if d else "large"
    return inst


SCALAR_RE = re.compile(r'"([A-Za-z_][A-Za-z0-9_]{0,40})"\s*:\s*'
                       r'(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|"[^"\\]{0,200}"|true|false|null)')


def scalars_from_text(text, keys):
    """First occurrence of each wanted key with a scalar value, read from a piece of JSON text."""
    out = {}
    for m in SCALAR_RE.finditer(text):
        k = m.group(1)
        if k in keys and k not in out:
            out[k] = json.loads(m.group(2))
    return out


def get_partial(url, nbytes, tail=False, timeout=180):
    """The first (or last) nbytes of a file, by an HTTP Range request; never reads more than nbytes + 1."""
    rng = "bytes=-%d" % nbytes if tail else "bytes=0-%d" % (nbytes - 1)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": rng})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(nbytes + 1)


def census(rev, out_dir, max_bytes, delay, only, log):
    os.makedirs(out_dir, exist_ok=True)
    ref_info, ref_rows = read_reference_table(rev, out_dir, log)
    ref_idx, ref_cols = table_index(ref_rows)
    ref_info["columns_used"] = ref_cols
    hard = {}
    try:
        hj = json.loads(fetch("metadata/hardset/hardset.json", rev).decode("utf-8"))
        for i, t in enumerate(hj.get("task_ids") or []):
            hard[t] = i + 1
    except Exception as e:  # noqa: BLE001
        log("hardset.json: %r" % (e,))
    meta = {}
    try:
        txt = fetch("metadata/hardset/hard_selection_inputs_180.csv", rev).decode("utf-8")
        for r in csv.DictReader(io.StringIO(txt)):
            meta[r["paper_id"]] = {"category": r.get("problem_class"), "field": r.get("application_field"),
                                   "formulation": r.get("formulation_type"),
                                   "timeout_frac": num(r.get("timeout_or_nonoptimal_frac")),
                                   "avg_vars": num(r.get("avg_num_var"))}
    except Exception as e:  # noqa: BLE001
        log("hard_selection_inputs: %r" % (e,))
    tasks = sorted(e["path"].split("/")[-1] for e in tree("tasks", rev) if e.get("type") == "directory")
    if only:
        tasks = [t for t in tasks if t in only]
    log("tasks: %d" % len(tasks))
    cases, errors = [], []
    for tid in tasks:
        try:
            files = tree("tasks/" + tid, rev, recursive=True)
        except Exception as e:  # noqa: BLE001
            errors.append({"task": tid, "error": repr(e)[:300]})
            continue
        code_text = None
        code = [e for e in files if e.get("type") == "file" and e["path"].endswith("/gurobi_code.py")]
        if code:
            try:
                code_text = fetch(code[0]["path"], rev).decode("utf-8", errors="replace")
            except Exception as e:  # noqa: BLE001
                errors.append({"task": tid, "error": "gurobi_code: " + repr(e)[:200]})
            time.sleep(delay)
        sense = sense_of(code_text)
        sols = [e for e in files if e.get("type") == "file" and "/gurobi_solution/" in e["path"]
                and e["path"].endswith(".json")]
        for e in sorted(sols, key=lambda e: e["path"]):
            fname = e["path"].split("/")[-1]
            cname = case_name(fname)
            size = int(e.get("size") or 0)
            rec = {"task": tid, "case": cname, "file": fname, "bytes": size, "sense": sense,
                   "hard_rank": hard.get(tid), **{("meta_" + k): v for k, v in (meta.get(tid) or {}).items()}}
            fields = {}
            if size <= max_bytes:
                try:
                    sol = json.loads(fetch(e["path"], rev).decode("utf-8"))
                    fields = scalars(sol)
                    rec["read"] = "solution"
                except Exception as ex:  # noqa: BLE001
                    rec["read"] = "error: " + repr(ex)[:150]
                time.sleep(delay)
            else:
                # Big file: read only its first and last 64 KB and pick the known scalar keys from the text.
                url = "%s/datasets/%s/resolve/%s/%s" % (BASE, REPO, rev, q(e["path"]))
                try:
                    head = get_partial(url, 65536).decode("utf-8", errors="replace")
                    time.sleep(delay)
                    tail = get_partial(url, 65536, tail=True).decode("utf-8", errors="replace")
                    fields = scalars_from_text(head, WANTED)
                    for k, v in scalars_from_text(tail, WANTED).items():
                        fields.setdefault(k, v)
                    rec["read"] = "range"
                except Exception as ex:  # noqa: BLE001
                    rec["read"] = "skipped: over %d bytes; range read failed: %s" % (max_bytes, repr(ex)[:120])
                time.sleep(delay)
            trow = ref_idx.get((tid, cname))
            if trow:
                rec["table"] = {k: v for k, v in trow.items()}
            src = dict(trow or {})
            src.update(fields)
            obj = num(pick(src, OBJ_KEYS))
            gap, gap_src = gap_from(src, obj)
            rec.update(fields={k: v for k, v in fields.items()}, objective=obj, gap=gap, gap_source=gap_src,
                       status=pick(src, STATUS_KEYS), runtime=num(pick(src, RUNTIME_KEYS)))
            rec["bound"] = implied_bound(obj, gap, sense) if sense else None
            rec["ceiling"] = ceiling(obj, gap, sense) if sense else None
            cases.append(rec)
        log("task %s sense=%s solutions=%d" % (tid, sense, len(sols)))
    return {"ref_info": ref_info, "cases": cases, "errors": errors, "hard": hard, "tasks": tasks}


def summarise(res):
    by = {}
    for c in res["cases"]:
        by.setdefault(c["task"], []).append(c)
    rows = []
    for tid in res["tasks"]:
        cs = by.get(tid, [])
        large = [c for c in cs if c["case"].startswith("large")]
        ceil = [c["ceiling"] for c in large if c.get("ceiling") is not None]
        gaps = [c["gap"] for c in large if c.get("gap") is not None]
        rows.append({
            "task": tid, "hard_rank": res["hard"].get(tid), "sense": cs[0]["sense"] if cs else None,
            "category": cs[0].get("meta_category") if cs else None,
            "field": cs[0].get("meta_field") if cs else None,
            "timeout_frac": cs[0].get("meta_timeout_frac") if cs else None,
            "large_cases": len(large), "large_with_gap": len(gaps),
            "max_gap": max(gaps) if gaps else None, "median_gap": sorted(gaps)[len(gaps) // 2] if gaps else None,
            "mean_ceiling": (sum(ceil) / len(ceil)) if ceil else None,
            "cases_ceiling_ge_1_5": sum(1 for x in ceil if x >= 1.5),
            "cases_ceiling_2": sum(1 for x in ceil if x >= 2.0 - 1e-12),
            "large_objectives": " ".join("%s=%s" % (c["case"], c.get("objective")) for c in large),
        })
    return rows


def fmt(x, d=4):
    if x is None:
        return ""
    if isinstance(x, float):
        return ("%." + str(d) + "g") % x
    return str(x)


def write_outputs(res, out_dir, rev, started):
    rows = summarise(res)
    with open(os.path.join(out_dir, "cases.jsonl"), "w", encoding="utf-8") as f:
        for c in res["cases"]:
            f.write(json.dumps(c, default=str) + "\n")
    keys = ["task", "case", "sense", "objective", "gap", "gap_source", "status", "runtime", "bound", "ceiling",
            "bytes", "read", "hard_rank"]
    with open(os.path.join(out_dir, "cases.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(keys)
        for c in res["cases"]:
            w.writerow([fmt(c.get(k), 10) if isinstance(c.get(k), float) else c.get(k) for k in keys])
    tk = list(rows[0].keys()) if rows else []
    with open(os.path.join(out_dir, "tasks.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=tk)
        w.writeheader()
        w.writerows(rows)
    ranked = sorted([r for r in rows if r["mean_ceiling"] is not None],
                    key=lambda r: (-r["mean_ceiling"], -(r["max_gap"] or 0)))
    hard_rows = [r for r in rows if r["hard_rank"]]
    n_large = sum(r["large_cases"] for r in rows)
    n_gap = sum(r["large_with_gap"] for r in rows)
    field_keys = {}
    for c in res["cases"]:
        for k in (c.get("fields") or {}):
            field_keys[k] = field_keys.get(k, 0) + 1
    stats = {
        "version": VERSION, "revision": rev, "started_utc": started,
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tasks": len(res["tasks"]), "tasks_with_cases": sum(1 for r in rows if r["large_cases"] or r["sense"]),
        "cases": len(res["cases"]), "large_cases": n_large, "large_cases_with_gap": n_gap,
        "cases_read": sum(1 for c in res["cases"] if c.get("read") == "solution"),
        "cases_range_read": sum(1 for c in res["cases"] if c.get("read") == "range"),
        "cases_skipped_size": sum(1 for c in res["cases"] if str(c.get("read", "")).startswith("skipped")),
        "errors": res["errors"],
        "sense_unknown_tasks": [r["task"] for r in rows if r["large_cases"] and r["sense"] is None],
        "solution_scalar_keys": dict(sorted(field_keys.items(), key=lambda kv: -kv[1])[:40]),
        "reference_table": {k: v for k, v in res["ref_info"].items() if k != "first_rows"},
        "reference_table_first_rows": res["ref_info"].get("first_rows"),
        "hard_tasks": len(hard_rows),
        "hard_tasks_with_large_gap_ge_10pct": sum(1 for r in hard_rows if (r["max_gap"] or 0) >= 0.10),
        "tasks_with_large_gap_ge_100pct": [r["task"] for r in rows if (r["max_gap"] or 0) >= 1.0],
        "tasks_with_a_ceiling_2_case": [r["task"] for r in rows if r["cases_ceiling_2"]],
        "guo2021": [{k: c.get(k) for k in ("case", "objective", "gap", "status", "ceiling")}
                    for c in res["cases"] if c["task"] == "guo2021"],
        "top30": [{k: r[k] for k in ("task", "hard_rank", "mean_ceiling", "max_gap", "cases_ceiling_2", "field")}
                  for r in ranked[:30]],
    }
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=1, default=str)
    lines = ["# FrontierOR reference census (refgap v%s)" % VERSION, "",
             "Benchmark revision `%s`. Made with AI agents working in MV2's name (MV2 of Munim, Inc.)." % rev,
             "Ceiling = the contest score an answer would get if it reached Gurobi's own bound "
             "(bound = objective -/+ MIP gap x |objective|).", "",
             "Tasks: %d; solution files: %d (%d read whole, %d big ones read by their first and last 64 KB, %d not "
             "read); large cases with a gap: %d of %d." % (
                 stats["tasks"], stats["cases"], stats["cases_read"], stats["cases_range_read"],
                 stats["cases_skipped_size"], n_gap, n_large),
             "", "## Top 30 tasks by mean ceiling over large instances", "",
             "| task | hard-set rank | sense | mean ceiling | large cases at 2 | max gap | median gap | field |",
             "|---|---|---|---|---|---|---|---|"]
    for r in ranked[:30]:
        lines.append("| %s | %s | %s | %s | %s/%s | %s | %s | %s |" % (
            r["task"], r["hard_rank"] or "", r["sense"] or "?", fmt(r["mean_ceiling"]), r["cases_ceiling_2"],
            r["large_cases"], fmt(r["max_gap"]), fmt(r["median_gap"]), r["field"] or ""))
    lines += ["", "Full data: tasks.csv, cases.csv, cases.jsonl, summary.json."]
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--rev", default=REV_DEFAULT)
    ap.add_argument("--max-bytes", type=int, default=3000000)
    ap.add_argument("--delay", type=float, default=0.35)
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args(argv)
    out = os.path.join(a.out_dir, "refgap")
    os.makedirs(out, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def log(msg):
        print(msg, flush=True)

    res = census(a.rev, out, a.max_bytes, a.delay, a.only, log)
    stats = write_outputs(res, out, a.rev, started)
    log("done: %d cases, %d large with gap, errors %d" % (stats["cases"], stats["large_cases_with_gap"],
                                                          len(stats["errors"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())

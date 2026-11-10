#!/usr/bin/env python3
"""Follow-up to the OPLib consistency census: were the 7 mismatching EA4OP routes scored with the pre-2020 files?

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

The census (oplib_audit.py, OPLib commit 823ac3e) found 7 of 344 stored EA4OP routes whose ROUTE_SCORE disagrees with
the scores in their own instance file, all Gen3: a280, fnl4461, nrw1379, rat195, rat575, rat783 and tsp225 (-gen3-50).
OPLib commit 8e9cd01 ("Fix Gen3 scores", 2020-09-29) rewrote the score section of eight Gen3 instances, these seven
and rat99, while the EA4OP routes were stored in 2017 and not changed. This script tests that explanation directly:
it downloads each of the eight instance files and its stored route at the fix's parent commit (2b8957e), at the fix
itself and at the current commit, and re-scores the current route against each version of the instance. Three Gen3
instances the fix did not touch serve as controls. Only derived numbers are written; OPLib's files are not
redistributed.

Usage:
    python oplib_prefix.py fetch --data-dir /data
    python oplib_prefix.py run --data-dir /data --out-dir /out
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import oplib_audit as A  # noqa: E402

PARENT = "2b8957e46dae9eb44c244fdfdc965382defdc310"  # "Add OP solutions obtained by EA4OP", 2017-07-24
FIX = "8e9cd01bf2c81607ec2f08b58ec658d66fd127f3"  # "Fix Gen3 scores", 2020-09-29
CURRENT = A.OPLIB_SHA  # 823ac3e, 2020-09-29, the census commit
COMMITS = {"parent": PARENT, "fix": FIX, "current": CURRENT}
FIXED = ["a280", "fnl4461", "nrw1379", "rat195", "rat575", "rat783", "rat99", "tsp225"]
CONTROLS = ["pa561", "kroA100", "pr76"]  # Gen3 instances not touched by the fix
CENSUS_INCONSISTENT = ["a280", "fnl4461", "nrw1379", "rat195", "rat575", "rat783", "tsp225"]


def rel_inst(fam):
    return "instances/gen3/%s-gen3-50.oplib" % fam


def rel_sol(fam):
    return "solutions/ea4op/gen3/%s-gen3-50.sol" % fam


def local(data_dir, key, rel):
    return os.path.join(data_dir, "oplib-prefix", key + "__" + A.local_name(rel))


def fetch(data_dir):
    os.makedirs(os.path.join(data_dir, "oplib-prefix"), exist_ok=True)
    got = missing = 0
    for fam in FIXED + CONTROLS:
        for key, sha in COMMITS.items():
            for rel in (rel_inst(fam), rel_sol(fam)):
                dest = local(data_dir, key, rel)
                if os.path.exists(dest) and os.path.getsize(dest) > 0:
                    got += 1
                    continue
                try:
                    data = A._get("https://raw.githubusercontent.com/bcamath-ds/OPLib/%s/%s" % (sha, rel), tries=2)
                    with open(dest, "wb") as f:
                        f.write(data)
                    got += 1
                except Exception as e:  # noqa: BLE001 - recorded, not fatal
                    missing += 1
                    print("missing", key, rel, repr(e)[:120], flush=True)
                time.sleep(0.2)
    print("files present", got, "| missing", missing, flush=True)


def read(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def compare_instances(a, b):
    """What differs between two parsed versions of one instance."""
    keys = ("DIMENSION", "COST_LIMIT", "EDGE_WEIGHT_TYPE", "EDGE_WEIGHT_FORMAT")
    head_diff = sorted(k for k in keys if a.head.get(k, "").strip() != b.head.get(k, "").strip())
    coords_same = a.coords == b.coords
    matrix_same = a.matrix == b.matrix
    ids = sorted(set(a.score) | set(b.score))
    changed = [i for i in ids if a.score.get(i) != b.score.get(i)]
    delta = sum(b.score.get(i, 0.0) - a.score.get(i, 0.0) for i in ids)
    return {"head_diff": head_diff, "coords_same": coords_same, "matrix_same": matrix_same,
            "depot_same": a.depot == b.depot, "nodes": len(ids), "scores_changed": len(changed),
            "score_total_delta": delta,
            "only_scores_differ": not head_diff and coords_same and matrix_same and a.depot == b.depot}


def route_delta(a, b, seq):
    vis = set(seq)
    return sum(b.score.get(i, 0.0) - a.score.get(i, 0.0) for i in vis)


def same_solution(text_a, text_b):
    if text_a is None or text_b is None:
        return None
    ha, sa = A.parse_sol(text_a)
    hb, sb = A.parse_sol(text_b)
    return sa == sb and A.num(ha.get("ROUTE_SCORE")) == A.num(hb.get("ROUTE_SCORE")) and \
        A.num(ha.get("ROUTE_COST")) == A.num(hb.get("ROUTE_COST"))


def check_family(texts):
    """texts: {"parent": (inst, sol), "fix": (...), "current": (...)} -> one result row."""
    row = {}
    cur_inst_t, cur_sol_t = texts["current"]
    if cur_inst_t is None or cur_sol_t is None:
        row["status"] = "missing_current"
        return row
    head, seq = A.parse_sol(cur_sol_t)
    insts = {}
    for key in ("parent", "fix", "current"):
        it = texts[key][0]
        if it is None:
            row[key] = {"status": "missing_file"}
            continue
        try:
            inst = A.Instance(it)
        except Exception as e:  # noqa: BLE001 - recorded
            row[key] = {"status": "error: %s" % repr(e)[:160]}
            continue
        insts[key] = inst
        r = A.audit_pair(inst, head, seq)
        info = {k: r.get(k) for k in ("status", "stated_score", "score_with_depot", "score_without_depot",
                                      "score_diff", "stated_cost", "cost", "limit", "fits_limit")}
        vs = A.gen3_variants(inst)
        rates = {k: A.match_rate(v, inst.score, inst.depot) for k, v in vs.items()}
        info["reading_match_rates"] = rates
        info["follows"] = sorted(k for k, x in rates.items() if x == 1.0)
        row[key] = info
    if "parent" in insts and "current" in insts:
        row["parent_vs_current"] = compare_instances(insts["parent"], insts["current"])
        row["route_score_delta_parent_to_current"] = route_delta(insts["parent"], insts["current"], seq)
    if "fix" in insts and "current" in insts:
        row["fix_vs_current"] = compare_instances(insts["fix"], insts["current"])
    row["solution_same_at_parent"] = same_solution(texts["parent"][1], cur_sol_t)
    row["solution_same_at_fix"] = same_solution(texts["fix"][1], cur_sol_t)
    row["status"] = "checked"
    return row


def run(data_dir, out_dir):
    out = os.path.join(out_dir, "oplib-prefix")
    os.makedirs(out, exist_ok=True)
    rows = {}
    for fam in FIXED + CONTROLS:
        texts = {k: (read(local(data_dir, k, rel_inst(fam))), read(local(data_dir, k, rel_sol(fam))))
                 for k in COMMITS}
        r = check_family(texts)
        r["family"] = fam
        r["group"] = "fixed" if fam in FIXED else "control"
        rows[fam] = r
        print(json.dumps({"family": fam, "group": r["group"], "status": r.get("status"),
                          "parent": (r.get("parent") or {}).get("status"),
                          "current": (r.get("current") or {}).get("status"),
                          "stated": (r.get("current") or {}).get("stated_score"),
                          "parent_score": (r.get("parent") or {}).get("score_with_depot"),
                          "current_score": (r.get("current") or {}).get("score_with_depot")}), flush=True)

    def st(fam, key):
        return (rows[fam].get(key) or {}).get("status")

    q = {}
    q["Q1"] = all(st(f, "parent") == "consistent" for f in CENSUS_INCONSISTENT)
    q["Q2"] = all((rows[f].get("parent_vs_current") or {}).get("only_scores_differ") is True for f in FIXED)
    q["Q3"] = st("rat99", "parent") == "consistent" and st("rat99", "current") == "consistent"
    q4 = [f for f in FIXED
          if ((((rows[f].get("parent") or {}).get("reading_match_rates") or {}).get("floor_raw")) or 0) >= 0.9]
    q["Q4"] = len(q4) >= 6
    q["Q5"] = all((rows[f].get("parent_vs_current") or {}).get("scores_changed") == 0 and
                  (rows[f].get("parent_vs_current") or {}).get("only_scores_differ") is True for f in CONTROLS)
    q["Q6"] = all(rows[f].get("solution_same_at_parent") is True for f in FIXED)
    tally = {"parent": PARENT, "fix": FIX, "current": CURRENT,
             "checks": {k: ("held" if v else "did not hold") for k, v in q.items()},
             "parent_consistent": sorted(f for f in FIXED + CONTROLS if st(f, "parent") == "consistent"),
             "current_consistent": sorted(f for f in FIXED + CONTROLS if st(f, "current") == "consistent"),
             "floor_raw_ge_0_9_at_parent": q4,
             "fix_equals_current": sorted(f for f in FIXED if (rows[f].get("fix_vs_current") or {}).get(
                 "scores_changed") == 0)}
    with open(os.path.join(out, "prefix.json"), "w", encoding="utf-8") as f:
        json.dump({"tally": tally, "rows": rows}, f, indent=1)
    lines = ["# OPLib follow-up: the 2017 EA4OP routes against the instance files before and after 8e9cd01", "",
             "MV2 of Munim, Inc. Made with AI agents working in MV2's name. Code Apache-2.0, text and numbers CC BY 4.0.",
             "", "Parent %s, fix %s, current %s. OPLib's files are not redistributed." % (PARENT, FIX, CURRENT), "",
             "```", json.dumps(tally, indent=1), "```", "",
             "| instance | group | stated | re-scored, parent file | parent status | re-scored, current file | "
             "current status | node scores changed | route delta | only scores differ | route same at parent |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for fam in FIXED + CONTROLS:
        r = rows[fam]
        p, c, d = r.get("parent") or {}, r.get("current") or {}, r.get("parent_vs_current") or {}
        lines.append("| %s-gen3-50 | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            fam, r["group"], c.get("stated_score"), p.get("score_with_depot"), p.get("status"),
            c.get("score_with_depot"), c.get("status"), d.get("scores_changed"),
            r.get("route_score_delta_parent_to_current"), d.get("only_scores_differ"),
            r.get("solution_same_at_parent")))
    with open(os.path.join(out, "prefix.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("CHECKS", json.dumps(tally["checks"]), flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "run"])
    ap.add_argument("--data-dir", default="/data")
    ap.add_argument("--out-dir", default="/out")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        fetch(a.data_dir)
    else:
        run(a.data_dir, a.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

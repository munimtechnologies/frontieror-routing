"""Calibration of the bodur2017 (SCFLP) solver on the pre-registered synthetic set (scflp_gen.CASES).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Phases, each written to disk as it finishes (a host stop keeps what is done):
1. write the 20 instances;
2. run the solver the contest way (kit/harness.py, subprocess, --time-limit 60) on every case: results-main.jsonl,
   plus the size of each solution file;
3. the expected-value (mean-demand) solution, evaluated on every scenario: extras.jsonl;
4. references: extensive-form MIP (scflp_exact.ext_mip, --mip-time s) for classes S and M; for class L the same
   solver with --ref-time s (not proven): refs.jsonl;
5. score every case (min(2, ref/obj), as the contest does when minimising) and write results.json / results.md with
   the tallies the pre-registered guesses B2-B7 are graded on.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOLVER_DIR = os.path.join(HERE, "bodur2017")
for p in (os.path.join(ROOT, "kit"), HERE, SOLVER_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import harness as H  # noqa: E402
import scflp_check  # noqa: E402
import scflp_exact  # noqa: E402
import scflp_gen  # noqa: E402

PROBLEM = "bodur2017"


def append(path, row):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def load_jsonl(path):
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                out[r["name"]] = r
    return out


def run(a):
    import solve as S  # the solver module (frontier_runtime must sit next to it)

    out = os.path.join(a.out_dir, "scflp")
    inst_dir = os.path.join(out, "instances")
    work = os.path.join(out, "work")
    os.makedirs(inst_dir, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    solve_py = os.path.join(SOLVER_DIR, "solve.py")
    cases = []
    for row in scflp_gen.CASES:
        name, cls = row[0], row[8]
        if a.only and name not in a.only:
            continue
        inst = scflp_gen.case_instance(row)
        ip = os.path.join(inst_dir, name + ".json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        cases.append({"name": name, "cls": cls, "instance_path": ip, "inst": inst, "F": row[1], "m": row[2],
                      "S": row[3], "cf": row[4], "var": row[5], "box": row[6]})
        print("instance", name, cls, row[1], row[2], row[3], flush=True)

    main_p = os.path.join(out, "results-main.jsonl")
    extra_p = os.path.join(out, "extras.jsonl")
    ref_p = os.path.join(out, "refs.jsonl")
    hb = H.Heartbeat()

    done = load_jsonl(main_p)
    for c in cases:
        if c["name"] in done:
            continue
        row = H.evaluate_case({"name": c["name"], "instance_path": c["instance_path"], "reference": None},
                              solve_py, PROBLEM, a.time_limit, scflp_check.check, "min", work, hb=hb)
        sp = os.path.join(work, c["name"] + ".solution.json")
        row["solution_bytes"] = os.path.getsize(sp) if os.path.exists(sp) else None
        row["cls"] = c["cls"]
        append(main_p, row)
        print("main", c["name"], row["status"], row.get("objective"), row["wall_s"], row["solution_bytes"],
              flush=True)

    done = load_jsonl(extra_p)
    for c in cases:
        if c["name"] in done:
            continue
        t0 = time.monotonic()
        try:
            ev = S.ev_baseline(c["inst"], a.ev_time)
        except Exception as e:  # noqa: BLE001 - record and go on
            ev = None
            print("ev failed", c["name"], repr(e), flush=True)
        row = {"name": c["name"], "ev": ev, "ev_s": round(time.monotonic() - t0, 3)}
        append(extra_p, row)
        print("extra", json.dumps(row), flush=True)

    done = load_jsonl(ref_p)
    for c in cases:
        if c["name"] in done:
            continue
        if c["cls"] in ("S", "M"):
            try:
                r = scflp_exact.ext_mip(c["inst"], a.mip_time)
                row = {"name": c["name"], "source": "ext-mip", "reference": r["objective"], "proven": r["proven"],
                       "bound": r["bound"], "status": r["status"], "time_s": r["time_s"], "vars": r["vars"],
                       "rows": r["rows"], "strong": r["strong"], "mip_objective": r["mip_objective"]}
            except Exception as e:  # noqa: BLE001 - e.g. out of memory: record it
                row = {"name": c["name"], "source": "ext-mip", "reference": None, "proven": False, "bound": None,
                       "error": repr(e)}
        else:
            hb.reset()
            rr = H.run_once(solve_py, PROBLEM, c["instance_path"], os.path.join(work, c["name"] + ".ref.json"),
                            a.ref_time)
            chk = scflp_check.check(c["inst"], rr["solution"]) if rr["solution"] else {"feasible": False}
            row = {"name": c["name"], "source": "solver-%ds" % int(a.ref_time),
                   "reference": chk.get("objective") if chk.get("feasible") else None, "proven": False,
                   "bound": None, "wall_s": rr["wall_s"], "exit": rr["exit"], "paused": hb.max_gap() > 5.0}
        append(ref_p, row)
        print("ref", json.dumps(row), flush=True)
    hb.stop()
    report(cases, out, a)


def report(cases, out, a):
    mains = load_jsonl(os.path.join(out, "results-main.jsonl"))
    extras = load_jsonl(os.path.join(out, "extras.jsonl"))
    refs = load_jsonl(os.path.join(out, "refs.jsonl"))
    rows = []
    for c in cases:
        r = dict(mains.get(c["name"], {"name": c["name"], "status": "not_run", "score": 0.0, "attempts": [],
                                       "wall_s": 0.0, "paused": False}))
        e = extras.get(c["name"], {})
        f = refs.get(c["name"], {})
        ref = f.get("reference")
        bound = f.get("bound") if isinstance(f.get("bound"), (int, float)) else None
        obj = r.get("objective") if r.get("status") == "ok" else None
        r.update(cls=c["cls"], F=c["F"], m=c["m"], S=c["S"], cf=c["cf"], var=c["var"], box=c["box"], reference=ref,
                 reference_proven=f.get("proven"), ref_source=f.get("source"), ref_strong=f.get("strong"),
                 ev=e.get("ev"), bound=bound)
        r["score"] = round(H.contest_score(obj, ref, "min"), 6) if obj is not None and ref is not None else 0.0
        if obj is not None and ref not in (None, 0):
            r["gap_pct"] = round(100.0 * (obj - ref) / abs(ref), 4)
        if obj is not None and bound is not None and obj > 0:
            r["gap_to_bound_pct"] = round(100.0 * (obj - bound) / obj, 4)
        if obj is not None and e.get("ev") is not None:
            r["vs_ev_pct"] = round(100.0 * (e["ev"] - obj) / max(1e-9, e["ev"]), 4)
        rows.append(r)

    def sel(cls):
        return [r for r in rows if r["cls"] in cls]

    small, mid, big = sel("S"), sel("M"), sel("L")
    sm = small + mid
    strong_m = [r for r in mid if r.get("ref_strong") and r.get("gap_to_bound_pct") is not None]
    tally = H.summarise(rows, a.time_limit) if rows else {}
    tally.update({
        "B2_feasible_no_mismatch": sum(1 for r in rows if r["status"] == "ok"),
        "B2_max_solution_bytes": max((r.get("solution_bytes") or 0 for r in rows), default=None),
        "B3_S_at_reference_0.01pct": sum(1 for r in small if r.get("gap_pct") is not None and r["gap_pct"] <= 0.01),
        "B3_S_proven_refs": sum(1 for r in small if r.get("reference_proven")),
        "B4_SM_mean_score": round(sum(r["score"] for r in sm) / len(sm), 6) if sm else None,
        "B5_L_within_0.5pct_of_ref": sum(1 for r in big if r.get("gap_pct") is not None and r["gap_pct"] <= 0.5),
        "B6_not_worse_than_ev": sum(1 for r in rows if r.get("vs_ev_pct") is not None and r["vs_ev_pct"] >= -1e-6),
        "B6_ev_available": sum(1 for r in rows if r.get("ev") is not None),
        "B7_M_strong_cases": len(strong_m),
        "B7_M_strong_mean_gap_to_bound_pct": round(sum(r["gap_to_bound_pct"] for r in strong_m) / len(strong_m), 4)
        if strong_m else None,
        "M_beats_reference": sum(1 for r in mid if r.get("gap_pct") is not None and r["gap_pct"] < -1e-6),
        "mean_vs_ev_pct": round(sum(r["vs_ev_pct"] for r in rows if r.get("vs_ev_pct") is not None)
                                / max(1, sum(1 for r in rows if r.get("vs_ev_pct") is not None)), 4),
    })
    intro = ("bodur2017 (SCFLP) solver v0.1.0, contest-style runs at %ss on 20 pre-registered synthetic instances. "
             "References: extensive-form MIP (HiGHS, %ss) for S/M, the same solver at %ss for L. Made with AI agents "
             "working in MV2's name (MV2 of Munim, Inc.)." % (a.time_limit, a.mip_time, a.ref_time))
    H.write_report(out, "SCFLP calibration v1", intro, rows, tally,
                   extra_cols=("cls", "F", "m", "S", "cf", "var", "box", "ref_source", "ref_strong", "bound",
                               "gap_to_bound_pct", "ev", "vs_ev_pct", "solution_bytes"))
    print("tally", json.dumps(tally), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--ref-time", type=float, default=180.0)
    ap.add_argument("--mip-time", type=float, default=150.0)
    ap.add_argument("--ev-time", type=float, default=20.0)
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args()
    run(a)


if __name__ == "__main__":
    main()

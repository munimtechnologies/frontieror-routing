"""Calibration of the barnhart2000 (ODIMCF) solver on the pre-registered synthetic set (odimcf_gen.CASES).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Phases, each written to disk as it finishes (a host stop keeps what is done):
1. write the 20 instances;
2. run the solver the contest way (kit/harness.py, subprocess, --time-limit 60) on every case: results-main.jsonl;
3. greedy-only objective and the column-generation Lagrangian bound (up to --lb-time s) per case: extras.jsonl;
4. references: arc MIP (odimcf_exact.arc_mip, --mip-time s) for classes S and M; for class L the same solver
   with --ref-time s (not proven): refs.jsonl;
5. score every case against its reference (min(2, ref/obj), as the contest does when minimising) and write
   results.json / results.md with the tallies the pre-registered guesses O1-O7 are graded on.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOLVER_DIR = os.path.join(HERE, "barnhart2000")
for p in (os.path.join(ROOT, "kit"), HERE, SOLVER_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import harness as H  # noqa: E402
import odimcf_check  # noqa: E402
import odimcf_exact  # noqa: E402
import odimcf_gen  # noqa: E402

PROBLEM = "barnhart2000"


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

    out = os.path.join(a.out_dir, "odimcf")
    inst_dir = os.path.join(out, "instances")
    work = os.path.join(out, "work")
    os.makedirs(inst_dir, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    solve_py = os.path.join(SOLVER_DIR, "solve.py")
    cases = []
    for row in odimcf_gen.CASES:
        name, cls = row[0], row[8]
        if a.only and name not in a.only:
            continue
        inst = odimcf_gen.case_instance(row)
        ip = os.path.join(inst_dir, name + ".json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        cases.append({"name": name, "cls": cls, "instance_path": ip, "inst": inst,
                      "N": inst["network"]["num_nodes"], "A": inst["network"]["num_arcs"],
                      "K": inst["commodities"]["num_commodities"]})
        print("instance", name, cls, cases[-1]["N"], cases[-1]["A"], cases[-1]["K"], flush=True)

    main_p = os.path.join(out, "results-main.jsonl")
    extra_p = os.path.join(out, "extras.jsonl")
    ref_p = os.path.join(out, "refs.jsonl")
    hb = H.Heartbeat()

    done = load_jsonl(main_p)
    for c in cases:
        if c["name"] in done:
            continue
        row = H.evaluate_case({"name": c["name"], "instance_path": c["instance_path"], "reference": None},
                              solve_py, PROBLEM, a.time_limit, odimcf_check.check, "min", work, hb=hb)
        row["cls"] = c["cls"]
        append(main_p, row)
        print("main", c["name"], row["status"], row.get("objective"), row["wall_s"], flush=True)

    done = load_jsonl(extra_p)
    for c in cases:
        if c["name"] in done:
            continue
        t0 = time.monotonic()
        g = S.greedy_best(c["inst"])
        tg = time.monotonic() - t0
        lbr = S.lagrangian_bound(c["inst"], a.lb_time)
        row = {"name": c["name"], "greedy": g, "greedy_s": round(tg, 3), "lb": lbr["lb"], "lp": lbr["lp"],
               "lp_converged": lbr["converged"], "cg_iters": lbr["iters"], "cg_cols": lbr["cols"]}
        append(extra_p, row)
        print("extra", json.dumps(row), flush=True)

    done = load_jsonl(ref_p)
    for c in cases:
        if c["name"] in done:
            continue
        if c["cls"] in ("S", "M"):
            r = odimcf_exact.arc_mip(c["inst"], a.mip_time)
            row = {"name": c["name"], "source": "arc-mip", "reference": r["objective"], "proven": r["proven"],
                   "bound": r["bound"], "status": r["status"], "time_s": r["time_s"], "vars": r["vars"],
                   "checker": r.get("checker")}
        else:
            hb.reset()
            rr = H.run_once(solve_py, PROBLEM, c["instance_path"], os.path.join(work, c["name"] + ".ref.json"),
                            a.ref_time)
            chk = odimcf_check.check(c["inst"], rr["solution"]) if rr["solution"] else {"feasible": False}
            row = {"name": c["name"], "source": "solver-%ds" % int(a.ref_time),
                   "reference": chk.get("objective") if chk.get("feasible") else None, "proven": False,
                   "bound": None, "wall_s": rr["wall_s"], "exit": rr["exit"],
                   "paused": hb.max_gap() > 5.0}
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
        bound_candidates = [b for b in (e.get("lb"), f.get("bound")) if isinstance(b, (int, float))]
        best_lb = max(bound_candidates) if bound_candidates else None
        obj = r.get("objective") if r.get("status") == "ok" else None
        r.update(cls=c["cls"], N=c["N"], A=c["A"], K=c["K"], reference=ref, reference_proven=f.get("proven"),
                 ref_source=f.get("source"), greedy=e.get("greedy"), lb=best_lb,
                 lp_converged=e.get("lp_converged"))
        r["score"] = round(H.contest_score(obj, ref, "min"), 6) if obj is not None and ref is not None else 0.0
        if obj is not None and ref not in (None, 0):
            r["gap_pct"] = round(100.0 * (obj - ref) / abs(ref), 4)
        elif obj is not None and ref == 0:
            r["gap_pct"] = 0.0 if obj == 0 else None
        if obj is not None and best_lb is not None and obj > 0:
            r["gap_to_lb_pct"] = round(100.0 * (obj - best_lb) / obj, 4)
        if obj is not None and e.get("greedy") is not None:
            r["vs_greedy_pct"] = round(100.0 * (e["greedy"] - obj) / max(1e-9, e["greedy"]), 4)
        rows.append(r)

    def sel(cls):
        return [r for r in rows if r["cls"] in cls]

    sm = sel("SM")
    big = sel("L")
    tally = H.summarise(rows, a.time_limit) if rows else {}
    tally.update({
        "O2_feasible_no_mismatch": sum(1 for r in rows if r["status"] == "ok"),
        "O3_SM_at_reference": sum(1 for r in sm if r.get("gap_pct") is not None and r["gap_pct"] <= 1e-6),
        "O3_SM_cases": len(sm),
        "O4_SM_mean_score": round(sum(r["score"] for r in sm) / len(sm), 6) if sm else None,
        "O5_L_within_1pct_of_ref": sum(1 for r in big if r.get("gap_pct") is not None and r["gap_pct"] <= 1.0),
        "O6_L_mean_gap_to_lb_pct": round(sum(r["gap_to_lb_pct"] for r in big if r.get("gap_to_lb_pct") is not None)
                                         / max(1, sum(1 for r in big if r.get("gap_to_lb_pct") is not None)), 4),
        "O7_not_worse_than_greedy": sum(1 for r in rows if r.get("vs_greedy_pct") is not None
                                        and r["vs_greedy_pct"] >= -1e-9),
        "SM_proven_refs": sum(1 for r in sm if r.get("reference_proven")),
    })
    intro = ("barnhart2000 (ODIMCF) solver, contest-style runs at %ss on 20 pre-registered synthetic instances. "
             "References: arc MIP (HiGHS, %ss) for S/M, the same solver at %ss for L. Made with AI agents working in "
             "MV2's name (MV2 of Munim, Inc.)." % (a.time_limit, a.mip_time, a.ref_time))
    H.write_report(out, "ODIMCF calibration v1", intro, rows, tally,
                   extra_cols=("cls", "N", "A", "K", "ref_source", "greedy", "lb", "gap_to_lb_pct", "vs_greedy_pct"))
    print("tally", json.dumps(tally), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--ref-time", type=float, default=300.0)
    ap.add_argument("--mip-time", type=float, default=180.0)
    ap.add_argument("--lb-time", type=float, default=30.0)
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args()
    run(a)


if __name__ == "__main__":
    main()

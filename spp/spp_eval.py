"""Calibrate the hoffman1993 (set partitioning) practice solver on OR-Library's airline crew instances.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Instances: OR-Library set partitioning files (J. E. Beasley; contributed by K. L. Hoffman and D. Levine; used in Chu
and Beasley 1998 and, in part, in Hoffman and Padberg 1993): sppnw01-43, sppaa01-06, sppkl01-02 and sppus02-04
(sppus01, 68 MB, is left out). They are downloaded at run time and not redistributed. Each is converted to the
FrontierOR hoffman1993 schema (no base constraints) and solved through the real CLI, 60 s, as the sandbox calls it.
Reference: HiGHS (scipy.optimize.milp) with mip_rel_gap 0 and a longer limit, run separately; whether it was proven
optimal is recorded. With --ref-file, references already computed by an earlier run are reused and only the missing
ones are computed. The checker here is written independently of solve.py's own check.

Usage:
    python spp_eval.py fetch --data-dir /data
    python spp_eval.py run --data-dir /data --out-dir /out --time-limit 60 --ref-time 300 [--ref-file refs-v1.json]
"""
import argparse
import itertools
import json
import os
import random
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "kit"))
sys.path.insert(0, os.path.join(HERE, "hoffman1993"))

import harness as H  # noqa: E402

ORLIB = "http://people.brunel.ac.uk/~mastjjb/jeb/orlib/files/spp%s.txt"
NAMES = (["nw%02d" % i for i in range(1, 44)] + ["aa%02d" % i for i in range(1, 7)] + ["kl01", "kl02"] +
         ["us02", "us03", "us04"])
UA = "MV2 of Munim, Inc. solver calibration (mv2@munimtech.com)"
ROT_BASE = 0  # same guess as solve.py: selected_rotations are 0-based positions in cost_vector


# ------------------------------------------------------------------ data
def fetch(data_dir):
    d = os.path.join(data_dir, "orlib-spp")
    os.makedirs(d, exist_ok=True)
    got = missing = 0
    for nm in NAMES:
        dest = os.path.join(d, nm + ".txt")
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            got += 1
            continue
        for k in range(3):
            try:
                req = urllib.request.Request(ORLIB % nm, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = r.read()
                with open(dest, "wb") as f:
                    f.write(data)
                got += 1
                break
            except Exception as e:  # noqa: BLE001 - retried, then recorded
                if k == 2:
                    missing += 1
                    print("missing", nm, repr(e)[:120], flush=True)
                time.sleep(3 * (k + 1))
        time.sleep(1.0)
    print("files present", got, "| missing", missing, flush=True)


def parse_orlib(text):
    tok = text.split()
    m, n = int(tok[0]), int(tok[1])
    pos, costs, cols = 2, [], []
    for _ in range(n):
        c, k = int(float(tok[pos])), int(tok[pos + 1])
        rows = [int(t) for t in tok[pos + 2:pos + 2 + k]]
        pos += 2 + k
        costs.append(c)
        cols.append(rows)
    return m, n, costs, cols


def to_instance(m, n, costs, cols, base=None):
    """FrontierOR hoffman1993 schema. Leg indices kept 1-based as in OR-Library."""
    inst = {"dimensions": {"num_rows": m, "num_cols": n}, "cost_vector": costs,
            "constraint_matrix_A": {"columns": [sorted(c) for c in cols]},
            "has_base_constraints": bool(base)}
    if base:
        inst["base_constraints"] = {"num_bases": len(base["D"]), "num_constraints": 2 * len(base["D"]),
                                    "D_matrix": {"rows": base["D"]}, "lower_bounds_d1": base["lo"],
                                    "upper_bounds_d2": base["hi"]}
    else:
        inst["base_constraints"] = {"num_bases": 0, "num_constraints": 0, "D_matrix": {"rows": []},
                                    "lower_bounds_d1": [], "upper_bounds_d2": []}
    return inst


# ------------------------------------------------------------------ independent checker
def checker(inst, sol, leg_base=1, tol=1e-6):
    m = inst["dimensions"]["num_rows"]
    n = inst["dimensions"]["num_cols"]
    sel = sol.get("selected_rotations")
    if not isinstance(sel, list):
        return {"feasible": False, "objective": None, "reason": "selected_rotations missing"}
    js = []
    for v in sel:
        if not isinstance(v, int) or not (ROT_BASE <= v < n + ROT_BASE):
            return {"feasible": False, "objective": None, "reason": "bad rotation index %r" % (v,)}
        js.append(v - ROT_BASE)
    if len(set(js)) != len(js):
        return {"feasible": False, "objective": None, "reason": "rotation repeated"}
    vv = sol.get("variable_values")
    if isinstance(vv, dict):
        ones = sorted(int(k) - ROT_BASE for k, x in vv.items() if float(x) > 0.5)
        if ones != sorted(js):
            return {"feasible": False, "objective": None, "reason": "variable_values disagree with selected_rotations"}
    count = [0] * m
    cols = inst["constraint_matrix_A"]["columns"]
    for j in js:
        for leg in cols[j]:
            count[leg - leg_base] += 1
    bad = [i for i, c in enumerate(count) if c != 1]
    if bad:
        return {"feasible": False, "objective": None,
                "reason": "%d legs not covered exactly once (first: %d)" % (len(bad), bad[0] + leg_base)}
    if inst.get("has_base_constraints"):
        bc = inst["base_constraints"]
        for b, row in enumerate(bc["D_matrix"]["rows"]):
            s = sum(row[j] for j in js)
            if s < bc["lower_bounds_d1"][b] - tol or s > bc["upper_bounds_d2"][b] + tol:
                return {"feasible": False, "objective": None, "reason": "base %d out of bounds" % b}
    return {"feasible": True, "objective": float(sum(inst["cost_vector"][j] for j in js)), "reason": ""}


# ------------------------------------------------------------------ tiny instances with a known optimum
def tiny_instance(seed, m=7, n=14, with_base=False):
    """A random SPP that has at least one feasible partition, plus its brute-force optimum."""
    inst, feas = tiny_instance_all(seed, m, n, with_base)
    return inst, (min(c for c, _ in feas) if feas else None)


def tiny_instance_all(seed, m=7, n=14, with_base=False):
    """The same random SPP, plus every feasible partition as (cost, columns), by brute force."""
    rng = random.Random(seed)
    legs = list(range(1, m + 1))
    rng.shuffle(legs)
    cols, cut = [], 0
    while cut < m:  # one planted partition
        k = rng.randint(1, 3)
        cols.append(sorted(legs[cut:cut + k]))
        cut += k
    planted = len(cols)
    while len(cols) < n:
        k = rng.randint(1, 4)
        cols.append(sorted(rng.sample(range(1, m + 1), k)))
    order = list(range(len(cols)))
    rng.shuffle(order)
    cols = [cols[i] for i in order]
    planted_pos = [p for p, i in enumerate(order) if i < planted]
    costs = [rng.randint(1, 20) * len(c) + rng.randint(0, 9) for c in cols]
    base = None
    if with_base:  # bounds chosen so that the planted partition is feasible and some others are not
        D = [[round(rng.uniform(0.5, 3.0), 2) for _ in cols]]
        sp = sum(D[0][j] for j in planted_pos)
        base = {"D": D, "lo": [round(0.8 * sp, 2)], "hi": [round(1.1 * sp, 2)]}
    inst = to_instance(m, len(cols), costs, cols, base)
    feas = []
    for r in range(1, len(cols) + 1):
        for comb in itertools.combinations(range(len(cols)), r):
            chk = checker(inst, {"selected_rotations": list(comb)})
            if chk["feasible"]:
                feas.append((chk["objective"], list(comb)))
    return inst, feas


# ------------------------------------------------------------------ run
def reference(inst, seconds):
    import solve as S
    P = S.load(inst)
    t0 = time.monotonic()
    chosen, proven = S.run_highs(P, seconds)
    wall = time.monotonic() - t0
    if chosen is None:
        return None, False, wall
    chk = checker(inst, {"selected_rotations": [j + ROT_BASE for j in chosen]})
    if not chk["feasible"]:
        return None, False, wall
    return chk["objective"], proven, wall


def run(data_dir, out_dir, time_limit, ref_time, only=None, refs=None):
    import solve as S
    out = os.path.join(out_dir, "spp")
    work = os.path.join(out, "work")
    os.makedirs(work, exist_ok=True)
    solve_py = os.path.join(HERE, "hoffman1993", "solve.py")
    hb = H.Heartbeat()
    refs = refs or {}
    rows = []
    for nm in (only or NAMES):
        src = os.path.join(data_dir, "orlib-spp", nm + ".txt")
        if not os.path.exists(src):
            rows.append({"name": nm, "status": "missing_file", "score": 0.0, "attempts": [], "wall_s": 0,
                         "paused": False})
            continue
        with open(src, encoding="utf-8") as f:
            m, n, costs, cols = parse_orlib(f.read())
        inst = to_instance(m, n, costs, cols)
        ipath = os.path.join(work, nm + ".json")
        with open(ipath, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        if nm in refs:
            ref, proven, ref_wall, ref_src = (refs[nm]["reference"], refs[nm]["proven"], refs[nm]["wall_s"],
                                              "ref-file")
        else:
            ref, proven, ref_wall = reference(inst, ref_time)
            ref_src = "computed"
        case = {"name": nm, "instance_path": ipath, "reference": ref, "reference_proven": proven}
        row = H.evaluate_case(case, solve_py, "hoffman1993", time_limit, checker, "min", work, hb=hb)
        row.update(rows_m=m, cols_n=n, ref_wall_s=round(ref_wall, 2), reference_source=ref_src)
        rows.append(row)
        os.remove(ipath)
        sol_path = os.path.join(work, nm + ".solution.json")
        if os.path.exists(sol_path):
            os.remove(sol_path)
        print(json.dumps({k: row.get(k) for k in ("name", "rows_m", "cols_n", "status", "objective", "reference",
                                                   "reference_proven", "gap_pct", "wall_s", "ref_wall_s",
                                                   "reference_source")}),
              flush=True)
    tally = H.summarise(rows, time_limit)
    tally["solver_version"] = S.VERSION
    tally["reference_proven"] = sum(1 for r in rows if r.get("reference_proven"))
    tally["reference_missing"] = [r["name"] for r in rows if r.get("reference") is None]
    tally["ref_time_s"] = ref_time
    # tiny instances against brute force, through the CLI with a 10 s limit
    tiny = []
    for seed in range(1, 13):
        inst, best = tiny_instance(seed, with_base=(seed % 3 == 0))
        ipath = os.path.join(work, "tiny%d.json" % seed)
        with open(ipath, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        r = H.evaluate_case({"name": "tiny%d" % seed, "instance_path": ipath, "reference": best}, solve_py,
                            "hoffman1993", 10, checker, "min", work, hb=hb)
        tiny.append({"seed": seed, "base": seed % 3 == 0, "optimum": best, "found": r.get("objective"),
                     "status": r["status"], "optimal": r["status"] == "ok" and r.get("objective") == best,
                     "wall_s": r["wall_s"]})
    tally["tiny_optimal"] = sum(1 for t in tiny if t["optimal"])
    tally["tiny_total"] = len(tiny)
    hb.stop()
    intro = ("MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0. OR-Library set partitioning "
             "instances (Beasley; Hoffman and Levine), downloaded at run time, not redistributed. Solver v%s run "
             "through the FrontierOR CLI with a %g s limit; reference = HiGHS via scipy.optimize.milp, mip_rel_gap 0, "
             "%g s limit, run separately (reference_proven = HiGHS proved optimality; reference_source = ref-file "
             "means it was computed by the earlier run froc-spp-orlib-v1)." % (S.VERSION, time_limit, ref_time))
    H.write_report(out, "hoffman1993 (set partitioning) solver: calibration on OR-Library", intro, rows, tally,
                   extra_cols=("rows_m", "cols_n", "ref_wall_s", "reference_source"))
    with open(os.path.join(out, "tiny.json"), "w", encoding="utf-8") as f:
        json.dump(tiny, f, indent=1)
    print("TALLY", json.dumps(tally), flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "run"])
    ap.add_argument("--data-dir", default="/data")
    ap.add_argument("--out-dir", default="/out")
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--ref-time", type=float, default=300.0)
    ap.add_argument("--ref-file", default="")
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        fetch(a.data_dir)
    else:
        refs = None
        if a.ref_file:
            with open(a.ref_file, encoding="utf-8") as f:
                refs = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
        run(a.data_dir, a.out_dir, a.time_limit, a.ref_time, [s for s in a.only.split(",") if s] or None, refs)
    return 0


if __name__ == "__main__":
    sys.exit(main())

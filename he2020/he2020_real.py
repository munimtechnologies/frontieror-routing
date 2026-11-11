"""he2020 (VRPTW with convex node costs) solver v0.1.0 on the six public FrontierOR instances, plus a rho check.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python he2020/he2020_real.py --hf-dir /data/hf --out-dir /out [--time-limit 60]

Writes /out/he2020-real/{rows.jsonl, results.json, results.md, manifest.json} (kit/frontieror_real.run_task), then
rho.jsonl / rho.md, one row per instance:
- the instance's top-level keys, whether it has the top-level "inconvenience_cost_factor_rho" that the official
  feasibility_check.py reads (default 0), and the rho in "inconvenience_cost_function" that gurobi_code.py optimises;
- n, fleet, capacity, the largest |preferred_time - window midpoint|;
- for the stored Gurobi solution and for ours: reported objective, recomputed routing cost and inconvenience cost
  (with the gurobi_code.py rho), and the official checker's verdict on (a) the instance as published and (b) a copy
  with the top-level key set to the gurobi_code.py rho;
- probe: our solution with objective_value replaced by its routing cost alone (what the official formula gives when
  rho is 0), run through the official checker on (a) and (b). This file is a test of the checker, never an entry.
"""
import argparse
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "kit"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import frontieror_real as FR  # noqa: E402
import he2020_check as HC  # noqa: E402

KEY = "inconvenience_cost_factor_rho"


def size_info(inst):
    rho, src = HC.rho_of(inst)
    return {"n_customers": inst.get("num_customers"), "vehicles": inst.get("num_vehicles"),
            "capacity": inst.get("vehicle_capacity"), "rho": rho, "rho_source": src,
            "has_top_level_rho_key": KEY in inst}


def verdicts(checker_py, inst_path, inj_path, sol, work, tag):
    sp = os.path.join(work, tag + ".json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(sol, f)
    a = FR.official(checker_py, inst_path, sp, os.path.join(work, tag + ".asis.result.json"))
    b = FR.official(checker_py, inj_path, sp, os.path.join(work, tag + ".injected.result.json"))
    return {"official_as_published": a.get("feasible"), "violated_as_published": a.get("violated"),
            "violations_as_published": (a.get("violations") or "")[:300],
            "official_with_key": b.get("feasible"), "violated_with_key": b.get("violated")}


def rho_rows(hf_dir, out):
    tdir = os.path.join(hf_dir, "tasks", "he2020")
    checker_py = os.path.join(tdir, "feasibility_check.py")
    work = os.path.join(out, "rho-work")
    os.makedirs(work, exist_ok=True)
    rows = []
    for name, ifile, sfile, _ in FR.CASES:
        ip = os.path.join(tdir, "instance", ifile)
        if not os.path.exists(ip):
            continue
        with open(ip, encoding="utf-8") as f:
            inst = json.load(f)
        rho, src = HC.rho_of(inst)
        mids = [abs(float(c["preferred_time"]) - (float(c["time_window"][0]) + float(c["time_window"][1])) / 2.0)
                for c in inst["customers"]]
        row = {"name": name, "top_level_keys": sorted(inst.keys()), "has_top_level_rho_key": KEY in inst,
               "top_level_rho": inst.get(KEY), "gurobi_code_rho": rho, "rho_source": src,
               "n": inst.get("num_customers"), "K": inst.get("num_vehicles"), "Q": inst.get("vehicle_capacity"),
               "max_abs_pref_minus_mid": max(mids) if mids else None}
        inj = copy.deepcopy(inst)
        inj[KEY] = rho
        inj_path = os.path.join(work, name + ".instance_with_key.json")
        with open(inj_path, "w", encoding="utf-8") as f:
            json.dump(inj, f)
        for who, path in (("gurobi", os.path.join(tdir, "gurobi_solution", sfile)),
                          ("ours", os.path.join(out, "work", name + ".solution.json"))):
            if not os.path.exists(path):
                row[who + "_present"] = False
                continue
            with open(path, encoding="utf-8") as f:
                sol = json.load(f)
            row[who + "_present"] = True
            routing, inconv = HC.costs(inst, sol, rho)
            rep = sol.get("objective_value")
            row.update({who + "_reported_objective": rep, who + "_routing": routing, who + "_inconvenience": inconv,
                        who + "_recomputed_total": routing + inconv,
                        who + "_inconvenience_share": (inconv / (routing + inconv)) if routing + inconv else None,
                        who + "_routes": len(sol.get("routes") or [])})
            if who == "gurobi":
                row.update(gurobi_status=sol.get("status"), gurobi_mip_gap=sol.get("mip_gap"),
                           gurobi_reported_routing=sol.get("routing_cost"),
                           gurobi_reported_inconvenience=sol.get("inconvenience_cost"))
            v = verdicts(checker_py, ip, inj_path, sol, work, name + "." + who)
            row.update({who + "_" + k: val for k, val in v.items()})
            if who == "ours":
                probe = dict(sol)
                probe["objective_value"] = routing
                pv = verdicts(checker_py, ip, inj_path, probe, work, name + ".probe_routing_only")
                row.update({"probe_routing_only_" + k: val for k, val in pv.items()})
        rows.append(row)
        print("rho", json.dumps(row, default=str)[:1500], flush=True)
    with open(os.path.join(out, "rho.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")
    cols = ["name", "n", "K", "has_top_level_rho_key", "gurobi_code_rho", "max_abs_pref_minus_mid",
            "gurobi_status", "gurobi_reported_objective", "gurobi_recomputed_total", "gurobi_inconvenience_share",
            "gurobi_official_as_published", "gurobi_violated_as_published", "gurobi_official_with_key",
            "ours_recomputed_total", "ours_inconvenience_share", "ours_official_as_published",
            "ours_official_with_key", "probe_routing_only_official_as_published",
            "probe_routing_only_official_with_key"]
    lines = ["# he2020: which rho does the official checker use?", "",
             "The official feasibility_check.py recomputes the objective with "
             "`instance.get(\"inconvenience_cost_factor_rho\", 0.0)`; gurobi_code.py optimises "
             "`instance[\"inconvenience_cost_function\"][\"rho\"]`. Each solution is checked on the instance as "
             "published and on a copy with the top-level key set to the gurobi_code.py rho. The probe row is our "
             "solution with objective_value set to its routing cost alone: a test of the checker, never an entry. "
             "Made with AI agents working in MV2's name (MV2 of Munim, Inc.).", "",
             "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    with open(os.path.join(out, "rho.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    a = ap.parse_args()
    out = os.path.join(a.out_dir, "he2020-real")
    FR.run_task("he2020", os.path.join(HERE, "solve.py"), HC.check, "min", a.hf_dir, out, a.time_limit,
                size_info=size_info, title="he2020 (VRPTW with convex node costs) solver v0.1.0",
                intro_extra="Our checker uses the rho of inconvenience_cost_function (the one gurobi_code.py "
                            "optimises); see rho.md for the official checker's rho. ")
    try:
        rho_rows(a.hf_dir, out)
    except Exception as e:  # noqa: BLE001
        print("RHO-FAILED", repr(e), flush=True)


if __name__ == "__main__":
    main()

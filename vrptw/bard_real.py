"""bard2002 (VRPTW, minimise vehicles) solver v0.1.0 on the six public FrontierOR instances, plus three data checks.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python vrptw/bard_real.py --hf-dir /data/hf --out-dir /out [--time-limit 60]

Writes /out/bard-real/{rows.jsonl, results.json, results.md, manifest.json} (kit/frontieror_real.run_task), then:
- extras.jsonl / extras.md, one row per instance: instance facts (customers, capacity, the
  travel_time_includes_service_time flag, service times, whether distance_matrix equals the truncated Euclidean
  distance), the stored Gurobi solution's status, gap, runtime and route count, depot timing of both solutions
  (bard_check.strict), and how full their routes are under plain capacity and under the load rule implied by the
  checker's constraint (5) (bard_check.plain_capacity);
- probe.json / probe.md: the official checker run on a 2-customer instance (demands 5 and 5, wide windows) with
  one route carrying 10 units, for vehicle capacities 10, 12, 14, 15 and 16, plus the solver's own load-witness
  search on the same cases.
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "kit"), HERE, os.path.join(HERE, "bard2002")):
    if p not in sys.path:
        sys.path.insert(0, p)

import bard_check  # noqa: E402
import frontieror_real as FR  # noqa: E402


def size_info(inst):
    return {"n_customers": len(inst.get("customers") or []), "capacity": inst.get("vehicle_capacity"),
            "fold_flag": inst.get("travel_time_includes_service_time")}


def matrix_facts(inst):
    nodes = [inst["depot"]] + list(inst["customers"])
    N = len(nodes)
    dm = inst.get("distance_matrix")
    out = {"has_matrix": bool(dm), "fold_flag": inst.get("travel_time_includes_service_time"),
           "service_values": sorted({float(v["service_time"]) for v in inst["customers"]})[:6],
           "primary_objective": str(inst.get("primary_objective"))[:120],
           "secondary_objective": str(inst.get("secondary_objective"))[:120]}
    if not dm:
        return out
    d_trunc, d_svc = 0.0, 0.0
    for i in range(N):
        for j in range(N):
            if i == j:
                continue
            e = math.sqrt((nodes[i]["x"] - nodes[j]["x"]) ** 2 + (nodes[i]["y"] - nodes[j]["y"]) ** 2)
            tr = math.floor(e * 10) / 10.0
            d_trunc = max(d_trunc, abs(float(dm[i][j]) - tr))
            d_svc = max(d_svc, abs(float(dm[i][j]) - (tr + float(nodes[i]["service_time"]))))
    out.update(max_abs_vs_truncated_euclid=round(d_trunc, 6), max_abs_vs_truncated_plus_service=round(d_svc, 6),
               matrix_is_truncated_euclid=d_trunc < 1e-6, matrix_includes_service=d_svc < 1e-6)
    return out


def probe(checker_py, work):
    import solve as S  # bard2002/solve.py

    rows = []
    for Q in (10, 12, 14, 15, 16):
        inst = {"num_customers": 2, "vehicle_capacity": Q,
                "depot": {"id": 0, "x": 0.0, "y": 0.0, "demand": 0, "ready_time": 0, "due_date": 1000,
                          "service_time": 0},
                "customers": [{"id": 1, "x": 1.0, "y": 0.0, "demand": 5, "ready_time": 0, "due_date": 1000,
                               "service_time": 0},
                              {"id": 2, "x": 2.0, "y": 0.0, "demand": 5, "ready_time": 0, "due_date": 1000,
                               "service_time": 0}],
                "scheduling_horizon": 1000, "travel_time_includes_service_time": False}
        one = {"objective_value": 1, "num_vehicles": 1, "routes": [[0, 1, 2, 0]], "total_distance": 4.0,
               "departure_times": {"1": 1.0, "2": 2.0}, "loads": {"1": 5, "2": 10}}
        two = {"objective_value": 2, "num_vehicles": 2, "routes": [[0, 1, 0], [0, 2, 0]], "total_distance": 6.0,
               "departure_times": {"1": 1.0, "2": 2.0}, "loads": {"1": 5, "2": 5}}
        ip = os.path.join(work, "probe_Q%d.instance.json" % Q)
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        row = {"Q": Q, "load_on_one_route": 10}
        for tag, sol in (("one_route", one), ("two_routes", two)):
            sp = os.path.join(work, "probe_Q%d.%s.json" % (Q, tag))
            with open(sp, "w", encoding="utf-8") as f:
                json.dump(sol, f)
            o = FR.official(checker_py, ip, sp, os.path.join(work, "probe_Q%d.%s.result.json" % (Q, tag)))
            row[tag + "_official_feasible"] = o.get("feasible")
            row[tag + "_official_violated"] = o.get("violated")
            row[tag + "_ours_feasible"] = bard_check.check(inst, sol).get("feasible")
        I = S.Inst(inst)
        row["any_load_witness_for_one_route"] = I.witness([[1, 2]]) is not None
        rows.append(row)
    with open(os.path.join(work, "..", "probe.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    lines = ["# bard2002 checker probe: one route carrying 10 units (demands 5 + 5)", "",
             "Official feasibility_check.py of the public FrontierOR benchmark, run on a 2-customer instance with "
             "wide time windows. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).", "",
             "| Q | one route: official | violated | one route: any load witness | two routes: official |",
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | %s | %s | %s |" % (r["Q"], r["one_route_official_feasible"],
                                                     r["one_route_official_violated"],
                                                     r["any_load_witness_for_one_route"],
                                                     r["two_routes_official_feasible"]))
    with open(os.path.join(work, "..", "probe.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("probe", json.dumps(rows), flush=True)
    return rows


def extras(hf_dir, out):
    tdir = os.path.join(hf_dir, "tasks", "bard2002")
    rows = []
    for name, ifile, sfile, _ in FR.CASES:
        ip = os.path.join(tdir, "instance", ifile)
        if not os.path.exists(ip):
            continue
        with open(ip, encoding="utf-8") as f:
            inst = json.load(f)
        row = {"name": name, "n": len(inst["customers"]), "Q": inst["vehicle_capacity"],
               "total_demand": sum(c["demand"] for c in inst["customers"]),
               "max_demand": max(c["demand"] for c in inst["customers"]),
               "depot_window": [inst["depot"]["ready_time"], inst["depot"]["due_date"]]}
        row["lb_capacity"] = int(math.ceil(row["total_demand"] / float(row["Q"]) - 1e-9))
        row.update(matrix_facts(inst))
        gp = os.path.join(tdir, "gurobi_solution", sfile)
        if os.path.exists(gp):
            with open(gp, encoding="utf-8") as f:
                g = json.load(f)
            row.update(gurobi_routes=len(g.get("routes") or []), gurobi_status=g.get("status_description"),
                       gurobi_gap=g.get("mip_gap"), gurobi_runtime=g.get("runtime_seconds"))
            row.update({"gurobi_" + k: v for k, v in bard_check.strict(inst, g).items()})
            row.update({"gurobi_" + k: v for k, v in bard_check.plain_capacity(inst, g).items()})
        sp = os.path.join(out, "work", name + ".solution.json")
        if os.path.exists(sp):
            with open(sp, encoding="utf-8") as f:
                s = json.load(f)
            row.update(ours_routes=len(s.get("routes") or []))
            row.update({"ours_" + k: v for k, v in bard_check.strict(inst, s).items()})
            row.update({"ours_" + k: v for k, v in bard_check.plain_capacity(inst, s).items()})
        rows.append(row)
    with open(os.path.join(out, "extras.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    cols = ["name", "n", "Q", "total_demand", "max_demand", "lb_capacity", "fold_flag", "service_values",
            "matrix_is_truncated_euclid", "matrix_includes_service", "gurobi_status", "gurobi_gap", "gurobi_routes",
            "gurobi_strict_ok", "gurobi_late_returns", "gurobi_max_load_frac", "gurobi_max_rule_frac", "ours_routes",
            "ours_strict_ok", "ours_max_load_frac", "ours_max_rule_frac"]
    lines = ["# bard2002: instance facts and both solutions", "",
             "Made with AI agents working in MV2's name (MV2 of Munim, Inc.).", "",
             "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    with open(os.path.join(out, "extras.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("extras", json.dumps(rows), flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    a = ap.parse_args()
    out = os.path.join(a.out_dir, "bard-real")
    FR.run_task("bard2002", os.path.join(HERE, "bard2002", "solve.py"), bard_check.check, "min", a.hf_dir, out,
                a.time_limit, size_info=size_info, title="bard2002 (VRPTW, fewest vehicles) solver v0.1.0")
    try:
        extras(a.hf_dir, out)
    except Exception as e:  # noqa: BLE001
        print("EXTRAS-FAILED", repr(e), flush=True)
    try:
        os.makedirs(os.path.join(out, "probe"), exist_ok=True)
        probe(os.path.join(a.hf_dir, "tasks", "bard2002", "feasibility_check.py"), os.path.join(out, "probe"))
    except Exception as e:  # noqa: BLE001
        print("PROBE-FAILED", repr(e), flush=True)


if __name__ == "__main__":
    main()

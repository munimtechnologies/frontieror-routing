#!/usr/bin/env python3
"""Calibrate MV2's nagy2015 (VRPDDP) solver on the public Salhi-Nagy CMT X/Y instances.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name.
License: Apache-2.0. The Salhi and Nagy (1999) instances are downloaded at run time from
github.com/falcopt/FSPD at a pinned commit and are not redistributed; only our own numbers are published.

Usage:
    python nagy_eval.py fetch --data-dir /data
    python nagy_eval.py run --data-dir /data --out-dir /out [--time-limit 60]

Every instance is converted to the FrontierOR nagy2015 JSON schema (depot = node 1 of the file as id 0,
customers 1..n in file order, Euclidean distances rounded to the nearest integer as the problem page
says; the route-length and service-time lines of CMT6-10, 13 and 14 are ignored because nagy2015 has
none) and solved by running nagy2015/solve.py as a subprocess, as the FrontierOR sandbox invokes it.
Every solution is checked by the independent checker in this file.

v2 (2026-11-09): the exact enumeration for tiny instances no longer requires every subset of a
route's requests to be load-feasible on its own (v1 did, which wrongly ruled out routes such as
delivery-then-pickup and gave optima that were too high).
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SOLVER = os.path.join(HERE, "nagy2015", "solve.py")
FSPD_SHA = "de480ce4c59accc9f71c76c76f32b707ee7305ad"
RAW = "https://raw.githubusercontent.com/falcopt/FSPD/" + FSPD_SHA + "/INSTANCES/"
SETS = ["CMTX", "CMTY"]
NUMS = list(range(1, 15))
UA = "MV2 of Munim, Inc. VRPDDP solver calibration (mv2@munimtech.com)"
# Proven optimum of CMT1X and CMT1Y as VRPSPD with unrounded Euclidean distances
# (Subramanian, Uchoa, Pessoa and Ochi, SEA 2010).
ANCHOR = {"CMTX/CMT1": 466.77, "CMTY/CMT1": 466.77}
EPS = 1e-6


# ---------------------------------------------------------------- FSPD format
def parse_fspd(text):
    head, coords, pd, cur = {}, {}, {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "EOF":
            continue
        if line.endswith("_SECTION"):
            cur = line
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            head[k.strip()] = v.strip()
            cur = None
            continue
        parts = line.split()
        if cur == "NODE_COORD_SECTION" and len(parts) >= 3:
            coords[int(parts[0])] = (float(parts[1]), float(parts[2]))
        elif cur == "PICKUP_AND_DELIVERY_SECTION" and len(parts) >= 7:
            # node, demand (ignored), earliest, latest, service, pickup, delivery
            pd[int(parts[0])] = (float(parts[5]), float(parts[6]))
    return head, coords, pd


def num(x):
    return int(x) if float(x).is_integer() else float(x)


def to_frontieror(text, real=False):
    """FSPD .vrp text -> nagy2015 instance dict. real=True keeps unrounded distances (anchor only)."""
    head, coords, pd = parse_fspd(text)
    nodes = sorted(coords)
    depot = nodes[0]
    cust = nodes[1:]
    xy = [coords[depot]] + [coords[c] for c in cust]
    m = len(xy)
    dm = []
    for i in range(m):
        row = []
        for j in range(m):
            d = math.hypot(xy[i][0] - xy[j][0], xy[i][1] - xy[j][1])
            row.append(round(d, 9) if real else int(math.floor(d + 0.5)))
        dm.append(row)
    customers = []
    for k, c in enumerate(cust, start=1):
        pk, dl = pd.get(c, (0.0, 0.0))
        customers.append({"id": k, "x": num(coords[c][0]), "y": num(coords[c][1]),
                          "delivery_demand": num(dl), "pickup_demand": num(pk)})
    inst = {"num_customers": len(cust), "vehicle_capacity": num(float(head["CAPACITY"])),
            "depot": {"id": 0, "x": num(coords[depot][0]), "y": num(coords[depot][1])},
            "customers": customers, "distance_matrix": dm}
    return inst, {"name": head.get("NAME", ""), "n": len(cust),
                  "ignored": {k: head[k] for k in ("DISTANCE", "SERVICE_TIME") if k in head}}


# ---------------------------------------------------------------- independent checker
def check(inst, sol):
    """Return (ok, reason, objective). Mirrors the documented nagy2015 rules."""
    n = int(inst["num_customers"])
    C = float(inst["vehicle_capacity"])
    D = inst["distance_matrix"]
    dl = {int(c["id"]): float(c["delivery_demand"]) for c in inst["customers"]}
    pk = {int(c["id"]): float(c["pickup_demand"]) for c in inst["customers"]}
    if "routes" not in sol or "objective_value" not in sol:
        return False, "missing routes or objective_value", None
    count = {}
    total = 0.0
    for rt in sol["routes"]:
        rt = [int(v) for v in rt]
        if len(rt) < 3 or rt[0] != 0 or rt[-1] != 0 or 0 in rt[1:-1]:
            return False, "bad route shape", None
        load = sum(dl[v] for v in rt[1:-1] if 1 <= v <= n)
        if load > C + EPS:
            return False, "leaves the depot over capacity", None
        for v in rt[1:-1]:
            if not 1 <= v <= 2 * n:
                return False, "unknown node %d" % v, None
            count[v] = count.get(v, 0) + 1
            load += -dl[v] if v <= n else pk[v - n]
            if load > C + EPS:
                return False, "over capacity after node %d" % v, None
        locs = [v if v <= n else v - n for v in rt]
        total += sum(float(D[a][b]) for a, b in zip(locs[:-1], locs[1:]))
    missing = [v for v in range(1, 2 * n + 1) if count.get(v, 0) != 1]
    if missing:
        return False, "%d nodes not visited exactly once" % len(missing), None
    if abs(total - float(sol["objective_value"])) > 1e-6 * max(1.0, abs(total)):
        return False, "objective mismatch %s vs %s" % (sol["objective_value"], total), total
    return True, "ok", total


# ---------------------------------------------------------------- exact solver for tiny instances
def exact(inst, spd=False):
    """Optimal VRPDDP (or VRPSPD) distance by enumeration; only for <= 12 requests.

    For a route serving request set S, the load after visiting a subset M of S first is
    sum(qd over S) - sum(qd over M) + sum(qp over M), whatever the order inside M. A path DP over
    (visited subset, last request) keeps only states whose visited subset leaves a feasible load.
    """
    n = int(inst["num_customers"])
    C = float(inst["vehicle_capacity"])
    D = inst["distance_matrix"]
    cs = sorted(inst["customers"], key=lambda c: int(c["id"]))
    if spd:
        loc = list(range(1, n + 1))
        qd = [float(c["delivery_demand"]) for c in cs]
        qp = [float(c["pickup_demand"]) for c in cs]
    else:
        loc = list(range(1, n + 1)) * 2
        qd = [float(c["delivery_demand"]) for c in cs] + [0.0] * n
        qp = [0.0] * n + [float(c["pickup_demand"]) for c in cs]
    K = len(loc)
    if K > 12:
        raise ValueError("too many requests for the exact solver")
    INF = float("inf")
    full = (1 << K) - 1
    route = [INF] * (1 << K)
    for S in range(1, full + 1):
        mem = [r for r in range(K) if (S >> r) & 1]
        dtot = sum(qd[r] for r in mem)
        if dtot > C + EPS:
            continue
        m = len(mem)
        size = 1 << m
        load = [0.0] * size
        load[0] = dtot
        okm = [True] * size
        for mask in range(1, size):
            low = (mask & -mask).bit_length() - 1
            prev = mask & (mask - 1)
            r = mem[low]
            load[mask] = load[prev] - qd[r] + qp[r]
            okm[mask] = load[mask] <= C + EPS  # order-free; prefixes are enforced by the path DP
        dp = [[INF] * m for _ in range(size)]
        for j in range(m):
            if okm[1 << j]:
                dp[1 << j][j] = float(D[0][loc[mem[j]]])
        for mask in range(1, size):
            if not okm[mask]:
                continue
            row = dp[mask]
            for j in range(m):
                cur = row[j]
                if cur == INF:
                    continue
                lj = loc[mem[j]]
                for k in range(m):
                    if (mask >> k) & 1:
                        continue
                    nm = mask | (1 << k)
                    if not okm[nm]:
                        continue
                    val = cur + float(D[lj][loc[mem[k]]])
                    if val < dp[nm][k]:
                        dp[nm][k] = val
        last = dp[size - 1]
        route[S] = min((last[j] + float(D[loc[mem[j]]][0]) for j in range(m)), default=INF)
    f = [INF] * (1 << K)
    f[0] = 0.0
    for mask in range(1, full + 1):
        low = mask & -mask
        rest = mask ^ low
        sub = rest
        best = INF
        while True:
            S = sub | low
            if route[S] < INF and f[mask ^ S] < INF:
                v = route[S] + f[mask ^ S]
                if v < best:
                    best = v
            if sub == 0:
                break
            sub = (sub - 1) & rest
        f[mask] = best
    return f[full]


def random_instance(seed, n):
    rng = random.Random(seed)
    C = 20
    xy = [(rng.randint(0, 50), rng.randint(0, 50)) for _ in range(n + 1)]
    customers = []
    for i in range(1, n + 1):
        customers.append({"id": i, "x": xy[i][0], "y": xy[i][1],
                          "delivery_demand": rng.choice([0, rng.randint(1, 15)]) if rng.random() < 0.2
                          else rng.randint(1, 15),
                          "pickup_demand": rng.randint(0, 15)})
    dm = [[int(math.floor(math.hypot(a[0] - b[0], a[1] - b[1]) + 0.5)) for b in xy] for a in xy]
    return {"num_customers": n, "vehicle_capacity": C, "depot": {"id": 0, "x": xy[0][0], "y": xy[0][1]},
            "customers": customers, "distance_matrix": dm}


# ---------------------------------------------------------------- running the solver
def run_solver(inst, time_limit, engine="auto", spd=False):
    with tempfile.TemporaryDirectory() as td:
        ip = os.path.join(td, "instance.json")
        op = os.path.join(td, "solution.json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        cmd = [sys.executable, SOLVER, "--problem", "nagy2015", "--instance", ip, "--output", op,
               "--time-limit", str(int(time_limit)), "--engine", engine]
        if spd:
            cmd.append("--spd")
        t = time.time()
        try:
            cp = subprocess.run(cmd, cwd=os.path.dirname(SOLVER), capture_output=True, text=True,
                                timeout=time_limit + 60)
        except subprocess.TimeoutExpired:
            return None, time.time() - t, "timeout", {}
        wall = time.time() - t
        stats = {}
        for line in cp.stderr.splitlines():
            if "NAGY_SOLVER_STATS " in line:
                try:
                    stats = json.loads(line.split("NAGY_SOLVER_STATS ", 1)[1])
                except ValueError:
                    pass
        if cp.returncode != 0:
            return None, wall, "exit %d: %s" % (cp.returncode, cp.stderr[-500:]), stats
        if not os.path.exists(op):
            return None, wall, "no output", stats
        with open(op, encoding="utf-8") as f:
            return json.load(f), wall, "", stats


def solve_and_check(inst, limit, engine, spd=False):
    sol, wall, err, stats = run_solver(inst, limit, engine, spd)
    out = {"wall_s": round(wall, 2), "overtime": wall > limit - 1.0, "engine_used": stats.get("engine"),
           "pyvrp_error": stats.get("pyvrp_error"), "stats": stats}
    if sol is None:
        out.update({"feasible": False, "why": err})
        return out
    ok, why, obj = check(inst, sol)
    out.update({"feasible": ok, "why": why, "objective": obj, "routes": len(sol.get("routes", []))})
    return out


def fetch(data_dir):
    root = os.path.join(data_dir, "fspd-" + FSPD_SHA[:7])
    os.makedirs(root, exist_ok=True)
    got = 0
    for s in SETS:
        for k in NUMS:
            rel = "%s/CMT%dH.vrp" % (s, k)
            dest = os.path.join(root, rel.replace("/", "__"))
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                got += 1
                continue
            req = urllib.request.Request(RAW + rel, headers={"User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = r.read()
                with open(dest, "wb") as f:
                    f.write(data)
                got += 1
            except Exception as e:  # recorded, not fatal
                print("missing", rel, e)
            time.sleep(0.3)
    print("fetched", got, "files into", root)


def load(root, s, k, real=False):
    path = os.path.join(root, ("%s/CMT%dH.vrp" % (s, k)).replace("/", "__"))
    if not os.path.exists(path):
        return None, None
    with open(path, encoding="utf-8") as f:
        return to_frontieror(f.read(), real=real)


def run(data_dir, out_dir, limit, spd_limit=30, tiny_limit=10):
    root = os.path.join(data_dir, "fspd-" + FSPD_SHA[:7])
    out = os.path.join(out_dir, "vrpddp")
    os.makedirs(out, exist_ok=True)
    res = {"fspd_commit": FSPD_SHA, "time_limit_s": limit, "tiny": [], "anchor": [], "rows": []}

    def save():
        with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)

    # 1) tiny instances against the exact optimum
    for seed in range(1, 13):
        n = 4 if seed <= 6 else 5
        inst = random_instance(seed, n)
        t = time.time()
        opt = exact(inst)
        row = {"seed": seed, "n": n, "optimum": opt, "spd_optimum": exact(inst, spd=True),
               "exact_s": round(time.time() - t, 2)}
        for eng in ("auto", "own"):
            r = solve_and_check(inst, tiny_limit, eng)
            r["optimal"] = bool(r.get("feasible") and abs(r["objective"] - opt) < 1e-6)
            r["below_optimum"] = bool(r.get("feasible") and r["objective"] < opt - 1e-6)
            row[eng] = r
        print("tiny", json.dumps(row), flush=True)
        res["tiny"].append(row)
        save()
    # 2) literature anchor: VRPSPD with unrounded distances on CMT1X / CMT1Y
    for key, ref in ANCHOR.items():
        s, name = key.split("/")
        inst, info = load(root, s, int(name[3:]), real=True)
        if inst is None:
            res["anchor"].append({"instance": key, "skipped": "file missing"})
            continue
        r = solve_and_check(inst, spd_limit, "auto", spd=True)
        r.update({"instance": key, "published_optimum": ref})
        if r.get("feasible"):
            r["gap_pct"] = round(100.0 * (r["objective"] - ref) / ref, 3)
        print("anchor", json.dumps(r), flush=True)
        res["anchor"].append(r)
        save()
    # 3) the 28 Salhi-Nagy instances, FrontierOR convention (rounded distances)
    for k in NUMS:
        for s in SETS:
            inst, info = load(root, s, k)
            row = {"instance": "%s/CMT%d" % (s, k)}
            if inst is None:
                row["skipped"] = "file missing"
                res["rows"].append(row)
                continue
            row.update({"n": info["n"], "ignored": info["ignored"],
                        "capacity": inst["vehicle_capacity"]})
            row["ddp_auto"] = solve_and_check(inst, limit, "auto")
            row["ddp_own"] = solve_and_check(inst, limit, "own")
            row["spd_auto"] = solve_and_check(inst, spd_limit, "auto", spd=True)
            a, o, p = (row["ddp_auto"].get("objective"), row["ddp_own"].get("objective"),
                       row["spd_auto"].get("objective"))
            if row["ddp_auto"].get("feasible") and row["ddp_own"].get("feasible"):
                row["own_over_auto"] = round(o / a, 5)
            if row["ddp_auto"].get("feasible") and row["spd_auto"].get("feasible"):
                row["split_saving_pct"] = round(100.0 * (p - a) / p, 3)
            print("row", json.dumps(row), flush=True)
            res["rows"].append(row)
            save()
    rows = [r for r in res["rows"] if "skipped" not in r]
    ratios = [r["own_over_auto"] for r in rows if "own_over_auto" in r]
    sav = [r["split_saving_pct"] for r in rows if "split_saving_pct" in r]
    tally = {
        "instances_run": len(rows),
        "skipped": [r["instance"] for r in res["rows"] if "skipped" in r],
        "auto_infeasible": [r["instance"] for r in rows if not r["ddp_auto"].get("feasible")],
        "auto_overtime": [r["instance"] for r in rows if r["ddp_auto"].get("overtime")],
        "own_infeasible": [r["instance"] for r in rows if not r["ddp_own"].get("feasible")],
        "own_overtime": [r["instance"] for r in rows if r["ddp_own"].get("overtime")],
        "auto_engines": sorted(set(str(r["ddp_auto"].get("engine_used")) for r in rows)),
        "auto_pyvrp_ran": sum(1 for r in rows
                              if isinstance(r["ddp_auto"].get("stats", {}).get("pyvrp"), (int, float))),
        "pyvrp_errors": sorted(set(str(r["ddp_auto"].get("pyvrp_error")) for r in rows
                                   if r["ddp_auto"].get("pyvrp_error"))),
        "mean_own_over_auto": round(sum(ratios) / len(ratios), 5) if ratios else None,
        "max_own_over_auto": max(ratios) if ratios else None,
        "ddp_le_spd": sum(1 for x in sav if x >= -1e-9),
        "ddp_lt_spd": sum(1 for x in sav if x > 1e-9),
        "mean_split_saving_pct": round(sum(sav) / len(sav), 3) if sav else None,
        "max_split_saving_pct": max(sav) if sav else None,
        "tiny_auto_optimal": sum(1 for t in res["tiny"] if t["auto"].get("optimal")),
        "tiny_own_optimal": sum(1 for t in res["tiny"] if t["own"].get("optimal")),
        "tiny_below_optimum": sum(1 for t in res["tiny"] for e in ("auto", "own") if t[e].get("below_optimum")),
        "tiny_total": len(res["tiny"]),
        "anchor_gaps_pct": {a["instance"]: a.get("gap_pct") for a in res["anchor"]},
    }
    res["tally"] = tally
    save()
    lines = ["# nagy2015 (VRPDDP) solver v2: calibration on the Salhi-Nagy CMT X/Y instances", "",
             "MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.", "",
             "Instances: Salhi and Nagy (1999) CMT X and Y sets, as published in github.com/falcopt/FSPD at commit "
             "%s, converted to the FrontierOR nagy2015 schema with distances rounded to the nearest integer. "
             "Route-length and service-time limits of CMT6-10, 13, 14 are ignored (nagy2015 has none), so those "
             "rows are not comparable with published VRPSPD tables. Each run is a subprocess call of solve.py "
             "exactly as the FrontierOR sandbox invokes it; every solution is re-checked independently." % FSPD_SHA,
             "", "- ddp_auto: the submission candidate (portfolio: PyVRP divisible, PyVRP non-divisible, own), %d s"
             % limit,
             "- ddp_own: the numpy-only fallback engine (non-divisible first, then divisible), %d s" % limit,
             "- spd_auto: the same instance without splitting (VRPSPD), %d s; split saving = (spd - ddp) / spd"
             % spd_limit, "", "## Tally", "", "```", json.dumps(tally, indent=1), "```", "",
             "## Per instance", "",
             "| instance | n | ddp auto | engine | ddp own | own/auto | spd auto | split saving % | auto wall s |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in res["rows"]:
        if "skipped" in r:
            lines.append("| %s | | | | | | | skipped: %s | |" % (r["instance"], r["skipped"]))
            continue
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["instance"], r["n"], r["ddp_auto"].get("objective", "NO: %s" % r["ddp_auto"].get("why")),
            r["ddp_auto"].get("engine_used"),
            r["ddp_own"].get("objective", "NO: %s" % r["ddp_own"].get("why")), r.get("own_over_auto"),
            r["spd_auto"].get("objective"), r.get("split_saving_pct"), r["ddp_auto"].get("wall_s")))
    lines += ["", "## Literature anchor (VRPSPD, unrounded distances, %d s)" % spd_limit, "",
              "| instance | ours | published optimum | gap % |", "|---|---|---|---|"]
    for a in res["anchor"]:
        lines.append("| %s | %s | %s | %s |" % (a["instance"], a.get("objective"), a.get("published_optimum"),
                                               a.get("gap_pct")))
    lines += ["", "## Tiny random instances vs exact optimum (%d s each)" % tiny_limit, "",
              "| seed | n | optimum | non-divisible optimum | auto | own |", "|---|---|---|---|---|---|"]
    for t in res["tiny"]:
        lines.append("| %d | %d | %s | %s | %s | %s |" % (t["seed"], t["n"], t["optimum"], t["spd_optimum"],
                                                          t["auto"].get("objective"), t["own"].get("objective")))
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("TALLY", json.dumps(tally))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "run"])
    ap.add_argument("--data-dir", default="/data")
    ap.add_argument("--out-dir", default="/out")
    ap.add_argument("--time-limit", type=int, default=60)
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.data_dir)
    else:
        run(a.data_dir, a.out_dir, a.time_limit)


if __name__ == "__main__":
    main()

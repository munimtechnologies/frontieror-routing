#!/usr/bin/env python3
"""Calibrate MV2's fischetti1998 (Orienteering Problem) solver on public OPLib instances.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name.
License: Apache-2.0. OPLib (Kobeaga, Merino and Lozano) instances and EA4OP solutions are
downloaded at run time from github.com/bcamath-ds/OPLib at a pinned commit and are not
redistributed; only our own numbers are published.

Usage:
    python op_eval.py fetch --data-dir /data
    python op_eval.py run --data-dir /data --out-dir /out [--time-limit 60]

Each instance is converted to the FrontierOR fischetti1998 JSON schema (depot prize 0,
TSPLIB EUC_2D nint distances, keys "(i,j)" with i < j) and solved by running
fischetti1998/solve.py as a subprocess exactly as the FrontierOR sandbox invokes it.
Every solution is checked by an independent checker in this file.
"""
import argparse
import itertools
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SOLVER = os.path.join(HERE, "fischetti1998", "solve.py")
OPLIB_SHA = "823ac3e8c156d45e868c295ee1c95c3fee05bdd2"
RAW = "https://raw.githubusercontent.com/bcamath-ds/OPLib/" + OPLIB_SHA + "/"
NAMES = ["eil51", "berlin52", "st70", "eil76", "pr76", "rat99", "kroA100", "eil101",
         "ch130", "ch150", "kroA150", "kroA200", "tsp225", "a280", "lin318"]
GENS = [1, 2, 3]
UA = "MV2 of Munim, Inc. OP solver calibration (mv2@munimtech.com)"
_INT = re.compile(r"-?\d+")


# ---------------------------------------------------------------- OPLib parsing
def parse_oplib(text):
    """Parse an OPLib .oplib (TSPLIB-style) or .sol file into a dict."""
    head, sections, cur = {}, {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "EOF":
            continue
        if line.endswith("_SECTION"):
            cur = line
            sections[cur] = []
            continue
        if ":" in line and cur is None:
            k, v = line.split(":", 1)
            head[k.strip()] = v.strip()
            continue
        if ":" in line and not line.replace(":", "").replace(" ", "").lstrip("-").isdigit():
            k, v = line.split(":", 1)
            head[k.strip()] = v.strip()
            cur = None
            continue
        if cur is not None:
            sections[cur].append(line.split())
    return head, sections


def nint(x):
    return int(x + 0.5)


def oplib_to_frontieror(text):
    """Return (instance dict in FrontierOR schema, info) or (None, reason)."""
    head, sec = parse_oplib(text)
    ewt = head.get("EDGE_WEIGHT_TYPE", "")
    if ewt != "EUC_2D":
        return None, "edge_weight_type " + ewt
    coords = {}
    for row in sec.get("NODE_COORD_SECTION", []):
        coords[int(row[0])] = (float(row[1]), float(row[2]))
    scores = {}
    for row in sec.get("NODE_SCORE_SECTION", []):
        scores[int(row[0])] = int(float(row[1]))
    depot = 1
    for row in sec.get("DEPOT_SECTION", []):
        v = int(row[0])
        if v > 0:
            depot = v
            break
    t0 = int(float(head["COST_LIMIT"]))
    ids = sorted(coords)
    prizes = {str(i): (0 if i == depot else scores.get(i, 0)) for i in ids}
    tt = {}
    for a, b in itertools.combinations(ids, 2):
        (xa, ya), (xb, yb) = coords[a], coords[b]
        tt["(%d,%d)" % (a, b)] = nint(math.sqrt((xa - xb) ** 2 + (ya - yb) ** 2))
    inst = {"n": len(ids), "depot": depot, "t0": t0, "prizes": prizes, "travel_times": tt}
    return inst, {"name": head.get("NAME", ""), "n": len(ids), "t0": t0}


def sol_route(text):
    head, sec = parse_oplib(text)
    seq = [int(r[0]) for r in sec.get("NODE_SEQUENCE_SECTION", []) if int(r[0]) > 0]
    return seq, head


# ---------------------------------------------------------------- independent checker
def _pairs(inst):
    out = {}
    for k, v in inst["travel_times"].items():
        a, b = [int(x) for x in _INT.findall(k)[:2]]
        out[(min(a, b), max(a, b))] = float(v)
    return out


def route_cost(inst, route, pairs=None):
    """Cost of a closed route given as a node list (depot first; closing edge added if needed)."""
    pairs = pairs or _pairs(inst)
    r = list(route)
    if r[0] != r[-1]:
        r = r + [r[0]]
    total = 0.0
    for a, b in zip(r[:-1], r[1:]):
        total += pairs[(min(a, b), max(a, b))]
    return total


def check_solution(inst, sol, pairs=None):
    """Return (ok, reason, objective, cost). Mirrors the documented fischetti1998 rules."""
    pairs = pairs or _pairs(inst)
    prizes = {int(_INT.findall(k)[0]): float(v) for k, v in inst["prizes"].items()}
    depot = int(inst["depot"])
    t0 = float(inst["t0"])
    for key in ("objective_value", "visited_nodes", "edges", "tour"):
        if key not in sol:
            return False, "missing " + key, None, None
    tour = [int(x) for x in sol["tour"]]
    if len(tour) < 2 or tour[0] != depot or tour[-1] != depot:
        return False, "tour must start and end at the depot", None, None
    inner = tour[1:-1]
    if depot in inner:
        return False, "depot repeated inside tour", None, None
    if len(set(inner)) != len(inner):
        return False, "city visited twice", None, None
    for v in tour:
        if v not in prizes and v != depot:
            return False, "unknown city %d" % v, None, None
    if len(set(tour)) < 3:
        return False, "fewer than three cities", None, None
    try:
        cost = route_cost(inst, tour, pairs)
    except KeyError as e:
        return False, "missing travel time %s" % (e,), None, None
    if cost > t0 + 1e-6:
        return False, "over budget %.3f > %.3f" % (cost, t0), None, cost
    want_edges = sorted((min(a, b), max(a, b)) for a, b in zip(tour[:-1], tour[1:]))
    got_edges = sorted((min(int(e[0]), int(e[1])), max(int(e[0]), int(e[1]))) for e in sol["edges"])
    if want_edges != got_edges:
        return False, "edges do not match tour", None, cost
    if sorted(set(int(v) for v in sol["visited_nodes"])) != sorted(set(tour)):
        return False, "visited_nodes do not match tour", None, cost
    obj = sum(prizes.get(v, 0.0) for v in set(tour))
    if abs(obj - float(sol["objective_value"])) > 1e-6:
        return False, "objective mismatch %s vs %s" % (sol["objective_value"], obj), obj, cost
    return True, "ok", obj, cost


# ---------------------------------------------------------------- exact solver for tiny instances
def exact_op(inst):
    """Held-Karp style DP; only for <= 12 cities. Returns the optimal prize."""
    pairs = _pairs(inst)
    prizes = {int(_INT.findall(k)[0]): float(v) for k, v in inst["prizes"].items()}
    depot = int(inst["depot"])
    others = sorted(v for v in prizes if v != depot)
    k = len(others)
    t0 = float(inst["t0"])

    def d(a, b):
        return 0.0 if a == b else pairs[(min(a, b), max(a, b))]

    INF = float("inf")
    dp = [[INF] * k for _ in range(1 << k)]
    for j in range(k):
        dp[1 << j][j] = d(depot, others[j])
    best = None
    for mask in range(1, 1 << k):
        for j in range(k):
            cur = dp[mask][j]
            if cur == INF or not (mask >> j) & 1:
                continue
            for nxt in range(k):
                if (mask >> nxt) & 1:
                    continue
                nm = mask | (1 << nxt)
                val = cur + d(others[j], others[nxt])
                if val < dp[nm][nxt]:
                    dp[nm][nxt] = val
    for mask in range(1, 1 << k):
        if bin(mask).count("1") < 2:
            continue
        close = min(dp[mask][j] + d(others[j], depot) for j in range(k) if (mask >> j) & 1)
        if close <= t0 + 1e-9:
            p = sum(prizes[others[j]] for j in range(k) if (mask >> j) & 1) + prizes.get(depot, 0.0)
            if best is None or p > best:
                best = p
    return best


def random_instance(seed, n=10, frac=0.35):
    rng = random.Random(seed)
    pts = {i: (rng.randint(0, 100), rng.randint(0, 100)) for i in range(1, n + 1)}
    prizes = {str(i): (0 if i == 1 else rng.randint(1, 20)) for i in pts}
    tt = {}
    for a, b in itertools.combinations(sorted(pts), 2):
        (xa, ya), (xb, yb) = pts[a], pts[b]
        tt["(%d,%d)" % (a, b)] = nint(math.hypot(xa - xb, ya - yb))
    total = sum(tt.values()) / (n - 1)
    return {"n": n, "depot": 1, "t0": int(total * frac * 2), "prizes": prizes, "travel_times": tt}


# ---------------------------------------------------------------- running the solver
def run_solver(inst, time_limit, problem="fischetti1998"):
    with tempfile.TemporaryDirectory() as td:
        ip = os.path.join(td, "instance.json")
        op = os.path.join(td, "solution.json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        t = time.time()
        try:
            cp = subprocess.run([sys.executable, SOLVER, "--problem", problem, "--instance", ip,
                                 "--output", op, "--time-limit", str(int(time_limit))],
                                cwd=os.path.dirname(SOLVER), capture_output=True, text=True,
                                timeout=time_limit + 30)
        except subprocess.TimeoutExpired:
            return None, time.time() - t, "timeout"
        wall = time.time() - t
        if cp.returncode != 0:
            return None, wall, "exit %d: %s" % (cp.returncode, cp.stderr[-500:])
        if not os.path.exists(op):
            return None, wall, "no output"
        with open(op, encoding="utf-8") as f:
            return json.load(f), wall, ""


def fetch(data_dir):
    root = os.path.join(data_dir, "oplib-" + OPLIB_SHA[:7])
    os.makedirs(root, exist_ok=True)
    got = 0
    for g in GENS:
        for name in NAMES:
            for rel in ("instances/gen%d/%s-gen%d-50.oplib" % (g, name, g),
                        "solutions/ea4op/gen%d/%s-gen%d-50.sol" % (g, name, g)):
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
                except Exception as e:  # missing files are recorded, not fatal
                    print("missing", rel, e)
                time.sleep(0.3)
    print("fetched", got, "files into", root)


def run(data_dir, out_dir, time_limit):
    root = os.path.join(data_dir, "oplib-" + OPLIB_SHA[:7])
    out = os.path.join(out_dir, "opeval")
    os.makedirs(out, exist_ok=True)
    rows = []
    # 1) exactness on tiny random instances (10 cities), 10 s limit each
    exact = []
    for seed in range(1, 13):
        inst = random_instance(seed)
        opt = exact_op(inst)
        sol, wall, err = run_solver(inst, 10)
        ok, why, obj, cost = (False, err, None, None) if sol is None else check_solution(inst, sol)
        exact.append({"seed": seed, "optimum": opt, "ours": obj, "feasible": ok, "why": why,
                      "wall_s": round(wall, 2), "matched": bool(ok and obj is not None and opt is not None
                                                                and abs(obj - opt) < 1e-9)})
        print("exact", exact[-1], flush=True)
    # 2) OPLib calibration
    for g in GENS:
        for name in NAMES:
            ipath = os.path.join(root, ("instances/gen%d/%s-gen%d-50.oplib" % (g, name, g)).replace("/", "__"))
            spath = os.path.join(root, ("solutions/ea4op/gen%d/%s-gen%d-50.sol" % (g, name, g)).replace("/", "__"))
            row = {"instance": "%s-gen%d-50" % (name, g), "gen": g}
            if not os.path.exists(ipath):
                row["skipped"] = "instance file missing"
                rows.append(row)
                continue
            with open(ipath, encoding="utf-8") as f:
                inst, info = oplib_to_frontieror(f.read())
            if inst is None:
                row["skipped"] = info
                rows.append(row)
                continue
            row.update({"n": info["n"], "t0": info["t0"]})
            pairs = _pairs(inst)
            prizes = {int(k): float(v) for k, v in inst["prizes"].items()}
            if os.path.exists(spath):
                with open(spath, encoding="utf-8") as f:
                    seq, sh = sol_route(f.read())
                try:
                    rc = route_cost(inst, seq, pairs)
                    row["ref_cost"] = rc
                    row["ref_valid"] = rc <= inst["t0"] + 1e-9 and len(set(seq)) == len(seq)
                    row["ref"] = sum(prizes.get(v, 0.0) for v in set(seq))
                    row["ref_file_score"] = sh.get("ROUTE_SCORE")
                except KeyError:
                    row["ref_valid"] = False
            sol, wall, err = run_solver(inst, time_limit)
            row["wall_s"] = round(wall, 2)
            row["overtime"] = wall > time_limit
            if sol is None:
                row.update({"feasible": False, "why": err})
            else:
                ok, why, obj, cost = check_solution(inst, sol, pairs)
                row.update({"feasible": ok, "why": why, "ours": obj, "cost": cost,
                            "visited": len(set(sol.get("tour", [])))})
                if ok and row.get("ref"):
                    row["ratio"] = round(obj / row["ref"], 5)
            print(json.dumps(row), flush=True)
            rows.append(row)
    scored = [r for r in rows if "ratio" in r and r.get("ref_valid")]
    tally = {
        "time_limit_s": time_limit,
        "instances_run": sum(1 for r in rows if "skipped" not in r),
        "skipped": [r["instance"] for r in rows if "skipped" in r],
        "infeasible": [r["instance"] for r in rows if "skipped" not in r and not r.get("feasible")],
        "overtime": [r["instance"] for r in rows if r.get("overtime")],
        "with_valid_reference": len(scored),
        "mean_ratio": round(sum(r["ratio"] for r in scored) / len(scored), 5) if scored else None,
        "min_ratio": min((r["ratio"] for r in scored), default=None),
        "matched_or_better": sum(1 for r in scored if r["ratio"] >= 1 - 1e-9),
        "better": sum(1 for r in scored if r["ratio"] > 1 + 1e-9),
        "exact_small_matched": sum(1 for e in exact if e["matched"]),
        "exact_small_total": len(exact),
    }
    with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"oplib_commit": OPLIB_SHA, "tally": tally, "exact_small": exact, "rows": rows}, f, indent=1)
    lines = ["# fischetti1998 (Orienteering Problem) solver: OPLib calibration", "",
             "MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.", "",
             "OPLib commit %s; reference = EA4OP route from OPLib, re-scored with depot prize 0 "
             "and re-costed with TSPLIB nint distances. Time limit %d s per instance, run as the "
             "FrontierOR sandbox does (subprocess, solve.py CLI)." % (OPLIB_SHA, time_limit), "",
             "## Tally", "", "```", json.dumps(tally, indent=1), "```", "",
             "## Per instance", "",
             "| instance | n | t0 | EA4OP ref | ours | ratio | feasible | wall s |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "skipped" in r:
            lines.append("| %s | | | | | | skipped: %s | |" % (r["instance"], r["skipped"]))
            continue
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["instance"], r.get("n"), r.get("t0"), r.get("ref"), r.get("ours"), r.get("ratio"),
            "yes" if r.get("feasible") else "NO (%s)" % r.get("why"), r.get("wall_s")))
    lines += ["", "## Exactness on 12 random 10-city instances (10 s each)", "",
              "| seed | optimum | ours | matched |", "|---|---|---|---|"]
    for e in exact:
        lines.append("| %d | %s | %s | %s |" % (e["seed"], e["optimum"], e["ours"], e["matched"]))
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

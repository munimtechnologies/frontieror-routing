#!/usr/bin/env python3
"""Calibrate MV2's cordeau2006 (DARP) solver on the public Cordeau (2006) a/b instances.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

The 42 instances (a2-16 ... a8-96, b2-16 ... b8-96; the Ropke et al. 2007 additions a3-18, a4-16, a4-24 are not in
this copy) are downloaded at run time from github.com/garciparedes/jinete (MIT) at a pinned commit and are not
redistributed; only our own numbers are published. Reference values: the optimal/best known values compiled by Ho et
al. (2018, Transportation Research Part B 111, "A survey of dial-a-ride problems"), as listed in the README of
github.com/sywang-20/darp-benchmark; they use unrounded Euclidean distances, as cordeau2006 does.

Usage:
    python darp_eval.py fetch --data-dir /data
    python darp_eval.py run --data-dir /data --out-dir /out [--time-limit 60]

Each file is converted to the FrontierOR cordeau2006 JSON schema (origin depot 0, pickups 1..n, drop-offs n+1..2n,
destination depot 2n+1 = copy of the depot row; user ids 1..n; windows as given in the file) and solved by running
cordeau2006/solve.py as a subprocess, as the FrontierOR sandbox invokes it. Every solution is checked by the
independent checker in this file, which re-derives nothing from the solver: it reads the written service times.

v2 (2026-11-10): the host that runs these jobs sometimes freezes the container for minutes. A heartbeat thread in the
harness measures the longest gap between its 0.25 s ticks during each solver call; a gap above 5 s means the call
was frozen, and the instance is solved again (at most 3 attempts in all). Every attempt is recorded. The v1 column
holds the v0.1.0 solver's results from job froc-darp-cordeau-v1.
"""
import argparse
import hashlib
import itertools
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SOLVER = os.path.join(HERE, "cordeau2006", "solve.py")
JINETE_SHA = "e9ee6c808ccf04765cf04d194b8f9da277dcfb03"
RAW = "https://raw.githubusercontent.com/garciparedes/jinete/%s/res/datasets/cordeau-laporte/%s.txt"
UA = "MV2 of Munim, Inc. DARP solver calibration (mv2@munimtech.com)"
SIZES = [(2, 16), (2, 20), (2, 24), (3, 24), (3, 30), (3, 36), (4, 32), (4, 40), (4, 48), (5, 40), (5, 50),
         (5, 60), (6, 48), (6, 60), (6, 72), (7, 56), (7, 70), (7, 84), (8, 64), (8, 80), (8, 96)]
NAMES = ["%s%d-%d" % (s, m, n) for s in "ab" for m, n in SIZES]
REF = {  # Ho et al. (2018) table as listed in the sywang-20/darp-benchmark README (read 2026-11-09)
    "a2-16": 294.25, "a2-20": 344.83, "a2-24": 431.12, "a3-24": 344.83, "a3-30": 494.85, "a3-36": 583.19,
    "a4-32": 485.5, "a4-40": 557.69, "a4-48": 668.82, "a5-40": 498.41, "a5-50": 686.62, "a5-60": 808.42,
    "a6-48": 604.12, "a6-60": 819.25, "a6-72": 916.05, "a7-56": 724.04, "a7-70": 889.12, "a7-84": 1033.37,
    "a8-64": 747.46, "a8-80": 945.73, "a8-96": 1229.66,
    "b2-16": 309.41, "b2-20": 332.64, "b2-24": 444.71, "b3-24": 394.51, "b3-30": 531.44, "b3-36": 603.79,
    "b4-32": 494.82, "b4-40": 656.63, "b4-48": 673.81, "b5-40": 613.72, "b5-50": 761.4, "b5-60": 902.04,
    "b6-48": 714.83, "b6-60": 860.07, "b6-72": 978.47, "b7-56": 823.97, "b7-70": 912.62, "b7-84": 1203.37,
    "b8-64": 839.89, "b8-80": 1036.34, "b8-96": 1185.55,
}
V1 = {  # v0.1.0 results (job froc-darp-cordeau-v1, 2026-11-09, 60 s); None = infeasible (users left unserved)
    "a2-16": None, "a2-20": 344.83, "a2-24": None, "a3-24": 349.43, "a3-30": 510.87, "a3-36": None,
    "a4-32": 491.21, "a4-40": None, "a4-48": 691.08, "a5-40": 515.01, "a5-50": 700.08, "a5-60": 819.96,
    "a6-48": 618.35, "a6-60": 844.52, "a6-72": 962.3, "a7-56": 757.79, "a7-70": 952.38, "a7-84": 1112.39,
    "a8-64": 776.8, "a8-80": 999.31, "a8-96": 1304.9,
    "b2-16": 309.41, "b2-20": None, "b2-24": 444.71, "b3-24": 398.07, "b3-30": None, "b3-36": 612.74,
    "b4-32": 503.01, "b4-40": 661.14, "b4-48": None, "b5-40": 622.19, "b5-50": 773.24, "b5-60": None,
    "b6-48": 716.9, "b6-60": 883.41, "b6-72": 1011.87, "b7-56": 840.74, "b7-70": 942.53, "b7-84": 1252.66,
    "b8-64": 851.58, "b8-80": 1074.07, "b8-96": 1238.04,
}
V1_TINY_OPTIMAL = {1, 3, 4, 5, 7, 8, 9, 10, 11, 12}
TOL = 1e-6
PAUSE_GAP_S = 5.0
MAX_ATTEMPTS = 3


# ---------------------------------------------------------------- Cordeau text format
def parse_cordeau(text):
    """Cordeau DARP text -> FrontierOR cordeau2006 instance dict.

    Header: m, n or 2n, T, Q, L. Rows: id x y service load earliest latest, depot first; the end depot row
    (id 2n+1) may or may not be present."""
    lines = [ln.strip().strip('"') for ln in text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    head = lines[0].split()
    m, h, T, Q, L = int(head[0]), int(head[1]), float(head[2]), float(head[3]), float(head[4])
    rows = [ln.split() for ln in lines[1:]]
    R = len(rows)
    if R in (2 * h + 1, 2 * h + 2):
        n = h
    elif R in (h + 1, h + 2) and h % 2 == 0:
        n = h // 2
    else:
        raise ValueError("cannot tell n from header %s and %d rows" % (head, R))
    rows = rows[:2 * n + 1]
    nodes = []

    def node(nid, r, ntype, user=None, paired=None, rtype=None):
        d = {"node_id": nid, "x": float(r[1]), "y": float(r[2]), "service_duration": float(r[3]),
             "load": float(r[4]), "earliest_time": float(r[5]), "latest_time": float(r[6]), "node_type": ntype}
        if user is not None:
            d.update({"user_id": user, "paired_node": paired, "request_type": rtype})
        return d

    for i in range(2 * n + 1):
        r = rows[i]
        if int(r[0]) != i:
            raise ValueError("row %d has id %s" % (i, r[0]))
    for i in range(2 * n + 1):
        r = rows[i]
        if i == 0:
            nodes.append(node(0, r, "origin_depot"))
        elif i <= n:
            rd = rows[i + n]
            wide_p = float(r[6]) - float(r[5])
            wide_d = float(rd[6]) - float(rd[5])
            nodes.append(node(i, r, "pickup", i, i + n, "outbound" if wide_p > wide_d else "inbound"))
        else:
            rp = rows[i - n]
            wide_p = float(rp[6]) - float(rp[5])
            wide_d = float(r[6]) - float(r[5])
            nodes.append(node(i, r, "dropoff", i - n, i - n, "outbound" if wide_p > wide_d else "inbound"))
    end = dict(nodes[0])
    end.update({"node_id": 2 * n + 1, "node_type": "destination_depot"})
    nodes.append(end)
    inst = {"num_vehicles": m, "num_users": n, "vehicle_capacity": Q, "maximum_ride_time": L,
            "num_nodes": 2 * n + 2, "nodes": nodes, "maximum_route_duration": T}
    return inst


# ---------------------------------------------------------------- independent checker
def check(inst, sol, vehicle_base=0):
    """Return (ok, reason, objective). Mirrors the cordeau2006 rules on the FrontierOR problem page."""
    nodes = {int(r["node_id"]): r for r in inst["nodes"]}
    n = int(inst["num_users"])
    N = 2 * n + 2
    Q = float(inst["vehicle_capacity"])
    L = float(inst["maximum_ride_time"])
    T = float(inst["maximum_route_duration"])

    def dist(a, b):
        return math.sqrt((nodes[a]["x"] - nodes[b]["x"]) ** 2 + (nodes[a]["y"] - nodes[b]["y"]) ** 2)

    for key in ("objective_value", "routes", "service_times", "ride_times"):
        if key not in sol:
            return False, "missing %s" % key, None
    routes = sol["routes"]
    if len(routes) > int(inst["num_vehicles"]):
        return False, "more routes than vehicles", None
    st = sol["service_times"]
    seen = {}
    total = 0.0
    for vk, rt in routes.items():
        rt = [int(v) for v in rt]
        if len(rt) < 2 or rt[0] != 0 or rt[-1] != N - 1:
            return False, "route %s does not run from 0 to %d" % (vk, N - 1), None
        try:
            v = int(vk)
        except ValueError:
            return False, "vehicle key %r" % vk, None
        if not vehicle_base <= v < vehicle_base + int(inst["num_vehicles"]):
            return False, "vehicle key %r out of range" % vk, None
        times = []
        for idx, node in enumerate(rt):
            if idx == 0:
                key = "depot_start_%s" % vk
            elif idx == len(rt) - 1:
                key = "depot_end_%s" % vk
            else:
                key = str(node)
                if node in (0, N - 1) or not 1 <= node <= 2 * n:
                    return False, "bad node %d in route %s" % (node, vk), None
                if node in seen:
                    return False, "node %d visited twice" % node, None
                seen[node] = vk
            if key not in st:
                return False, "no service time for %s" % key, None
            times.append(float(st[key]))
        load = 0.0
        for idx, node in enumerate(rt):
            r = nodes[node]
            b = times[idx]
            if b < float(r["earliest_time"]) - TOL or b > float(r["latest_time"]) + TOL:
                return False, "node %d served at %.6f outside [%s, %s]" % (node, b, r["earliest_time"],
                                                                         r["latest_time"]), None
            if idx > 0:
                p = rt[idx - 1]
                need = times[idx - 1] + float(nodes[p]["service_duration"]) + dist(p, node)
                if b < need - TOL:
                    return False, "node %d starts %.6f before %.6f" % (node, b, need), None
                total += dist(p, node)
            load += float(r["load"]) if 0 < idx < len(rt) - 1 else 0.0
            if load < -TOL or load > Q + TOL:
                return False, "load %.3f after node %d" % (load, node), None
        if times[-1] - times[0] > T + TOL:
            return False, "route %s lasts %.6f > %s" % (vk, times[-1] - times[0], T), None
        pos = {node: idx for idx, node in enumerate(rt)}
        for node in rt[1:-1]:
            if nodes[node]["node_type"] == "pickup":
                d = int(nodes[node]["paired_node"])
                if d not in pos:
                    return False, "user of node %d dropped by another vehicle" % node, None
                if pos[d] < pos[node]:
                    return False, "drop-off before pickup for node %d" % node, None
                ride = times[pos[d]] - (times[pos[node]] + float(nodes[node]["service_duration"]))
                if ride > L + TOL or ride < dist(node, d) - TOL:
                    return False, "ride time %.6f of user at node %d" % (ride, node), None
                uk = str(nodes[node]["user_id"])
                if uk not in sol["ride_times"] or abs(float(sol["ride_times"][uk]) - ride) > 1e-5:
                    return False, "ride_times[%s] does not match the service times" % uk, None
    missing = [v for v in range(1, 2 * n + 1) if v not in seen]
    if missing:
        return False, "%d nodes not visited" % len(missing), None
    if abs(total - float(sol["objective_value"])) > 1e-6 * max(1.0, abs(total)):
        return False, "objective mismatch %s vs %s" % (sol["objective_value"], total), total
    return True, "ok", total


# ---------------------------------------------------------------- exact solver for tiny instances
def route_feasible(inst, seq):
    """Bellman-Ford on the route's difference constraints (independent of the solver's method)."""
    nodes = {int(r["node_id"]): r for r in inst["nodes"]}
    n = int(inst["num_users"])
    full = [0] + list(seq) + [2 * n + 1]
    k = len(full)
    src = k
    edges = []  # (u, v, w): x_v - x_u <= w

    def dist(a, b):
        return math.sqrt((nodes[a]["x"] - nodes[b]["x"]) ** 2 + (nodes[a]["y"] - nodes[b]["y"]) ** 2)

    for idx, node in enumerate(full):
        r = nodes[node]
        edges.append((src, idx, float(r["latest_time"])))
        edges.append((idx, src, -float(r["earliest_time"])))
        if idx > 0:
            p = full[idx - 1]
            edges.append((idx, idx - 1, -(float(nodes[p]["service_duration"]) + dist(p, node))))
    pos = {node: idx for idx, node in enumerate(full)}
    for node in seq:
        r = nodes[node]
        if r["node_type"] == "pickup":
            d = int(r["paired_node"])
            if d not in pos or pos[d] < pos[node]:
                return False
            edges.append((pos[node], pos[d], float(r["service_duration"]) + float(inst["maximum_ride_time"])))
    edges.append((0, k - 1, float(inst["maximum_route_duration"])))
    D = [0.0] * (k + 1)
    for _ in range(k + 1):
        changed = False
        for u, v, w in edges:
            if D[u] + w < D[v] - 1e-12:
                D[v] = D[u] + w
                changed = True
        if not changed:
            return True
    return False


def exact(inst):
    """Optimal DARP cost by enumeration (<= 4 users)."""
    nodes = {int(r["node_id"]): r for r in inst["nodes"]}
    n = int(inst["num_users"])
    m = int(inst["num_vehicles"])
    Q = float(inst["vehicle_capacity"])
    if n > 4:
        raise ValueError("too many users for the exact solver")

    def dist(a, b):
        return math.sqrt((nodes[a]["x"] - nodes[b]["x"]) ** 2 + (nodes[a]["y"] - nodes[b]["y"]) ** 2)

    best_route = {}
    for size in range(0, n + 1):
        for users in itertools.combinations(range(1, n + 1), size):
            best = math.inf if users else 0.0
            if users:
                stops = list(users) + [u + n for u in users]
                for perm in itertools.permutations(stops):
                    pos = {v: i for i, v in enumerate(perm)}
                    if any(pos[u] > pos[u + n] for u in users):
                        continue
                    load, ok = 0.0, True
                    for v in perm:
                        load += float(nodes[v]["load"])
                        if load > Q + 1e-9:
                            ok = False
                            break
                    if not ok:
                        continue
                    full = [0] + list(perm) + [2 * n + 1]
                    c = sum(dist(a, b) for a, b in zip(full[:-1], full[1:]))
                    if c < best and route_feasible(inst, perm):
                        best = c
            best_route[frozenset(users)] = best
    best = math.inf
    for assign in itertools.product(range(m), repeat=n):
        groups = [frozenset(u for u, a in zip(range(1, n + 1), assign) if a == k) for k in range(m)]
        c = sum(best_route[g] for g in groups)
        if c < best:
            best = c
    return best


def random_instance(seed, n, m=2, horizon=120.0):
    """Cordeau-style tiny instance: half outbound (window at drop-off), half inbound (window at pickup)."""
    rng = random.Random(seed)
    Q, L = 3, 30.0
    xy = [(0.0, 0.0)] + [(round(rng.uniform(-10, 10), 3), round(rng.uniform(-10, 10), 3)) for _ in range(2 * n)]
    nodes = [{"node_id": 0, "x": 0.0, "y": 0.0, "earliest_time": 0.0, "latest_time": horizon,
              "service_duration": 0.0, "load": 0.0, "node_type": "origin_depot"}]
    win = {}
    for u in range(1, n + 1):
        a = float(rng.randint(10, int(horizon) - 40))
        win[u] = (a, a + 15.0)
    for u in range(1, n + 1):
        out = u <= n // 2
        e, l = win[u] if not out else (0.0, horizon)
        nodes.append({"node_id": u, "x": xy[u][0], "y": xy[u][1], "earliest_time": e, "latest_time": l,
                      "service_duration": 3.0, "load": 1.0, "node_type": "pickup", "user_id": u,
                      "paired_node": u + n, "request_type": "outbound" if out else "inbound"})
    for u in range(1, n + 1):
        out = u <= n // 2
        e, l = win[u] if out else (0.0, horizon)
        nodes.append({"node_id": u + n, "x": xy[u + n][0], "y": xy[u + n][1], "earliest_time": e,
                      "latest_time": l, "service_duration": 3.0, "load": -1.0, "node_type": "dropoff",
                      "user_id": u, "paired_node": u, "request_type": "outbound" if out else "inbound"})
    end = dict(nodes[0])
    end.update({"node_id": 2 * n + 1, "node_type": "destination_depot"})
    nodes.append(end)
    return {"num_vehicles": m, "num_users": n, "vehicle_capacity": Q, "maximum_ride_time": L,
            "num_nodes": 2 * n + 2, "nodes": nodes, "maximum_route_duration": horizon}


# ---------------------------------------------------------------- running the solver
class Heartbeat:
    """Longest gap between 0.25 s ticks while active; a frozen container shows up as one long gap."""

    def __init__(self, tick=0.25):
        self.tick = tick
        self.max_gap = 0.0
        self._stop = threading.Event()
        self._t = None

    def _run(self):
        last = time.monotonic()
        while not self._stop.wait(self.tick):
            now = time.monotonic()
            if now - last > self.max_gap:
                self.max_gap = now - last
            last = now

    def __enter__(self):
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(2.0)
        return False


def run_solver(inst, time_limit, extra=()):
    with tempfile.TemporaryDirectory() as td:
        ip = os.path.join(td, "instance.json")
        op = os.path.join(td, "solution.json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        cmd = [sys.executable, SOLVER, "--problem", "cordeau2006", "--instance", ip, "--output", op,
               "--time-limit", str(int(time_limit))] + list(extra)
        t = time.time()
        try:
            cp = subprocess.run(cmd, cwd=os.path.dirname(SOLVER), capture_output=True, text=True,
                                timeout=time_limit + 60)
        except subprocess.TimeoutExpired:
            return None, time.time() - t, "timeout", {}
        wall = time.time() - t
        stats = {}
        for line in cp.stderr.splitlines():
            if "DARP_SOLVER_STATS " in line:
                try:
                    stats = json.loads(line.split("DARP_SOLVER_STATS ", 1)[1])
                except ValueError:
                    pass
        if cp.returncode != 0:
            return None, wall, "exit %d: %s" % (cp.returncode, cp.stderr[-500:]), stats
        if not os.path.exists(op):
            return None, wall, "no output", stats
        with open(op, encoding="utf-8") as f:
            return json.load(f), wall, "", stats


def solve_and_check(inst, limit, extra=(), max_attempts=MAX_ATTEMPTS):
    attempts = []
    for _ in range(max_attempts):
        with Heartbeat() as hb:
            sol, wall, err, stats = run_solver(inst, limit, extra)
        paused = hb.max_gap > PAUSE_GAP_S
        attempts.append({"wall_s": round(wall, 2), "max_gap_s": round(hb.max_gap, 2), "paused": paused})
        if not paused:
            break
    out = {"wall_s": round(wall, 2), "overtime": wall > limit - 1.0, "stats": stats, "attempts": attempts,
           "paused": attempts[-1]["paused"]}
    if sol is None:
        out.update({"feasible": False, "why": err})
        return out
    ok, why, obj = check(inst, sol)
    out.update({"feasible": ok, "why": why, "objective": obj, "routes": len(sol.get("routes", {}))})
    return out


def fetch(data_dir):
    root = os.path.join(data_dir, "cordeau-jinete-" + JINETE_SHA[:7])
    os.makedirs(root, exist_ok=True)
    got, sums = 0, {}
    for name in NAMES:
        dest = os.path.join(root, name + ".txt")
        if not (os.path.exists(dest) and os.path.getsize(dest) > 0):
            for ref in (JINETE_SHA, "master"):
                req = urllib.request.Request(RAW % (ref, name), headers={"User-Agent": UA})
                try:
                    with urllib.request.urlopen(req, timeout=60) as r:
                        data = r.read()
                    with open(dest, "wb") as f:
                        f.write(data)
                    if ref != JINETE_SHA:
                        print("fetched", name, "from", ref, "(pinned commit failed)")
                    break
                except Exception as e:  # recorded, not fatal
                    print("missing", name, ref, e)
            time.sleep(0.3)
        if os.path.exists(dest):
            got += 1
            with open(dest, "rb") as f:
                sums[name] = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(root, "sha256.json"), "w", encoding="utf-8") as f:
        json.dump(sums, f, indent=1)
    print("fetched", got, "files into", root)


def load(root, name):
    path = os.path.join(root, name + ".txt")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return parse_cordeau(f.read())


def run(data_dir, out_dir, limit, tiny_limit=5, names=None):
    root = os.path.join(data_dir, "cordeau-jinete-" + JINETE_SHA[:7])
    out = os.path.join(out_dir, "darp")
    os.makedirs(out, exist_ok=True)
    sums = {}
    if os.path.exists(os.path.join(root, "sha256.json")):
        with open(os.path.join(root, "sha256.json"), encoding="utf-8") as f:
            sums = json.load(f)
    res = {"jinete_commit": JINETE_SHA, "time_limit_s": limit, "tiny": [], "rows": []}

    def save():
        with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)

    # 1) tiny instances against the exact optimum
    for seed in range(1, 13):
        n = 3 if seed <= 6 else 4
        inst = random_instance(seed, n)
        t = time.time()
        opt = exact(inst)
        row = {"seed": seed, "n": n, "optimum": opt, "exact_s": round(time.time() - t, 2),
               "v1_optimal": seed in V1_TINY_OPTIMAL}
        r = solve_and_check(inst, tiny_limit)
        if math.isinf(opt):
            r["optimal"] = not r.get("feasible")
        else:
            r["optimal"] = bool(r.get("feasible") and abs(r["objective"] - opt) < 1e-6)
        row["solver"] = r
        print("tiny", json.dumps(row), flush=True)
        res["tiny"].append(row)
        save()
    # 2) the Cordeau (2006) a/b instances
    for name in (names or NAMES):
        inst = load(root, name)
        row = {"instance": name, "sha256": sums.get(name), "v1": V1.get(name)}
        if inst is None:
            row["skipped"] = "file missing"
            res["rows"].append(row)
            continue
        maxl = max(float(r["latest_time"]) for r in inst["nodes"] if r["node_type"] in ("pickup", "dropoff"))
        row.update({"n": inst["num_users"], "m": inst["num_vehicles"], "Q": inst["vehicle_capacity"],
                    "L": inst["maximum_ride_time"], "T": inst["maximum_route_duration"],
                    "depot_window": [inst["nodes"][0]["earliest_time"], inst["nodes"][0]["latest_time"]],
                    "max_user_latest": maxl, "reference": REF.get(name)})
        r = solve_and_check(inst, limit)
        row["run"] = r
        if r.get("feasible") and row["reference"]:
            row["gap_pct"] = round(100.0 * (r["objective"] - row["reference"]) / row["reference"], 3)
        if r.get("feasible") and row["v1"]:
            row["v2_over_v1"] = round(r["objective"] / row["v1"], 5)
        print("row", json.dumps(row), flush=True)
        res["rows"].append(row)
        save()
    rows = [r for r in res["rows"] if "skipped" not in r]

    def gaps(prefix):
        return [r["gap_pct"] for r in rows if r["instance"].startswith(prefix) and "gap_pct" in r]

    ga, gb = gaps("a"), gaps("b")
    both = [r for r in rows if "v2_over_v1" in r]
    tally = {
        "solver_version": "0.2.0",
        "instances_run": len(rows),
        "skipped": [r["instance"] for r in res["rows"] if "skipped" in r],
        "infeasible": [r["instance"] for r in rows if not r["run"].get("feasible")],
        "why_infeasible": {r["instance"]: r["run"].get("why") for r in rows if not r["run"].get("feasible")},
        "overtime": [r["instance"] for r in rows if r["run"].get("overtime")],
        "paused_attempts": sum(sum(1 for a in r["run"]["attempts"] if a["paused"]) for r in rows)
        + sum(sum(1 for a in t["solver"]["attempts"] if a["paused"]) for t in res["tiny"]),
        "still_paused": [r["instance"] for r in rows if r["run"].get("paused")],
        "max_wall_s": max((r["run"].get("wall_s", 0) for r in rows), default=None),
        "a_count": len(ga), "a_mean_gap_pct": round(sum(ga) / len(ga), 3) if ga else None,
        "a_within_0_1_pct": sum(1 for g in ga if g <= 0.1),
        "b_count": len(gb), "b_mean_gap_pct": round(sum(gb) / len(gb), 3) if gb else None,
        "b_within_0_1_pct": sum(1 for g in gb if g <= 0.1),
        "below_reference": [r["instance"] for r in rows if r.get("gap_pct") is not None and r["gap_pct"] < -0.005],
        "tiny_optimal": sum(1 for t in res["tiny"] if t["solver"].get("optimal")),
        "tiny_total": len(res["tiny"]),
        "v1_compared": len(both),
        "v2_better_than_v1": sum(1 for r in both if r["v2_over_v1"] < 1 - 1e-6),
        "v2_worse_than_v1": sum(1 for r in both if r["v2_over_v1"] > 1 + 1e-6),
        "mean_v2_over_v1": round(sum(r["v2_over_v1"] for r in both) / len(both), 5) if both else None,
        "full_checks_used": sum(1 for r in rows if any(r["run"].get("stats", {}).get("full_checks") or [0])),
        "workers_used": sorted(set(str(r["run"].get("stats", {}).get("workers")) for r in rows)),
        "pool_errors": sorted(set(str(r["run"].get("stats", {}).get("pool_error")) for r in rows
                                  if r["run"].get("stats", {}).get("pool_error"))),
    }
    res["tally"] = tally
    save()
    lines = ["# cordeau2006 (DARP) solver v0.2.0: calibration on the Cordeau (2006) a/b instances", "",
             "MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.", "",
             "Instances: Cordeau (2006) a and b sets as published in github.com/garciparedes/jinete (MIT) at commit "
             "%s (not redistributed here), converted to the FrontierOR cordeau2006 schema. Reference = optimal or "
             "best known value from Ho et al. (2018) as listed in github.com/sywang-20/darp-benchmark. Each run is a "
             "subprocess call of solve.py exactly as the FrontierOR sandbox invokes it (%d s, 2 workers); every "
             "solution is re-checked by an independent checker that reads the written service times. A solver call "
             "during which the container was frozen (heartbeat gap > %.0f s) is re-run, at most %d attempts. "
             "v1 = the v0.1.0 solver (job froc-darp-cordeau-v1)." % (JINETE_SHA, limit, PAUSE_GAP_S, MAX_ATTEMPTS),
             "", "## Tally", "", "```", json.dumps(tally, indent=1), "```", "",
             "## Per instance", "",
             "| instance | n | m | v2 | v1 | reference | gap % | v2/v1 | wall s | attempts | iterations (per worker) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in res["rows"]:
        if "skipped" in r:
            lines.append("| %s | | | skipped: %s | | | | | | | |" % (r["instance"], r["skipped"]))
            continue
        obj = r["run"].get("objective")
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["instance"], r["n"], r["m"], round(obj, 2) if r["run"].get("feasible") else
            "NO: %s" % r["run"].get("why"), r["v1"] if r["v1"] is not None else "NO", r["reference"],
            r.get("gap_pct"), r.get("v2_over_v1"), r["run"].get("wall_s"), len(r["run"]["attempts"]),
            r["run"].get("stats", {}).get("iterations")))
    lines += ["", "## Tiny random instances vs exact optimum (%d s each)" % tiny_limit, "",
              "| seed | users | optimum | v2 | v2 optimal | v1 optimal |", "|---|---|---|---|---|---|"]
    for t in res["tiny"]:
        lines.append("| %d | %d | %s | %s | %s | %s |" % (t["seed"], t["n"], t["optimum"],
                                                         t["solver"].get("objective"), t["solver"].get("optimal"),
                                                         t["v1_optimal"]))
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

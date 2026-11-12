"""Tests for MV2's ropke2009 (PDPTW) solver. MV2 of Munim, Inc.; made with AI agents working in MV2's name.
License: Apache-2.0.

  python -m unittest -v test_ropke2009

If the official FrontierOR checker is present (env ROPKE_CHECKER, or /data/hf/tasks/ropke2009/feasibility_check.py),
the tests also run it on our solutions; otherwise those tests are skipped.
"""
import importlib.util
import itertools
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import solve as S  # noqa: E402


def gen(n, K, seed, Q=10, H=600.0, width=60.0, svc=5):
    """Synthetic PDPTW instance in the FrontierOR ropke2009 schema; every request is feasible alone."""
    rng = random.Random(seed)
    depot = (25.0, 25.0)
    P = [(rng.uniform(0, 50), rng.uniform(0, 50)) for _ in range(n)]
    D = [(rng.uniform(0, 50), rng.uniform(0, 50)) for _ in range(n)]

    def dist(u, v):
        return math.sqrt((u[0] - v[0]) ** 2 + (u[1] - v[1]) ** 2)
    nodes = [{"id": 0, "type": "depot_origin", "x": depot[0], "y": depot[1], "demand": 0, "service_time": 0,
              "time_window": [0.0, H]}]
    pw, dw, loads = [], [], []
    for r in range(n):
        ap = dist(depot, P[r]) + rng.uniform(0, H * 0.5)
        ad = ap + svc + dist(P[r], D[r]) + rng.uniform(0, 30)
        if ad + width + svc + dist(D[r], depot) > H:
            shift = ad + width + svc + dist(D[r], depot) - H
            ap -= shift
            ad -= shift
        ap = max(ap, dist(depot, P[r]))
        pw.append([round(ap, 3), round(ap + width, 3)])
        dw.append([round(ad, 3), round(ad + width, 3)])
        loads.append(rng.randint(1, max(1, Q // 2)))
    for r in range(n):
        nodes.append({"id": r + 1, "type": "pickup", "x": P[r][0], "y": P[r][1], "demand": loads[r],
                      "service_time": svc, "time_window": pw[r], "pair": n + r + 1})
    for r in range(n):
        nodes.append({"id": n + r + 1, "type": "delivery", "x": D[r][0], "y": D[r][1], "demand": -loads[r],
                      "service_time": svc, "time_window": dw[r], "pair": r + 1})
    nodes.append({"id": 2 * n + 1, "type": "depot_destination", "x": depot[0], "y": depot[1], "demand": 0,
                  "service_time": 0, "time_window": [0.0, H]})
    reqs = [{"request_id": r + 1, "pickup_node": r + 1, "delivery_node": n + r + 1, "load": loads[r],
             "pickup_coord": list(P[r]), "delivery_coord": list(D[r]), "pickup_time_window": pw[r],
             "delivery_time_window": dw[r], "travel_time_pickup_to_delivery": dist(P[r], D[r])} for r in range(n)]
    return {"num_requests": n, "num_nodes": 2 * n + 2, "num_vehicles": K, "vehicle_capacity": Q,
            "planning_horizon": H, "fixed_cost_per_vehicle": 0,
            "objective": {"primary": "min distance", "secondary": "none"},
            "depot": {"x": depot[0], "y": depot[1], "time_window": [0.0, H]}, "requests": reqs, "nodes": nodes}


def route_cost(pb, s):
    return sum(pb.dist[s[k]][s[k + 1]] for k in range(len(s) - 1))


def brute_insert(pb, s, r):
    """All (i <= j) positions by building the route and checking it from scratch."""
    best = (S.INF, -1, -1)
    base = route_cost(pb, s)
    for i in range(len(s) - 1):
        for j in range(i, len(s) - 1):
            t = list(s)
            t.insert(j + 1, pb.n + r)
            t.insert(i + 1, r)
            if pb.route_feasible(t):
                c = route_cost(pb, t) - base
                if c < best[0] - 1e-12:
                    best = (c, i, j)
    return best


def brute_optimum(pb):
    """Exact optimum for tiny instances: best route per request subset, then best partition into <= K routes."""
    n = pb.n
    best_sub = {}
    for size in range(1, n + 1):
        for sub in itertools.combinations(range(1, n + 1), size):
            nodes = list(sub) + [n + r for r in sub]
            bc = S.INF
            for perm in itertools.permutations(nodes):
                pos = {v: k for k, v in enumerate(perm)}
                if any(pos[r] > pos[n + r] for r in sub):
                    continue
                s = [pb.o] + list(perm) + [pb.e]
                if pb.route_feasible(s):
                    c = route_cost(pb, s)
                    if c < bc:
                        bc = c
            best_sub[frozenset(sub)] = bc
    full = frozenset(range(1, n + 1))
    memo = {}

    def part(rest, k):
        if not rest:
            return 0.0
        if k == 0:
            return S.INF
        key = (rest, k)
        if key in memo:
            return memo[key]
        first = min(rest)
        others = sorted(rest - {first})
        bv = S.INF
        for size in range(0, len(others) + 1):
            for comb in itertools.combinations(others, size):
                sub = frozenset((first,) + comb)
                c = best_sub[sub]
                if c < S.INF:
                    v = c + part(rest - sub, k - 1)
                    if v < bv:
                        bv = v
        memo[key] = bv
        return bv
    return part(full, pb.K)


def official_checker():
    p = os.environ.get("ROPKE_CHECKER") or "/data/hf/tasks/ropke2009/feasibility_check.py"
    if not os.path.exists(p):
        return None
    spec = importlib.util.spec_from_file_location("ropke_official", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Insertion(unittest.TestCase):
    def test_matches_brute_force(self):
        checked = 0
        for seed in range(30):
            inst = gen(8, 3, seed, width=40.0 + 10 * (seed % 5))
            pb = S.Problem(inst)
            rng = random.Random(seed)
            order = list(range(1, pb.n + 1))
            rng.shuffle(order)
            s = [pb.o, pb.e]
            placed = []
            for r in order[:5]:
                c, i, j = brute_insert(pb, s, r)
                if c < S.INF:
                    s.insert(j + 1, pb.n + r)
                    s.insert(i + 1, r)
                    placed.append(r)
            R = S.Route(pb, list(s))
            self.assertAlmostEqual(R.cost, route_cost(pb, s), places=9)
            for r in order:
                if r in placed:
                    continue
                want = brute_insert(pb, s, r)
                got = S.best_insertion(pb, R, r)
                if want[0] == S.INF:
                    self.assertEqual(got[0], S.INF, "seed %d r %d: brute says infeasible" % (seed, r))
                else:
                    self.assertLess(got[0], S.INF, "seed %d r %d: missed a feasible insertion" % (seed, r))
                    self.assertAlmostEqual(got[0], want[0], places=9)
                    t = list(s)
                    t.insert(got[2] + 1, pb.n + r)
                    t.insert(got[1] + 1, r)
                    self.assertTrue(pb.route_feasible(t))
                    self.assertAlmostEqual(route_cost(pb, t) - route_cost(pb, s), got[0], places=9)
                checked += 1
        self.assertGreater(checked, 50)

    def test_solo_cost(self):
        pb = S.Problem(gen(5, 5, 3))
        for r in range(1, 6):
            R = S.Route(pb, [pb.o, pb.e])
            self.assertAlmostEqual(S.best_insertion(pb, R, r)[0], pb.solo[r], places=9)


class Search(unittest.TestCase):
    def test_reaches_brute_force_optimum(self):
        hits, report = 0, []
        for seed in (11, 12, 13):
            inst = gen(4, 4, seed, width=80.0)
            pb = S.Problem(inst)
            opt = brute_optimum(pb)
            self.assertLess(opt, S.INF)
            with tempfile.TemporaryDirectory() as d:
                out = os.path.join(d, "sol.json")
                S.T_START = time.monotonic()
                obj, log = S.solve(inst, out, 6.0, seed=seed, workers=1)
                with open(out, encoding="utf-8") as f:
                    sol = json.load(f)
            self.assertIsNotNone(obj)
            self.assertTrue(S.verify(pb, [x["nodes"] for x in sol["routes"]])[0])
            self.assertGreaterEqual(sol["objective_value"], opt - 1e-6, "below the brute-force optimum?")
            report.append((seed, opt, sol["objective_value"]))
            if sol["objective_value"] <= opt + 1e-6:
                hits += 1
        print("brute-force optimum vs ours:", report)
        self.assertGreaterEqual(hits, 2, report)

    def test_verify_rejects_bad(self):
        inst = gen(6, 6, 5)
        pb = S.Problem(inst)
        st = S.construct(pb, random.Random(1))
        self.assertFalse(st.unassigned)
        routes = st.copy_routes()
        self.assertTrue(S.verify(pb, routes)[0])
        bad = [list(s) for s in routes]
        for s in bad:
            if len(s) > 2:
                r = next(v for v in s if 1 <= v <= pb.n)
                ip, idd = s.index(r), s.index(pb.n + r)
                s[ip], s[idd] = s[idd], s[ip]
                break
        self.assertFalse(S.verify(pb, bad)[0])
        missing = [list(s) for s in routes]
        for s in missing:
            if len(s) > 2:
                r = next(v for v in s if 1 <= v <= pb.n)
                s.remove(r)
                s.remove(pb.n + r)
                break
        self.assertFalse(S.verify(pb, missing)[0])


class Official(unittest.TestCase):
    def test_official_checker_agrees(self):
        mod = official_checker()
        if mod is None:
            self.skipTest("official checker not present")
        for seed in range(6):
            inst = gen(10, 10, 100 + seed)
            pb = S.Problem(inst)
            st = S.construct(pb, random.Random(seed))
            self.assertFalse(st.unassigned)
            sol = S.solution_json(pb, st.copy_routes())
            r = mod.check_feasibility(inst, sol)
            self.assertTrue(r["feasible"], str(r.get("violations"))[:500])
            bad = json.loads(json.dumps(sol))
            bad["objective_value"] = sol["objective_value"] * 1.01 + 1.0
            self.assertFalse(mod.check_feasibility(inst, bad)["feasible"])
            sw = json.loads(json.dumps(sol))
            s = sw["routes"][0]["nodes"]
            r0 = next(v for v in s if 1 <= v <= pb.n)
            ip, idd = s.index(r0), s.index(pb.n + r0)
            s[ip], s[idd] = s[idd], s[ip]
            self.assertEqual(S.verify(pb, [x["nodes"] for x in sw["routes"]])[0],
                             mod.check_feasibility(inst, sw)["feasible"])


class Cli(unittest.TestCase):
    def test_contest_cli(self):
        inst = gen(14, 14, 77)
        with tempfile.TemporaryDirectory() as d:
            ip = os.path.join(d, "inst.json")
            op = os.path.join(d, "out.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            t0 = time.monotonic()
            p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "ropke2009",
                                "--instance", ip, "--output", op, "--time-limit", "5"],
                               capture_output=True, text=True, timeout=30)
            wall = time.monotonic() - t0
            self.assertEqual(p.returncode, 0, p.stderr[-800:])
            self.assertLess(wall, 5.0)
            with open(op, encoding="utf-8") as f:
                sol = json.load(f)
        pb = S.Problem(inst)
        routes = [x["nodes"] for x in sol["routes"]]
        self.assertTrue(S.verify(pb, routes)[0])
        self.assertEqual(sol["objective_value"], S.checker_objective(pb, routes))
        self.assertLessEqual(len(routes), pb.K)


if __name__ == "__main__":
    unittest.main()

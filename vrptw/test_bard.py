"""Tests for the bard2002 solver and checker. MV2 of Munim, Inc.; made with AI agents in MV2's name. Apache-2.0.

  python vrptw/test_bard.py -v
If the environment variable BARD_OFFICIAL points at the official bard2002 feasibility_check.py, solver outputs are
also checked with it.
"""
import itertools
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SOLVER_DIR = os.path.join(HERE, "bard2002")
for p in (HERE, SOLVER_DIR, os.path.join(os.path.dirname(HERE), "kit")):
    if p not in sys.path:
        sys.path.insert(0, p)

import bard_check  # noqa: E402
import solve as S  # noqa: E402


def gen(n, seed, Q=200, width=120.0, service=10, H=1000, demand=(1, 30), fold=False, matrix=False):
    rng = random.Random(seed)
    depot = {"id": 0, "x": 50.0, "y": 50.0, "demand": 0, "ready_time": 0, "due_date": H, "service_time": 0}
    cs = []
    for i in range(1, n + 1):
        x, y = rng.uniform(0, 100), rng.uniform(0, 100)
        d = math.floor(math.hypot(x - 50, y - 50) * 10) / 10.0
        lo = d + 1
        hi = H - d - service - width - 1
        e = int(rng.uniform(lo, max(lo, hi)))
        cs.append({"id": i, "x": round(x, 1), "y": round(y, 1), "demand": rng.randint(*demand), "ready_time": e,
                   "due_date": int(e + width), "service_time": service})
    inst = {"num_customers": n, "vehicle_capacity": Q, "depot": depot, "customers": cs, "scheduling_horizon": H,
            "travel_time_includes_service_time": fold, "primary_objective": "min vehicles",
            "secondary_objective": "min distance"}
    if matrix:
        nodes = [depot] + cs
        inst["distance_matrix"] = [[0.0 if i == j else math.floor(math.hypot(a["x"] - b["x"], a["y"] - b["y"]) * 10)
                                    / 10.0 for j, b in enumerate(nodes)] for i, a in enumerate(nodes)]
    return inst


def run_solver(inst, limit=4.0):
    d = tempfile.mkdtemp()
    ip, op = os.path.join(d, "in.json"), os.path.join(d, "out.json")
    with open(ip, "w", encoding="utf-8") as f:
        json.dump(inst, f)
    p = subprocess.run([sys.executable, "solve.py", "--problem", "bard2002", "--instance", ip, "--output", op,
                        "--time-limit", str(limit)], cwd=SOLVER_DIR, capture_output=True, text=True,
                       timeout=limit + 20)
    with open(op, encoding="utf-8") as f:
        sol = json.load(f)
    return sol, p, ip, op


def official(ip, op):
    path = os.environ.get("BARD_OFFICIAL")
    if not path or not os.path.exists(path):
        return None
    rp = op + ".result.json"
    subprocess.run([sys.executable, path, "--instance_path", ip, "--solution_path", op, "--result_path", rp],
                   capture_output=True, text=True, timeout=300)
    with open(rp, encoding="utf-8") as f:
        return json.load(f)


def brute(I):
    cust = I.cust
    n = len(cust)
    ok = [False] * (1 << n)
    for mask in range(1, 1 << n):
        mem = [cust[i] for i in range(n) if mask >> i & 1]
        ok[mask] = any(I.route_ok(list(p)) for p in itertools.permutations(mem))
    INF = 10 ** 9
    dp = [INF] * (1 << n)
    dp[0] = 0
    for mask in range(1, 1 << n):
        low = mask & -mask
        sub = mask
        while sub:
            if sub & low and ok[sub] and dp[mask ^ sub] + 1 < dp[mask]:
                dp[mask] = dp[mask ^ sub] + 1
            sub = (sub - 1) & mask
    return dp[(1 << n) - 1]


class TestModel(unittest.TestCase):
    def test_tau_fold_and_adjustment(self):
        inst = gen(5, 1, service=10)
        I = S.Inst(inst)
        self.assertAlmostEqual(I.tau[1][2], max(I.raw[1][2] + 10, I.a[2] - I.b[1]))
        inst["travel_time_includes_service_time"] = True
        J = S.Inst(inst)
        self.assertAlmostEqual(J.tau[1][2], max(J.raw[1][2], J.a[2] - J.b[1]))
        self.assertEqual(I.raw, J.raw)

    def test_matrix_is_used(self):
        inst = gen(5, 2, matrix=True)
        inst["distance_matrix"][1][2] = 99.9
        self.assertEqual(S.Inst(inst).raw[1][2], 99.9)

    def test_load_rule_threshold(self):
        for Q, expect in ((10, False), (14, False), (15, True), (16, True)):
            inst = {"vehicle_capacity": Q,
                    "depot": {"x": 0, "y": 0, "demand": 0, "ready_time": 0, "due_date": 1000, "service_time": 0},
                    "customers": [{"x": 1, "y": 0, "demand": 5, "ready_time": 0, "due_date": 1000,
                                   "service_time": 0},
                                  {"x": 2, "y": 0, "demand": 5, "ready_time": 0, "due_date": 1000,
                                   "service_time": 0}]}
            I = S.Inst(inst)
            self.assertEqual(I.cap_ok([1, 2]), expect, Q)
            self.assertEqual(I.witness([[1, 2]]) is not None, expect, Q)
            if expect:
                y = I.witness([[1, 2]])
                sol = {"objective_value": 1, "num_vehicles": 1, "routes": [[0, 1, 2, 0]], "total_distance": 4.0,
                       "departure_times": {"1": 1.0, "2": 2.0}, "loads": {"1": y[1], "2": y[2]}}
                self.assertTrue(bard_check.check(inst, sol)["feasible"])
            else:
                sol = {"objective_value": 1, "num_vehicles": 1, "routes": [[0, 1, 2, 0]], "total_distance": 4.0,
                       "departure_times": {"1": 1.0, "2": 2.0}, "loads": {"1": 5, "2": 10}}
                self.assertFalse(bard_check.check(inst, sol)["feasible"])

    def test_witness_cross_route(self):
        # route A = [1, 2, 3] (demands 30, 20, 10; load 60), route B = [4, 5] (demands 45, 5), Q = 100.
        # The pair (3, 4) forces y4 >= y3 + 2*45 - 100 = 50 > 45, so B's loads must be lifted above its own sums.
        cs = []
        for k, (x, y, d) in enumerate(((51, 50, 30), (52, 50, 20), (53, 50, 10), (50, 51, 45), (50, 52, 5)), 1):
            cs.append({"id": k, "x": x, "y": y, "demand": d, "ready_time": 0, "due_date": 500, "service_time": 0})
        inst = {"vehicle_capacity": 100, "customers": cs,
                "depot": {"x": 50, "y": 50, "demand": 0, "ready_time": 0, "due_date": 1000, "service_time": 0}}
        I = S.Inst(inst)
        routes = [[1, 2, 3], [4, 5]]
        self.assertTrue(all(I.route_ok(r) for r in routes))
        y = I.witness(routes)
        self.assertIsNotNone(y)
        self.assertGreaterEqual(y[4], 50 - 1e-9)
        self.assertGreaterEqual(y[5], 55 - 1e-9)
        sol, why = I.build(routes)
        self.assertIsNotNone(sol, why)
        self.assertTrue(bard_check.check(inst, sol)["feasible"], bard_check.check(inst, sol)["reason"])
        plain = dict(sol, loads={"1": 30, "2": 50, "3": 60, "4": 45, "5": 50})
        self.assertFalse(bard_check.check(inst, plain)["feasible"])


class TestSolver(unittest.TestCase):
    def check_out(self, inst, sol, ip, op):
        c = bard_check.check(inst, sol)
        self.assertTrue(c["feasible"], c["reason"])
        self.assertEqual(sol["objective_value"], len(sol["routes"]))
        self.assertTrue(bard_check.strict(inst, sol)["strict_ok"])
        o = official(ip, op)
        if o is not None:
            self.assertTrue(o["feasible"], o.get("violations"))

    def test_cli_hand_instance(self):
        inst = gen(25, 7, Q=60, width=150)
        sol, p, ip, op = run_solver(inst, 5.0)
        self.assertEqual(p.returncode, 0, p.stderr[-800:])
        self.check_out(inst, sol, ip, op)

    def test_cli_with_matrix_and_fold(self):
        inst = gen(15, 8, Q=200, width=200, matrix=True, fold=True)
        sol, p, ip, op = run_solver(inst, 4.0)
        self.check_out(inst, sol, ip, op)

    def test_matches_brute_force_on_small(self):
        hits = 0
        for seed in (11, 12, 13):
            inst = gen(6, seed, Q=40, width=80, demand=(5, 15))
            b = brute(S.Inst(inst))
            sol, p, ip, op = run_solver(inst, 3.0)
            self.check_out(inst, sol, ip, op)
            self.assertGreaterEqual(len(sol["routes"]), b)
            hits += int(len(sol["routes"]) == b)
        self.assertGreaterEqual(hits, 2)

    def test_eliminate_from_singletons(self):
        inst = gen(12, 21, Q=1000, width=900, demand=(1, 5))
        I = S.Inst(inst)
        rng = random.Random(0)
        stats = {"ejections": 0}
        cur = [[c] for c in I.cust]
        import time
        for _ in range(11):
            new = S.eliminate(I, cur, time.monotonic() + 2.0, rng, stats)
            if new is None:
                break
            cur = new
        self.assertLess(len(cur), 12)
        sol, why = I.build(cur)
        self.assertIsNotNone(sol, why)
        self.assertTrue(bard_check.check(inst, sol)["feasible"])


class TestChecker(unittest.TestCase):
    def test_rejects_tampering(self):
        inst = gen(10, 31, Q=200, width=300)
        I = S.Inst(inst)
        sol, _ = I.build([[c] for c in I.cust])
        self.assertTrue(bard_check.check(inst, sol)["feasible"])
        bad = dict(sol, num_vehicles=sol["num_vehicles"] - 1)
        self.assertFalse(bard_check.check(inst, bad)["feasible"])
        bad = dict(sol, total_distance=sol["total_distance"] + 1.0)
        self.assertFalse(bard_check.check(inst, bad)["feasible"])
        bad = dict(sol, routes=sol["routes"][1:], num_vehicles=len(sol["routes"]) - 1,
                   objective_value=len(sol["routes"]) - 1)
        self.assertFalse(bard_check.check(inst, bad)["feasible"])


if __name__ == "__main__":
    unittest.main()

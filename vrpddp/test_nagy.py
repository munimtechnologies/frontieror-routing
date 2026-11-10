"""Tests for MV2's nagy2015 (VRPDDP) solver and its calibration harness.

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.
Run: python -m unittest -v test_nagy
"""
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nagy_eval as E  # noqa: E402

_spec = importlib.util.spec_from_file_location("nagy_solve", os.path.join(HERE, "nagy2015", "solve.py"))
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

try:
    import pyvrp  # noqa: F401
    HAVE_PYVRP = True
except Exception:  # noqa: BLE001
    HAVE_PYVRP = False


def hand(C):
    """Two customers at the same place, 5 from the depot, each delivering 6 and picking up 6."""
    return {"num_customers": 2, "vehicle_capacity": C, "depot": {"id": 0, "x": 0, "y": 0},
            "customers": [{"id": 1, "x": 0, "y": 5, "delivery_demand": 6, "pickup_demand": 6},
                          {"id": 2, "x": 0, "y": 5, "delivery_demand": 6, "pickup_demand": 6}],
            "distance_matrix": [[0, 5, 5], [5, 0, 0], [5, 0, 0]]}


def split_helps():
    """C = 10; customer 1 (5 away) delivers 4 and picks up 8; customer 2 (10 away, 5 beyond 1)
    delivers 6. Order matters: 0-1-2-0 overloads at customer 1, 0-2-1-0 fits, so both optima are 20."""
    return {"num_customers": 2, "vehicle_capacity": 10, "depot": {"id": 0, "x": 0, "y": 0},
            "customers": [{"id": 1, "x": 0, "y": 5, "delivery_demand": 4, "pickup_demand": 8},
                          {"id": 2, "x": 0, "y": 10, "delivery_demand": 6, "pickup_demand": 0}],
            "distance_matrix": [[0, 5, 10], [5, 0, 5], [10, 5, 0]]}


def run_own(inst, limit=3.0):
    return S.solve(inst, limit, engine="own", start=time.time())


class TestExact(unittest.TestCase):
    def test_hand_optimum(self):
        self.assertAlmostEqual(E.exact(hand(10)), 20.0)
        self.assertAlmostEqual(E.exact(hand(12)), 10.0)

    def test_split_can_beat_non_divisible(self):
        # Non-divisible: one route 0-1-2-0 leaves with 10, after 1: 10-4+8 = 14 > 10; 0-2-1-0: 10, 4, 4-4+8 = 8
        # -> feasible, cost 10+5+5 = 20. So both are 20 here; the test only pins the values.
        self.assertAlmostEqual(E.exact(split_helps(), spd=True), 20.0)
        self.assertAlmostEqual(E.exact(split_helps()), 20.0)

    def test_spd_never_below_ddp(self):
        for seed in range(1, 6):
            inst = E.random_instance(seed, 4)
            self.assertGreaterEqual(E.exact(inst, spd=True) + 1e-9, E.exact(inst))

    def test_exact_never_above_a_checked_solution(self):
        for seed in range(1, 4):
            inst = E.random_instance(seed, 4)
            sol = run_own(inst, 2.0)
            ok, why, obj = E.check(inst, sol)
            self.assertTrue(ok, why)
            self.assertLessEqual(E.exact(inst), obj + 1e-9)


class TestOwnEngine(unittest.TestCase):
    def test_hand_instances(self):
        for C, want in ((10, 20.0), (12, 10.0)):
            sol = run_own(hand(C))
            ok, why, obj = E.check(hand(C), sol)
            self.assertTrue(ok, why)
            self.assertAlmostEqual(obj, want)

    def test_feasible_on_random(self):
        inst = E.random_instance(99, 12)
        sol = run_own(inst)
        ok, why, obj = E.check(inst, sol)
        self.assertTrue(ok, why)
        self.assertEqual(sorted(v for r in sol["routes"] for v in r[1:-1]), list(range(1, 25)))

    def test_never_below_exact(self):
        inst = E.random_instance(7, 4)
        opt = E.exact(inst)
        sol = run_own(inst)
        ok, why, obj = E.check(inst, sol)
        self.assertTrue(ok, why)
        self.assertGreaterEqual(obj + 1e-9, opt)

    def test_routes_detailed_matches_routes(self):
        inst = E.random_instance(5, 6)
        sol = run_own(inst)
        self.assertEqual(len(sol["routes"]), len(sol["routes_detailed"]))
        for rt, det in zip(sol["routes"], sol["routes_detailed"]):
            self.assertEqual(rt, [d["node"] for d in det])
            for d in det:
                if d["node"] == 0:
                    self.assertEqual(d["role"], "depot")
                elif d["node"] <= 6:
                    self.assertEqual(d["role"], "linehaul")
                    self.assertEqual(d["customer"], d["node"])
                else:
                    self.assertEqual(d["role"], "backhaul")
                    self.assertEqual(d["customer"], d["node"] - 6)

    def test_spd_mode_keeps_pairs_together(self):
        inst = E.random_instance(3, 6)
        sol = S.solve(inst, 3.0, engine="own", spd=True, start=time.time())
        ok, why, obj = E.check(inst, sol)
        self.assertTrue(ok, why)
        for rt in sol["routes"]:
            inner = rt[1:-1]
            self.assertEqual(len(inner) % 2, 0)
            for a, b in zip(inner[0::2], inner[1::2]):
                self.assertEqual(b, a + 6)


class TestHelpers(unittest.TestCase):
    def test_spd_to_ddp_keeps_feasibility_and_cost(self):
        inst = E.random_instance(4, 6)
        P = S.parse_instance(inst)
        sol_spd = S.solve(inst, 2.0, engine="own", spd=True, start=time.time())
        ok, why, obj_spd = E.check(inst, sol_spd)
        self.assertTrue(ok, why)
        req_spd = [[v - 1 for v in rt[1:-1:2]] for rt in sol_spd["routes"]]
        sol_ddp, ok2, why2 = S.build_solution(P, S.expand(S.spd_to_ddp(req_spd, 6), 6))
        self.assertTrue(ok2, why2)
        self.assertAlmostEqual(sol_ddp["objective_value"], obj_spd)

    def test_normalise_routes(self):
        self.assertEqual(S.normalise_routes([[1, 0], [2]], 3), [[1, 0], [2]])
        self.assertEqual(S.normalise_routes([[2, 1], [3], []], 3), [[1, 0], [2]])
        self.assertIsNone(S.normalise_routes([[1, 1], [2]], 3))
        self.assertIsNone(S.normalise_routes([[0, 1]], 3))


class TestInsertionRule(unittest.TestCase):
    def test_o1_rule_matches_full_recheck(self):
        rng = random.Random(1)
        for trial in range(200):
            n = 6
            C = 20.0
            qd = np.array([rng.randint(0, 12) for _ in range(n)] + [0] * n, dtype=float)
            qp = np.array([0] * n + [rng.randint(0, 12) for _ in range(n)], dtype=float)
            loc = np.concatenate((np.arange(1, n + 1), np.arange(1, n + 1)))
            D = np.zeros((n + 1, n + 1))
            own = S.Own(D, loc, qd, qp, C, seed=trial)
            reqs = list(range(2 * n))
            rng.shuffle(reqs)
            route = reqs[:rng.randint(0, 6)]
            v = reqs[-1]

            def feasible(rt):
                load = qd[rt].sum() if rt else 0.0
                if load > C + 1e-9:
                    return False
                for r in rt:
                    load += qp[r] - qd[r]
                    if load > C + 1e-9:
                        return False
                return True

            if not feasible(route):
                continue
            A, B, pref, suf, cost, dab, mx = own.arrays(route)
            for p in range(len(route) + 1):
                rule = (pref[p] + qd[v] <= C + 1e-9) and (suf[p] + qp[v] <= C + 1e-9)
                self.assertEqual(rule, feasible(route[:p] + [v] + route[p:]), (route, v, p))


class TestChecker(unittest.TestCase):
    def test_rejects(self):
        inst = hand(10)
        self.assertTrue(E.check(inst, {"objective_value": 20, "routes": [[0, 1, 3, 0], [0, 2, 4, 0]]})[0])
        self.assertFalse(E.check(inst, {"objective_value": 10, "routes": [[0, 1, 2, 3, 4, 0]]})[0])
        self.assertFalse(E.check(inst, {"objective_value": 10, "routes": [[0, 1, 3, 0]]})[0])
        self.assertFalse(E.check(inst, {"objective_value": 19, "routes": [[0, 1, 3, 0], [0, 2, 4, 0]]})[0])
        self.assertFalse(E.check(inst, {"objective_value": 20, "routes": [[0, 3, 4, 0], [0, 1, 2, 0]]})[0])


class TestConverter(unittest.TestCase):
    TEXT = "\n".join([
        "NAME : T1", "COMMENT : 0", "TYPE : CVRP", "DIMENSION : 3", "EDGE_WEIGHT_TYPE : EUC_2D",
        "CAPACITY : 160", "DISTANCE : 200", "SERVICE_TIME : 10", "NODE_COORD_SECTION",
        "1 30 40", "2 37 52", "3 49 49", "PICKUP_AND_DELIVERY_SECTION",
        "1 0 0 0 0 0 0", "2 0 0 0 0 2.01923 4.98077", "3 0 0 0 0 0 30"])

    def test_schema(self):
        inst, info = E.to_frontieror(self.TEXT)
        self.assertEqual(inst["num_customers"], 2)
        self.assertEqual(inst["vehicle_capacity"], 160)
        self.assertEqual(inst["depot"], {"id": 0, "x": 30, "y": 40})
        c1, c2 = inst["customers"]
        self.assertEqual((c1["id"], c1["delivery_demand"], c1["pickup_demand"]), (1, 4.98077, 2.01923))
        self.assertEqual((c2["id"], c2["delivery_demand"], c2["pickup_demand"]), (2, 30, 0))
        # (30,40)-(37,52): sqrt(49+144)=13.89 -> 14 ; (30,40)-(49,49): sqrt(361+81)=21.02 -> 21
        self.assertEqual(inst["distance_matrix"][0], [0, 14, 21])
        self.assertEqual(info["ignored"], {"DISTANCE": "200", "SERVICE_TIME": "10"})
        real, _ = E.to_frontieror(self.TEXT, real=True)
        self.assertAlmostEqual(real["distance_matrix"][0][1], 13.892443989, places=6)


class TestCli(unittest.TestCase):
    def test_cli_writes_checked_solution_in_time(self):
        inst = E.random_instance(11, 10)
        with tempfile.TemporaryDirectory() as td:
            ip, op = os.path.join(td, "i.json"), os.path.join(td, "o.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            t = time.time()
            cp = subprocess.run([sys.executable, os.path.join(HERE, "nagy2015", "solve.py"), "--problem",
                                 "nagy2015", "--instance", ip, "--output", op, "--time-limit", "6",
                                 "--engine", "own"], capture_output=True, text=True, timeout=60)
            wall = time.time() - t
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertLess(wall, 6.0)
            with open(op, encoding="utf-8") as f:
                sol = json.load(f)
            ok, why, obj = E.check(inst, sol)
            self.assertTrue(ok, why)


@unittest.skipUnless(HAVE_PYVRP, "pyvrp not installed")
class TestPyvrpEngine(unittest.TestCase):
    def test_pyvrp_feasible(self):
        inst = E.random_instance(21, 12)
        P = S.parse_instance(inst)
        loc, qd, qp = S.requests(P)
        rr = S.pyvrp_routes(P, loc, qd, qp, time.time() + 2.0)
        self.assertIsNotNone(rr)
        sol, ok, why = S.build_solution(P, S.expand(rr, P["n"]))
        self.assertTrue(ok, why)
        self.assertTrue(E.check(inst, sol)[0])

    def test_pyvrp_spd_feasible(self):
        inst = E.random_instance(22, 10)
        P = S.parse_instance(inst)
        loc, qd, qp = S.requests(P, spd=True)
        rr = S.pyvrp_routes(P, loc, qd, qp, time.time() + 2.0)
        self.assertIsNotNone(rr)
        sol, ok, why = S.build_solution(P, S.expand(rr, P["n"], spd=True))
        self.assertTrue(ok, why)

    def test_pyvrp_hand(self):
        for C, want in ((10, 20.0), (12, 10.0)):
            sol = S.solve(hand(C), 8.0, engine="pyvrp", start=time.time())
            ok, why, obj = E.check(hand(C), sol)
            self.assertTrue(ok, why)
            self.assertAlmostEqual(obj, want)


if __name__ == "__main__":
    unittest.main()

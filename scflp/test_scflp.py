"""Tests for the bodur2017 (SCFLP) solver, checker, generator and reference MIP.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Run: python scflp/test_scflp.py -v   (needs numpy, scipy, ortools; frontier_runtime.py next to bodur2017/solve.py)
"""
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
SOLVER_DIR = os.path.join(HERE, "bodur2017")
for p in (HERE, SOLVER_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np  # noqa: E402

import scflp_check  # noqa: E402
import scflp_exact  # noqa: E402
import scflp_gen  # noqa: E402
import solve as S  # noqa: E402


def hand_instance():
    """Two facilities, two customers, two scenarios; facility 0 is cheap to open but small."""
    return {
        "num_facilities": 2, "num_customers": 2, "num_scenarios": 2, "capacity_factor": 2.0,
        "variance_level": "normal",
        "facilities": [{"id": 0, "opening_cost": 10.0, "capacity": 10.0, "location_x": 0, "location_y": 0},
                       {"id": 1, "opening_cost": 50.0, "capacity": 30.0, "location_x": 1, "location_y": 0}],
        "customers": [{"id": 0, "deterministic_demand": 4.0, "demand_std_fraction": 0.1, "location_x": 0,
                       "location_y": 0},
                      {"id": 1, "deterministic_demand": 6.0, "demand_std_fraction": 0.1, "location_x": 1,
                       "location_y": 0}],
        "transportation_costs": [[1.0, 2.0], [3.0, 1.0]],
        "scenarios": [{"id": 0, "probability": 0.5, "demands": [4.0, 5.0]},
                      {"id": 1, "probability": 0.5, "demands": [5.0, 7.0]}],
    }


def write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


class TestChecker(unittest.TestCase):
    def setUp(self):
        self.inst = hand_instance()
        # both open; scenario 0: f0 -> c0 4, f0 -> c1 5 (9 <= 10); scenario 1: f0 -> c0 5, f0 -> c1 5, f1 -> c1 2
        self.sol = {"objective_value": None, "open_facilities": [0, 1], "x": {"0": 1, "1": 1},
                    "y": {"0": {"0": {"0": 4.0, "1": 5.0}, "1": {"0": 0.0, "1": 0.0}},
                          "1": {"0": {"0": 5.0, "1": 5.0}, "1": {"1": 2.0}}}}
        # cost: 60 + 0.5*(4 + 10) + 0.5*(5 + 10 + 2) = 60 + 7 + 8.5 = 75.5

    def test_feasible_and_objective(self):
        r = scflp_check.check(self.inst, self.sol)
        self.assertTrue(r["feasible"], r["reason"])
        self.assertAlmostEqual(r["objective"], 75.5, places=9)

    def test_demand_shortfall(self):
        self.sol["y"]["1"]["1"]["1"] = 1.0
        self.assertFalse(scflp_check.check(self.inst, self.sol)["feasible"])

    def test_capacity_exceeded(self):
        self.sol["y"]["1"]["0"]["1"] = 6.0  # f0 ships 11 > 10
        self.sol["y"]["1"]["1"]["1"] = 1.0
        self.assertFalse(scflp_check.check(self.inst, self.sol)["feasible"])

    def test_closed_facility_ships(self):
        self.sol["x"]["1"] = 0
        self.sol["open_facilities"] = [0]
        self.assertFalse(scflp_check.check(self.inst, self.sol)["feasible"])

    def test_aggregate_rule(self):
        # facility 1 alone has capacity 30 >= 12; facility 0 alone (10) fails the aggregate rule
        sol = {"objective_value": 0, "open_facilities": [0], "x": {"0": 1, "1": 0},
               "y": {"0": {"0": {"0": 4.0, "1": 5.0}}, "1": {"0": {"0": 5.0, "1": 5.0}}}}
        r = scflp_check.check(self.inst, sol)
        self.assertFalse(r["feasible"])
        self.assertIn("aggregate", r["reason"])

    def test_x_disagrees(self):
        self.sol["x"]["0"] = 0
        self.assertFalse(scflp_check.check(self.inst, self.sol)["feasible"])


class TestGenerator(unittest.TestCase):
    def test_schema_and_determinism(self):
        a = scflp_gen.make_instance(6, 9, 5, 2.0, "high", 10.0, 7)
        b = scflp_gen.make_instance(6, 9, 5, 2.0, "high", 10.0, 7)
        self.assertEqual(json.dumps(a), json.dumps(b))
        for k in ("num_facilities", "num_customers", "num_scenarios", "capacity_factor", "variance_level",
                  "facilities", "customers", "transportation_costs", "scenarios"):
            self.assertIn(k, a)
        self.assertEqual(len(a["transportation_costs"]), 6)
        self.assertEqual(len(a["transportation_costs"][0]), 9)
        self.assertAlmostEqual(sum(s["probability"] for s in a["scenarios"]), 1.0, places=9)
        for i, f in enumerate(a["facilities"]):
            for j, c in enumerate(a["customers"]):
                d = math.hypot(f["location_x"] - c["location_x"], f["location_y"] - c["location_y"])
                self.assertAlmostEqual(a["transportation_costs"][i][j], d, delta=2e-3)
        dmax = max(sum(s["demands"]) for s in a["scenarios"])
        self.assertGreaterEqual(sum(f["capacity"] for f in a["facilities"]), dmax)

    def test_cases_unique(self):
        names = [r[0] for r in scflp_gen.CASES]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 20)


class TestEvaluation(unittest.TestCase):
    def test_flow_matches_lp(self):
        inst = scflp_gen.make_instance(5, 8, 4, 2.5, "normal", 10.0, 11)
        P = S.Problem(inst)
        rng = random.Random(3)
        tested = 0
        for _ in range(40):
            mask = np.array([rng.random() < 0.6 for _ in range(P.F)])
            if not P.capacity_ok(mask):
                continue
            r = S.evaluate(P, mask, keep=True)
            self.assertIsNotNone(r)
            lp = scflp_exact.eval_open_lp(inst, np.flatnonzero(mask).tolist())
            self.assertIsNotNone(lp)
            self.assertGreaterEqual(r[0], lp - 1e-6 * max(1.0, lp))
            self.assertLessEqual(r[0], lp * (1 + 1e-4) + 1e-6)
            sol = S.build_solution(P, mask, r[1], r[0])
            chk = scflp_check.check(inst, sol)
            self.assertTrue(chk["feasible"], chk.get("reason"))
            self.assertAlmostEqual(chk["objective"], sol["objective_value"], delta=1e-7 * max(1.0, lp))
            tested += 1
            if tested >= 5:
                break
        self.assertGreaterEqual(tested, 3)

    def test_output_modes(self):
        inst = scflp_gen.make_instance(6, 7, 3, 3.0, "high", 2.0, 5)
        P = S.Problem(inst)
        mask = np.ones(P.F, dtype=bool)
        r = S.evaluate(P, mask, keep=True)
        objs = []
        for mode in ("full", "open", "sparse"):
            sol = S.build_solution(P, mask, r[1], r[0], mode=mode)
            chk = scflp_check.check(inst, sol)
            self.assertTrue(chk["feasible"], mode + ": " + str(chk.get("reason")))
            objs.append(chk["objective"])
        self.assertAlmostEqual(objs[0], objs[2], delta=1e-7 * max(1.0, objs[0]))
        full = S.build_solution(P, mask, r[1], r[0], mode="full")
        self.assertEqual(len(full["y"]), 3)
        self.assertEqual(len(full["y"]["0"]), 6)
        self.assertEqual(len(full["y"]["0"]["0"]), 7)

    def test_ext_mip_matches_brute_force(self):
        inst = scflp_gen.make_instance(6, 6, 3, 2.0, "high", 10.0, 21)
        bf, arg = scflp_exact.brute_force(inst)
        r = scflp_exact.ext_mip(inst, 60)
        self.assertTrue(r["proven"])
        self.assertAlmostEqual(r["objective"], bf, delta=1e-5 * max(1.0, bf))

    def test_solver_ext_mip_matches_brute_force(self):
        inst = scflp_gen.make_instance(6, 6, 3, 2.0, "normal", 2.0, 22)
        bf, arg = scflp_exact.brute_force(inst)
        P = S.Problem(inst)
        r = S.ext_mip(P, P.D, P.p, 60, strong=True)
        self.assertEqual(r["status"], 0)
        e = S.evaluate(P, r["mask"])
        self.assertLessEqual(e[0], bf * (1 + 1e-4) + 1e-6)

    def test_stratified_weights(self):
        inst = scflp_gen.make_instance(4, 5, 30, 2.0, "high", 10.0, 9)
        P = S.Problem(inst)
        idx, w = S.stratified(P, 5, random.Random(1))
        self.assertEqual(len(idx), 5)
        self.assertEqual(len(set(idx.tolist())), 5)
        self.assertEqual(int(idx[0]), int(np.argmax(P.Dtot)))
        self.assertAlmostEqual(float(w.sum()), 1.0, places=9)
        self.assertTrue((w > 0).all())


class TestSolveCli(unittest.TestCase):
    def run_cli(self, inst, limit):
        d = tempfile.mkdtemp()
        ip, op = os.path.join(d, "in.json"), os.path.join(d, "out.json")
        write(ip, inst)
        t0 = time.monotonic()
        p = subprocess.run([sys.executable, "solve.py", "--problem", "bodur2017", "--instance", ip, "--output", op,
                            "--time-limit", str(limit)], cwd=SOLVER_DIR, capture_output=True, text=True,
                           timeout=limit + 30)
        wall = time.monotonic() - t0
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        with open(op, encoding="utf-8") as f:
            sol = json.load(f)
        return sol, wall

    def test_tiny_optimal(self):
        inst = scflp_gen.make_instance(6, 6, 3, 1.5, "high", 10.0, 31)
        bf, arg = scflp_exact.brute_force(inst)
        sol, wall = self.run_cli(inst, 10)
        self.assertLess(wall, 10.0)
        chk = scflp_check.check(inst, sol)
        self.assertTrue(chk["feasible"], chk.get("reason"))
        self.assertAlmostEqual(sol["objective_value"], chk["objective"], delta=1e-6 * max(1.0, chk["objective"]))
        self.assertLessEqual(chk["objective"], bf * (1 + 1e-4) + 1e-6)

    def test_hand_instance(self):
        sol, wall = self.run_cli(hand_instance(), 8)
        chk = scflp_check.check(hand_instance(), sol)
        self.assertTrue(chk["feasible"], chk.get("reason"))
        bf, arg = scflp_exact.brute_force(hand_instance())
        self.assertLessEqual(chk["objective"], bf * (1 + 1e-4) + 1e-6)

    def test_deadline_on_medium(self):
        inst = scflp_gen.make_instance(40, 60, 60, 2.0, "high", 10.0, 41)
        sol, wall = self.run_cli(inst, 8)
        self.assertLess(wall, 8.0)
        chk = scflp_check.check(inst, sol)
        self.assertTrue(chk["feasible"], chk.get("reason"))
        self.assertAlmostEqual(sol["objective_value"], chk["objective"], delta=1e-6 * max(1.0, chk["objective"]))


if __name__ == "__main__":
    unittest.main()

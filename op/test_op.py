"""Tests for MV2's fischetti1998 solver and its OPLib calibration harness.

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "fischetti1998"))

import op_eval  # noqa: E402
import solve as op_solve  # noqa: E402

MINI_OPLIB = """NAME : mini5
COMMENT : five points for a test
TYPE : OP
DIMENSION : 5
COST_LIMIT : 25
EDGE_WEIGHT_TYPE : EUC_2D
NODE_COORD_SECTION
1 0 0
2 3 4
3 6 8
4 0 10
5 30 30
NODE_SCORE_SECTION
1 1
2 5
3 7
4 2
5 100
DEPOT_SECTION
1
-1
EOF
"""

MINI_SOL = """NAME : mini5
TYPE : OP
DIMENSION : 5
COST_LIMIT : 25
ROUTE_NODES : 3
ROUTE_SCORE : 13
ROUTE_COST : 20
NODE_SEQUENCE_SECTION
1
2
3
-1
DEPOT_SECTION
1
-1
EOF
"""


class TestOplib(unittest.TestCase):
    def test_convert_mini(self):
        inst, info = op_eval.oplib_to_frontieror(MINI_OPLIB)
        self.assertEqual(info["n"], 5)
        self.assertEqual(inst["depot"], 1)
        self.assertEqual(inst["t0"], 25)
        self.assertEqual(inst["prizes"]["1"], 0)  # depot prize forced to 0
        self.assertEqual(inst["prizes"]["5"], 100)
        self.assertEqual(inst["travel_times"]["(1,2)"], 5)
        self.assertEqual(inst["travel_times"]["(1,3)"], 10)
        self.assertEqual(inst["travel_times"]["(2,3)"], 5)
        self.assertNotIn("(2,1)", inst["travel_times"])
        self.assertEqual(len(inst["travel_times"]), 10)

    def test_non_euc_skipped(self):
        inst, why = op_eval.oplib_to_frontieror(MINI_OPLIB.replace("EUC_2D", "GEO"))
        self.assertIsNone(inst)
        self.assertIn("GEO", why)

    def test_sol_route(self):
        seq, head = op_eval.sol_route(MINI_SOL)
        self.assertEqual(seq, [1, 2, 3])
        self.assertEqual(head["ROUTE_SCORE"], "13")
        inst, _ = op_eval.oplib_to_frontieror(MINI_OPLIB)
        self.assertEqual(op_eval.route_cost(inst, seq), 20.0)


class TestChecker(unittest.TestCase):
    def setUp(self):
        self.inst, _ = op_eval.oplib_to_frontieror(MINI_OPLIB)

    def good(self):
        return {"objective_value": 12, "visited_nodes": [1, 2, 3],
                "edges": [[1, 2], [2, 3], [1, 3]], "tour": [1, 2, 3, 1]}

    def test_accepts_good(self):
        ok, why, obj, cost = op_eval.check_solution(self.inst, self.good())
        self.assertTrue(ok, why)
        self.assertEqual(obj, 12.0)
        self.assertEqual(cost, 20.0)

    def test_rejects_wrong_objective(self):
        s = self.good()
        s["objective_value"] = 13
        self.assertFalse(op_eval.check_solution(self.inst, s)[0])

    def test_rejects_over_budget(self):
        s = {"objective_value": 105, "visited_nodes": [1, 2, 5],
             "edges": [[1, 2], [2, 5], [1, 5]], "tour": [1, 2, 5, 1]}
        ok, why, _, _ = op_eval.check_solution(self.inst, s)
        self.assertFalse(ok)
        self.assertIn("over budget", why)

    def test_rejects_two_cities(self):
        s = {"objective_value": 5, "visited_nodes": [1, 2], "edges": [[1, 2], [1, 2]],
             "tour": [1, 2, 1]}
        self.assertFalse(op_eval.check_solution(self.inst, s)[0])

    def test_rejects_repeat(self):
        s = {"objective_value": 12, "visited_nodes": [1, 2, 3],
             "edges": [[1, 2], [2, 3], [2, 3], [1, 2]], "tour": [1, 2, 3, 2, 1]}
        self.assertFalse(op_eval.check_solution(self.inst, s)[0])


class TestSolver(unittest.TestCase):
    def test_parse_key_spacing(self):
        inst, _ = op_eval.oplib_to_frontieror(MINI_OPLIB)
        spaced = dict(inst)
        spaced["travel_times"] = {k.replace(",", ", "): v for k, v in inst["travel_times"].items()}
        a = op_solve.parse_instance(inst)
        b = op_solve.parse_instance(spaced)
        self.assertEqual(a[0], b[0])
        self.assertTrue((a[1] == b[1]).all())
        self.assertEqual(a[3], 0)

    def test_solve_mini_feasible_and_best(self):
        inst, _ = op_eval.oplib_to_frontieror(MINI_OPLIB)
        sol = op_solve.solve(inst, 3, start=time.time())
        ok, why, obj, cost = op_eval.check_solution(inst, sol)
        self.assertTrue(ok, why)
        # best: 1-2-3-4-1 costs 5+5+sqrt(36+4)=6+10 = 26 > 25; 1-2-3-1 = 20 (12); 1-3-4-1: 10+6+10=26;
        # 1-2-4-1: 5+nint(sqrt(9+36))=7+10=22 (7); so the optimum is 12.
        self.assertEqual(obj, op_eval.exact_op(inst))
        self.assertEqual(obj, 12.0)

    def test_three_cities_even_with_zero_prizes(self):
        inst, _ = op_eval.oplib_to_frontieror(MINI_OPLIB)
        inst = dict(inst)
        inst["prizes"] = {k: 0 for k in inst["prizes"]}
        sol = op_solve.solve(inst, 3, start=time.time())
        ok, why, obj, _ = op_eval.check_solution(inst, sol)
        self.assertTrue(ok, why)
        self.assertGreaterEqual(len(set(sol["tour"])), 3)

    def test_random_instances_feasible(self):
        for seed in (101, 102, 103):
            inst = op_eval.random_instance(seed, n=25, frac=0.3)
            sol = op_solve.solve(inst, 3, start=time.time())
            ok, why, obj, _ = op_eval.check_solution(inst, sol)
            self.assertTrue(ok, "seed %d: %s" % (seed, why))

    def test_cli_end_to_end(self):
        """Runs solve.py as the FrontierOR sandbox does: CLI flags, files, exit code, time."""
        inst = op_eval.random_instance(11, n=30, frac=0.3)
        sol, wall, err = op_eval.run_solver(inst, 5)
        self.assertEqual(err, "")
        self.assertIsNotNone(sol)
        ok, why, obj, _ = op_eval.check_solution(inst, sol)
        self.assertTrue(ok, why)
        self.assertLess(wall, 5.0)
        with tempfile.TemporaryDirectory() as td:
            ip = os.path.join(td, "i.json")
            op = os.path.join(td, "o.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            cp = subprocess.run([sys.executable, op_eval.SOLVER, "--problem", "fischetti1998",
                                 "--instance", ip, "--output", op, "--time-limit", "3"],
                                capture_output=True, text=True, timeout=60)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            with open(op, encoding="utf-8") as f:
                self.assertIn("objective_value", json.load(f))


if __name__ == "__main__":
    unittest.main()

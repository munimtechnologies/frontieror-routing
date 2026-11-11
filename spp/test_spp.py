"""Tests for the hoffman1993 (set partitioning) solver and its calibration harness. Needs scipy and ortools.

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.
"""
import json
import os
import random
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "kit"))
sys.path.insert(0, os.path.join(HERE, "hoffman1993"))
sys.path.insert(0, HERE)

import frontier_runtime as R  # noqa: E402
import harness as H  # noqa: E402
import solve as S  # noqa: E402
import spp_eval as E  # noqa: E402

ORLIB_TEXT = """3 4
5 2 1
2
4 1 3 7 1
3
2 1 2
"""
# 3 rows, 4 columns: c1 {1,2} cost 5; c2 {3} cost 4; c3 {3} cost 7; c4 {2} cost 2  (line breaks inside columns)

# LP relaxation is fractional: the three pairs at 1/2 each cost 1.5, while every partition costs at least 2.
FRACTIONAL = E.to_instance(3, 6, [1, 1, 1, 1, 1, 1], [[1, 2], [2, 3], [1, 3], [1], [2], [3]])


def clock(limit):
    return R.Clock(limit, start=time.monotonic())


class Parsing(unittest.TestCase):
    def test_parse_orlib_wrapped(self):
        m, n, costs, cols = E.parse_orlib(ORLIB_TEXT)
        self.assertEqual((m, n), (3, 4))
        self.assertEqual(costs, [5, 4, 7, 2])
        self.assertEqual(cols, [[1, 2], [3], [3], [2]])

    def test_leg_base_detection(self):
        inst1 = E.to_instance(3, 4, [5, 4, 7, 2], [[1, 2], [3], [3], [2]])
        inst0 = E.to_instance(3, 4, [5, 4, 7, 2], [[0, 1], [2], [2], [1]])
        p1, p0 = S.load(inst1), S.load(inst0)
        self.assertEqual((p1["leg_base"], p0["leg_base"]), (1, 0))
        self.assertEqual(p1["cols"], p0["cols"])
        self.assertEqual(p1["cols"], [[0, 1], [2], [2], [1]])
        self.assertTrue(p1["int_costs"])
        self.assertFalse(S.load(E.to_instance(1, 1, [1.5], [[1]]))["int_costs"])

    def test_same_rotation_index_guess(self):
        self.assertEqual(S.ROT_BASE, E.ROT_BASE)

    def test_tiny_all_agrees_with_tiny(self):
        for seed in (1, 2, 3):
            inst, best = E.tiny_instance(seed, with_base=(seed == 3))
            inst2, feas = E.tiny_instance_all(seed, with_base=(seed == 3))
            self.assertEqual(inst, inst2)
            self.assertEqual(best, min(c for c, _ in feas))


class Checker(unittest.TestCase):
    def setUp(self):
        self.inst = E.to_instance(3, 4, [5, 4, 7, 2], [[1, 2], [3], [3], [2]])

    def test_feasible_and_cost(self):
        r = E.checker(self.inst, {"selected_rotations": [0, 1]})
        self.assertTrue(r["feasible"])
        self.assertEqual(r["objective"], 9.0)

    def test_uncovered_double_and_bad(self):
        self.assertFalse(E.checker(self.inst, {"selected_rotations": [0]})["feasible"])
        self.assertFalse(E.checker(self.inst, {"selected_rotations": [0, 1, 2]})["feasible"])
        self.assertFalse(E.checker(self.inst, {"selected_rotations": [0, 3, 1]})["feasible"])  # leg 2 twice
        self.assertFalse(E.checker(self.inst, {"selected_rotations": [0, 9]})["feasible"])
        self.assertFalse(E.checker(self.inst, {"selected_rotations": [0, 1, 1]})["feasible"])
        self.assertFalse(E.checker(self.inst, {"selected_rotations": [0, 1],
                                               "variable_values": {"0": 1.0, "1": 0.0, "2": 1.0}})["feasible"])

    def test_solver_solution_format(self):
        P = S.load(self.inst)
        obj, sol = S.solution(P, [1, 0])
        self.assertEqual(obj, 9.0)
        self.assertEqual(sol["selected_rotations"], [0, 1])
        self.assertEqual(sol["variable_values"], {"0": 1.0, "1": 1.0, "2": 0.0, "3": 0.0})
        self.assertTrue(E.checker(self.inst, sol)["feasible"])
        json.dumps(sol)  # plain Python numbers only

    def test_base_bounds(self):
        base = {"D": [[1.0, 2.0, 0.5, 1.0]], "lo": [2.5], "hi": [4.0]}
        inst = E.to_instance(3, 4, [5, 4, 7, 2], [[1, 2], [3], [3], [2]], base)
        self.assertTrue(E.checker(inst, {"selected_rotations": [0, 1]})["feasible"])  # 3.0
        self.assertFalse(E.checker(inst, {"selected_rotations": [0, 2]})["feasible"])  # 1.5
        self.assertFalse(S.check(S.load(inst), [0, 2]))
        self.assertTrue(S.check(S.load(inst), [0, 1]))


class Engines(unittest.TestCase):
    def test_highs_matches_brute_force(self):
        for seed in range(1, 9):
            inst, best = E.tiny_instance(seed, with_base=(seed % 2 == 0))
            chosen, proven = S.run_highs(S.load(inst), 20)
            self.assertIsNotNone(chosen, seed)
            self.assertTrue(proven, seed)
            r = E.checker(inst, {"selected_rotations": chosen})
            self.assertTrue(r["feasible"], seed)
            self.assertEqual(r["objective"], best, seed)

    def test_milp_subset_maps_back_to_original_positions(self):
        for seed in range(1, 6):
            inst, best = E.tiny_instance(seed)
            P = S.load(inst)
            sub = list(range(P["n"]))[::-1]  # reversed on purpose
            chosen, code = S._milp(P, 20, sub)
            self.assertEqual(code, "optimal", seed)
            r = E.checker(inst, {"selected_rotations": sorted(chosen)})
            self.assertTrue(r["feasible"], seed)
            self.assertEqual(r["objective"], best, seed)
        chosen, code = S._milp(S.load(FRACTIONAL), 10, [0, 1])  # pairs {1,2} and {2,3} cannot partition
        self.assertIsNone(chosen)
        self.assertIn(code, ("infeasible", "other"))

    def test_cpsat_matches_brute_force(self):
        with tempfile.TemporaryDirectory() as d:
            for seed in range(1, 9):
                inst, best = E.tiny_instance(seed, with_base=(seed % 2 == 0))
                inc = R.Incumbent(os.path.join(d, "o%d.json" % seed), "min")
                optimal = S.run_cpsat(S.load(inst), 10, inc)
                self.assertTrue(optimal, seed)
                self.assertEqual(inc.value, best, seed)
                self.assertTrue(E.checker(inst, inc.solution)["feasible"], seed)

    def test_cpsat_on_a_subset(self):
        with tempfile.TemporaryDirectory() as d:
            inst, feas = E.tiny_instance_all(2)
            best_cost, best_cols = min(feas)
            P = S.load(inst)
            inc = R.Incumbent(os.path.join(d, "o.json"), "min")
            self.assertTrue(S.run_cpsat(P, 10, inc, subset=best_cols))  # only the optimal partition's columns
            self.assertEqual(inc.value, best_cost)
            inc2 = R.Incumbent(os.path.join(d, "o2.json"), "min")
            self.assertFalse(S.run_cpsat(P, 10, inc2, subset=best_cols[:1] if len(best_cols) > 1 else []))
            self.assertIsNone(inc2.value)

    def test_tiny_planted_partition_is_feasible_under_base(self):
        for seed in range(1, 13):
            inst, best = E.tiny_instance(seed, with_base=True)
            self.assertIsNotNone(best, seed)


class Pruning(unittest.TestCase):
    """The bound and the reduced-cost pruning, checked by brute force against every feasible partition."""

    def _ys(self, P, seed):
        lp = S.run_lp(P, 10)
        self.assertIsNotNone(lp)
        rng = random.Random(seed)
        ys = [lp["y"] if lp["y"] is not None else [0.0] * P["m"], [0.0] * P["m"]]
        ys += [[rng.uniform(-30, 60) for _ in range(P["m"])] for _ in range(4)]
        return ys

    def test_lagrangian_is_a_lower_bound_for_any_y(self):
        for seed in range(1, 11):
            inst, feas = E.tiny_instance_all(seed, with_base=(seed % 3 == 0))
            P = S.load(inst)
            best = min(c for c, _ in feas)
            for y in self._ys(P, seed):
                L, rc = S.lagrangian(P, y)
                self.assertLessEqual(L, best + 1e-6, seed)
                Lb, _ = S.best_lagrangian(P, y)
                self.assertGreaterEqual(Lb, L - 1e-9)
                self.assertLessEqual(Lb, best + 1e-6, seed)

    def test_lp_dual_bound_equals_lp_value(self):
        P = S.load(FRACTIONAL)
        lp = S.run_lp(P, 10)
        self.assertAlmostEqual(lp["fun"], 1.5, places=6)
        L, _ = S.best_lagrangian(P, lp["y"])
        self.assertAlmostEqual(L, 1.5, places=5)

    def test_pruning_keeps_every_column_of_every_improving_solution(self):
        for seed in range(1, 11):
            inst, feas = E.tiny_instance_all(seed, with_base=(seed % 3 == 0))
            P = S.load(inst)
            costs = sorted({c for c, _ in feas})
            for y in self._ys(P, seed):
                L, rc = S.best_lagrangian(P, y)
                for ub in costs[:4] + [costs[-1] + 1]:
                    keep = set(int(j) for j in S.keep_columns(P, L, rc, ub))
                    better = [cols for c, cols in feas if c <= ub - 1]
                    for cols in better:
                        self.assertTrue(set(cols) <= keep, (seed, ub, cols))
                    if better:
                        self.assertFalse(S.proven_by_bound(P, L, ub), (seed, ub))
                    if S.proven_by_bound(P, L, ub):
                        self.assertEqual(better, [])

    def test_restricted_grows_until_feasible(self):
        import numpy as np
        old = (S.HEUR_K_MIN, S.HEUR_K_PER_ROW)
        S.HEUR_K_MIN, S.HEUR_K_PER_ROW = 1, 0
        try:
            with tempfile.TemporaryDirectory() as d:
                for seed in (1, 4, 7):
                    inst, best = E.tiny_instance(seed)
                    P = S.load(inst)
                    inc = R.Incumbent(os.path.join(d, "r%d.json" % seed), "min")
                    rc = np.zeros(P["n"])
                    tried, proven = S.restricted(P, inc, clock(30), rc, None, 20)
                    self.assertIsNotNone(inc.value, seed)
                    self.assertTrue(E.checker(inst, inc.solution)["feasible"], seed)
                    self.assertGreaterEqual(len(tried), 2, (seed, tried))  # 1 column cannot cover 7 legs
                    self.assertEqual(tried[0][0], 1)
                    if proven:
                        self.assertEqual(tried[-1][0], P["n"])
                        self.assertEqual(inc.value, best)
        finally:
            S.HEUR_K_MIN, S.HEUR_K_PER_ROW = old


class Solve(unittest.TestCase):
    def test_solve_in_process_matches_brute_force(self):
        with tempfile.TemporaryDirectory() as d:
            for seed in range(1, 13):
                inst, best = E.tiny_instance(seed, with_base=(seed % 3 == 0))
                inc = R.Incumbent(os.path.join(d, "s%d.json" % seed), "min")
                log = S.solve(inst, clock(20), inc)
                self.assertEqual(inc.value, best, (seed, log))
                self.assertTrue(E.checker(inst, inc.solution)["feasible"], seed)
                self.assertNotIn("fallback", log, seed)
                self.assertIn("proven", log, (seed, log))

    def test_fractional_lp_goes_through_pruning(self):
        with tempfile.TemporaryDirectory() as d:
            inc = R.Incumbent(os.path.join(d, "f.json"), "min")
            log = S.solve(FRACTIONAL, clock(20), inc)
            self.assertEqual(inc.value, 2.0, log)
            self.assertAlmostEqual(log["lp"], 1.5, places=6)
            self.assertNotEqual(log.get("proven"), "lp_integral")
            self.assertIn("proven", log, log)


class Cli(unittest.TestCase):
    def test_cli_through_harness(self):
        with tempfile.TemporaryDirectory() as d:
            for seed in (3, 4):
                inst, best = E.tiny_instance(seed, with_base=(seed == 3))
                ip = os.path.join(d, "t%d.json" % seed)
                with open(ip, "w", encoding="utf-8") as f:
                    json.dump(inst, f)
                row = H.evaluate_case({"name": "t%d" % seed, "instance_path": ip, "reference": best},
                                      os.path.join(HERE, "hoffman1993", "solve.py"), "hoffman1993", 10, E.checker,
                                      "min", d)
                self.assertEqual(row["status"], "ok", row)
                self.assertEqual(row["objective"], best)
                self.assertEqual(row["score"], 1.0)
                self.assertLess(row["wall_s"], 10.0)


if __name__ == "__main__":
    unittest.main()

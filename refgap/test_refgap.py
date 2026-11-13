"""Tests for refgap (pure functions only; no network).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
"""
import unittest

import refgap as R


class TestScore(unittest.TestCase):
    def test_equal_is_one(self):
        self.assertEqual(R.contest_score(5.0, 5.0, "min"), 1.0)
        self.assertEqual(R.contest_score(0.0, 0.0, "max"), 1.0)

    def test_positive_min_and_max(self):
        self.assertAlmostEqual(R.contest_score(80.0, 100.0, "min"), 1.25)
        self.assertAlmostEqual(R.contest_score(125.0, 100.0, "min"), 0.8)
        self.assertAlmostEqual(R.contest_score(125.0, 100.0, "max"), 1.25)
        self.assertEqual(R.contest_score(10.0, 100.0, "min"), 2.0)  # cap

    def test_negative_flips(self):
        # guo2021 large_1 at 60 s: ours -793,407.6 against Gurobi -732,149.2 (minimise) -> 1.0837
        self.assertAlmostEqual(R.contest_score(-793407.6, -732149.2, "min"), 1.083669, places=5)
        self.assertAlmostEqual(R.contest_score(-50.0, -100.0, "max"), 2.0)
        self.assertAlmostEqual(R.contest_score(-150.0, -100.0, "max"), 100.0 / 150.0)

    def test_opposite_signs_and_zero_reference(self):
        # guo2021 large_2: Gurobi +32,031, ours -566,256.4 -> better across zero -> 2
        self.assertEqual(R.contest_score(-566256.4, 32031.0, "min"), 2.0)
        self.assertEqual(R.contest_score(5.0, -1.0, "min"), 0.0)
        self.assertEqual(R.contest_score(-1.0, 0.0, "min"), 2.0)
        self.assertEqual(R.contest_score(1.0, 0.0, "min"), 0.0)


class TestCeiling(unittest.TestCase):
    def test_bound_side(self):
        self.assertAlmostEqual(R.implied_bound(100.0, 0.1, "min"), 90.0)
        self.assertAlmostEqual(R.implied_bound(100.0, 0.1, "max"), 110.0)
        self.assertAlmostEqual(R.implied_bound(-100.0, 0.1, "min"), -110.0)
        self.assertIsNone(R.implied_bound(None, 0.1, "min"))
        self.assertIsNone(R.implied_bound(100.0, None, "min"))

    def test_ceiling_values(self):
        self.assertEqual(R.ceiling(100.0, 0.0, "min"), 1.0)
        self.assertAlmostEqual(R.ceiling(100.0, 0.2, "min"), 1.25)
        self.assertEqual(R.ceiling(100.0, 0.6, "min"), 2.0)
        self.assertEqual(R.ceiling(32031.0, 25.0, "min"), 2.0)  # bound across zero
        self.assertAlmostEqual(R.ceiling(-100.0, 0.5, "min"), 1.5)
        self.assertAlmostEqual(R.ceiling(100.0, 0.5, "max"), 1.5)


class TestParsing(unittest.TestCase):
    def test_case_name(self):
        self.assertEqual(R.case_name("large_solution_3.json"), "large_3")
        self.assertEqual(R.case_name("tiny_solution.json"), "tiny")
        self.assertEqual(R.case_name("odd.json"), "odd")

    def test_table_case(self):
        self.assertEqual(R.table_case("large_instance_3.json"), "large_3")
        self.assertEqual(R.table_case("tasks/x/instance/large_instance_12.json"), "large_12")
        self.assertEqual(R.table_case("tiny_instance.json"), "tiny")
        self.assertEqual(R.table_case("large_2"), "large_2")

    def test_sense(self):
        self.assertEqual(R.sense_of("m.setObjective(e, GRB.MAXIMIZE)"), "max")
        self.assertEqual(R.sense_of("m.setObjective(e, GRB.MINIMIZE)"), "min")
        self.assertEqual(R.sense_of("m.setObjective(e)"), "min")
        self.assertIsNone(R.sense_of("GRB.MINIMIZE # or GRB.MAXIMIZE"))
        self.assertIsNone(R.sense_of(None))

    def test_gap_from(self):
        self.assertEqual(R.gap_from({"mip_gap": 0.25}, 10.0), (0.25, "mip_gap"))
        g, k = R.gap_from({"obj_bound": 80.0}, 100.0)
        self.assertAlmostEqual(g, 0.2)
        self.assertEqual(k, "obj_bound")
        self.assertEqual(R.gap_from({"status": "OPTIMAL"}, 10.0), (0.0, "status"))
        self.assertEqual(R.gap_from({"status": 2}, 10.0), (0.0, "status"))
        self.assertEqual(R.gap_from({"status": "TIME_LIMIT"}, 10.0), (None, None))
        self.assertEqual(R.gap_from({"mip_gap": "inf"}, 10.0), (None, None))

    def test_scalars(self):
        s = R.scalars({"objective_value": 3.5, "x": [1, 2], "y": {"a": 1}, "status": "OPTIMAL", "b": True})
        self.assertEqual(s, {"objective_value": 3.5, "status": "OPTIMAL", "b": True})

    def test_scalars_from_text(self):
        head = '{"objective_value": -1.5e3, "status": "TIME_LIMIT", "x": {"0,1": 1}, "mip_gap": 0.0312'
        out = R.scalars_from_text(head, R.WANTED)
        self.assertEqual(out["objective_value"], -1500.0)
        self.assertEqual(out["status"], "TIME_LIMIT")
        self.assertAlmostEqual(out["mip_gap"], 0.0312)
        self.assertNotIn("x", out)
        self.assertEqual(R.scalars_from_text('"runtime": null', R.WANTED), {"runtime": None})

    def test_num(self):
        self.assertIsNone(R.num(True))
        self.assertIsNone(R.num("nan"))
        self.assertIsNone(R.num("abc"))
        self.assertEqual(R.num("2.5"), 2.5)


class TestSummary(unittest.TestCase):
    def test_summarise_counts(self):
        res = {"tasks": ["a", "b"], "hard": {"a": 1}, "cases": [
            {"task": "a", "case": "tiny", "sense": "min", "gap": 0.0, "ceiling": 1.0, "objective": 1.0},
            {"task": "a", "case": "large_1", "sense": "min", "gap": 0.6, "ceiling": 2.0, "objective": 10.0},
            {"task": "a", "case": "large_2", "sense": "min", "gap": 0.2, "ceiling": 1.25, "objective": 10.0},
        ]}
        rows = {r["task"]: r for r in R.summarise(res)}
        self.assertEqual(rows["a"]["large_cases"], 2)
        self.assertEqual(rows["a"]["cases_ceiling_2"], 1)
        self.assertEqual(rows["a"]["cases_ceiling_ge_1_5"], 1)
        self.assertAlmostEqual(rows["a"]["mean_ceiling"], 1.625)
        self.assertAlmostEqual(rows["a"]["max_gap"], 0.6)
        self.assertEqual(rows["b"]["large_cases"], 0)
        self.assertIsNone(rows["b"]["mean_ceiling"])


if __name__ == "__main__":
    unittest.main()

"""Tests for the OPLib pre-fix follow-up.

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import oplib_prefix as P  # noqa: E402

OLD = """NAME : toy
TYPE : OP
DIMENSION: 4
COST_LIMIT : 20
EDGE_WEIGHT_TYPE : EUC_2D
NODE_COORD_SECTION
1 0 0
2 3 0
3 6 0
4 0 4
NODE_SCORE_SECTION
1 0
2 5
3 7
4 2
DEPOT_SECTION
 1
 -1
EOF
"""
# same instance, node 3 rescored 7 -> 9 and node 4 rescored 2 -> 3 (node 4 is not on the route)
NEW = OLD.replace("3 7\n4 2", "3 9\n4 3")

SOL = """NAME : toy
TYPE : OP
ROUTE_NODES : 3
ROUTE_SCORE : %s
ROUTE_COST : 12
NODE_SEQUENCE_SECTION
1
2
3
-1
EOF
"""


class Prefix(unittest.TestCase):
    def test_route_scored_with_old_file(self):
        texts = {"parent": (OLD, SOL % 12), "fix": (NEW, SOL % 12), "current": (NEW, SOL % 12)}
        r = P.check_family(texts)
        self.assertEqual(r["status"], "checked")
        self.assertEqual(r["parent"]["status"], "consistent")
        self.assertEqual(r["current"]["status"], "inconsistent")
        self.assertEqual(r["current"]["score_with_depot"], 14.0)
        d = r["parent_vs_current"]
        self.assertEqual(d["scores_changed"], 2)
        self.assertEqual(d["score_total_delta"], 3.0)
        self.assertTrue(d["only_scores_differ"])
        self.assertEqual(r["route_score_delta_parent_to_current"], 2.0)
        self.assertEqual(r["fix_vs_current"]["scores_changed"], 0)
        self.assertTrue(r["solution_same_at_parent"])

    def test_coordinate_change_is_not_only_scores(self):
        moved = OLD.replace("4 0 4", "4 0 5")
        texts = {"parent": (moved, SOL % 12), "fix": (OLD, SOL % 12), "current": (OLD, SOL % 12)}
        r = P.check_family(texts)
        self.assertFalse(r["parent_vs_current"]["only_scores_differ"])
        self.assertEqual(r["parent_vs_current"]["scores_changed"], 0)

    def test_limit_change_is_reported(self):
        texts = {"parent": (OLD.replace("COST_LIMIT : 20", "COST_LIMIT : 25"), SOL % 12),
                 "fix": (OLD, SOL % 12), "current": (OLD, SOL % 12)}
        r = P.check_family(texts)
        self.assertEqual(r["parent_vs_current"]["head_diff"], ["COST_LIMIT"])
        self.assertFalse(r["parent_vs_current"]["only_scores_differ"])

    def test_missing_parent_file_and_changed_solution(self):
        texts = {"parent": (None, (SOL % 12).replace("\n3\n", "\n4\n")), "fix": (NEW, None),
                 "current": (NEW, SOL % 12)}
        r = P.check_family(texts)
        self.assertEqual(r["parent"]["status"], "missing_file")
        self.assertNotIn("parent_vs_current", r)
        self.assertFalse(r["solution_same_at_parent"])
        self.assertIsNone(r["solution_same_at_fix"])

    def test_missing_current_route(self):
        r = P.check_family({"parent": (OLD, SOL % 12), "fix": (NEW, SOL % 12), "current": (NEW, None)})
        self.assertEqual(r["status"], "missing_current")

    def test_run_writes_tally(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for fam in P.FIXED + P.CONTROLS:
                for key in P.COMMITS:
                    inst = OLD if (key == "parent" and fam in P.FIXED) else NEW
                    for rel, text in ((P.rel_inst(fam), inst), (P.rel_sol(fam), SOL % 12)):
                        path = P.local(d, key, rel)
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(text)
            P.run(d, d)
            import json
            with open(os.path.join(d, "oplib-prefix", "prefix.json"), encoding="utf-8") as f:
                t = json.load(f)["tally"]
            self.assertEqual(t["checks"]["Q1"], "held")
            self.assertEqual(t["checks"]["Q2"], "held")
            self.assertEqual(t["checks"]["Q3"], "did not hold")  # rat99 is inconsistent with NEW here
            self.assertEqual(t["checks"]["Q5"], "held")
            self.assertEqual(t["checks"]["Q6"], "held")
            self.assertTrue(os.path.exists(os.path.join(d, "oplib-prefix", "prefix.md")))


if __name__ == "__main__":
    unittest.main()

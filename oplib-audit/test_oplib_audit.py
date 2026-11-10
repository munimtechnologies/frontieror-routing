"""Tests for the OPLib consistency census.

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import oplib_audit as A  # noqa: E402

INST = """NAME : toy
COMMENT : five nodes on a line
TYPE : OP
DIMENSION: 5
COST_LIMIT : 20
EDGE_WEIGHT_TYPE : EUC_2D
NODE_COORD_SECTION
1 0 0
2 3 0
3 6 0
4 0 4
5 100 100
NODE_SCORE_SECTION
1 1
2 5
3 7
4 2
5 50
DEPOT_SECTION
 1
 -1
EOF
"""

SOL = """NAME : toy
TYPE : OP
DIMENSION : 5
COST_LIMIT : 20
ROUTE_NODES : 3
ROUTE_SCORE : %s
ROUTE_COST : %s
NODE_SEQUENCE_SECTION
1
2
3
-1
EOF
"""


class Parsing(unittest.TestCase):
    def test_header_and_sections(self):
        inst = A.Instance(INST)
        self.assertEqual(inst.n, 5)
        self.assertEqual(inst.limit, 20.0)
        self.assertEqual(inst.depot, 1)
        self.assertEqual(inst.score[5], 50.0)
        self.assertEqual(inst.coords[4], (0.0, 4.0))

    def test_solution_sequence_stops_at_minus_one(self):
        head, seq = A.parse_sol(SOL % (13, 12))
        self.assertEqual(seq, [1, 2, 3])
        self.assertEqual(head["ROUTE_SCORE"], "13")


class Distances(unittest.TestCase):
    def test_euc_2d_rounds_to_nearest(self):
        inst = A.Instance(INST)
        self.assertEqual(inst.d(1, 2), 3.0)
        self.assertEqual(inst.d(2, 4), 5.0)
        self.assertEqual(inst.d(1, 1), 0.0)

    def test_att(self):
        self.assertEqual(A.att(10.0, 0.0), 4)  # sqrt(10) = 3.16 -> 3 < 3.16 -> 4
        self.assertEqual(A.att(0.0, 0.0), 0)

    def test_explicit_formats(self):
        M = A.explicit_matrix([1, 2, 3], 3, "UPPER_ROW")
        self.assertEqual((M[0][1], M[0][2], M[1][2], M[2][1]), (1, 2, 3, 3))
        M = A.explicit_matrix([0, 1, 0, 2, 3, 0], 3, "LOWER_DIAG_ROW")
        self.assertEqual((M[1][0], M[2][0], M[2][1], M[0][2]), (1, 2, 3, 2))
        M = A.explicit_matrix([0, 4, 5, 4, 0, 6, 5, 6, 0], 3, "FULL_MATRIX")
        self.assertEqual((M[0][1], M[1][2], M[2][0]), (4, 6, 5))

    def test_geo_is_symmetric_integer(self):
        p, q = A.geo_latlon(38.24, 20.42), A.geo_latlon(39.57, 26.15)
        d1, d2 = A.geo_dist(p, q), A.geo_dist(q, p)
        self.assertEqual(d1, d2)
        self.assertIsInstance(d1, int)
        self.assertGreater(d1, 0)


class Audit(unittest.TestCase):
    def test_consistent_pair(self):
        inst = A.Instance(INST)
        head, seq = A.parse_sol(SOL % (13, 12))  # 1+5+7 with depot, cost 3+3+6
        r = A.audit_pair(inst, head, seq)
        self.assertEqual(r["cost"], 12.0)
        self.assertEqual(r["score_with_depot"], 13.0)
        self.assertEqual(r["score_without_depot"], 12.0)
        self.assertTrue(r["score_matches_with_depot"])
        self.assertEqual(r["status"], "consistent")

    def test_score_without_depot_also_counts_as_match(self):
        inst = A.Instance(INST)
        head, seq = A.parse_sol(SOL % (12, 12))
        r = A.audit_pair(inst, head, seq)
        self.assertEqual(r["status"], "consistent")
        self.assertFalse(r["score_matches_with_depot"])

    def test_wrong_score_and_wrong_cost_are_flagged(self):
        inst = A.Instance(INST)
        r = A.audit_pair(inst, *A.parse_sol(SOL % (20, 12)))
        self.assertEqual(r["status"], "inconsistent")
        self.assertEqual(r["score_diff"], 7.0)
        r = A.audit_pair(inst, *A.parse_sol(SOL % (13, 11)))
        self.assertEqual(r["status"], "inconsistent")
        self.assertFalse(r["cost_matches"])

    def test_over_limit_is_flagged(self):
        inst = A.Instance(INST.replace("COST_LIMIT : 20", "COST_LIMIT : 10"))
        r = A.audit_pair(inst, *A.parse_sol(SOL % (13, 12)))
        self.assertFalse(r["fits_limit"])
        self.assertEqual(r["status"], "inconsistent")

    def test_unknown_node_is_bad_route(self):
        inst = A.Instance(INST)
        r = A.audit_pair(inst, *A.parse_sol((SOL % (13, 12)).replace("\n3\n", "\n9\n")))
        self.assertEqual(r["status"], "bad_route")


class Gen3(unittest.TestCase):
    def test_readings(self):
        text = INST.replace("2 3 0", "2 10 0").replace("3 6 0", "3 5 0").replace("4 0 4", "4 2.4 0")
        text = text.replace("5 100 100", "5 0 7")
        inst = A.Instance(text)
        vs = A.gen3_variants(inst)
        # raw distances 10, 5, 2.4, 7 from the depot; max 10
        self.assertEqual(vs["floor_raw"], {2: 100, 3: 50, 4: 24, 5: 70})
        self.assertEqual(vs["round_raw"][3], 51)
        self.assertEqual(vs["floor_tsplib"][4], 20)  # nint(2.4) = 2 -> 1 + floor(19.8)
        inst.score = {1: 0, 2: 100, 3: 50, 4: 24, 5: 70}
        self.assertEqual(A.match_rate(vs["floor_raw"], inst.score, inst.depot), 1.0)
        self.assertLess(A.match_rate(vs["round_raw"], inst.score, inst.depot), 1.0)


if __name__ == "__main__":
    unittest.main()

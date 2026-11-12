"""Tests for the gpshim 0.2.1 change: ObjVal of a quadratic objective is the objective as written at the solution.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Run from a folder holding the patched gpshim.py: python -m unittest -v test_gpshim021
"""
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gpshim as gp  # noqa: E402
from gpshim import GRB  # noqa: E402


class TestTrueObjVal(unittest.TestCase):
    def setUp(self):
        gp.set_deadline(None)

    def test_version(self):
        self.assertEqual(gp.__version__, "0.2.1")

    def test_secant_min_objval_is_true_objective(self):
        # min (t - 3.3)^2 + b, t >= 5 - 5 b, t in [0, 10]: the secant model over-estimates the square
        m = gp.Model()
        b = m.addVar(vtype=GRB.BINARY)
        t = m.addVar(lb=0, ub=10)
        m.addConstr(t >= 5 - 5 * b)
        m.setObjective((t - 3.3) * (t - 3.3) + b, GRB.MINIMIZE)
        m.optimize()
        info = gp._STATS[-1]["reform"]
        self.assertEqual(info["secants"], 1)
        true_obj = (t.X - 3.3) ** 2 + b.X
        self.assertAlmostEqual(m.ObjVal, true_obj, places=9)
        self.assertIn("obj_solver", info)
        self.assertGreaterEqual(info["obj_solver"], m.ObjVal - 1e-7)  # the secant value is never below the truth
        self.assertAlmostEqual(gp._STATS[-1]["obj"], m.ObjVal, places=9)

    def test_secant_max_objval_is_true_objective(self):
        # max 3 b + t - (t - 1.7)^2, t <= 2 + 2 b, t in [0, 4]
        m = gp.Model()
        b = m.addVar(vtype=GRB.BINARY)
        t = m.addVar(lb=0, ub=4)
        m.addConstr(t <= 2 + 2 * b)
        m.setObjective(3 * b + t - (t - 1.7) * (t - 1.7), GRB.MAXIMIZE)
        m.optimize()
        self.assertEqual(gp._STATS[-1]["reform"]["secants"], 1)
        true_obj = 3 * b.X + t.X - (t.X - 1.7) ** 2
        self.assertAlmostEqual(m.ObjVal, true_obj, places=9)
        # true optimum: b = 1, t = 2.2, value 3 + 2.2 - 0.25 = 4.95; 32 pieces on [0, 4] lose at most 0.0157
        self.assertGreaterEqual(m.ObjVal, 4.95 - 0.016)
        self.assertLessEqual(m.ObjVal, 4.95 + 1e-7)

    def test_many_squares_like_he2020(self):
        # routing-style cost plus a sum of squared lateness terms; checker-style recomputation must match ObjVal
        rng = random.Random(7)
        n = 6
        m = gp.Model()
        y = m.addVars(n, vtype=GRB.BINARY, name="y")
        late = m.addVars(n, lb=0, ub=5, name="late")
        cost = [rng.randint(1, 9) for _ in range(n)]
        due = [rng.uniform(0.5, 4.5) for _ in range(n)]
        for i in range(n):
            m.addConstr(late[i] >= due[i] - 5 * y[i])
        m.addConstr(gp.quicksum(y[i] for i in range(n)) <= 3)
        obj = gp.QuadExpr()
        for i in range(n):
            obj += cost[i] * y[i] + 0.7 * late[i] * late[i]
        m.setObjective(obj, GRB.MINIMIZE)
        m.optimize()
        self.assertEqual(gp._STATS[-1]["reform"]["secants"], n)
        recomputed = sum(cost[i] * y[i].X + 0.7 * late[i].X ** 2 for i in range(n))
        self.assertAlmostEqual(m.ObjVal, recomputed, places=9)
        self.assertAlmostEqual(obj.getValue(), recomputed, places=9)

    def test_binary_products_unchanged(self):
        m = gp.Model()
        x = m.addVars(3, vtype=GRB.BINARY)
        m.addConstr(x[0] + x[1] + x[2] <= 2)
        m.setObjective(2 * x[0] * x[1] + 3 * x[1] * x[2] - x[0] + 0.5, GRB.MAXIMIZE)  # x1 = x2 = 1: 3.5
        m.optimize()
        self.assertEqual(gp._STATS[-1]["reform"]["secants"], 0)
        self.assertAlmostEqual(m.ObjVal, 3.5, places=6)

    def test_linear_model_untouched(self):
        m = gp.Model()
        x = m.addVar(lb=0, ub=4, vtype=GRB.INTEGER)
        m.setObjective(2 * x + 1, GRB.MAXIMIZE)
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, 9.0, places=6)
        self.assertNotIn("obj_solver", gp._STATS[-1]["reform"])

    def test_continuous_qp_objval(self):
        m = gp.Model()
        x = m.addVar(name="x")
        y = m.addVar(name="y")
        m.addConstr(x + y <= 1)
        m.setObjective((x - 1) * (x - 1) + (y - 2) * (y - 2), GRB.MINIMIZE)
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, (x.X - 1) ** 2 + (y.X - 2) ** 2, places=9)
        self.assertAlmostEqual(m.ObjVal, 2.0, delta=1e-4)


if __name__ == "__main__":
    unittest.main()

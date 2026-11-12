"""Tests for gpshim 0.2 (a gurobipy-compatible layer on HiGHS) and gp_solve.py.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Needs numpy and highspy (or scipy for the linear tests). Run from this folder: python -m unittest -v test_gpshim
"""
import itertools
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gpshim as gp  # noqa: E402
from gpshim import GRB  # noqa: E402


class TestModelling(unittest.TestCase):
    """The 0.1 behaviour, unchanged."""

    def setUp(self):
        gp.set_deadline(None)

    def test_knapsack_brute_force(self):
        for seed in range(5):
            rng = random.Random(seed)
            n = 12
            w = [rng.randint(1, 30) for _ in range(n)]
            p = [rng.randint(1, 40) for _ in range(n)]
            cap = sum(w) // 3
            m = gp.Model("knap")
            x = m.addVars(n, vtype=GRB.BINARY, name="x")
            m.addConstr(gp.quicksum(w[i] * x[i] for i in range(n)) <= cap, name="cap")
            m.setObjective(gp.quicksum(p[i] * x[i] for i in range(n)), GRB.MAXIMIZE)
            m.optimize()
            best = max(sum(p[i] for i in range(n) if s >> i & 1) for s in range(1 << n)
                       if sum(w[i] for i in range(n) if s >> i & 1) <= cap)
            self.assertEqual(m.Status, GRB.OPTIMAL)
            self.assertAlmostEqual(m.ObjVal, best, places=6)
            self.assertAlmostEqual(sum(p[i] * round(x[i].X) for i in range(n)), best, places=6)
            self.assertLessEqual(sum(w[i] * round(x[i].X) for i in range(n)), cap)

    def test_assignment_tupledict(self):
        rng = random.Random(7)
        n = 5
        c = {(i, j): rng.randint(1, 50) for i in range(n) for j in range(n)}
        m = gp.Model()
        x = m.addVars(range(n), range(n), vtype=GRB.BINARY, name="x")
        for i in range(n):
            m.addConstr(x.sum(i, "*") == 1)
            m.addConstr(x.sum("*", i) == 1)
        m.setObjective(x.prod(c), GRB.MINIMIZE)
        m.optimize()
        best = min(sum(c[i, pi[i]] for i in range(n)) for pi in itertools.permutations(range(n)))
        self.assertAlmostEqual(m.ObjVal, best, places=6)
        self.assertEqual(sorted(x.keys())[0], (0, 0))
        self.assertEqual(x[1, 2].VarName, "x[1,2]")

    def test_lp_duals(self):
        m = gp.Model()
        x = m.addVar(name="x")
        y = m.addVar(name="y")
        c1 = m.addConstr(x + 2 * y >= 4)
        c2 = m.addConstr(3 * x + y >= 6)
        m.setObjective(x + y)
        m.optimize()
        self.assertEqual(m.Status, GRB.OPTIMAL)
        self.assertAlmostEqual(m.ObjVal, 2.8, places=6)
        self.assertAlmostEqual(x.X, 1.6, places=6)
        self.assertAlmostEqual(y.x, 1.2, places=6)
        self.assertAlmostEqual(c1.Pi, 0.4, places=6)
        self.assertAlmostEqual(c2.Pi, 0.2, places=6)
        self.assertAlmostEqual(c1.Slack, 0.0, places=6)

    def test_infeasible_and_hasattr(self):
        m = gp.Model()
        x = m.addVar(lb=0, ub=10)
        m.addConstr(x >= 2)
        m.addConstr(x <= 1)
        m.optimize()
        self.assertIn(m.Status, (GRB.INFEASIBLE, GRB.INF_OR_UNBD))
        self.assertEqual(m.SolCount, 0)
        with self.assertRaises(gp.GurobiError):
            _ = m.ObjVal
        with self.assertRaises(gp.GurobiError):
            _ = x.X
        # reference scripts write `m.MIPGap if hasattr(m, "MIPGap") else None`: must not crash
        self.assertFalse(hasattr(m, "MIPGap"))
        self.assertFalse(hasattr(x, "X"))
        m.computeIIS()  # does nothing, marks nothing
        self.assertEqual([c for c in m.getConstrs() if c.IISConstr], [])

    def test_model_sense_attribute_and_constant(self):
        m = gp.Model()
        x = m.addVar(ub=4, vtype=GRB.INTEGER)
        m.setObjective(2 * x + 3)
        m.ModelSense = GRB.MAXIMIZE
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, 11.0, places=6)
        self.assertEqual(m.ModelSense, GRB.MAXIMIZE)

    def test_indicator_big_m(self):
        m = gp.Model()
        b = m.addVar(vtype=GRB.BINARY)
        x = m.addVar(lb=0, ub=10)
        m.addConstr((b == 1) >> (x <= 3))
        m.setObjective(x + 20 * b, GRB.MAXIMIZE)
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, 23.0, places=6)
        self.assertAlmostEqual(x.X, 3.0, places=6)
        m2 = gp.Model()
        b2 = m2.addVar(vtype=GRB.BINARY)
        x2 = m2.addVar(lb=0, ub=10)
        m2.addGenConstrIndicator(b2, 0, x2, GRB.GREATER_EQUAL, 5)
        m2.setObjective(x2 + 7 * b2, GRB.MINIMIZE)
        m2.optimize()
        self.assertAlmostEqual(m2.ObjVal, 5.0, places=6)  # b2 = 0 forces x2 >= 5 (cost 5) < b2 = 1 (cost 7)

    def test_numpy_scalars(self):
        import numpy as np
        m = gp.Model()
        x = m.addVar(ub=1)
        y = m.addVar(ub=1)
        e = np.float64(2.0) * x + np.int64(3) * y
        self.assertIsInstance(e, gp.LinExpr)
        m.setObjective(e, GRB.MAXIMIZE)
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, 5.0, places=6)

    def test_unsupported_raise(self):
        m = gp.Model()
        x = m.addVar(ub=1)
        y = m.addVar(ub=1)
        z = m.addVar(ub=1)
        with self.assertRaises(gp.GurobiError):
            _ = (x * y) * z  # degree 3
        with self.assertRaises(gp.GurobiError):
            m.addMVar(3)

    def test_deadline_caps_time_limit(self):
        m = gp.Model()
        x = m.addVar(ub=1)
        m.setObjective(x)
        m.setParam("TimeLimit", 100)
        gp.set_deadline(time.time() + 0.2)
        m.optimize()
        gp.set_deadline(None)
        self.assertLessEqual(gp._STATS[-1]["time_limit"], 0.5 + 1e-9)

    def test_case_insensitive_attributes_and_user_attrs(self):
        m = gp.Model()
        v = m.addVar(lb=0, ub=GRB.INFINITY, name="v")
        self.assertEqual(v.UB, GRB.INFINITY)
        v.lb = 1
        v.UB = 2
        m._vars = "user data"  # gurobipy code stores callback data like this
        m.setObjective(v, GRB.MINIMIZE)
        m.optimize()
        self.assertAlmostEqual(v.x, 1.0, places=6)
        self.assertEqual(v.X, v.x)
        self.assertEqual(m.NumVars, 1)
        self.assertEqual(m._vars, "user data")

    def test_old_style_constraint_and_linexpr_forms(self):
        m = gp.Model()
        x = m.addVar(ub=10)
        y = m.addVar(ub=10)
        m.addConstr(x + y, GRB.LESS_EQUAL, 5, "c")
        e = gp.LinExpr([1.0, 2.0], [x, y])
        e.addTerms([1.0], [x])
        e.addConstant(1.0)
        m.setObjective(e, GRB.MAXIMIZE)
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, 11.0, places=6)  # e = 2x + 2y + 1 with x + y <= 5
        self.assertAlmostEqual(e.getValue(), 11.0, places=6)
        self.assertIsNotNone(m.getConstrByName("c"))

    def test_relax_bound(self):
        m = gp.Model()
        x = m.addVars(3, vtype=GRB.BINARY)
        m.addConstr(2 * x[0] + 2 * x[1] + 2 * x[2] <= 3)
        m.setObjective(x.sum(), GRB.MAXIMIZE)
        r = m.relax()
        r.optimize()
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, 1.0, places=6)
        self.assertAlmostEqual(r.ObjVal, 1.5, places=6)

    def test_injection_as_gurobipy(self):
        saved = sys.modules.get("gurobipy")
        sys.modules["gurobipy"] = gp
        try:
            import gurobipy as g2
            from gurobipy import GRB as G2, quicksum
            m = g2.Model("inj")
            z = m.addVars([(1, 2), (3, 4)], vtype=G2.BINARY)
            m.addConstr(quicksum(z.values()) <= 1)
            m.setObjective(3 * z[1, 2] + 4 * z[3, 4], G2.MAXIMIZE)
            m.optimize()
            self.assertAlmostEqual(m.objVal, 4.0, places=6)
        finally:
            if saved is None:
                sys.modules.pop("gurobipy", None)
            else:
                sys.modules["gurobipy"] = saved


class TestQuadratic(unittest.TestCase):
    def setUp(self):
        gp.set_deadline(None)

    def test_binary_products_exact_brute_force(self):
        # quadratic knapsack: max sum p_i x_i + sum_{i<j} P_ij x_i x_j, sum w_i x_i <= cap
        for seed in range(3):
            rng = random.Random(100 + seed)
            n = 8
            p = [rng.randint(0, 20) for _ in range(n)]
            P = [[rng.randint(-5, 15) for _ in range(n)] for _ in range(n)]
            w = [rng.randint(1, 20) for _ in range(n)]
            cap = sum(w) // 2
            m = gp.Model("qkp")
            x = m.addVars(n, vtype=GRB.BINARY, name="x")
            m.addConstr(gp.quicksum(w[i] * x[i] for i in range(n)) <= cap)
            obj = gp.QuadExpr()
            for i in range(n):
                obj += p[i] * x[i]
                for j in range(i + 1, n):
                    obj += P[i][j] * x[i] * x[j]
            m.setObjective(obj, GRB.MAXIMIZE)
            m.optimize()

            def val(s):
                return (sum(p[i] for i in range(n) if s >> i & 1)
                        + sum(P[i][j] for i in range(n) for j in range(i + 1, n) if s >> i & 1 and s >> j & 1))
            best = max(val(s) for s in range(1 << n) if sum(w[i] for i in range(n) if s >> i & 1) <= cap)
            self.assertEqual(m.Status, GRB.OPTIMAL)
            self.assertAlmostEqual(m.ObjVal, best, places=5)
            chosen = sum(1 << i for i in range(n) if x[i].X > 0.5)
            self.assertEqual(val(chosen), best)
            self.assertAlmostEqual(obj.getValue(), best, places=5)
            self.assertEqual(gp._STATS[-1]["reform"]["secants"], 0)

    def test_binary_times_bounded_continuous_in_constraint(self):
        m = gp.Model()
        b = m.addVar(vtype=GRB.BINARY, name="b")
        y = m.addVar(lb=0, ub=10, name="y")
        m.addConstr(b * y <= 4)  # if b = 1 then y <= 4
        m.setObjective(y + 7 * b, GRB.MAXIMIZE)  # b = 0: 10; b = 1: 4 + 7 = 11
        m.optimize()
        self.assertEqual(m.NumQConstrs, 1)
        self.assertAlmostEqual(m.ObjVal, 11.0, places=6)
        self.assertAlmostEqual(b.X, 1.0, places=6)
        self.assertAlmostEqual(y.X, 4.0, places=6)

    def test_convex_qp_continuous(self):
        m = gp.Model()
        x = m.addVar(name="x")
        y = m.addVar(name="y")
        m.addConstr(x + y <= 1)
        m.setObjective((x - 1) * (x - 1) + (y - 2) * (y - 2), GRB.MINIMIZE)  # optimum (0, 1), value 2
        m.optimize()
        self.assertTrue(gp._STATS[-1]["reform"]["qp"])
        self.assertEqual(m.Status, GRB.OPTIMAL)
        self.assertAlmostEqual(m.ObjVal, 2.0, delta=1e-4)
        self.assertAlmostEqual(x.X, 0.0, delta=1e-3)
        self.assertAlmostEqual(y.X, 1.0, delta=1e-3)

    def test_concave_max_qp_flips_sense(self):
        m = gp.Model()
        x = m.addVar(lb=0, ub=10)
        m.setObjective(-(x - 3) ** 2, GRB.MAXIMIZE)  # optimum x = 3, value 0
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, 0.0, delta=1e-4)
        self.assertAlmostEqual(x.X, 3.0, delta=1e-3)

    def test_secant_square_in_mip_objective(self):
        # min (t - 3.3)^2 + b, t >= 5 - 5 b: b = 0 costs 2.89, b = 1 costs 1 (t = 3.3)
        m = gp.Model()
        b = m.addVar(vtype=GRB.BINARY)
        t = m.addVar(lb=0, ub=10)
        m.addConstr(t >= 5 - 5 * b)
        m.setObjective((t - 3.3) * (t - 3.3) + b, GRB.MINIMIZE)
        m.optimize()
        self.assertEqual(gp._STATS[-1]["reform"]["secants"], 1)
        self.assertAlmostEqual(b.X, 1.0, places=6)
        true_obj = (t.X - 3.3) ** 2 + b.X
        # 32 segments of [0, 10]: the interpolation over-estimates by at most (10/32)^2/4 = 0.0244
        self.assertLessEqual(true_obj, m.ObjVal + 1e-6)
        self.assertLessEqual(m.ObjVal, 1.0 + 0.0245)
        self.assertLessEqual(abs(t.X - 3.3), 10.0 / 32 + 1e-6)

    def test_secant_quadratic_constraint_is_conservative(self):
        m = gp.Model()
        x = m.addVar(lb=0, ub=1)
        y = m.addVar(lb=0, ub=1)
        m.addQConstr(x * x + y * y <= 1)
        m.setObjective(x + y, GRB.MAXIMIZE)  # optimum sqrt(2) = 1.41421
        m.optimize()
        self.assertLessEqual(x.X ** 2 + y.X ** 2, 1.0 + 1e-7)
        self.assertGreaterEqual(x.X + y.X, 1.41)

    def test_secant_uses_bounds_implied_by_constraints(self):
        # portfolio-style: x >= 0 with no declared upper bound, but x1 + x2 == 1 implies x <= 1
        m = gp.Model()
        x1 = m.addVar(lb=0)
        x2 = m.addVar(lb=0)
        z1 = m.addVar(vtype=GRB.BINARY)
        z2 = m.addVar(vtype=GRB.BINARY)
        m.addConstr(x1 + x2 == 1)
        m.addConstr(x1 <= z1)
        m.addConstr(x2 <= z2)
        m.setObjective(x1 * x1 + x2 * x2, GRB.MINIMIZE)  # optimum x1 = x2 = 0.5, value 0.5
        m.optimize()
        info = gp._STATS[-1]["reform"]
        self.assertGreaterEqual(info["implied_bounds_used"], 1)
        self.assertEqual(info["secants"], 2)
        self.assertLessEqual(x1.X ** 2 + x2.X ** 2, m.ObjVal + 1e-6)
        self.assertLessEqual(m.ObjVal, 0.5 + 0.01)
        self.assertAlmostEqual(x1.X + x2.X, 1.0, places=6)

    def test_nonconvex_raises(self):
        m = gp.Model()
        x = m.addVar(lb=0, ub=5)
        y = m.addVar(lb=0, ub=5)
        b = m.addVar(vtype=GRB.BINARY)
        m.addConstr(x + y + b <= 6)
        m.setObjective(x * y + b, GRB.MAXIMIZE)  # bilinear continuous in a MIP
        with self.assertRaises(gp.GurobiError):
            m.optimize()


class TestGeneral(unittest.TestCase):
    def setUp(self):
        gp.set_deadline(None)

    def test_max_and_constant(self):
        m = gp.Model()
        x1 = m.addVar(lb=0, ub=10)
        x2 = m.addVar(lb=0, ub=10)
        r = m.addVar(lb=0, ub=100)
        m.addConstr(x1 <= 4)
        m.addConstr(x2 <= 5)
        m.addGenConstrMax(r, [x1, x2], constant=3)
        m.setObjective(r, GRB.MAXIMIZE)  # r = max(x1, x2, 3) <= 5
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, 5.0, places=6)
        m2 = gp.Model()
        a1 = m2.addVar(lb=0, ub=1)
        a2 = m2.addVar(lb=0, ub=2)
        r2 = m2.addVar(lb=0, ub=100)
        m2.addGenConstrMax(r2, [a1, a2], constant=3)
        m2.setObjective(r2, GRB.MAXIMIZE)  # max(a1, a2, 3) = 3 whatever a1, a2 are
        m2.optimize()
        self.assertAlmostEqual(m2.ObjVal, 3.0, places=6)

    def test_min(self):
        m = gp.Model()
        x1 = m.addVar(lb=0, ub=10)
        x2 = m.addVar(lb=0, ub=10)
        r = m.addVar(lb=0, ub=10)
        m.addConstr(x1 >= 4)
        m.addConstr(x2 >= 6)
        m.addGenConstrMin(r, [x1, x2])
        m.setObjective(r, GRB.MINIMIZE)  # r = min(x1, x2) >= 4
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, 4.0, places=6)
        m.setObjective(r, GRB.MAXIMIZE)  # r = min(x1, x2) <= 10
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, 10.0, places=6)

    def test_abs(self):
        m = gp.Model()
        x = m.addVar(lb=-5, ub=5)
        r = m.addVar(lb=0, ub=100)
        m.addConstr(x <= -3)
        m.addGenConstrAbs(r, x)
        m.setObjective(r, GRB.MINIMIZE)  # |x| with x <= -3: 3
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, 3.0, places=6)
        m2 = gp.Model()
        x2 = m2.addVar(lb=-5, ub=2)
        r2 = m2.addVar(lb=0, ub=100)
        m2.addConstr(x2 >= -4)
        m2.addGenConstrAbs(r2, x2)
        m2.setObjective(r2, GRB.MAXIMIZE)  # |x| with -4 <= x <= 2: 4
        m2.optimize()
        self.assertAlmostEqual(m2.ObjVal, 4.0, places=6)

    def test_and_or(self):
        m = gp.Model()
        b1 = m.addVar(vtype=GRB.BINARY)
        b2 = m.addVar(vtype=GRB.BINARY)
        r = m.addVar(vtype=GRB.BINARY)
        m.addConstr(b1 == 1)
        m.addConstr(b2 == 0)
        m.addGenConstrAnd(r, [b1, b2])
        m.setObjective(r, GRB.MAXIMIZE)
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, 0.0, places=6)
        m2 = gp.Model()
        c1 = m2.addVar(vtype=GRB.BINARY)
        c2 = m2.addVar(vtype=GRB.BINARY)
        r2 = m2.addVar(vtype=GRB.BINARY)
        m2.addConstr(c1 == 1)
        m2.addGenConstrOr(r2, [c1, c2])
        m2.setObjective(r2, GRB.MINIMIZE)
        m2.optimize()
        self.assertAlmostEqual(m2.ObjVal, 1.0, places=6)

    def test_pwl(self):
        m = gp.Model()
        x = m.addVar(lb=0, ub=3)
        y = m.addVar(lb=-GRB.INFINITY)
        m.addGenConstrPWL(x, y, [0, 1, 3], [0, 2, 3])
        m.addConstr(x == 2)
        m.setObjective(y, GRB.MINIMIZE)
        m.optimize()
        self.assertAlmostEqual(y.X, 2.5, places=6)
        m.setObjective(y, GRB.MAXIMIZE)
        m.optimize()
        self.assertAlmostEqual(y.X, 2.5, places=6)


def _components(n, edges):
    adj = {i: [] for i in range(n)}
    for i, j in edges:
        adj[i].append(j)
        adj[j].append(i)
    seen, comps = set(), []
    for s in range(n):
        if s in seen:
            continue
        comp, stack = [], [s]
        seen.add(s)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        comps.append(comp)
    return comps


class TestLazyCallbacks(unittest.TestCase):
    def setUp(self):
        gp.set_deadline(None)

    def test_tsp_subtour_callback_matches_brute_force(self):
        for seed in range(3):
            rng = random.Random(seed)
            n = 7
            pts = [(rng.randint(0, 100), rng.randint(0, 100)) for _ in range(n)]
            d = {(i, j): round(math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]))
                 for i in range(n) for j in range(i + 1, n)}
            m = gp.Model("tsp")
            m.Params.LazyConstraints = 1
            x = m.addVars(d.keys(), vtype=GRB.BINARY, name="x")
            for i in range(n):
                m.addConstr(gp.quicksum(x[min(i, j), max(i, j)] for j in range(n) if j != i) == 2)
            m.setObjective(x.prod(d), GRB.MINIMIZE)
            m._x = x
            m._calls = []

            def subtour(model, where):
                if where != GRB.Callback.MIPSOL:
                    return
                model._calls.append(where)
                vals = model.cbGetSolution(model._x)
                sel = [k for k, v in vals.items() if v > 0.5]
                for comp in _components(n, sel):
                    if len(comp) < n:
                        model.cbLazy(gp.quicksum(model._x[i, j] for i in comp for j in comp if i < j)
                                     <= len(comp) - 1)

            m.optimize(subtour)
            best = min(sum(d[min(a, b), max(a, b)] for a, b in zip((0,) + p, p + (0,)))
                       for p in itertools.permutations(range(1, n)))
            self.assertEqual(m.Status, GRB.OPTIMAL)
            self.assertAlmostEqual(m.ObjVal, best, places=6)
            used = [k for k in d if x[k].X > 0.5]
            self.assertEqual(len(used), n)
            self.assertEqual(len(_components(n, used)), 1)
            self.assertGreaterEqual(len(m._calls), 1)
            self.assertEqual(gp._STATS[-1]["reform"]["lazy_rounds"], len(m._calls))

    def test_lazy_terminate_and_plain(self):
        m = gp.Model()
        x = m.addVar(vtype=GRB.BINARY)
        m.setObjective(x, GRB.MAXIMIZE)

        def cut(model, where):
            if where == GRB.Callback.MIPSOL and model.cbGetSolution(x) > 0.5:
                model.cbLazy(x <= 0)
        m.optimize(cut)
        self.assertAlmostEqual(m.ObjVal, 0.0, places=6)
        self.assertAlmostEqual(x.X, 0.0, places=6)

        m2 = gp.Model()
        y = m2.addVar(vtype=GRB.BINARY)
        m2.setObjective(y, GRB.MAXIMIZE)

        def cut_and_stop(model, where):
            if where == GRB.Callback.MIPSOL:
                model.cbLazy(y, GRB.LESS_EQUAL, 0)
                model.terminate()
        m2.optimize(cut_and_stop)
        self.assertEqual(m2.Status, GRB.INTERRUPTED)
        self.assertEqual(m2.SolCount, 0)


class TestMultiObjective(unittest.TestCase):
    def test_hierarchical_matches_brute_force(self):
        rng = random.Random(5)
        n = 7
        w = [rng.randint(1, 10) for _ in range(n)]
        cost = [rng.randint(1, 30) for _ in range(n)]
        cap = sum(w) // 2
        m = gp.Model()
        x = m.addVars(n, vtype=GRB.BINARY)
        m.addConstr(gp.quicksum(w[i] * x[i] for i in range(n)) <= cap)
        m.ModelSense = GRB.MINIMIZE
        m.setObjectiveN(gp.quicksum(-1 * x[i] for i in range(n)), index=0, priority=2, abstol=0, reltol=0)
        m.setObjectiveN(gp.quicksum(cost[i] * x[i] for i in range(n)), index=1, priority=1, abstol=0, reltol=0)
        m.optimize()
        feas = [s for s in range(1 << n) if sum(w[i] for i in range(n) if s >> i & 1) <= cap]
        cnt = max(bin(s).count("1") for s in feas)
        best_cost = min(sum(cost[i] for i in range(n) if s >> i & 1) for s in feas if bin(s).count("1") == cnt)
        chosen = [i for i in range(n) if x[i].X > 0.5]
        self.assertEqual(len(chosen), cnt)
        self.assertEqual(sum(cost[i] for i in chosen), best_cost)
        self.assertAlmostEqual(m.ObjVal, -cnt, places=6)  # ObjVal = objective 0
        self.assertEqual(m.NumObj, 2)


FAKE_CODE = textwrap.dedent('''
    import argparse, json, time
    import gurobipy as gp
    from gurobipy import GRB
    _START = time.time()

    def main():
        ap = argparse.ArgumentParser()
        ap.add_argument("--instance_path", required=True)
        ap.add_argument("--solution_path", required=True)
        ap.add_argument("--time_limit", type=int, required=True)
        ap.add_argument("--log_path", default=None)
        a = ap.parse_args()
        data = json.load(open(a.instance_path))
        m = gp.Model("fake")
        m.setParam("TimeLimit", a.time_limit)
        x = m.addVars(len(data["p"]), vtype=GRB.BINARY)
        m.addConstr(gp.quicksum(data["w"][i] * x[i] for i in x) <= data["cap"])
        m.setObjective(gp.quicksum(data["p"][i] * x[i] for i in x), GRB.MAXIMIZE)
        m.optimize()
        sol = {"objective_value": m.ObjVal if m.SolCount else None,
               "chosen": [i for i in x if x[i].X > 0.5] if m.SolCount else [],
               "time_limit_seen": a.time_limit}
        json.dump(sol, open(a.solution_path, "w"))

    if __name__ == "__main__":
        main()
''')


class TestEntryPoint(unittest.TestCase):
    def test_gp_solve_runs_reference_code(self):
        d = tempfile.mkdtemp(prefix="gpshim-test-")
        for name, src in (("solve.py", os.path.join(HERE, "gp_solve.py")), ("gpshim.py", os.path.join(HERE, "gpshim.py"))):
            with open(src, encoding="utf-8") as f, open(os.path.join(d, name), "w", encoding="utf-8") as g:
                g.write(f.read())
        with open(os.path.join(d, "gurobi_code.py"), "w", encoding="utf-8") as f:
            f.write(FAKE_CODE)
        inst = {"p": [10, 13, 7, 8], "w": [5, 7, 4, 3], "cap": 10}
        ip = os.path.join(d, "inst.json")
        op = os.path.join(d, "out.json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        t0 = time.time()
        p = subprocess.run([sys.executable, "solve.py", "--problem", "fake", "--instance", ip, "--output", op,
                            "--time-limit", "10"], cwd=d, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr[-800:])
        self.assertLess(time.time() - t0, 10.0)
        with open(op, encoding="utf-8") as f:
            sol = json.load(f)
        self.assertAlmostEqual(sol["objective_value"], 21.0, places=6)  # items 1 (13) + 3 (8): w 10
        self.assertEqual(sorted(sol["chosen"]), [1, 3])
        self.assertEqual(sol["time_limit_seen"], 8)  # 10 - max(2, 1.0)


if __name__ == "__main__":
    unittest.main()

"""Tests for gpshim (a gurobipy-compatible layer on HiGHS) and gp_solve.py.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Needs numpy and highspy (or scipy). Run from this folder: python -m unittest -v test_gpshim
"""
import itertools
import json
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

    def test_infeasible(self):
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

    def test_quadratic_raises(self):
        m = gp.Model()
        x = m.addVar()
        y = m.addVar()
        with self.assertRaises(gp.GurobiError):
            _ = x * y
        with self.assertRaises(gp.GurobiError):
            m.optimize(lambda model, where: None)

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

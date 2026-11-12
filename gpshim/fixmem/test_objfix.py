"""Tests for gpshim_objfix and the solve_probe entry point.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python fetch_base.py . && python -m unittest -v test_objfix

Needs numpy and highspy (no OR-Tools). gpshim.py comes from fetch_base.py.
"""
import importlib
import itertools
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gpshim as gp  # noqa: E402
import gpshim_objfix  # noqa: E402

GRB = gp.GRB


def fresh():
    """A gpshim module with the add-on installed once, and the record list cleared."""
    gpshim_objfix.install(gp)
    del gpshim_objfix.RECORDS[:]
    return gp


class TestTrueObjective(unittest.TestCase):
    def test_square_in_mip_objective_is_reported_exactly(self):
        # min x^2 + y, x in [0, 1], x >= 0.3, y binary. gpshim replaces x^2 in a MIP objective by its
        # piecewise-linear interpolation on 32 segments, which over-estimates 0.3^2 = 0.09 (0.0902344 at x = 0.3).
        g = fresh()
        m = g.Model()
        x = m.addVar(lb=0.0, ub=1.0, name="x")
        y = m.addVar(vtype=GRB.BINARY, name="y")
        m.addConstr(x >= 0.3)
        m.setObjective(x * x + y, GRB.MINIMIZE)
        m.optimize()
        self.assertEqual(m.SolCount, 1)
        self.assertAlmostEqual(m.ObjVal, x.X ** 2 + y.X, places=9)
        self.assertAlmostEqual(x.X, 0.3, places=5)
        recs = [r for r in gpshim_objfix.RECORDS if "after" in r]
        self.assertEqual(len(recs), 1)
        self.assertTrue(recs[0]["changed"])
        self.assertGreater(recs[0]["before"], recs[0]["after"] + 1e-4)

    def test_binary_products_at_optimum_unchanged(self):
        # quadratic knapsack, solved to optimality: the McCormick value equals the true value
        g = fresh()
        p = [[0, 5, 2, 0], [5, 0, 1, 4], [2, 1, 0, 3], [0, 4, 3, 0]]
        lin = [1, 2, 3, 1]
        w = [3, 4, 2, 3]
        cap = 7
        m = g.Model()
        x = [m.addVar(vtype=GRB.BINARY) for _ in range(4)]
        m.addConstr(g.quicksum(w[i] * x[i] for i in range(4)) <= cap)
        obj = g.quicksum(lin[i] * x[i] for i in range(4))
        obj = obj + g.quicksum(p[i][j] * x[i] * x[j] for i in range(4) for j in range(i + 1, 4))
        m.setObjective(obj, GRB.MAXIMIZE)
        m.optimize()
        best = None
        for bits in itertools.product((0, 1), repeat=4):
            if sum(w[i] * bits[i] for i in range(4)) <= cap:
                val = sum(lin[i] * bits[i] for i in range(4)) + sum(
                    p[i][j] * bits[i] * bits[j] for i in range(4) for j in range(i + 1, 4))
                best = val if best is None else max(best, val)
        self.assertAlmostEqual(m.ObjVal, best, places=6)
        recs = [r for r in gpshim_objfix.RECORDS if "after" in r]
        self.assertEqual(len(recs), 1)
        self.assertFalse(recs[0]["changed"])

    def test_linear_model_untouched(self):
        g = fresh()
        m = g.Model()
        x = m.addVar(ub=4.0)
        y = m.addVar(vtype=GRB.INTEGER, ub=3.0)
        m.addConstr(x + 2 * y <= 7.5)
        m.setObjective(x + 3 * y + 1.0, GRB.MAXIMIZE)
        m.optimize()
        self.assertAlmostEqual(m.ObjVal, 1.0 + x.X + 3 * y.X, places=6)
        self.assertEqual([r for r in gpshim_objfix.RECORDS if "after" in r], [])

    def test_true_objective_by_hand(self):
        g = fresh()
        m = g.Model()
        a = m.addVar(vtype=GRB.BINARY)
        b = m.addVar(vtype=GRB.BINARY)
        c = m.addVar(lb=0.0, ub=10.0)
        m.setObjective(2.0 * a * b + 3.0 * c + 0.5 * c * a + 7.0, GRB.MAXIMIZE)
        for v, val in ((a, 1.0), (b, 1.0), (c, 4.0)):
            object.__setattr__(v, "_x", val)
        self.assertAlmostEqual(gpshim_objfix.true_objective(m), 2.0 + 12.0 + 2.0 + 7.0, places=12)
        object.__setattr__(c, "_x", None)
        self.assertIsNone(gpshim_objfix.true_objective(m))

    def test_install_twice_wraps_once(self):
        g = fresh()
        first = g.Model.optimize
        gpshim_objfix.install(g)
        self.assertIs(g.Model.optimize, first)
        self.assertTrue(getattr(g.Model.optimize, "_mv2_objfix", False))


class TestEntryPoint(unittest.TestCase):
    def test_probe_writes_solution_and_stage_marks(self):
        code = '''
import argparse, json
import gurobipy as gp
from gurobipy import GRB
ap = argparse.ArgumentParser()
ap.add_argument("--instance_path"); ap.add_argument("--solution_path"); ap.add_argument("--time_limit", type=int)
a = ap.parse_args()
inst = json.load(open(a.instance_path))
m = gp.Model()
x = [m.addVar(vtype=GRB.BINARY) for _ in range(inst["n"])]
m.addConstr(gp.quicksum(x) <= 2)
m.setObjective(gp.quicksum(x[i] * x[i + 1] for i in range(inst["n"] - 1)) + 0.5 * x[0], GRB.MAXIMIZE)
m.optimize()
json.dump({"objective_value": m.ObjVal}, open(a.solution_path, "w"))
'''
        with tempfile.TemporaryDirectory() as d:
            for name in ("solve_probe.py", "gpshim.py", "gpshim_objfix.py"):
                with open(os.path.join(HERE, name), encoding="utf-8") as f:
                    body = f.read()
                with open(os.path.join(d, "solve.py" if name == "solve_probe.py" else name), "w",
                          encoding="utf-8") as f:
                    f.write(body)
            with open(os.path.join(d, "gurobi_code.py"), "w", encoding="utf-8") as f:
                f.write(code)
            ip, op = os.path.join(d, "in.json"), os.path.join(d, "out.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump({"n": 5}, f)
            env = dict(os.environ)
            env["MV2_MEM_LOG"] = os.path.join(d, "mem.jsonl")
            env["MV2_OBJFIX_LOG"] = os.path.join(d, "fix.jsonl")
            p = subprocess.run([sys.executable, "solve.py", "--problem", "t", "--instance", ip, "--output", op,
                                "--time-limit", "10"], cwd=d, capture_output=True, text=True, timeout=120, env=env)
            self.assertEqual(p.returncode, 0, p.stderr[-2000:])
            with open(op, encoding="utf-8") as f:
                self.assertAlmostEqual(json.load(f)["objective_value"], 1.5, places=6)
            with open(env["MV2_MEM_LOG"], encoding="utf-8") as f:
                stages = [json.loads(line)["stage"] for line in f if line.strip()]
            for s in ("start", "imported", "optimize_enter", "highs_enter", "highs_exit", "optimize_exit", "exit"):
                self.assertIn(s, stages)
            self.assertLess(stages.index("optimize_enter"), stages.index("highs_enter"))
            with open(env["MV2_OBJFIX_LOG"], encoding="utf-8") as f:
                fix = [json.loads(line) for line in f if line.strip()]
            self.assertEqual(len(fix), 1)
            self.assertAlmostEqual(fix[0]["after"], 1.5, places=6)


if __name__ == "__main__":
    importlib.invalidate_caches()
    unittest.main()

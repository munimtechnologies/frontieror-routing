"""Tests for gpshim_cpsat 0.3.1 (the OR-Tools CP-SAT backend for gpshim, CP-SAT in a worker process) and gp_solve.py.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Needs gpshim.py 0.2.0 next to this file (python fetch_base.py .), numpy, highspy and ortools.
Run from this folder: python -m unittest -v test_gpshim_cpsat

This test process imports highspy first and never imports OR-Tools, the order that broke 0.3.0 (see
gpshim_cpsat_worker.py). Whether OR-Tools is installed is probed in a separate process.
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
try:
    import highspy  # noqa: F401  - loaded first on purpose
    HAVE_HIGHSPY = True
except ImportError:
    HAVE_HIGHSPY = False
import gpshim as gp  # noqa: E402
from gpshim import GRB  # noqa: E402
import gpshim_cpsat as cs  # noqa: E402

cs.install(gp)
HAVE_ORTOOLS = subprocess.run([sys.executable, "-c", "import ortools.sat.python.cp_model"],
                              capture_output=True).returncode == 0


def last():
    return gp._STATS[-1]


def ortools_in_this_process():
    return any(k == "ortools" or k.startswith("ortools.") for k in sys.modules)


def components(n, edges):
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


def knapsack(seed, n=12):
    rng = random.Random(seed)
    w = [rng.randint(1, 30) for _ in range(n)]
    p = [rng.randint(1, 40) for _ in range(n)]
    cap = sum(w) // 3
    m = gp.Model()
    x = m.addVars(n, vtype=GRB.BINARY)
    m.addConstr(gp.quicksum(w[i] * x[i] for i in range(n)) <= cap)
    m.setObjective(gp.quicksum(p[i] * x[i] for i in range(n)), GRB.MAXIMIZE)
    best = max(sum(p[i] for i in range(n) if s >> i & 1) for s in range(1 << n)
               if sum(w[i] for i in range(n) if s >> i & 1) <= cap)
    return m, x, w, cap, best


@unittest.skipUnless(HAVE_ORTOOLS, "ortools not installed")
class TestCpsatBackend(unittest.TestCase):
    def setUp(self):
        gp.set_deadline(None)
        cs.set_backend("cpsat")

    def tearDown(self):
        cs.set_backend(None)

    def test_knapsack_brute_force(self):
        for seed in range(5):
            m, x, w, cap, best = knapsack(seed)
            m.optimize()
            self.assertEqual(last()["backend"], "cpsat", last())
            self.assertEqual(m.Status, GRB.OPTIMAL)
            self.assertAlmostEqual(m.ObjVal, best, places=6)
            self.assertLessEqual(sum(w[i] * round(x[i].X) for i in range(len(w))), cap)

    def test_assignment_decimal_costs(self):
        rng = random.Random(3)
        n = 5
        c = {(i, j): rng.randint(100, 5000) / 100.0 for i in range(n) for j in range(n)}
        m = gp.Model()
        x = m.addVars(range(n), range(n), vtype=GRB.BINARY)
        for i in range(n):
            m.addConstr(x.sum(i, "*") == 1)
            m.addConstr(x.sum("*", i) == 1)
        m.setObjective(x.prod(c), GRB.MINIMIZE)
        m.optimize()
        best = min(sum(c[i, pi[i]] for i in range(n)) for pi in itertools.permutations(range(n)))
        self.assertEqual(last()["backend"], "cpsat", last())
        self.assertNotIn("rounded", last()["note"])
        self.assertAlmostEqual(m.ObjVal, best, places=6)

    def test_fractional_row_coefficients(self):
        m = gp.Model()
        x = m.addVar(lb=0, ub=10, vtype=GRB.INTEGER)
        y = m.addVar(lb=0, ub=10, vtype=GRB.INTEGER)
        m.addConstr(0.5 * x + 0.25 * y <= 1.3)
        m.setObjective(x + y, GRB.MAXIMIZE)
        m.optimize()
        best = max(a + b for a in range(11) for b in range(11) if 0.5 * a + 0.25 * b <= 1.3 + 1e-9)
        self.assertEqual(best, 5)
        self.assertEqual(last()["backend"], "cpsat", last())
        self.assertAlmostEqual(m.ObjVal, best, places=6)
        self.assertLessEqual(0.5 * x.X + 0.25 * y.X, 1.3 + 1e-9)

    def test_irrational_objective_is_rounded_but_objval_exact(self):
        n = 8
        cost = [math.sqrt(k + 2) for k in range(n)]
        w = [3, 5, 2, 7, 4, 6, 1, 5]
        m = gp.Model()
        x = m.addVars(n, vtype=GRB.BINARY)
        m.addConstr(gp.quicksum(x[i] for i in range(n)) <= 3)
        m.addConstr(gp.quicksum(w[i] * x[i] for i in range(n)) <= 12)
        m.setObjective(gp.quicksum(cost[i] * x[i] for i in range(n)), GRB.MAXIMIZE)
        m.optimize()
        best = max(sum(cost[i] for i in range(n) if s >> i & 1) for s in range(1 << n)
                   if bin(s).count("1") <= 3 and sum(w[i] for i in range(n) if s >> i & 1) <= 12)
        self.assertEqual(last()["backend"], "cpsat", last())
        self.assertIn("objective rounded", last()["note"])
        self.assertAlmostEqual(m.ObjVal, best, places=9)
        chosen = sum(cost[i] for i in range(n) if x[i].X > 0.5)
        self.assertAlmostEqual(m.ObjVal, chosen, places=12)

    def test_random_small_integer_programs_match_brute_force(self):
        senses = ["<", ">", "="]
        agree = 0
        for seed in range(25):
            rng = random.Random(100 + seed)
            A = [[rng.randint(-20, 20) / 10.0 for _ in range(3)] for _ in range(3)]
            b = [rng.randint(-30, 30) / 10.0 for _ in range(3)]
            sn = [senses[rng.randint(0, 2) if k == 0 else rng.randint(0, 1)] for k in range(3)]
            c = [rng.randint(-9, 9) for _ in range(3)]
            m = gp.Model()
            v = [m.addVar(lb=-3, ub=3, vtype=GRB.INTEGER) for _ in range(3)]
            for k in range(3):
                e = gp.quicksum(A[k][i] * v[i] for i in range(3))
                if sn[k] == "<":
                    m.addConstr(e <= b[k])
                elif sn[k] == ">":
                    m.addConstr(e >= b[k])
                else:
                    m.addConstr(e == b[k])
            m.setObjective(gp.quicksum(c[i] * v[i] for i in range(3)), GRB.MINIMIZE)
            m.optimize()
            best = None
            for pt in itertools.product(range(-3, 4), repeat=3):
                ok = True
                for k in range(3):
                    act = sum(A[k][i] * pt[i] for i in range(3))
                    if (sn[k] == "<" and act > b[k] + 1e-9) or (sn[k] == ">" and act < b[k] - 1e-9) or \
                            (sn[k] == "=" and abs(act - b[k]) > 1e-9):
                        ok = False
                        break
                if ok:
                    val = sum(c[i] * pt[i] for i in range(3))
                    best = val if best is None else min(best, val)
            self.assertEqual(last()["backend"], "cpsat", last())
            if best is None:
                self.assertIn(m.Status, (GRB.INFEASIBLE, GRB.INF_OR_UNBD), seed)
                self.assertEqual(m.SolCount, 0)
            else:
                self.assertEqual(m.Status, GRB.OPTIMAL, seed)
                self.assertAlmostEqual(m.ObjVal, best, places=6, msg=str(seed))
            agree += 1
        self.assertEqual(agree, 25)

    @unittest.skipUnless(HAVE_HIGHSPY, "highspy not installed")
    def test_continuous_column_falls_back_to_highs(self):
        m = gp.Model()
        x = m.addVar(lb=0, ub=4, vtype=GRB.INTEGER)
        y = m.addVar(lb=0, ub=4)
        m.addConstr(x + y <= 3.5)
        m.setObjective(2 * x + y, GRB.MAXIMIZE)
        m.optimize()
        self.assertEqual(last()["backend"], "highspy")
        self.assertIn("cpsat_skip: 1 non-integer columns", last()["note"])
        self.assertAlmostEqual(m.ObjVal, 6.5, places=6)

    @unittest.skipUnless(HAVE_HIGHSPY, "highspy not installed")
    def test_too_many_decimals_falls_back(self):
        m = gp.Model()
        x = m.addVar(lb=0, ub=10, vtype=GRB.INTEGER)
        m.addConstr((1.0 / 3.0) * x <= 2)
        m.setObjective(x, GRB.MAXIMIZE)
        m.optimize()
        self.assertEqual(last()["backend"], "highspy")
        self.assertIn("more than 6 decimals", last()["note"])
        self.assertAlmostEqual(m.ObjVal, 6.0, places=6)

    def test_infinite_bounds_are_capped_and_logged(self):
        m = gp.Model()
        x = m.addVar(vtype=GRB.INTEGER)  # [0, inf)
        y = m.addVar(lb=-GRB.INFINITY, vtype=GRB.INTEGER)  # free
        m.addConstr(2 * x >= 7)
        m.addConstr(y >= -3.5)
        m.setObjective(x + y, GRB.MINIMIZE)
        m.optimize()
        self.assertEqual(last()["backend"], "cpsat", last())
        self.assertIn("capped=3", last()["note"])
        self.assertAlmostEqual(x.X, 4.0, places=9)
        self.assertAlmostEqual(y.X, -3.0, places=9)
        self.assertAlmostEqual(m.ObjVal, 1.0, places=9)

    def test_integer_infeasible(self):
        m = gp.Model()
        x = m.addVar(lb=0, ub=5, vtype=GRB.INTEGER)
        y = m.addVar(lb=0, ub=5, vtype=GRB.INTEGER)
        m.addConstr(x + y == 2.5)
        m.setObjective(x, GRB.MINIMIZE)
        m.optimize()
        self.assertEqual(last()["backend"], "cpsat", last())
        self.assertEqual(m.Status, GRB.INFEASIBLE)
        self.assertEqual(m.SolCount, 0)

    def test_infeasible_found_by_cpsat_search(self):
        # parity: x0 + x1 + x2 = 2 with x0 = x1 = x2 has no integer solution, but every row alone is satisfiable
        m = gp.Model()
        x = m.addVars(3, lb=0, ub=1, vtype=GRB.INTEGER)
        m.addConstr(x[0] + x[1] + x[2] == 2)
        m.addConstr(x[0] - x[1] == 0)
        m.addConstr(x[1] - x[2] == 0)
        m.setObjective(x[0], GRB.MINIMIZE)
        m.optimize()
        self.assertEqual(last()["backend"], "cpsat", last())
        self.assertEqual(m.Status, GRB.INFEASIBLE)

    def test_objective_constant_and_maximise(self):
        m = gp.Model()
        x = m.addVar(lb=0, ub=3, vtype=GRB.INTEGER)
        y = m.addVar(lb=0, ub=10, vtype=GRB.INTEGER)
        m.addConstr(x + y <= 4)
        m.setObjective(3 * x + 2 * y + 10, GRB.MAXIMIZE)
        m.optimize()
        self.assertEqual(last()["backend"], "cpsat", last())
        self.assertAlmostEqual(m.ObjVal, 21.0, places=9)
        self.assertAlmostEqual(m.ObjBound, 21.0, places=6)

    def test_range_and_hints(self):
        rng = random.Random(11)
        n = 10
        w = [rng.randint(1, 9) for _ in range(n)]
        p = [rng.randint(1, 9) for _ in range(n)]
        m = gp.Model()
        x = m.addVars(n, vtype=GRB.BINARY)
        m.addRange(gp.quicksum(w[i] * x[i] for i in range(n)), 10, 20)
        for i in range(n):
            x[i].Start = 0.0
        m.setObjective(gp.quicksum(p[i] * x[i] for i in range(n)), GRB.MINIMIZE)
        m.optimize()
        best = min(sum(p[i] for i in range(n) if s >> i & 1) for s in range(1 << n)
                   if 10 <= sum(w[i] for i in range(n) if s >> i & 1) <= 20)
        self.assertEqual(last()["backend"], "cpsat", last())
        self.assertIn("hints=%d" % n, last()["note"])
        self.assertAlmostEqual(m.ObjVal, best, places=9)

    def test_tsp_lazy_callback(self):
        starts_before = cs._CHILD["starts"]
        for seed in range(3):
            rng = random.Random(seed)
            n = 7
            pts = [(rng.randint(0, 100), rng.randint(0, 100)) for _ in range(n)]
            d = {(i, j): round(math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]))
                 for i in range(n) for j in range(i + 1, n)}
            m = gp.Model()
            m.Params.LazyConstraints = 1
            x = m.addVars(d.keys(), vtype=GRB.BINARY)
            for i in range(n):
                m.addConstr(gp.quicksum(x[min(i, j), max(i, j)] for j in range(n) if j != i) == 2)
            m.setObjective(x.prod(d), GRB.MINIMIZE)
            m._x = x

            def subtour(model, where):
                if where != GRB.Callback.MIPSOL:
                    return
                vals = model.cbGetSolution(model._x)
                sel = [k for k, v in vals.items() if v > 0.5]
                for comp in components(n, sel):
                    if len(comp) < n:
                        model.cbLazy(gp.quicksum(model._x[i, j] for i in comp for j in comp if i < j)
                                     <= len(comp) - 1)

            m.optimize(subtour)
            best = min(sum(d[min(a, b), max(a, b)] for a, b in zip((0,) + q, q + (0,)))
                       for q in itertools.permutations(range(1, n)))
            self.assertEqual(last()["backend"], "cpsat", last())
            self.assertEqual(m.Status, GRB.OPTIMAL)
            self.assertAlmostEqual(m.ObjVal, best, places=6)
            used = [k for k in d if x[k].X > 0.5]
            self.assertEqual(len(components(n, used)), 1)
        # the worker is reused across lazy rounds and models (at most one start here)
        self.assertLessEqual(cs._CHILD["starts"] - starts_before, 1)

    def test_hierarchical_multiobjective(self):
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
        self.assertEqual(last()["backend"], "cpsat", last())


@unittest.skipUnless(HAVE_ORTOOLS and HAVE_HIGHSPY, "needs ortools and highspy")
class TestIsolation(unittest.TestCase):
    """The 0.3.0 failure: highspy loaded first made OR-Tools unusable in the same process."""

    def setUp(self):
        gp.set_deadline(None)

    def tearDown(self):
        cs.set_backend(None)

    def test_both_backends_in_one_process(self):
        self.assertIn("highspy", sys.modules)
        cs.set_backend("cpsat")
        m, _, _, _, best = knapsack(42)
        m.optimize()
        self.assertEqual(last()["backend"], "cpsat", last())
        self.assertAlmostEqual(m.ObjVal, best, places=6)
        cs.set_backend("highs")
        m2, _, _, _, best2 = knapsack(43)
        m2.optimize()
        self.assertEqual(last()["backend"], "highspy", last())
        self.assertAlmostEqual(m2.ObjVal, best2, places=6)
        self.assertFalse(ortools_in_this_process())

    def test_dead_worker_falls_back_to_highs(self):
        bad = os.path.join(tempfile.mkdtemp(prefix="gpshim-badworker-"), "bad_worker.py")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("import sys\nsys.exit(3)\n")
        saved = cs._WORKER[0]
        cs.stop_worker()
        cs._WORKER[0] = bad
        try:
            cs.set_backend("cpsat")
            m, _, _, _, best = knapsack(7)
            m.optimize()
            self.assertEqual(last()["backend"], "highspy", last())
            self.assertIn("cpsat_skip: worker", last()["note"])
            self.assertAlmostEqual(m.ObjVal, best, places=6)
        finally:
            cs.stop_worker()
            cs._WORKER[0] = saved

    def test_worker_restarts_after_stop(self):
        cs.set_backend("cpsat")
        cs.stop_worker()
        m, _, _, _, best = knapsack(8)
        m.optimize()
        self.assertEqual(last()["backend"], "cpsat", last())
        self.assertAlmostEqual(m.ObjVal, best, places=6)


class TestDefaultStaysHighs(unittest.TestCase):
    @unittest.skipUnless(HAVE_HIGHSPY, "highspy not installed")
    def test_highs_is_default(self):
        cs.set_backend("highs")
        try:
            m = gp.Model()
            x = m.addVars(4, vtype=GRB.BINARY)
            m.addConstr(gp.quicksum(x[i] for i in range(4)) <= 2)
            m.setObjective(gp.quicksum((i + 1) * x[i] for i in range(4)), GRB.MAXIMIZE)
            m.optimize()
            self.assertEqual(last()["backend"], "highspy")
            self.assertNotIn("cpsat_skip", last()["note"] or "")
            self.assertAlmostEqual(m.ObjVal, 7.0, places=6)
        finally:
            cs.set_backend(None)


FAKE_CODE = textwrap.dedent('''
    import argparse, json
    import gurobipy as gp
    from gurobipy import GRB

    def main():
        ap = argparse.ArgumentParser()
        ap.add_argument("--instance_path", required=True)
        ap.add_argument("--solution_path", required=True)
        ap.add_argument("--time_limit", type=int, required=True)
        a = ap.parse_args()
        data = json.load(open(a.instance_path))
        m = gp.Model("fake")
        m.setParam("TimeLimit", a.time_limit)
        x = m.addVars(len(data["p"]), vtype=GRB.BINARY)
        m.addConstr(gp.quicksum(data["w"][i] * x[i] for i in x) <= data["cap"])
        m.setObjective(gp.quicksum(data["p"][i] * x[i] for i in x), GRB.MAXIMIZE)
        m.optimize()
        sol = {"objective_value": m.ObjVal if m.SolCount else None,
               "chosen": [i for i in x if x[i].X > 0.5] if m.SolCount else []}
        json.dump(sol, open(a.solution_path, "w"))

    if __name__ == "__main__":
        main()
''')


@unittest.skipUnless(HAVE_ORTOOLS, "ortools not installed")
class TestEntryPoint(unittest.TestCase):
    def test_backend_file_selects_cpsat(self):
        d = tempfile.mkdtemp(prefix="gpshim-cpsat-test-")
        for name, src in (("solve.py", "gp_solve.py"), ("gpshim.py", "gpshim.py"),
                          ("gpshim_cpsat.py", "gpshim_cpsat.py"),
                          ("gpshim_cpsat_worker.py", "gpshim_cpsat_worker.py")):
            with open(os.path.join(HERE, src), encoding="utf-8") as f, \
                    open(os.path.join(d, name), "w", encoding="utf-8") as g:
                g.write(f.read())
        with open(os.path.join(d, "gpshim_backend.txt"), "w", encoding="utf-8") as f:
            f.write("cpsat\n")
        with open(os.path.join(d, "gurobi_code.py"), "w", encoding="utf-8") as f:
            f.write(FAKE_CODE)
        ip, op, lg = (os.path.join(d, k) for k in ("inst.json", "out.json", "shim.jsonl"))
        with open(ip, "w", encoding="utf-8") as f:
            json.dump({"p": [10, 13, 7, 8], "w": [5, 7, 4, 3], "cap": 10}, f)
        env = dict(os.environ)
        env.pop("MV2_GPSHIM_BACKEND", None)
        env["MV2_GPSHIM_LOG"] = lg
        t0 = time.time()
        p = subprocess.run([sys.executable, "solve.py", "--problem", "fake", "--instance", ip, "--output", op,
                            "--time-limit", "10"], cwd=d, capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(p.returncode, 0, p.stderr[-800:])
        self.assertLess(time.time() - t0, 10.0)
        with open(op, encoding="utf-8") as f:
            sol = json.load(f)
        self.assertAlmostEqual(sol["objective_value"], 21.0, places=6)
        self.assertEqual(sorted(sol["chosen"]), [1, 3])
        with open(lg, encoding="utf-8") as f:
            stats = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(stats[-1]["backend"], "cpsat", stats[-1])


if __name__ == "__main__":
    unittest.main()

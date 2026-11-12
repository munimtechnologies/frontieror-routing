"""Tests for MV2's desaulniers2010 (SDVRPTW) solver. MV2 of Munim, Inc. Made with AI agents working in MV2's name.
License: Apache-2.0.

  python -m unittest -v test_desaulniers2010
If DESAUL_OFFICIAL points to the benchmark's feasibility_check.py, solver outputs are also judged by it.
"""
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import solve as S  # noqa: E402


def trunc1(x):
    return math.floor(x * 10.0) / 10.0


def make_instance(pts, demands, windows, Q, service=10, depot=(0, 0), horizon=1000):
    n = len(pts)
    locs = [depot] + list(pts)
    dm = [[trunc1(math.hypot(a[0] - b[0], a[1] - b[1])) for b in locs] for a in locs]
    return {
        "num_customers": n, "vehicle_capacity": Q,
        "num_vehicles_upper_bound": sum(math.ceil(d / Q) for d in demands),
        "scheduling_horizon": horizon,
        "depot": {"id": 0, "x": depot[0], "y": depot[1], "time_window": [0, horizon], "service_time": 0,
                  "demand": 0},
        "customers": [{"id": i + 1, "x": pts[i][0], "y": pts[i][1], "demand": demands[i],
                       "time_window": list(windows[i]), "service_time": service} for i in range(n)],
        "distance_matrix": dm, "travel_time_equals_distance": True, "triangle_inequality": True,
        "split_deliveries_allowed": True, "service_time_independent_of_quantity": True,
    }


def random_instance(n, seed, Q=100):
    rng = random.Random(seed)
    pts = [(rng.randint(0, 100), rng.randint(0, 100)) for _ in range(n)]
    dem = [rng.randint(10, 70) for _ in range(n)]
    win = []
    for (x, y) in pts:
        d0 = math.hypot(x - 50, y - 50)
        a = rng.randint(int(d0), 600)
        win.append((a, a + rng.randint(60, 200)))
    return make_instance(pts, dem, win, Q, depot=(50, 50), horizon=1000)


def official():
    p = os.environ.get("DESAUL_OFFICIAL")
    if not p or not os.path.exists(p):
        return None
    spec = importlib.util.spec_from_file_location("desaul_official", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run(inst, tl=3.0, workers=1):
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "sol.json")
        obj, log = S.solve(inst, out, tl, seed=1, workers=workers, t0=time.monotonic())
        with open(out, encoding="utf-8") as f:
            sol = json.load(f)
    return obj, log, sol


def routes_of(sol):
    return [S.Route(r["route"][1:-1], {int(k): v for k, v in r["deliveries"].items()}) for r in sol["routes"]]


class TestSolver(unittest.TestCase):
    def check_sol(self, inst, sol):
        pb = S.Problem(inst)
        ok, why = S.verify(pb, routes_of(sol))
        self.assertTrue(ok, why)
        self.assertEqual(sol["num_vehicles_used"], len(sol["routes"]))
        self.assertAlmostEqual(sol["objective_value"], S.total_cost(pb, routes_of(sol)), places=4)
        self.assertEqual(sorted(sol["deliveries"]), sorted(str(i) for i in range(1, inst["num_customers"] + 1)))
        off = official()
        if off is not None:
            self.assertIsNone(off._frontieror_validate_solution_contract(sol))
            r = off.check_feasibility(inst, sol)
            self.assertTrue(r["feasible"], r.get("violations"))

    def test_split_beats_unsplit(self):
        # three customers of demand 6 far from the depot, capacity 9: unsplit needs 3 trips, split needs 2
        inst = make_instance([(50, 0), (50, 1), (51, 0)], [6, 6, 6], [(0, 1000)] * 3, 9, service=1)
        obj, log, sol = run(inst)
        self.check_sol(inst, sol)
        self.assertEqual(len(sol["routes"]), 2)
        self.assertLess(obj, 210.0)
        self.assertGreaterEqual(log["split_customers"], 1)

    def test_big_demand(self):
        inst = make_instance([(10, 0), (0, 10)], [25, 4], [(0, 1000)] * 2, 10, service=1)
        obj, log, sol = run(inst)
        self.check_sol(inst, sol)
        self.assertEqual(log["dedicated_routes"], 2)
        visits = sum(1 for r in sol["routes"] if 1 in r["route"])
        self.assertGreaterEqual(visits, 3)

    def test_random_instances(self):
        for seed in (1, 2, 3):
            inst = random_instance(25, seed)
            obj, log, sol = run(inst, tl=4.0)
            self.check_sol(inst, sol)
            self.assertLessEqual(obj, log["unsplit_best"] + 1e-6)

    def test_time_windows_respected(self):
        # two customers whose windows force separate trips even though capacity would allow one
        inst = make_instance([(10, 0), (-10, 0)], [3, 3], [(10, 11), (10, 11)], 50, service=1)
        obj, log, sol = run(inst)
        self.check_sol(inst, sol)
        self.assertEqual(len(sol["routes"]), 2)

    def test_two_workers(self):
        inst = random_instance(20, 7)
        obj, log, sol = run(inst, tl=4.0, workers=2)
        self.check_sol(inst, sol)


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.inst = make_instance([(10, 0), (0, 10)], [5, 5], [(0, 1000)] * 2, 10, service=1)
        self.pb = S.Problem(self.inst)

    def test_accepts_good(self):
        self.assertTrue(S.verify(self.pb, [S.Route([1, 2], {1: 5, 2: 5})])[0])

    def test_rejects_capacity(self):
        pb = S.Problem(make_instance([(10, 0), (0, 10)], [6, 5], [(0, 1000)] * 2, 10))
        self.assertFalse(S.verify(pb, [S.Route([1, 2], {1: 6, 2: 5})])[0])

    def test_rejects_shortfall(self):
        self.assertFalse(S.verify(self.pb, [S.Route([1, 2], {1: 5, 2: 4})])[0])

    def test_rejects_unvisited_delivery(self):
        self.assertFalse(S.verify(self.pb, [S.Route([1], {1: 5, 2: 5})])[0])

    def test_rejects_window(self):
        pb = S.Problem(make_instance([(10, 0)], [5], [(0, 5)], 10))
        self.assertFalse(S.verify(pb, [S.Route([1], {1: 5})])[0])

    def test_official_rejects_tampered(self):
        off = official()
        if off is None:
            self.skipTest("DESAUL_OFFICIAL not set")
        obj, log, sol = run(self.inst)
        bad = json.loads(json.dumps(sol))
        bad["objective_value"] = sol["objective_value"] * 0.5
        self.assertFalse(off.check_feasibility(self.inst, bad)["feasible"])
        bad = json.loads(json.dumps(sol))
        k = next(iter(bad["routes"][0]["deliveries"]))
        bad["routes"][0]["deliveries"][k] = 0
        self.assertFalse(off.check_feasibility(self.inst, bad)["feasible"])


class TestCLI(unittest.TestCase):
    def test_cli(self):
        inst = random_instance(15, 11)
        with tempfile.TemporaryDirectory() as d:
            ip = os.path.join(d, "inst.json")
            op = os.path.join(d, "out.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            t = time.monotonic()
            subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "desaulniers2010",
                            "--instance", ip, "--output", op, "--time-limit", "5"], check=True, timeout=30)
            self.assertLess(time.monotonic() - t, 6.5)
            with open(op, encoding="utf-8") as f:
                sol = json.load(f)
        TestSolver.check_sol(self, inst, sol)


if __name__ == "__main__":
    unittest.main()

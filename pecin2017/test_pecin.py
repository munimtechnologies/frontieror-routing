"""Tests for the pecin2017 (VRPTW) solver v0.1.1 and its independent checker.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Offline and standard library only. When pyvrp is installed, the tiny instances must also reach the brute-force optimum
(4 of 5, within 0.01: PyVRP optimises distances rounded up to 1/1000); without it only feasibility and the bound are
tested. When PECIN_OFFICIAL points to the benchmark's feasibility_check.py, our checker must agree with it on valid
and broken solutions.
"""
import importlib.util
import itertools
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pecin_check as C  # noqa: E402
import solve as S  # noqa: E402

HAVE_PYVRP = importlib.util.find_spec("pyvrp") is not None


def make(seed, n, cap=20, horizon=200.0, wide=False):
    rng = random.Random(seed)
    nodes = [{"id": 0, "type": "depot_source", "x": 50.0, "y": 50.0, "demand": 0, "service_time": 0,
              "time_window_open": 0.0, "time_window_close": horizon}]
    for i in range(1, n + 1):
        x, y = rng.uniform(0, 100), rng.uniform(0, 100)
        d0 = math.hypot(x - 50, y - 50)
        if wide:
            o, c = 0.0, horizon - d0 - 5
        else:
            o = rng.uniform(d0, max(d0, horizon - d0 - 40))
            c = o + rng.uniform(20, 60)
            c = min(c, horizon - d0 - 5)
            o = min(o, c)
        nodes.append({"id": i, "type": "customer", "x": round(x, 3), "y": round(y, 3), "demand": rng.randint(1, 8),
                      "service_time": 5, "time_window_open": round(o, 3), "time_window_close": round(c, 3)})
    nodes.append({"id": n + 1, "type": "depot_sink", "x": 50.0, "y": 50.0, "demand": 0, "service_time": 0,
                  "time_window_open": 0.0, "time_window_close": horizon})
    return {"problem_parameters": {"n_nodes": n + 2, "n_customers": n, "vehicle_capacity": cap,
                                   "planning_horizon": horizon, "travel_cost_type": "euclidean",
                                   "travel_time_type": "euclidean"}, "nodes": nodes}


def brute(inst):
    """Optimum by enumerating set partitions into ordered routes (tiny n only)."""
    I = S.Inst(inst)
    cs = I.customers
    best = [math.inf]
    memo = {}

    def best_route(subset):
        key = frozenset(subset)
        if key not in memo:
            b = math.inf
            for perm in itertools.permutations(subset):
                if I.route_ok(list(perm)):
                    b = min(b, I.route_cost(list(perm)))
            memo[key] = b
        return memo[key]

    def rec(left, acc):
        if acc >= best[0]:
            return
        if not left:
            best[0] = acc
            return
        first = left[0]
        rest = left[1:]
        for k in range(len(rest) + 1):
            for comb in itertools.combinations(rest, k):
                sub = (first,) + comb
                c = best_route(sub)
                if c < math.inf:
                    rec([x for x in rest if x not in comb], acc + c)

    rec(cs, 0.0)
    return best[0]


def run_cli(inst, limit, env=None):
    with tempfile.TemporaryDirectory() as d:
        sd = os.path.join(d, "s")
        os.makedirs(sd)
        shutil.copy(os.path.join(HERE, "solve.py"), sd)
        shutil.copy(os.path.join(HERE, "frontier_runtime.py"), sd)
        ip, op = os.path.join(d, "in.json"), os.path.join(d, "out.json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        e = dict(os.environ)
        e.update(env or {})
        t0 = time.monotonic()
        p = subprocess.run([sys.executable, "solve.py", "--problem", "pecin2017", "--instance", ip, "--output", op,
                            "--time-limit", str(limit)], cwd=sd, capture_output=True, text=True, timeout=limit + 15,
                           env=e)
        wall = time.monotonic() - t0
        assert p.returncode == 0, p.stderr[-1500:]
        assert wall < limit, "over time: %.2f" % wall
        with open(op, encoding="utf-8") as f:
            sol = json.load(f)
        logp = op + ".log.json"
        lg = None
        if os.path.exists(logp):
            with open(logp, encoding="utf-8") as f:
                lg = json.load(f)
        return sol["objective_value"], sol, lg


class Checker(unittest.TestCase):
    def test_rules(self):
        inst = make(1, 4, wide=True)
        ok = {"objective_value": 0.0, "routes": [[0, 1, 5], [0, 2, 5], [0, 3, 5], [0, 4, 5]]}
        r = C.check(inst, ok)
        self.assertFalse(r["feasible"])  # stated objective 0 is wrong
        ok["objective_value"] = r["objective"]
        self.assertTrue(C.check(inst, ok)["feasible"])
        bad = [
            {"objective_value": 1.0, "routes": [[0, 1, 2, 3, 5]]},  # customer 4 missing
            {"objective_value": 1.0, "routes": [[0, 1, 5], [0, 1, 2, 3, 4, 5]]},  # 1 twice
            {"objective_value": 1.0, "routes": [[1, 2, 3, 4, 5]]},  # does not start at 0
            {"objective_value": 1.0, "routes": [[0, 1, 0, 2, 3, 4, 5]]},  # depot inside
            {"objective_value": True, "routes": [[0, 1, 2, 3, 4, 5]]},  # bool objective
        ]
        for s in bad:
            self.assertFalse(C.check(inst, s)["feasible"], s)

    def test_capacity_and_lateness(self):
        inst = make(2, 3, cap=5, wide=True)
        for v in inst["nodes"][1:4]:
            v["demand"] = 3
        s = {"objective_value": 0.0, "routes": [[0, 1, 2, 4], [0, 3, 4]]}
        self.assertIn("load", C.check(inst, s)["reason"])
        inst = make(3, 2, wide=True)
        inst["nodes"][2]["time_window_close"] = 0.5  # unreachable in time
        s = {"objective_value": 0.0, "routes": [[0, 1, 3], [0, 2, 3]]}
        self.assertIn("late", C.check(inst, s)["reason"])


class Solver(unittest.TestCase):
    def test_insertion_valid_and_scaling_conservative(self):
        for seed in range(6):
            inst = make(10 + seed, 25)
            I = S.Inst(inst)
            routes = S.insertion(I, time.monotonic() + 5)
            self.assertTrue(I.valid(routes))
            obj, sol = I.solution(routes)
            r = C.check(inst, sol)
            self.assertTrue(r["feasible"], r)
            text, locs = S.vrplib_text(I)
            self.assertEqual(locs[0], I.src)
            self.assertIn("EDGE_WEIGHT_SECTION", text)
            # every scaled travel time is >= the float one
            rows = text.split("EDGE_WEIGHT_SECTION\n")[1].split("DEMAND_SECTION")[0].strip().split("\n")
            for a, row in zip(locs, rows):
                for b, w in zip(locs, row.split()):
                    if a != b:
                        bb = I.sink if b == I.src else b
                        self.assertGreaterEqual(int(w), I.d(a, bb) * S.SCALE - 1e-6)
            # windows: openings rounded up, closings rounded down
            tw = text.split("TIME_WINDOW_SECTION\n")[1].split("DEPOT_SECTION")[0].strip().split("\n")
            for i, row in zip(locs[1:], tw[1:]):
                _, e, l_ = row.split()
                self.assertGreaterEqual(int(e), I.open[i] * S.SCALE - 1e-6)
                self.assertLessEqual(int(l_), I.close[i] * S.SCALE + 1e-6)

    def test_tiny_reaches_brute_force(self):
        at = 0
        for seed in range(5):
            inst = make(100 + seed, 6, cap=12)
            opt = brute(inst)
            val, sol, _ = run_cli(inst, 6)
            r = C.check(inst, sol)
            self.assertTrue(r["feasible"], r)
            self.assertGreaterEqual(val, opt - 1e-6)
            if abs(val - opt) <= 0.01:
                at += 1
        if HAVE_PYVRP:
            self.assertGreaterEqual(at, 4)


class CLI(unittest.TestCase):
    def test_cli_medium_and_log(self):
        inst = make(7, 60, cap=30)
        val, sol, lg = run_cli(inst, 8, env={"MV2_PECIN_LOG": "1", "MV2_PECIN_SEED": "3"})
        r = C.check(inst, sol)
        self.assertTrue(r["feasible"], r)
        I = S.Inst(inst)
        self.assertLessEqual(val, sum(I.route_cost([c]) for c in I.customers) + 1e-6)
        self.assertIsNotNone(lg)
        self.assertEqual(lg["version"], S.__version__)
        self.assertEqual(lg["seed"], 3)
        if HAVE_PYVRP:
            self.assertNotIn("pyvrp_error", lg, lg)
            self.assertNotEqual(lg.get("pyvrp"), "?")

    def test_two_second_limit_still_answers(self):
        inst = make(8, 40, cap=25)
        val, sol, _ = run_cli(inst, 3)
        self.assertTrue(C.check(inst, sol)["feasible"])


class Official(unittest.TestCase):
    """Our checker against the benchmark's own feasibility_check.py, when PECIN_OFFICIAL is set."""

    def test_agreement(self):
        path = os.environ.get("PECIN_OFFICIAL")
        if not path or not os.path.exists(path):
            self.skipTest("official checker not available")
        spec = importlib.util.spec_from_file_location("pecin_official", path)
        off = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(off)
        n = 0
        for seed in range(6):
            inst = make(200 + seed, 20, cap=25)
            I = S.Inst(inst)
            routes = S.insertion(I, time.monotonic() + 5)
            _, good = I.solution(routes)
            cases = [good]
            b1 = json.loads(json.dumps(good))
            b1["objective_value"] = good["objective_value"] * 0.98  # outside the 0.1% tolerance
            cases.append(b1)
            b2 = json.loads(json.dumps(good))
            b2["routes"] = b2["routes"][1:]  # customers missing
            cases.append(b2)
            if len(good["routes"]) >= 2:
                b3 = json.loads(json.dumps(good))
                merged = b3["routes"][0][:-1] + b3["routes"][1][1:]
                b3["routes"] = [merged] + b3["routes"][2:]
                b3["objective_value"] = C.check(inst, {"objective_value": 0.0, "routes": b3["routes"]})["objective"] \
                    or b3["objective_value"]
                cases.append(b3)
            for s in cases:
                ours = C.check(inst, s)["feasible"]
                theirs = off.check_feasibility(inst, s)["feasible"]
                self.assertEqual(ours, theirs, (seed, s["routes"][:2]))
                n += 1
        self.assertGreaterEqual(n, 18)


if __name__ == "__main__":
    unittest.main()

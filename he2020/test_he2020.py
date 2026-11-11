"""Tests for the he2020 solver v0.1.0 and its checker. Apache-2.0. MV2 of Munim, Inc.; made with AI agents.

  python he2020/test_he2020.py -v
Optional: HE_OFFICIAL=<path to the benchmark's he2020 feasibility_check.py> also compares with the official checker.
"""
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(os.path.dirname(HERE), "kit")
for p in (KIT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import he2020_check as HC  # noqa: E402
import solve as S  # noqa: E402


def line_inst(c1_window, c2_window=(0, 20), lE=100.0):
    """Two customers: d(0,1)=1, d(1,2)=1, d(2,E)=1, no service; preferred 10 and 5; rho 1."""
    d = [[0, 1, 2, 0], [1, 0, 1, 1], [2, 1, 0, 1], [0, 1, 1, 0]]
    return {"num_customers": 2, "num_vehicles": 1, "vehicle_capacity": 10, "service_time": 0,
            "depot": {"id": 0, "x": 0, "y": 0, "time_window": [0, 100], "demand": 0},
            "depot_end": {"id": 3, "x": 0, "y": 0, "time_window": [0, lE], "demand": 0},
            "customers": [{"id": 1, "x": 1, "y": 0, "demand": 1, "time_window": list(c1_window), "service_time": 0,
                           "preferred_time": 10.0},
                          {"id": 2, "x": 2, "y": 0, "demand": 1, "time_window": list(c2_window), "service_time": 0,
                           "preferred_time": 5.0}],
            "distance_matrix": d,
            "inconvenience_cost_function": {"type": "quadratic", "formula": "rho*(t-p)^2", "rho": 1.0}}


def random_inst(n=12, K=4, Q=40, rho=0.05, seed=1):
    rng = random.Random(seed)
    pts = [(50.0, 50.0)] + [(rng.uniform(0, 100), rng.uniform(0, 100)) for _ in range(n)] + [(50.0, 50.0)]
    N = n + 2
    d = [[round(math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]), 1) for j in range(N)] for i in range(N)]
    cust = []
    for i in range(1, n + 1):
        e = rng.randint(0, 500)
        w = rng.randint(80, 300)
        cust.append({"id": i, "x": pts[i][0], "y": pts[i][1], "demand": rng.randint(1, 10),
                     "time_window": [e, e + w], "service_time": 10, "preferred_time": e + w / 2.0,
                     "inconvenience_cost_at_preferred_time": 0.0})
    return {"num_customers": n, "num_vehicles": K, "vehicle_capacity": Q, "planning_horizon": 1000,
            "service_time": 10,
            "depot": {"id": 0, "x": 50, "y": 50, "time_window": [0, 1000], "demand": 0},
            "depot_end": {"id": n + 1, "x": 50, "y": 50, "time_window": [0, 1000], "demand": 0},
            "customers": cust, "distance_matrix": d,
            "inconvenience_cost_function": {"type": "quadratic", "formula": "rho*(t-p)^2", "rho": rho}}


class TestSchedule(unittest.TestCase):
    def test_binding_precedence(self):
        I = S.Inst(line_inst((0, 10)))
        dist, inc, t = I.eval([1, 2], want=True)
        self.assertAlmostEqual(dist, 3.0)
        self.assertAlmostEqual(t[0], 7.0, places=9)
        self.assertAlmostEqual(t[1], 8.0, places=9)
        self.assertAlmostEqual(inc, 18.0, places=9)

    def test_binding_window(self):
        I = S.Inst(line_inst((0, 6)))
        dist, inc, t = I.eval([1, 2], want=True)
        self.assertAlmostEqual(t[0], 6.0, places=9)
        self.assertAlmostEqual(t[1], 7.0, places=9)
        self.assertAlmostEqual(inc, 20.0, places=9)

    def test_infeasible_return(self):
        I = S.Inst(line_inst((0, 10), lE=1.5))
        self.assertIsNone(I.eval([1, 2]))

    def test_rho_sources(self):
        inst = line_inst((0, 10))
        self.assertEqual(S.rho_of(inst), (1.0, "inconvenience_cost_function.rho"))
        del inst["inconvenience_cost_function"]
        inst["inconvenience_cost_factor_rho"] = 2.0
        self.assertEqual(S.rho_of(inst), (2.0, "inconvenience_cost_factor_rho"))
        del inst["inconvenience_cost_factor_rho"]
        self.assertEqual(S.rho_of(inst), (0.0, "none"))

    def test_pava_vs_slsqp(self):
        try:
            import numpy as np
            from scipy.optimize import minimize
        except Exception:  # noqa: BLE001
            self.skipTest("scipy not installed")
        rng = random.Random(7)
        checked = 0
        for trial in range(60):
            inst = random_inst(n=8, K=8, Q=1000, rho=1.0, seed=100 + trial)
            I = S.Inst(inst)
            r = rng.sample(I.cust, rng.randint(1, 5))
            ev = I.eval(r, want=True)
            if ev is None:
                continue
            dist, inc, t = ev
            m = len(r)
            E = I.E
            cons = []
            for k in range(m):
                j = r[k]
                cons.append({"type": "ineq", "fun": lambda x, k=k, j=j: x[k] - I.e[j]})
                cons.append({"type": "ineq", "fun": lambda x, k=k, j=j: I.l[j] - x[k]})
                if k == 0:
                    cons.append({"type": "ineq", "fun": lambda x, j=j: x[0] - (I.e[0] + I.d[0][j])})
                else:
                    a = r[k - 1]
                    cons.append({"type": "ineq",
                                 "fun": lambda x, k=k, a=a, j=j: x[k] - x[k - 1] - I.s[a] - I.d[a][j]})
            last = r[-1]
            cons.append({"type": "ineq", "fun": lambda x: I.l[E] - x[m - 1] - I.s[last] - I.d[last][E]})
            pref = np.array([I.p[j] for j in r])
            _, _, et = I._forward(r)
            res = minimize(lambda x: float(np.sum((x - pref) ** 2)), np.array(et), method="SLSQP",
                           constraints=cons, options={"ftol": 1e-12, "maxiter": 500})
            ref = float(np.sum((np.array(res.x) - pref) ** 2))
            feas = all(c["fun"](res.x) >= -1e-6 for c in cons)
            self.assertTrue(I._verify_times(r, list(t)))
            if feas:
                self.assertLessEqual(inc, ref + 1e-6 * (1.0 + ref), (r, inc, ref))
                checked += 1
        self.assertGreaterEqual(checked, 10)


class TestBuild(unittest.TestCase):
    def test_fleet_and_cover(self):
        inst = random_inst(n=6, K=2, Q=1000, seed=3)
        I = S.Inst(inst)
        sol, why = I.build([[c] for c in I.cust])
        self.assertIsNone(sol)
        self.assertIn("fleet", why)
        sol, why = I.build([I.cust[:2]])
        self.assertIsNone(sol)

    def test_vrplib_integer_copy(self):
        inst = random_inst(n=5, seed=4)
        I = S.Inst(inst)
        text = S.vrplib_text(I)
        lines = text.splitlines()
        k = lines.index("EDGE_WEIGHT_SECTION")
        row1 = [int(v) for v in lines[k + 2].split()]
        self.assertEqual(row1[0], int(round(I.d[1][I.E] * 10)))
        self.assertEqual(row1[2], int(round(I.d[1][2] * 10)))


class TestSolveEndToEnd(unittest.TestCase):
    def run_solver(self, inst, limit=6):
        with tempfile.TemporaryDirectory() as td:
            ip = os.path.join(td, "inst.json")
            op = os.path.join(td, "out.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            env = dict(os.environ)
            env["PYTHONPATH"] = KIT + os.pathsep + env.get("PYTHONPATH", "")
            p = subprocess.run([sys.executable, "solve.py", "--problem", "he2020", "--instance", ip, "--output", op,
                                "--time-limit", str(limit)], cwd=HERE, capture_output=True, text=True,
                               timeout=limit + 30, env=env)
            self.assertTrue(os.path.exists(op), p.stderr[-1500:])
            with open(op, encoding="utf-8") as f:
                return json.load(f), td, ip

    def test_solution_valid(self):
        inst = random_inst(n=12, K=4, Q=40, seed=11)
        sol, _, _ = self.run_solver(inst)
        chk = HC.check(inst, sol)
        self.assertTrue(chk["feasible"], chk)
        self.assertLessEqual(abs(sol["objective_value"] - chk["objective"]), 1e-6 * max(1.0, abs(chk["objective"])))
        self.assertLessEqual(len(sol["routes"]), inst["num_vehicles"])
        self.assertGreater(chk["inconvenience"], -1e-12)

    def test_official_agrees_when_key_present(self):
        off = os.environ.get("HE_OFFICIAL")
        if not off or not os.path.exists(off):
            self.skipTest("HE_OFFICIAL not set")
        inst = random_inst(n=10, K=4, Q=40, seed=21)
        inst["inconvenience_cost_factor_rho"] = inst["inconvenience_cost_function"]["rho"]
        sol, _, _ = self.run_solver(inst, limit=5)
        bad = json.loads(json.dumps(sol))
        first = bad["routes"][0][1]
        cw = [c for c in inst["customers"] if c["id"] == first][0]["time_window"]
        bad["schedule"][str(first)] = cw[0] - 5.0
        for tag, s, want in (("good", sol, True), ("bad", bad, False)):
            with tempfile.TemporaryDirectory() as td:
                ip, sp, rp = (os.path.join(td, x) for x in ("i.json", "s.json", "r.json"))
                with open(ip, "w", encoding="utf-8") as f:
                    json.dump(inst, f)
                with open(sp, "w", encoding="utf-8") as f:
                    json.dump(s, f)
                subprocess.run([sys.executable, off, "--instance_path", ip, "--solution_path", sp, "--result_path",
                                rp], capture_output=True, text=True, timeout=120, cwd=td)
                with open(rp, encoding="utf-8") as f:
                    res = json.load(f)
                self.assertEqual(res["feasible"], want, (tag, res.get("violations")))
                self.assertEqual(HC.check(inst, s)["feasible"], want, tag)


if __name__ == "__main__":
    unittest.main()

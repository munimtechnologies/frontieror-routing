"""Tests for solve.py (FrontierOR pessoa2021, robust CVRP with a cardinality budget). Standard library only.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Run from this folder: python -m unittest -v test_pessoa2021
With PESSOA_OFFICIAL=<path to the task's feasibility_check.py>, verify() is also compared with the official checker.
"""
import itertools
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


def make_instance(n, m, seed, gamma=2, slack=0.15, asym=False):
    """An instance in the task's JSON layout. The capacity is set from a random partition into m groups, so a
    robust-feasible answer with m non-empty routes always exists (slack 0 = as tight as that partition)."""
    rng = random.Random(seed)
    pts = [(rng.randint(0, 1000), rng.randint(0, 1000)) for _ in range(n + 1)]
    D = []
    for i in range(n + 1):
        row = []
        for j in range(n + 1):
            d = int(round(math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])))
            if asym and i != j:
                d += rng.randint(0, 60)
            row.append(0 if i == j else d)
        D.append(row)
    custs = []
    for i in range(1, n + 1):
        b = rng.randint(1, 30)
        custs.append({"id": i, "x": pts[i][0], "y": pts[i][1], "nominal_demand": b,
                      "demand_deviation": int(round(b * rng.uniform(0.1, 0.6)))})
    ids = list(range(1, n + 1))
    rng.shuffle(ids)
    groups = [ids[k::m] for k in range(m)] if n >= m else [[i] for i in ids]
    bar = {c["id"]: c["nominal_demand"] for c in custs}
    hat = {c["id"]: c["demand_deviation"] for c in custs}

    def wc(g):
        devs = sorted((hat[i] for i in g), reverse=True)
        return sum(bar[i] for i in g) + sum(devs[:min(gamma, len(devs))])
    C = int(math.ceil(max(wc(g) for g in groups) * (1.0 + slack)))
    return {"num_customers": n, "num_vehicles": m, "vehicle_capacity": C, "uncertainty_set": {"Gamma": gamma},
            "depot": {"id": 0, "x": pts[0][0], "y": pts[0][1]}, "customers": custs, "distance_matrix": D}


def brute_force(pb):
    """Exact optimum: every assignment of customers to m labelled routes (non-empty when n >= m), best order each."""
    memo = {}

    def best_tour(group):
        key = tuple(sorted(group))
        if key in memo:
            return memo[key]
        if not key:
            memo[key] = 0
            return 0
        b = math.inf
        for perm in itertools.permutations(key):
            b = min(b, pb.route_cost(list(perm)))
        memo[key] = b
        return b
    best = math.inf
    for lab in itertools.product(range(pb.m), repeat=pb.n):
        groups = [[] for _ in range(pb.m)]
        for i, r in enumerate(lab):
            groups[r].append(i + 1)
        if pb.n >= pb.m and any(not g for g in groups):
            continue
        if any(g and pb.worst_case(g) > pb.C for g in groups):
            continue
        best = min(best, sum(best_tour(g) for g in groups))
    return best


class TestRobustLoad(unittest.TestCase):
    def test_worst_case_is_max_over_budget_vertices(self):
        rng = random.Random(3)
        for _ in range(60):
            n = rng.randint(1, 7)
            gamma = rng.randint(0, 8)
            inst = make_instance(n, 1, rng.randint(0, 10 ** 6), gamma=gamma)
            pb = S.Problem(inst)
            g = list(range(1, n + 1))
            want = 0
            for k in range(0, min(gamma, n) + 1):
                for sub in itertools.combinations(g, k):
                    want = max(want, sum(pb.bar[i] for i in g) + sum(pb.hat[i] for i in sub))
            self.assertEqual(pb.worst_case(g), want)

    def test_incremental_insertion_load(self):
        rng = random.Random(5)
        for t in range(40):
            gamma = t % 5
            inst = make_instance(14, 3, 100 + t, gamma=gamma)
            pb = S.Problem(inst)
            s = S.initial(pb, rng, "random")
            for r in range(pb.m):
                for c in range(1, pb.n + 1):
                    if c in s.routes[r]:
                        continue
                    g = s.gth[r]
                    add = pb.hat[c] - g if pb.hat[c] > g else 0
                    pred = s.nom[r] + pb.bar[c] + s.top[r] + add
                    self.assertEqual(pred, pb.worst_case(s.routes[r] + [c]), (t, r, c))
                self.assertEqual(s.load(r), pb.worst_case(s.routes[r]))


class TestState(unittest.TestCase):
    def check(self, s):
        fresh = S.Sol(s.pb, s.routes)
        for f in ("rcost", "nom", "top", "gth", "exc"):
            self.assertEqual(getattr(fresh, f), getattr(s, f), f)
        for v in range(1, s.pb.n + 1):
            self.assertEqual(s.routes[s.where[v]].count(v), 1)
        self.assertEqual(sorted(v for r in s.routes for v in r), list(range(1, s.pb.n + 1)))

    def test_ruin_recreate_keeps_caches_exact(self):
        rng = random.Random(9)
        for t in range(6):
            pb = S.Problem(make_instance(40, 5, 200 + t, gamma=t % 4, asym=(t % 2 == 1)))
            s = S.initial(pb, rng, "weight")
            self.check(s)
            for _ in range(200):
                rem = S.ruin(s, rng, 10.0, 10.0)
                self.assertTrue(rem)
                self.assertEqual(len(rem), len(set(rem)))
                S.insert_all(s, S.sort_removed(pb, rem, rng), rng)
                self.check(s)

    def test_polish_never_worsens(self):
        rng = random.Random(11)
        for t in range(4):
            pb = S.Problem(make_instance(30, 3, 300 + t, asym=(t >= 2)))
            s = S.initial(pb, rng, "random")
            d0 = s.distance()
            S.polish(s)
            self.assertLessEqual(s.distance(), d0)
            self.check(s)


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.pb = S.Problem(make_instance(20, 4, 7))
        s = S.Search(self.pb, 1, time.time() + 0.8).run()
        self.assertTrue(s.feasible())
        self.sol = S.build_solution(self.pb, s)

    def test_accepts_valid(self):
        ok, why, obj = S.verify(self.pb, self.sol)
        self.assertTrue(ok, why)
        self.assertAlmostEqual(obj, self.sol["objective_value"], places=6)
        for rt in self.sol["routes"]:
            self.assertLessEqual(rt["worst_case_demand"], self.pb.C)
            self.assertTrue(rt["customers"])

    def test_rejections(self):
        pb, sol = self.pb, self.sol
        bad = []
        b = json.loads(json.dumps(sol))
        del b["routes"]
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["objective_value"] += 5 + 0.01 * b["objective_value"]
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["objective_value"] = True
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["routes"] = b["routes"][:-1]
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["routes"][0]["customers"].append(b["routes"][1]["customers"][0])
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["routes"][0]["customers"] = b["routes"][0]["customers"][1:]
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["routes"][0]["customers"].append(pb.n + 1)
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["routes"].append({"customers": [], "cost": 0, "worst_case_demand": 0})
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["status"] = "infeasible"
        bad.append(b)
        # everything on one route: over capacity (objective made consistent)
        b = json.loads(json.dumps(sol))
        allc = [c for rt in b["routes"] for c in rt["customers"]]
        b["routes"] = [{"customers": allc}] + [{"customers": []} for _ in range(pb.m - 1)]
        b["objective_value"] = float(pb.route_cost(allc) + (pb.m - 1) * pb.D[0][0])
        bad.append(b)
        for x in bad:
            self.assertFalse(S.verify(pb, x)[0], str(x)[:200])


class TestOptimum(unittest.TestCase):
    def test_search_finds_brute_force_optimum(self):
        cases = [(7, 2, 1, 2, 0.1, False), (7, 3, 2, 1, 0.0, False), (6, 2, 3, 0, 0.0, True),
                 (7, 2, 4, 9, 0.05, True), (6, 3, 5, 3, 0.0, False), (2, 3, 6, 1, 0.0, False)]
        for n, m, seed, gamma, slack, asym in cases:
            pb = S.Problem(make_instance(n, m, seed, gamma=gamma, slack=slack, asym=asym))
            opt = brute_force(pb)
            best = S.Search(pb, seed, time.time() + 2.0).run()
            self.assertTrue(best.feasible(), (n, m, seed))
            self.assertAlmostEqual(best.distance(), opt, places=6, msg=(n, m, seed, gamma))
            sol = S.build_solution(pb, best)
            ok, why, obj = S.verify(pb, sol)
            self.assertTrue(ok, why)
            self.assertEqual(len(sol["routes"]), m)

    def test_tight_capacity_found(self):
        for seed in (21, 22, 23):
            pb = S.Problem(make_instance(24, 4, seed, gamma=3, slack=0.0))
            best = S.Search(pb, seed, time.time() + 2.0).run()
            self.assertTrue(best.feasible(), seed)
            self.assertTrue(S.verify(pb, S.build_solution(pb, best))[0])


@unittest.skipUnless(os.path.exists(os.environ.get("PESSOA_OFFICIAL", "")), "official checker not available")
class TestAgainstOfficialChecker(unittest.TestCase):
    """verify() and the official feasibility_check.py must agree on valid and broken solutions."""

    def test_agreement(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("official_pessoa", os.environ["PESSOA_OFFICIAL"])
        off = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(off)
        agree = 0
        for seed in range(6):
            inst = make_instance(18, 3, 400 + seed, gamma=seed % 4, slack=0.05 * (seed % 3), asym=(seed % 2 == 1))
            pb = S.Problem(inst)
            best = S.Search(pb, seed, time.time() + 0.5).run()
            good = S.build_solution(pb, best)
            cases = [good]
            b = json.loads(json.dumps(good))
            b["objective_value"] += 0.5 + 0.002 * abs(b["objective_value"])
            cases.append(b)
            b = json.loads(json.dumps(good))
            b["objective_value"] += 0.0004 * abs(b["objective_value"])
            cases.append(b)  # inside the 0.1% tolerance
            b = json.loads(json.dumps(good))
            b["routes"] = b["routes"][:-1]
            cases.append(b)
            b = json.loads(json.dumps(good))
            moved = b["routes"][1]["customers"].pop()
            b["routes"][0]["customers"].append(moved)
            b["objective_value"] = float(sum(pb.route_cost(r["customers"]) for r in b["routes"]))
            cases.append(b)  # feasible or over capacity, depending on the loads
            b = json.loads(json.dumps(good))
            allc = [c for rt in b["routes"] for c in rt["customers"]]
            b["routes"] = [{"customers": allc}] + [{"customers": []} for _ in range(pb.m - 1)]
            b["objective_value"] = float(pb.route_cost(allc))
            cases.append(b)
            b = json.loads(json.dumps(good))
            b["routes"][0]["customers"] = list(reversed(b["routes"][0]["customers"]))
            b["objective_value"] = float(sum(pb.route_cost(r["customers"]) for r in b["routes"]))
            cases.append(b)
            for k, sol in enumerate(cases):
                c = off._frontieror_validate_solution_contract(sol)
                if c is None:
                    try:
                        c = off.check_feasibility(inst, sol)
                    except Exception as e:  # noqa: BLE001 - the official CLI turns a crash into a rejection
                        c = {"feasible": False, "violations": [repr(e)]}
                ok = S.verify(pb, sol)[0]
                self.assertEqual(bool(c["feasible"]), ok, (seed, k, c.get("violations")))
                agree += 1
        self.assertGreaterEqual(agree, 40)


class TestCLI(unittest.TestCase):
    def run_cli(self, inst, T, env_extra):
        d = tempfile.mkdtemp()
        ip = os.path.join(d, "inst.json")
        op = os.path.join(d, "sol.json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        env = dict(os.environ)
        env.update(env_extra)
        env["MV2_RCVRP_LOG"] = "1"
        t0 = time.time()
        p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "pessoa2021",
                            "--instance", ip, "--output", op, "--time-limit", str(T)],
                           capture_output=True, text=True, timeout=T + 30, env=env)
        wall = time.time() - t0
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        with open(op, encoding="utf-8") as f:
            sol = json.load(f)
        with open(op + ".log.json", encoding="utf-8") as f:
            log = json.load(f)
        return sol, log, wall

    def test_two_workers_within_time(self):
        inst = make_instance(100, 8, 500, gamma=3, slack=0.05)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 6, {})
        self.assertLess(wall, 6.0)
        ok, why, obj = S.verify(pb, sol)
        self.assertTrue(ok, why)
        self.assertAlmostEqual(obj, log["best"], places=6)
        self.assertIn(log["best_source"], ("parent", "child"))
        self.assertGreater(log["parent"]["iterations"], 50)
        if hasattr(os, "fork"):
            self.assertIn("child", log)

    def test_one_worker_asymmetric(self):
        inst = make_instance(60, 5, 501, gamma=2, asym=True)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 5, {"MV2_RCVRP_WORKERS": "1"})
        self.assertLess(wall, 5.0)
        self.assertTrue(S.verify(pb, sol)[0])
        self.assertNotIn("child", log)
        self.assertFalse(log["symmetric"])

    def test_tiny_budget_still_answers(self):
        inst = make_instance(100, 10, 502, gamma=1, slack=0.1)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 4, {})
        self.assertLess(wall, 4.0)
        self.assertTrue(S.verify(pb, sol)[0])


if __name__ == "__main__":
    unittest.main()

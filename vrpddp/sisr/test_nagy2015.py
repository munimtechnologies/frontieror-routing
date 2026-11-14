"""Tests for MV2's nagy2015 (VRPDDP) SISR engine. Standard library only.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python -m unittest -v test_nagy2015
With MV2_FROC_HF=<Hugging Face frontieror/FrontierOR copy>, TestContestWay also runs the official checker.
"""
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import solve as S  # noqa: E402


def make_inst(n, seed, cap=None, spread=100):
    rng = random.Random(seed)
    pts = [(rng.randint(0, spread), rng.randint(0, spread)) for _ in range(n + 1)]
    C = cap if cap is not None else rng.randint(15, 40)
    custs = []
    for i in range(1, n + 1):
        custs.append({"id": i, "x": pts[i][0], "y": pts[i][1], "delivery_demand": rng.randint(0, min(12, C)),
                      "pickup_demand": rng.randint(0, min(12, C))})
    dm = [[int(round(math.hypot(a[0] - b[0], a[1] - b[1]))) for b in pts] for a in pts]
    return {"num_customers": n, "vehicle_capacity": C, "depot": {"id": 0, "x": pts[0][0], "y": pts[0][1]},
            "customers": custs, "distance_matrix": dm}


def simulate_ok(P, r):
    load = sum(P.dd[v] for v in r)
    if load > P.C:
        return False
    for v in r:
        load += P.pp[v] - P.dd[v]
        if load > P.C:
            return False
    return True


def all_arrangements(nodes):
    """Every set of non-empty ordered routes covering nodes, each exactly once."""
    out = []

    def rec(k, routes):
        if k == len(nodes):
            out.append([list(r) for r in routes])
            return
        v = nodes[k]
        for ri in range(len(routes)):
            r = routes[ri]
            for pos in range(len(r) + 1):
                r.insert(pos, v)
                rec(k + 1, routes)
                del r[pos]
        routes.append([v])
        rec(k + 1, routes)
        routes.pop()

    rec(0, [])
    return out


def brute_optimum(P):
    best = math.inf
    n = P.n
    for routes in all_arrangements(P.nodes):
        if all(simulate_ok(P, r) for r in routes):
            bad = any(r[k] > n and r[k + 1] == r[k] - n for r in routes for k in range(len(r) - 1))
            if bad:
                continue
            best = min(best, P.total(routes))
    return best


class TestLoadRule(unittest.TestCase):
    def test_profile_and_insertion_rule_match_simulation(self):
        rng = random.Random(7)
        for t in range(60):
            inst = make_inst(6, 100 + t, cap=rng.randint(10, 30))
            P = S.Problem(inst)
            nodes = P.nodes[:]
            rng.shuffle(nodes)
            r = nodes[:rng.randint(0, 6)]
            self.assertEqual(P.route_ok(r), simulate_ok(P, r))
            PM, SM = P.profile(r)
            for u in nodes[len(r):]:
                for k in range(len(r) + 1):
                    rule = PM[k] + P.dd[u] <= P.C and SM[k] + P.pp[u] <= P.C
                    self.assertEqual(rule, simulate_ok(P, r[:k] + [u] + r[k:]), (r, u, k))

    def test_arrangement_count(self):
        # Lah numbers: sum over k of L(4, k) = 73
        self.assertEqual(len(all_arrangements([1, 2, 3, 4])), 73)


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.inst = make_inst(5, 3, cap=60)
        self.P = S.Problem(self.inst)

    def test_accepts_built_solution(self):
        routes = [[1, 6, 2, 7], [3, 8, 4, 9, 5, 10]]
        sol = S.build_solution(self.P, routes)
        r = S.verify(self.inst, sol)
        self.assertTrue(r["feasible"], r)
        self.assertAlmostEqual(r["objective"], sol["objective_value"])

    def test_rejections(self):
        P = self.P
        good = S.build_solution(P, [[1, 6, 2, 7], [3, 8, 4, 9, 5, 10]])
        cases = {
            "missing": [[0, 1, 6, 2, 7, 0], [0, 3, 8, 4, 9, 5, 0]],
            "duplicate": [[0, 1, 6, 2, 7, 0], [0, 3, 8, 4, 9, 5, 10, 1, 0]],
            "backhaul-then-linehaul": [[0, 6, 1, 2, 7, 0], [0, 3, 8, 4, 9, 5, 10, 0]],
            "self-loop": [[0, 1, 6, 2, 7, 0], [0, 3, 8, 4, 9, 5, 10, 0], [0, 0]],
        }
        for name, routes in cases.items():
            sol = dict(good, routes=routes)
            obj = sum(P.D[a][b] for r in routes for a, b in zip(r, r[1:]))
            sol["objective_value"] = float(obj)
            self.assertFalse(S.verify(self.inst, sol)["feasible"], name)
        wrong = dict(good, objective_value=good["objective_value"] * 1.01 + 1)
        self.assertFalse(S.verify(self.inst, wrong)["feasible"])
        self.assertFalse(S.verify(self.inst, dict(good, routes_detailed=[]))["feasible"])

    def test_capacity_rejection(self):
        inst = make_inst(4, 11, cap=12)
        for c in inst["customers"]:
            c["delivery_demand"], c["pickup_demand"] = 5, 5
        P = S.Problem(inst)
        routes = [[1, 2, 3], [4, 5, 6, 7, 8]]  # 15 deliveries on one route > 12
        sol = S.build_solution(P, routes)
        self.assertFalse(P.valid(routes))
        self.assertFalse(S.verify(inst, sol)["feasible"])

    def test_fix_order(self):
        P = self.P
        routes = [[6, 1, 2, 7], [3, 8, 4, 9, 10, 5]]
        sol = S.build_solution(P, routes)
        self.assertEqual(sol["routes"][0], [0, 1, 6, 2, 7, 0])
        self.assertEqual(sol["routes"][1], [0, 3, 8, 4, 9, 5, 10, 0])
        self.assertTrue(S.verify(self.inst, sol)["feasible"])


class TestSearch(unittest.TestCase):
    def test_finds_brute_force_optimum_tiny(self):
        for seed in (1, 2, 3, 4):
            inst = make_inst(3, 40 + seed, cap=random.Random(seed).randint(8, 20))
            P = S.Problem(inst)
            opt = brute_optimum(P)
            sol = S.solve(inst, seed=seed, budget=1.5)
            chk = S.verify(inst, sol)
            self.assertTrue(chk["feasible"], chk)
            self.assertAlmostEqual(sol["objective_value"], opt, msg="seed %d" % seed)

    def test_medium_feasible_and_improves(self):
        inst = make_inst(60, 5, cap=50)
        P = S.Problem(inst)
        st = S.State(P, [])
        S.recreate(st, list(P.nodes), random.Random(1), blink=0.0)  # the same construction solve(seed=1) starts from
        construct = st.total()
        log = {}
        sol = S.solve(inst, seed=1, budget=3.0, log=log)
        chk = S.verify(inst, sol)
        self.assertTrue(chk["feasible"], chk)
        self.assertLessEqual(sol["objective_value"], construct + 1e-9)
        self.assertGreater(log["own_iterations"], 10)

    def test_main_contest_way(self):
        inst = make_inst(30, 21, cap=45)
        with tempfile.TemporaryDirectory() as d:
            ip, op = os.path.join(d, "i.json"), os.path.join(d, "o.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "nagy2015",
                                "--instance", ip, "--output", op, "--time-limit", "4"], capture_output=True,
                               text=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stderr[-800:])
            with open(op, encoding="utf-8") as f:
                sol = json.load(f)
            self.assertTrue(S.verify(inst, sol)["feasible"])


HF = os.environ.get("MV2_FROC_HF")


@unittest.skipUnless(HF and os.path.isdir(os.path.join(HF or "", "tasks", "nagy2015")), "needs MV2_FROC_HF")
class TestContestWay(unittest.TestCase):
    def setUp(self):
        tdir = os.path.join(HF, "tasks", "nagy2015")
        spec = importlib.util.spec_from_file_location("nagy_official", os.path.join(tdir, "feasibility_check.py"))
        self.off = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.off)
        with open(os.path.join(tdir, "instance", "tiny_instance.json"), encoding="utf-8") as f:
            self.tiny = json.load(f)

    def official(self, inst, sol):
        bad = self.off._frontieror_validate_solution_contract(sol)
        if bad is not None:
            return False
        try:
            return bool(self.off.check_feasibility(inst, sol)["feasible"])
        except Exception:  # noqa: BLE001 - the official program turns exceptions into a rejection
            return False

    def test_tiny_official_and_mirror_agree_on_mutations(self):
        sol = S.solve(self.tiny, seed=1, budget=2.0)
        self.assertTrue(self.official(self.tiny, sol))
        self.assertTrue(S.verify(self.tiny, sol)["feasible"])
        rng = random.Random(3)
        agree = 0
        for t in range(80):
            routes = [list(r) for r in sol["routes"]]
            kind = t % 4
            ri = rng.randrange(len(routes))
            r = routes[ri]
            if kind == 0 and len(r) > 3:  # swap two inner visits
                a, b = rng.sample(range(1, len(r) - 1), 2)
                r[a], r[b] = r[b], r[a]
            elif kind == 1 and len(r) > 3:  # move a visit to another route
                v = r.pop(rng.randrange(1, len(r) - 1))
                routes[rng.randrange(len(routes))].insert(1, v)
            elif kind == 2:  # merge two routes
                if len(routes) > 1:
                    o = routes.pop((ri + 1) % len(routes))
                    routes[ri if ri < len(routes) else 0][-1:] = o[1:]
            else:  # drop a visit
                if len(r) > 3:
                    r.pop(1)
            routes = [x for x in routes if len(x) > 2]
            obj = float(sum(S.Problem(self.tiny).D[a][b] for x in routes for a, b in zip(x, x[1:])))
            cand = dict(sol, routes=routes, objective_value=obj)
            agree += self.official(self.tiny, cand) == S.verify(self.tiny, cand)["feasible"]
        self.assertEqual(agree, 80)


if __name__ == "__main__":
    unittest.main()

"""Tests for MV2's reihaneh2019 (VRDAP) engine. Standard library only.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python -m unittest -v test_reihaneh2019

TestContestWay runs only when MV2_FROC_HF points at a downloaded copy of the FrontierOR dataset (tasks/reihaneh2019):
it runs solve.py the contest way on the public tiny instance and judges the answer with the official checker.
"""
import copy
import importlib.util
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
_spec = importlib.util.spec_from_file_location("mv2_vrdap_solve", os.path.join(HERE, "solve.py"))
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


def tags(v):
    return {r.split(":")[0] for r in v.get("reasons", [])}


def make_instance(seed, m, n, Q=10, dmax=5, vextra=2, demands=None):
    rng = random.Random(seed)
    depot = (50.0, 50.0)
    sites = [(rng.uniform(0, 100), rng.uniform(0, 100)) for _ in range(m)]
    cxy = [(rng.uniform(0, 100), rng.uniform(0, 100)) for _ in range(n)]
    dem = demands if demands is not None else [rng.randint(1, dmax) for _ in range(n)]
    nodes = [depot] + sites
    c = [[round(math.dist(a, b), 4) for b in nodes] for a in nodes]
    f = [[round(math.dist(p, s), 4) for s in sites] for p in cxy]
    return {"num_delivery_sites": m, "num_customers": n, "vehicle_capacity": Q,
            "num_vehicles": math.ceil(sum(dem) / Q) + vextra,
            "depot": {"id": 0, "x": depot[0], "y": depot[1]},
            "delivery_sites": [{"id": i + 1, "x": s[0], "y": s[1]} for i, s in enumerate(sites)],
            "customers": [{"id": k + 1, "x": p[0], "y": p[1], "demand": dem[k]} for k, p in enumerate(cxy)],
            "routing_cost_matrix": c, "assignment_cost_matrix": f}


def independent_cost(inst, sol):
    """A separate, plain reading of the problem: returns the cost, or raises AssertionError if the answer breaks a rule."""
    m, n, Q, V = (inst["num_delivery_sites"], inst["num_customers"], inst["vehicle_capacity"],
                  inst["num_vehicles"])
    c, f = inst["routing_cost_matrix"], inst["assignment_cost_matrix"]
    d = {cu["id"]: cu["demand"] for cu in inst["customers"]}
    routes = sol["routes"]
    assert len(routes) <= V, "too many tours"
    site_tour = {}
    cost = 0.0
    for v, r in routes.items():
        assert 1 <= int(v) <= V
        seq = r["sequence"]
        assert seq[0] == 0 and seq[-1] == 0 and len(seq) >= 3
        inner = seq[1:-1]
        assert 0 not in inner and len(set(inner)) == len(inner)
        assert [list(a) for a in r["arcs"]] == [[seq[x], seq[x + 1]] for x in range(len(seq) - 1)]
        for i in inner:
            assert 1 <= i <= m
            assert i not in site_tour, "site on two tours"
            site_tour[i] = int(v)
        cost += sum(c[seq[x]][seq[x + 1]] for x in range(len(seq) - 1))
    load = {}
    assert sorted(int(k) for k in sol["assignments"]) == list(range(1, n + 1))
    for k_str, i in sol["assignments"].items():
        k = int(k_str)
        assert i in site_tour, "customer at a site no tour visits"
        ct = sol["customer_tours"][k_str]
        assert ct["site"] == i and ct["vehicle"] == site_tour[i]
        load[site_tour[i]] = load.get(site_tour[i], 0) + d[k]
        cost += f[k - 1][i - 1]
    assert all(x <= Q for x in load.values()), "tour over capacity"
    assert abs(cost - sol["objective_value"]) <= 1e-6 * max(1.0, cost)
    return cost


def set_partitions(items):
    if not items:
        yield []
        return
    first, rest = items[0], items[1:]
    for part in set_partitions(rest):
        for idx in range(len(part)):
            yield part[:idx] + [[first] + part[idx]] + part[idx + 1:]
        yield [[first]] + part


def brute_force(inst):
    m, n, Q, V = (inst["num_delivery_sites"], inst["num_customers"], inst["vehicle_capacity"],
                  inst["num_vehicles"])
    c, f = inst["routing_cost_matrix"], inst["assignment_cost_matrix"]
    d = [0] + [cu["demand"] for cu in sorted(inst["customers"], key=lambda x: x["id"])]
    tsp = {}

    def tour(block):
        key = tuple(sorted(block))
        if key not in tsp:
            tsp[key] = min(c[0][p[0]] + sum(c[p[x]][p[x + 1]] for x in range(len(p) - 1)) + c[p[-1]][0]
                           for p in itertools.permutations(key))
        return tsp[key]

    routing = {}
    best = math.inf
    for asg in itertools.product(range(1, m + 1), repeat=n):
        load = [0] * (m + 1)
        fc = 0.0
        for k, i in enumerate(asg, 1):
            load[i] += d[k]
            fc += f[k - 1][i - 1]
        if fc >= best:
            continue
        opened = tuple(i for i in range(1, m + 1) if load[i] > 0)
        if any(load[i] > Q for i in opened):
            continue
        key = (opened, tuple(load[i] for i in opened))
        if key not in routing:
            rb = math.inf
            for part in set_partitions(list(opened)):
                if len(part) > V or any(sum(load[i] for i in b) > Q for b in part):
                    continue
                rb = min(rb, sum(tour(b) for b in part))
            routing[key] = rb
        best = min(best, fc + routing[key])
    return best


class TestBasics(unittest.TestCase):
    def test_tour_helpers(self):
        inst = make_instance(3, 6, 10)
        P = S.Problem(inst)
        seq = [3, 1, 5]
        base = S.tour_cost(P.c, seq)
        delta, pos = S.best_pos(P.c, seq, 2)
        brute = min(S.tour_cost(P.c, seq[:p] + [2] + seq[p:]) - base for p in range(len(seq) + 1))
        self.assertAlmostEqual(delta, brute, places=9)
        self.assertAlmostEqual(S.tour_cost(P.c, seq[:pos] + [2] + seq[pos:]) - base, brute, places=9)
        self.assertAlmostEqual(S.best_pos(P.c, [], 4)[0], P.c[0][4] + P.c[4][0], places=9)
        tour = [1, 2, 3, 4, 5, 6]
        best = min(S.tour_cost(P.c, list(p)) for p in itertools.permutations(tour))
        got, gc = S.opt_tour(P.c, tour)
        self.assertEqual(sorted(got), tour)
        self.assertAlmostEqual(gc, S.tour_cost(P.c, got), places=9)
        self.assertLessEqual(gc, S.tour_cost(P.c, tour) + 1e-9)
        self.assertLessEqual(gc, best * 1.25 + 1e-9)

    def test_feasible_and_independent(self):
        for seed in range(4):
            inst = make_instance(100 + seed, 12, 30, Q=12)
            sol = S.solve(inst, seed=seed + 1, budget=1.0)
            self.assertIsNotNone(sol)
            v = S.verify(inst, sol)
            self.assertTrue(v["feasible"], v["reason"])
            cost = independent_cost(inst, sol)
            self.assertAlmostEqual(v["objective"], cost, places=6)

    def test_brute_force_optimum(self):
        hits, worst = 0, 0.0
        for seed in range(6):
            inst = make_instance(200 + seed, 4, 5, Q=8)
            opt = brute_force(inst)
            sol = S.solve(inst, seed=1, budget=1.5)
            self.assertIsNotNone(sol)
            self.assertTrue(S.verify(inst, sol)["feasible"])
            got = independent_cost(inst, sol)
            self.assertGreaterEqual(got, opt - 1e-6)
            if got <= opt + 1e-6:
                hits += 1
            worst = max(worst, got / opt - 1.0)
        self.assertGreaterEqual(hits, 5, "optimum on %d of 6" % hits)
        self.assertLess(worst, 0.01)

    def test_tight_capacity_needs_packing(self):
        inst = make_instance(7, 6, 9, Q=6, demands=[2] * 9, vextra=0)
        self.assertEqual(inst["num_vehicles"], 3)
        sol = S.solve(inst, seed=1, budget=1.0)
        self.assertIsNotNone(sol)
        self.assertTrue(S.verify(inst, sol)["feasible"])
        independent_cost(inst, sol)
        st = S.ffd_state(S.Problem(inst))
        self.assertIsNotNone(st)
        self.assertTrue(S.verify(inst, S.build_solution(S.Problem(inst), st))["feasible"])


class TestVerifyMirror(unittest.TestCase):
    def setUp(self):
        self.inst = make_instance(11, 8, 16, Q=10)
        self.sol = S.solve(self.inst, seed=3, budget=0.8)
        self.assertTrue(S.verify(self.inst, self.sol)["feasible"])

    def bad(self, sol, tag):
        v = S.verify(self.inst, sol)
        self.assertFalse(v["feasible"], tag)
        return v

    def test_missing_customer(self):
        s = copy.deepcopy(self.sol)
        del s["customer_tours"]["1"]
        self.assertIn("C10", tags(self.bad(s, "missing")))

    def test_wrong_objective(self):
        s = copy.deepcopy(self.sol)
        s["objective_value"] *= 1.01
        self.assertEqual(tags(self.bad(s, "objective")), {"C12"})
        s["objective_value"] = True
        self.bad(s, "bool objective")

    def test_site_on_two_tours(self):
        s = copy.deepcopy(self.sol)
        site = s["routes"]["1"]["sequence"][1]
        nv = str(len(s["routes"]) + 1)
        if int(nv) > self.inst["num_vehicles"]:
            self.skipTest("no spare vehicle")
        s["routes"][nv] = {"arcs": [[0, site], [site, 0]], "sequence": [0, site, 0]}
        s["objective_value"] += self.inst["routing_cost_matrix"][0][site] + self.inst["routing_cost_matrix"][site][0]
        self.assertIn("C1", tags(self.bad(s, "twice")))

    def test_over_capacity(self):
        inst = make_instance(5, 4, 6, Q=6, demands=[3, 3, 3, 3, 1, 1])
        P = S.Problem(inst)
        st = S.empty_state(P)
        st.tours, st.tload, st.tcost = [[1, 2, 3, 4]], [14.0], [S.tour_cost(P.c, [1, 2, 3, 4])]
        for i in (1, 2, 3, 4):
            st.tour_of[i] = 0
        for k, i in zip(range(1, 7), (1, 2, 3, 4, 1, 2)):
            st.asg[k] = i
            st.sload[i] += P.d[k]
            st.fcost += P.f[k][i]
        v = S.verify(inst, S.build_solution(P, st))
        self.assertFalse(v["feasible"])
        self.assertIn("C8", tags(v))

    def test_assigned_site_not_visited(self):
        s = copy.deepcopy(self.sol)
        visited = {i for r in s["routes"].values() for i in r["sequence"]}
        free = [i for i in range(1, self.inst["num_delivery_sites"] + 1) if i not in visited]
        if not free:
            self.skipTest("every site visited")
        old = s["assignments"]["2"]
        s["assignments"]["2"] = free[0]
        s["objective_value"] += (self.inst["assignment_cost_matrix"][1][free[0] - 1]
                                 - self.inst["assignment_cost_matrix"][1][old - 1])
        self.bad(s, "unvisited site")

    def test_flow_and_depot(self):
        s = copy.deepcopy(self.sol)
        r = s["routes"]["1"]
        r["arcs"] = r["arcs"][:-1]
        self.assertIn("C3", tags(self.bad(s, "flow")))
        self.assertFalse(S.verify(self.inst, {"routes": {}})["feasible"])
        self.assertFalse(S.verify(self.inst, None)["feasible"])


class TestCLI(unittest.TestCase):
    def test_cli_writes_feasible_in_time(self):
        inst = make_instance(21, 15, 40, Q=15)
        with tempfile.TemporaryDirectory() as td:
            ip = os.path.join(td, "in.json")
            op = os.path.join(td, "out.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            t0 = time.monotonic()
            p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "reihaneh2019",
                                "--instance", ip, "--output", op, "--time-limit", "5"],
                               capture_output=True, text=True, timeout=60)
            wall = time.monotonic() - t0
            self.assertEqual(p.returncode, 0, p.stderr[-500:])
            self.assertLess(wall, 5.0)
            with open(op, encoding="utf-8") as f:
                sol = json.load(f)
            self.assertTrue(S.verify(inst, sol)["feasible"])
            independent_cost(inst, sol)


@unittest.skipUnless(os.environ.get("MV2_FROC_HF"), "set MV2_FROC_HF to a FrontierOR dataset copy")
class TestContestWay(unittest.TestCase):
    def test_tiny_official(self):
        tdir = os.path.join(os.environ["MV2_FROC_HF"], "tasks", "reihaneh2019")
        ip = os.path.join(tdir, "instance", "tiny_instance.json")
        checker = os.path.join(tdir, "feasibility_check.py")
        with open(ip, encoding="utf-8") as f:
            inst = json.load(f)
        with tempfile.TemporaryDirectory() as td:
            op = os.path.join(td, "tiny.solution.json")
            rp = os.path.join(td, "tiny.result.json")
            p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "reihaneh2019",
                                "--instance", ip, "--output", op, "--time-limit", "10"],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 0, p.stderr[-500:])
            subprocess.run([sys.executable, checker, "--instance_path", ip, "--solution_path", op,
                            "--result_path", rp], capture_output=True, text=True, timeout=600, cwd=td)
            with open(rp, encoding="utf-8") as f:
                res = json.load(f)
            with open(op, encoding="utf-8") as f:
                sol = json.load(f)
            self.assertTrue(res.get("feasible"), str(res.get("violations"))[:500])
            self.assertTrue(S.verify(inst, sol)["feasible"])
        gp = os.path.join(tdir, "gurobi_solution", "tiny_solution.json")
        if os.path.exists(gp):
            with open(gp, encoding="utf-8") as f:
                g = json.load(f)
            self.assertTrue(S.verify(inst, g)["feasible"], S.verify(inst, g)["reason"])


if __name__ == "__main__":
    unittest.main()

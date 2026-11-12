"""Tests for MV2's vidal2011 (MDPVRP) solver. MV2 of Munim, Inc. Made with AI agents working in MV2's name.
License: Apache-2.0.

  python -m unittest -v test_vidal2011
If VIDAL_OFFICIAL points to the benchmark's feasibility_check.py, solver outputs are also judged by it, and our
verify() is compared with it on randomly broken solutions.
"""
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
sys.path.insert(0, HERE)
import solve as S  # noqa: E402


def make_instance(depots, custs, t, m, Q, T):
    """custs: list of (x, y, demand, service, pattern_list)."""
    return {
        "problem_type": "MDPVRP", "n": len(custs), "d": len(depots), "t": t, "m": m,
        "vehicle_capacity": Q, "route_duration_limit": T,
        "depots": [{"id": i, "x": x, "y": y} for i, (x, y) in enumerate(depots)],
        "customers": [{"id": i, "x": x, "y": y, "demand": q, "service_duration": s, "frequency": len(p[0]),
                       "pattern_list": p} for i, (x, y, q, s, p) in enumerate(custs)],
    }


def random_instance(n, d, t, m, seed, Q=60, T=500, qmax=20):
    rng = random.Random(seed)
    depots = [(rng.randint(0, 100), rng.randint(0, 100)) for _ in range(d)]
    custs = []
    for _ in range(n):
        f = rng.choice([1, 1, 2] if t >= 2 else [1])
        allp = [list(c) for c in itertools.combinations(range(1, t + 1), f)]
        pats = rng.sample(allp, rng.randint(1, len(allp)))
        custs.append((rng.randint(0, 100), rng.randint(0, 100), rng.randint(1, qmax), rng.randint(0, 5), pats))
    return make_instance(depots, custs, t, m, Q, T)


def official():
    p = os.environ.get("VIDAL_OFFICIAL")
    if not p or not os.path.exists(p):
        return None
    spec = importlib.util.spec_from_file_location("vidal_official", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(inst, tl=6.0, workers=1, seed=1):
    with tempfile.TemporaryDirectory() as dd:
        out = os.path.join(dd, "sol.json")
        obj, log = S.solve(inst, out, tl, seed=seed, workers=workers, t0=time.monotonic())
        with open(out, encoding="utf-8") as f:
            sol = json.load(f)
    return obj, log, sol


# ------------------------------------------------------------------------------------------- brute force
def brute_force(inst):
    pb = S.Problem(inst)
    d, n, t, m = pb.d, pb.n, pb.t, pb.m
    route_memo = {}

    def best_route(o, S_):
        key = (o, S_)
        if key in route_memo:
            return route_memo[key]
        best = math.inf
        if sum(pb.dem[v] for v in S_) <= pb.Q:
            for perm in itertools.permutations(S_):
                c, ld, sv = pb.route_eval(o, list(perm))
                if c + sv <= pb.T + 1e-9 and c < best:
                    best = c
        route_memo[key] = best
        return best

    part_memo = {}

    def best_part(o, S_, k):
        if not S_:
            return 0.0
        if k == 0:
            return math.inf
        key = (o, S_, k)
        if key in part_memo:
            return part_memo[key]
        items = sorted(S_)
        first, rest = items[0], items[1:]
        best = math.inf
        for r in range(len(rest) + 1):
            for comb in itertools.combinations(rest, r):
                A = frozenset((first,) + comb)
                ca = best_route(o, A)
                if ca == math.inf:
                    continue
                cb = best_part(o, S_ - A, k - 1)
                if ca + cb < best:
                    best = ca + cb
        part_memo[key] = best
        return best

    best = math.inf
    for choice in itertools.product(*[pb.opts[c] for c in range(n)]):
        tot = 0.0
        for o in range(d):
            for l in range(1, t + 1):
                S_ = frozenset(d + c for c in range(n) if choice[c][0] == o and l in pb.days[c][choice[c][1]])
                tot += best_part(o, S_, m)
                if tot >= best:
                    break
            if tot >= best:
                break
        best = min(best, tot)
    return best


class TestSolver(unittest.TestCase):
    def check_sol(self, inst, sol):
        pb = S.Problem(inst)
        ok, why, cost = S.verify(pb, sol)
        self.assertTrue(ok, why)
        self.assertAlmostEqual(sol["objective_value"], cost, places=6)
        off = official()
        if off is not None:
            self.assertIsNone(off._frontieror_validate_solution_contract(sol))
            r = off.check_feasibility(inst, sol)
            self.assertTrue(r["feasible"], r.get("violations"))

    def test_brute_force_optimum(self):
        for seed in (1, 2, 3):
            inst = random_instance(4, 2, 2, 2, seed, Q=25, T=400)
            opt = brute_force(inst)
            self.assertLess(opt, math.inf)
            obj, log, sol = run(inst, tl=6.0)
            self.check_sol(inst, sol)
            self.assertGreaterEqual(obj, opt - 1e-6)
            self.assertLessEqual(obj, opt + 1e-6, "seed %d: %s vs optimum %s" % (seed, obj, opt))

    def test_brute_force_tight_capacity(self):
        # capacity 22 forces two routes on each period (customers 0 and 1 alone carry 20 on both periods)
        custs = [(10, 50, 10, 0, [[1, 2]]), (90, 50, 10, 0, [[1, 2]]), (50, 10, 10, 0, [[1], [2]]),
                 (50, 90, 10, 0, [[1], [2]]), (20, 20, 4, 0, [[1], [2]])]
        inst = make_instance([(50, 50)], custs, 2, 2, 22, 600)
        opt = brute_force(inst)
        self.assertLess(opt, math.inf)
        obj, log, sol = run(inst, tl=6.0)
        self.check_sol(inst, sol)
        self.assertLessEqual(obj, opt + 1e-6)

    def test_random_instances(self):
        for seed in (1, 2, 3):
            inst = random_instance(30, 3, 4, 3, seed)
            obj, log, sol = run(inst, tl=6.0)
            self.check_sol(inst, sol)
            if log["construction"]["violated_routes"] == 0:
                self.assertLessEqual(obj, log["construction"]["cost"] + 1e-6)
            self.assertLessEqual(max(r["vehicle"] for r in sol["routes"]), 3)

    def test_duration_binds(self):
        # depot at the origin, customers 30 away in four directions: duration 70 allows one customer per route
        custs = [(30, 0, 1, 5, [[1]]), (-30, 0, 1, 5, [[1]]), (0, 30, 1, 5, [[1]]), (0, -30, 1, 5, [[1]])]
        inst = make_instance([(0, 0)], custs, 1, 4, 100, 70)
        obj, log, sol = run(inst)
        self.check_sol(inst, sol)
        self.assertEqual(len(sol["routes"]), 4)
        self.assertAlmostEqual(obj, 240.0, places=6)

    def test_two_workers(self):
        inst = random_instance(25, 2, 3, 3, 7)
        obj, log, sol = run(inst, tl=6.0, workers=2)
        self.check_sol(inst, sol)


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.inst = random_instance(12, 2, 3, 2, 5)
        self.pb = S.Problem(self.inst)
        _, _, self.sol = run(self.inst, tl=4.0)

    def tampered(self):
        bad = json.loads(json.dumps(self.sol))
        return bad

    def fix_obj(self, sol):
        cost = 0.0
        for r in sol["routes"]:
            seq = [self.pb.d + c for c in r["customers"]]
            cost += self.pb.route_eval(r["depot"], seq)[0]
        sol["objective_value"] = cost
        return sol

    def both_reject(self, bad):
        self.assertFalse(S.verify(self.pb, bad)[0])
        off = official()
        if off is not None:
            self.assertFalse(off.check_feasibility(self.inst, bad)["feasible"])

    def test_accepts_own(self):
        self.assertTrue(S.verify(self.pb, self.sol)[0])

    def test_rejects_objective(self):
        bad = self.tampered()
        bad["objective_value"] *= 0.5
        self.both_reject(bad)

    def test_rejects_vehicle_over_m(self):
        bad = self.tampered()
        bad["routes"][0]["vehicle"] = self.inst["m"] + 1
        self.both_reject(bad)

    def test_rejects_double_departure(self):
        bad = self.tampered()
        r0 = bad["routes"][0]
        twin = [r for r in bad["routes"][1:] if r["depot"] == r0["depot"] and r["period"] == r0["period"]]
        if not twin:
            self.skipTest("only one route on that depot and period")
        twin[0]["vehicle"] = r0["vehicle"]
        self.both_reject(bad)

    def test_rejects_missing_visit(self):
        bad = self.tampered()
        bad["routes"][0]["customers"] = bad["routes"][0]["customers"][1:]
        bad["routes"] = [r for r in bad["routes"] if r["customers"]]
        self.both_reject(self.fix_obj(bad))

    def test_rejects_wrong_pattern(self):
        bad = self.tampered()
        k = next(iter(bad["assignments"]))
        bad["assignments"][k]["pattern"] = [99]
        self.both_reject(bad)

    def test_rejects_wrong_depot(self):
        bad = self.tampered()
        r = bad["routes"][0]
        c = r["customers"][0]
        bad["assignments"][str(c)]["depot"] = 1 - bad["assignments"][str(c)]["depot"]
        self.both_reject(bad)

    def test_agrees_with_official_on_random_breaks(self):
        off = official()
        if off is None:
            self.skipTest("VIDAL_OFFICIAL not set")
        rng = random.Random(3)
        disagree = []
        for trial in range(300):
            bad = self.tampered()
            routes = bad["routes"]
            kind = rng.randrange(4)
            if kind == 0:  # move a visit to another route (any depot / period)
                a = rng.choice(routes)
                if a["customers"]:
                    c = a["customers"].pop(rng.randrange(len(a["customers"])))
                    b = rng.choice(routes)
                    b["customers"].insert(rng.randint(0, len(b["customers"])), c)
            elif kind == 1:  # shuffle a route
                a = rng.choice(routes)
                rng.shuffle(a["customers"])
            elif kind == 2:  # merge two routes of the same depot and period
                a = rng.choice(routes)
                same = [r for r in routes if r is not a and r["depot"] == a["depot"] and r["period"] == a["period"]]
                if same:
                    a["customers"] += same[0]["customers"]
                    routes.remove(same[0])
            else:  # change a pattern to another feasible one
                c = rng.randrange(self.pb.n)
                bad["assignments"][str(c)]["pattern"] = list(rng.choice(self.pb.pat[c]))
            bad["routes"] = [r for r in routes if r["customers"]]
            self.fix_obj(bad)
            ours = S.verify(self.pb, bad)[0]
            theirs = bool(off.check_feasibility(self.inst, bad)["feasible"])
            if ours != theirs:
                disagree.append((trial, kind, ours, theirs))
        self.assertEqual(disagree, [])


class TestCLI(unittest.TestCase):
    def test_cli(self):
        inst = random_instance(20, 2, 4, 3, 11)
        with tempfile.TemporaryDirectory() as dd:
            ip = os.path.join(dd, "inst.json")
            op = os.path.join(dd, "out.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            t = time.monotonic()
            subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "vidal2011",
                            "--instance", ip, "--output", op, "--time-limit", "10"], check=True, timeout=60)
            self.assertLess(time.monotonic() - t, 9.0)
            with open(op, encoding="utf-8") as f:
                sol = json.load(f)
        TestSolver.check_sol(self, inst, sol)


if __name__ == "__main__":
    unittest.main()

"""Tests for solve.py (FrontierOR alba2013, double TSP with multiple stacks). Standard library only.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Run from this folder: python -m unittest -v test_alba2013
With DTSP_OFFICIAL=<path to the task's feasibility_check.py>, verify() is also compared with the official checker.
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


def make_instance(n, s, l, seed, asym=False):
    rng = random.Random(seed)

    def region():
        pts = [(rng.randint(0, 100), rng.randint(0, 100)) for _ in range(n + 1)]
        M = []
        for i in range(n + 1):
            row = []
            for j in range(n + 1):
                d = 0 if i == j else int(round(math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])))
                if asym and i != j:
                    d += rng.randint(0, 9)
                row.append(d)
            M.append(row)
        return pts, M
    pp, PM = region()
    dp, DM = region()
    return {"parameters": {"num_stacks_s": s, "stack_height_l": l, "num_requests_n": n,
                           "num_pickup_vertices": n + 1, "num_delivery_vertices": n + 1,
                           "coordinate_range": [0, 100], "distance_metric": "rounded_euclidean"},
            "pickup_region": {"depot_index": 0, "coordinates": [{"vertex_id": i, "x": x, "y": y}
                                                                for i, (x, y) in enumerate(pp)],
                              "distance_matrix": PM},
            "delivery_region": {"depot_index": 0, "coordinates": [{"vertex_id": i, "x": x, "y": y}
                                                                  for i, (x, y) in enumerate(dp)],
                                "distance_matrix": DM},
            "requests": [{"request_id": i, "pickup_vertex": i, "delivery_vertex": i, "item_size": 1}
                         for i in range(1, n + 1)]}


def brute_force(pb):
    """Exact optimum over every pair of tours, judged by the checker's LIFO rule."""
    items = pb.items
    pc = {}
    for p in itertools.permutations(items):
        pc[p] = pb.tour_cost(pb.CP, [0] + list(p))
    dc = {}
    for d in itertools.permutations(items):
        dc[d] = pb.tour_cost(pb.CD, [0] + list(d))
    dsorted = sorted(dc, key=lambda d: dc[d])
    best = math.inf
    for p in sorted(pc, key=lambda p: pc[p]):
        if pc[p] + dc[dsorted[0]] >= best:
            break
        for d in dsorted:
            if pc[p] + dc[d] >= best:
                break
            if S.loading_feasible(list(p), list(d), pb.s, pb.l):
                best = pc[p] + dc[d]
                break
    return best


def interleavings(seqs):
    if all(not q for q in seqs):
        yield []
        return
    for k, q in enumerate(seqs):
        if q:
            rest = [r if j != k else r[1:] for j, r in enumerate(seqs)]
            for tail in interleavings(rest):
                yield [q[0]] + tail


class TestDP(unittest.TestCase):
    def test_dp_matches_all_interleavings(self):
        rng = random.Random(1)
        for t in range(40):
            n = rng.randint(1, 8)
            pb = S.Problem(make_instance(n, 3, n, 100 + t, asym=(t % 2 == 1)))
            items = list(pb.items)
            rng.shuffle(items)
            s = rng.randint(1, 3)
            seqs = [[] for _ in range(s)]
            for v in items:
                seqs[rng.randrange(s)].append(v)
            want = min(pb.tour_cost(pb.CP, [0] + o) for o in interleavings(seqs))
            got, order = S.dp_tour(seqs, pb.CP)
            self.assertEqual(got, want, (t, seqs))
            self.assertEqual(sorted(order), sorted(items))
            self.assertEqual(pb.tour_cost(pb.CP, [0] + order), got)
            for q in seqs:  # every sequence kept in its own order
                pos = [order.index(v) for v in q]
                self.assertEqual(pos, sorted(pos))

    def test_plan_solutions_always_verify(self):
        rng = random.Random(2)
        for t in range(30):
            n = rng.randint(2, 14)
            s = rng.randint(1, 4)
            l = int(math.ceil(n / float(s))) + rng.randint(0, 2)
            pb = S.Problem(make_instance(n, s, l, 200 + t, asym=(t % 3 == 0)))
            plan = S.deal(rng.sample(pb.items, n), s, l, chunk=(t % 2 == 0))
            self.assertTrue(all(len(st) <= l for st in plan))
            self.assertEqual(sorted(v for st in plan for v in st), pb.items)
            sol = S.build_solution(pb, plan)
            ok, why, obj = S.verify(pb, sol)
            self.assertTrue(ok, why)
            self.assertAlmostEqual(obj, S.plan_tours(pb, plan)[0], places=6)

    def test_neighbour_keeps_plans_valid(self):
        rng = random.Random(3)
        for t in range(10):
            n, s = 20, 1 + t % 4
            l = int(math.ceil(n / float(s))) + t % 2
            plan = S.deal(list(range(1, n + 1)), s, l)
            for _ in range(500):
                q = S.neighbour(plan, rng, l)
                if q is None:
                    continue
                self.assertEqual(len(q), s)
                self.assertTrue(all(len(st) <= l for st in q))
                self.assertEqual(sorted(v for st in q for v in st), list(range(1, n + 1)))
                plan = q


class TestOptimum(unittest.TestCase):
    def test_search_finds_brute_force_optimum(self):
        cases = [(5, 2, 3, 1, False), (5, 2, 5, 2, True), (4, 1, 4, 3, False), (5, 3, 2, 4, False),
                 (5, 2, 4, 5, True), (4, 2, 2, 6, False)]
        for n, s, l, seed, asym in cases:
            pb = S.Problem(make_instance(n, s, l, seed, asym=asym))
            opt = brute_force(pb)
            best = S.Search(pb, seed, time.time() + 1.5).run()
            sol = S.build_solution(pb, best)
            ok, why, obj = S.verify(pb, sol)
            self.assertTrue(ok, why)
            self.assertAlmostEqual(obj, opt, places=6, msg=(n, s, l, seed))


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.pb = S.Problem(make_instance(12, 2, 6, 7))
        best = S.Search(self.pb, 1, time.time() + 0.8).run()
        self.sol = S.build_solution(self.pb, best)

    def test_accepts_valid(self):
        ok, why, obj = S.verify(self.pb, self.sol)
        self.assertTrue(ok, why)
        self.assertAlmostEqual(obj, self.sol["objective_value"], places=6)
        self.assertEqual(self.sol["pickup_tour"][0], 0)
        self.assertEqual(self.sol["delivery_tour"][0], 0)

    def test_rejections(self):
        pb, sol = self.pb, self.sol
        bad = []
        for f in ("pickup_tour", "delivery_tour", "objective_value"):
            b = json.loads(json.dumps(sol))
            del b[f]
            bad.append(b)
        b = json.loads(json.dumps(sol))
        b["objective_value"] += 5 + 0.01 * b["objective_value"]
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["objective_value"] = True
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["pickup_tour"] = b["pickup_tour"][:-1]
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["delivery_tour"][-1] = b["delivery_tour"][1]
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["delivery_tour"].append(pb.n + 1)
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["pickup_tour"] = b["pickup_tour"][1:] + b["pickup_tour"][:1]  # rotated listing
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["pickup_tour"][1] = float(b["pickup_tour"][1])
        bad.append(b)
        # delivering in pickup order with ONE stack is never LIFO-feasible for n >= 2
        inst1 = make_instance(6, 1, 6, 9)
        pb1 = S.Problem(inst1)
        t = [0, 1, 2, 3, 4, 5, 6]
        b1 = {"objective_value": float(pb1.tour_cost(pb1.CP, t) + pb1.tour_cost(pb1.CD, t)),
              "pickup_tour": t, "delivery_tour": list(t)}
        self.assertFalse(S.verify(pb1, b1)[0])
        b1["delivery_tour"] = [0, 6, 5, 4, 3, 2, 1]
        b1["objective_value"] = float(pb1.tour_cost(pb1.CP, t) + pb1.tour_cost(pb1.CD, b1["delivery_tour"]))
        self.assertTrue(S.verify(pb1, b1)[0])
        for x in bad:
            self.assertFalse(S.verify(pb, x)[0], str(x)[:300])

    def test_rotation_rule(self):
        # one stack, n = 2: pickup 1, 2 forces delivery 2, 1. Delivery listed [2, 0, 1] drives 0-1-2 (wrong order)
        inst = make_instance(2, 1, 2, 11)
        pb = S.Problem(inst)
        d = [2, 0, 1]
        sol = {"objective_value": float(pb.tour_cost(pb.CP, [0, 1, 2]) + pb.tour_cost(pb.CD, d)),
               "pickup_tour": [0, 1, 2], "delivery_tour": d}
        self.assertFalse(S.verify(pb, sol)[0])
        self.assertTrue(S.verify(pb, sol, strict_depot_first=False)[0])  # the official checker's reading
        sol2 = dict(sol, delivery_tour=[0, 1, 2])
        self.assertFalse(S.verify(pb, sol2, strict_depot_first=False)[0])


@unittest.skipUnless(os.path.exists(os.environ.get("DTSP_OFFICIAL", "")), "official checker not available")
class TestAgainstOfficialChecker(unittest.TestCase):
    """verify(strict_depot_first=False) and the official feasibility_check.py must agree."""

    def test_agreement(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("official_alba", os.environ["DTSP_OFFICIAL"])
        off = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(off)
        rng = random.Random(5)
        agree = 0
        for seed in range(6):
            n, s = 10 + seed, 1 + seed % 3
            l = int(math.ceil(n / float(s))) + seed % 2
            inst = make_instance(n, s, l, 400 + seed, asym=(seed % 2 == 1))
            pb = S.Problem(inst)
            best = S.Search(pb, seed, time.time() + 0.5).run()
            good = S.build_solution(pb, best)

            def recost(b):
                b["objective_value"] = float(pb.tour_cost(pb.CP, b["pickup_tour"]) +
                                             pb.tour_cost(pb.CD, b["delivery_tour"]))
                return b
            cases = [good]
            b = json.loads(json.dumps(good))
            b["objective_value"] += 0.5 + 0.002 * abs(b["objective_value"])
            cases.append(b)
            b = json.loads(json.dumps(good))
            b["objective_value"] += 0.0004 * abs(b["objective_value"])
            cases.append(b)
            b = json.loads(json.dumps(good))
            d = b["delivery_tour"]
            d[1], d[2] = d[2], d[1]
            cases.append(recost(b))
            b = json.loads(json.dumps(good))
            b["delivery_tour"] = [0] + b["delivery_tour"][1:][::-1]
            cases.append(recost(b))
            for _ in range(3):
                b = json.loads(json.dumps(good))
                p = list(pb.items)
                q = list(pb.items)
                rng.shuffle(p)
                rng.shuffle(q)
                b["pickup_tour"], b["delivery_tour"] = [0] + p, [0] + q
                cases.append(recost(b))
            b = json.loads(json.dumps(good))
            b["delivery_tour"] = b["delivery_tour"][3:] + b["delivery_tour"][:3]
            cases.append(recost(b))
            b = json.loads(json.dumps(good))
            b["pickup_tour"] = b["pickup_tour"][:-1]
            cases.append(b)
            b = json.loads(json.dumps(good))
            b["pickup_tour"][-1] = b["pickup_tour"][1]
            cases.append(recost(b))
            for k, sol in enumerate(cases):
                c = off._frontieror_validate_solution_contract(sol)
                if c is None:
                    try:
                        c = off.check_feasibility(inst, sol)
                    except Exception as e:  # noqa: BLE001 - the official CLI turns a crash into a rejection
                        c = {"feasible": False, "violations": [repr(e)]}
                ok = S.verify(pb, sol, strict_depot_first=False)[0]
                self.assertEqual(bool(c["feasible"]), ok, (seed, k, c.get("violations")))
                agree += 1
        self.assertGreaterEqual(agree, 60)


class TestCLI(unittest.TestCase):
    def run_cli(self, inst, T, env_extra):
        d = tempfile.mkdtemp()
        ip = os.path.join(d, "inst.json")
        op = os.path.join(d, "sol.json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        env = dict(os.environ)
        env.update(env_extra)
        env["MV2_DTSP_LOG"] = "1"
        t0 = time.time()
        p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "alba2013",
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
        inst = make_instance(20, 2, 10, 500)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 6, {})
        self.assertLess(wall, 6.0)
        ok, why, obj = S.verify(pb, sol)
        self.assertTrue(ok, why)
        self.assertAlmostEqual(obj, log["best"], places=6)
        self.assertGreater(log["parent"]["iterations"], 100)
        if hasattr(os, "fork"):
            self.assertIn("child", log)

    def test_one_worker_three_stacks(self):
        inst = make_instance(33, 3, 11, 501, asym=True)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 5, {"MV2_DTSP_WORKERS": "1"})
        self.assertLess(wall, 5.0)
        self.assertTrue(S.verify(pb, sol)[0])
        self.assertNotIn("child", log)

    def test_tiny_budget_still_answers(self):
        inst = make_instance(40, 3, 14, 502)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 4, {})
        self.assertLess(wall, 4.0)
        self.assertTrue(S.verify(pb, sol)[0])


if __name__ == "__main__":
    unittest.main()

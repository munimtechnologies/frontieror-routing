"""Tests for solve.py (FrontierOR fischetti1997, E-GTSP). Standard library only.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Run from this folder: python -m unittest -v test_fischetti1997
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


def make_instance(n, m, seed):
    rng = random.Random(seed)
    pts = [(rng.randint(0, 1000), rng.randint(0, 1000)) for _ in range(n)]
    cl = list(range(m)) + [rng.randrange(m) for _ in range(n - m)]
    rng.shuffle(cl)
    clusters = [[v for v in range(n) if cl[v] == c] for c in range(m)]
    vals = []
    for i in range(n):
        for j in range(i + 1, n):
            vals.append(int(round(math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]))))
    return {"problem_size": {"n": n, "m": m, "num_edges": n * (n - 1) // 2},
            "nodes": [{"id": v, "x": pts[v][0], "y": pts[v][1], "cluster": cl[v]} for v in range(n)],
            "clusters": [{"id": c, "node_ids": clusters[c], "size": len(clusters[c])} for c in range(m)],
            "distance_matrix_upper_triangular": {"values": vals}}


def brute_force(pb):
    best = math.inf
    rest = list(range(1, pb.m))
    for perm in itertools.permutations(rest):
        order = (0,) + perm
        if order[1] > order[-1]:
            continue  # each cycle once per direction is enough
        for sel in itertools.product(*[pb.members[c] for c in order]):
            best = min(best, pb.cost(list(sel)))
    return best


def random_tour(pb, rng):
    order = list(range(pb.m))
    rng.shuffle(order)
    return [rng.choice(pb.members[c]) for c in order]


class TestProblem(unittest.TestCase):
    def test_matrix_matches_checker_indexing(self):
        inst = make_instance(12, 5, 1)
        pb = S.Problem(inst)
        vals = inst["distance_matrix_upper_triangular"]["values"]
        n = pb.n
        for i in range(n):
            self.assertEqual(pb.D[i][i], 0)
            for j in range(i + 1, n):
                idx = i * (2 * n - i - 1) // 2 + (j - i - 1)  # the official checker's formula
                self.assertEqual(pb.D[i][j], vals[idx])
                self.assertEqual(pb.D[j][i], vals[idx])

    def test_bad_sizes_raise(self):
        inst = make_instance(10, 4, 2)
        inst["distance_matrix_upper_triangular"]["values"].pop()
        with self.assertRaises(ValueError):
            S.Problem(inst)


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.pb = S.Problem(make_instance(20, 6, 3))
        rng = random.Random(4)
        self.t = random_tour(self.pb, rng)
        self.c = self.pb.cost(self.t)

    def test_accepts_valid(self):
        ok, why, cost = S.verify(self.pb, S.solution_dict(self.t, self.c))
        self.assertTrue(ok, why)
        self.assertEqual(cost, self.c)

    def test_rejections(self):
        pb, t, c = self.pb, self.t, self.c
        bad = []
        bad.append({"tour": t, "visited_nodes": t})  # no objective
        bad.append(S.solution_dict(t, c + 1))  # wrong objective
        bad.append(S.solution_dict(t[:-1], c))  # one cluster missing
        other = [v for v in pb.members[pb.cl[t[0]]] if v != t[0]]
        if other:
            bad.append(S.solution_dict(t + [other[0]], c))  # two nodes of one cluster
        bad.append(S.solution_dict(t[:-1] + [pb.n], c))  # invalid id
        sol = S.solution_dict(t, c)
        sol["visited_nodes"] = sol["visited_nodes"][:-1]
        bad.append(sol)
        sol = S.solution_dict(t, c)
        sol["objective_value"] = True
        bad.append(sol)
        for b in bad:
            ok, why, _ = S.verify(pb, b)
            self.assertFalse(ok, b)


class TestMoves(unittest.TestCase):
    def test_cluster_opt_matches_brute_force_for_fixed_order(self):
        for seed in range(4):
            pb = S.Problem(make_instance(18, 7, 10 + seed))
            rng = random.Random(seed)
            t = random_tour(pb, rng)
            order = [pb.cl[v] for v in t]
            best = min(pb.cost(list(sel)) for sel in itertools.product(*[pb.members[c] for c in order]))
            s = S.Search(pb, 1, time.time() + 60)
            nt, nc = s.cluster_opt(t)
            self.assertEqual(nc, best)
            self.assertEqual(pb.cost(nt), best)
            # same cyclic order of clusters
            no = [pb.cl[v] for v in nt]
            k = no.index(order[0])
            self.assertEqual(no[k:] + no[:k], order)

    def test_moves_never_worsen_and_keep_tours_valid(self):
        for seed in range(5):
            pb = S.Problem(make_instance(80, 25, 20 + seed))
            rng = random.Random(seed)
            s = S.Search(pb, seed, time.time() + 60)
            for move in ("two_opt", "relocate", "local_search"):
                t = random_tour(pb, rng)
                c0 = pb.cost(t)
                r = getattr(s, move)(t)
                nt = r if move == "local_search" else t
                c1 = pb.cost(nt)
                self.assertLessEqual(c1, c0)
                ok, why, _ = S.verify(pb, S.solution_dict(nt, c1))
                self.assertTrue(ok, (move, why))

    def test_perturb_is_a_permutation(self):
        pb = S.Problem(make_instance(40, 12, 5))
        s = S.Search(pb, 3, time.time() + 60)
        rng = random.Random(1)
        for _ in range(200):
            t = random_tour(pb, rng)
            p = s.perturb(t)
            self.assertEqual(sorted(p), sorted(t))
            self.assertEqual(len(p), len(t))

    def test_search_finds_brute_force_optimum(self):
        for seed in range(3):
            pb = S.Problem(make_instance(15, 6, 30 + seed))
            opt = brute_force(pb)
            s = S.Search(pb, seed, time.time() + 1.0)
            best, bc = s.run()
            self.assertEqual(bc, opt)
            self.assertEqual(pb.cost(best), opt)
            self.assertTrue(S.verify(pb, S.solution_dict(best, bc))[0])


@unittest.skipUnless(os.path.exists(os.environ.get("FISCHETTI_OFFICIAL", "")), "official checker not available")
class TestAgainstOfficialChecker(unittest.TestCase):
    """verify() and the official feasibility_check.py must agree on valid and broken solutions."""

    def test_agreement(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("official_fischetti", os.environ["FISCHETTI_OFFICIAL"])
        off = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(off)
        d = tempfile.mkdtemp()
        agree = 0
        for seed in range(6):
            inst = make_instance(40, 10, 70 + seed)
            pb = S.Problem(inst)
            ip = os.path.join(d, "i%d.json" % seed)
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            rng = random.Random(seed)
            t = random_tour(pb, rng)
            c = pb.cost(t)
            cases = [S.solution_dict(t, c), S.solution_dict(t, c + 0.4), S.solution_dict(t, c + 3),
                     S.solution_dict(t[:-1], pb.cost(t[:-1])), S.solution_dict(list(reversed(t)), c)]
            other = [v for v in pb.members[pb.cl[t[0]]] if v != t[0]]
            if other:
                t2 = [other[0]] + t[1:]
                cases.append(S.solution_dict(t2, pb.cost(t2)))  # another valid selection
                t3 = t[:-1] + [other[0]]
                cases.append(S.solution_dict(t3, pb.cost(t3)))  # cluster of t[0] twice, last cluster missing
            for k, sol in enumerate(cases):
                sp = os.path.join(d, "s%d_%d.json" % (seed, k))
                with open(sp, "w", encoding="utf-8") as f:
                    json.dump(sol, f)
                r = off.check_feasibility(ip, sp)
                ok = S.verify(pb, sol)[0]
                self.assertEqual(bool(r["feasible"]), ok, (seed, k, r.get("violations")))
                agree += 1
        self.assertGreaterEqual(agree, 30)


class TestCLI(unittest.TestCase):
    def run_cli(self, inst, T, env_extra):
        d = tempfile.mkdtemp()
        ip = os.path.join(d, "inst.json")
        op = os.path.join(d, "sol.json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        env = dict(os.environ)
        env.update(env_extra)
        env["MV2_GTSP_LOG"] = "1"
        t0 = time.time()
        p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "fischetti1997",
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
        inst = make_instance(150, 40, 50)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 6, {})
        self.assertLess(wall, 6.0)
        ok, why, cost = S.verify(pb, sol)
        self.assertTrue(ok, why)
        self.assertEqual(cost, log["best"])
        self.assertIn(log["best_source"], ("parent", "child"))
        if hasattr(os, "fork"):
            self.assertIn("child", log)

    def test_one_worker(self):
        inst = make_instance(120, 30, 51)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 5, {"MV2_GTSP_WORKERS": "1"})
        self.assertLess(wall, 5.0)
        self.assertTrue(S.verify(pb, sol)[0])
        self.assertNotIn("child", log)
        self.assertEqual(log["best_source"], "parent")

    def test_tiny_budget_still_answers(self):
        inst = make_instance(60, 15, 52)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 3, {})
        self.assertLess(wall, 3.0)
        self.assertTrue(S.verify(pb, sol)[0])


if __name__ == "__main__":
    unittest.main()

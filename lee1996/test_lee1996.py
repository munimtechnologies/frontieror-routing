"""Tests for MV2's lee1996 (Steiner tree-star) solver. Apache-2.0.
MV2 of Munim, Inc.; made with AI agents working in MV2's name.

  python -m unittest -v test_lee1996            (LEE_OFFICIAL=<path to the official feasibility_check.py> adds one)
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
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import solve as L  # noqa: E402

SOLVE = os.path.join(HERE, "solve.py")


def make_inst(m, n, seed, wmax=60):
    rng = random.Random(seed)
    T = [[rng.randint(0, 100), rng.randint(0, 100)] for _ in range(m)]
    P = [[rng.randint(0, 100), rng.randint(0, 100)] for _ in range(n)]

    def dist(p, q):
        return math.hypot(p[0] - q[0], p[1] - q[1])

    return {"parameters": {"m": m, "n": n},
            "target_nodes": {"count": m, "coordinates": T},
            "steiner_nodes": {"count": n, "coordinates": P, "node_weights": [rng.randint(0, wmax) for _ in range(n)]},
            "cost_matrices": {"assignment_costs": {"matrix": [[dist(t, p) for p in P] for t in T]},
                              "interconnection_costs": {"matrix": [[dist(p, q) for q in P] for p in P]}}}


def brute_mst(D, S):
    k = len(S)
    if k <= 1:
        return 0.0
    pairs = list(itertools.combinations(S, 2))
    best = float("inf")
    for sub in itertools.combinations(pairs, k - 1):
        parent = {v: v for v in S}

        def find(v):
            while parent[v] != v:
                parent[v] = parent[parent[v]]
                v = parent[v]
            return v

        ok = True
        for a, b in sub:
            ra, rb = find(a), find(b)
            if ra == rb:
                ok = False
                break
            parent[ra] = rb
        if ok:
            best = min(best, sum(D[a][b] for a, b in sub))
    return best


def brute_opt(pb):
    best = None
    for r in range(1, pb.n + 1):
        for S in itertools.combinations(range(pb.n), r):
            c = L.State(pb, list(S)).cost
            if best is None or c < best[0]:
                best = (c, S)
    return best


class TestCore(unittest.TestCase):
    def test_mst_matches_bruteforce(self):
        pb = L.Problem(make_inst(5, 7, 1))
        rng = random.Random(3)
        for _ in range(25):
            S = sorted(rng.sample(range(pb.n), rng.randint(1, 6)))
            cost, edges = L.mst(pb.D, S, want_edges=True)
            self.assertAlmostEqual(cost, brute_mst(pb.D, S), places=9)
            self.assertEqual(len(edges), len(S) - 1)
            self.assertAlmostEqual(sum(pb.d[j][k] for j, k in edges), cost, places=9)

    def test_state_cost_matches_built_solution(self):
        pb = L.Problem(make_inst(30, 12, 2))
        rng = random.Random(4)
        for _ in range(20):
            S = rng.sample(range(pb.n), rng.randint(1, pb.n))
            st = L.State(pb, S)
            ok, why, obj = L.verify(pb, L.build_solution(pb, S))
            self.assertTrue(ok, why)
            self.assertAlmostEqual(st.cost, obj, places=7)

    def test_deltas_are_exact_and_bounds_are_safe(self):
        for seed in (5, 6, 7):
            pb = L.Problem(make_inst(25, 10, seed))
            rng = random.Random(seed)
            for _ in range(6):
                st = L.State(pb, rng.sample(range(pb.n), rng.randint(1, pb.n - 1)))
                outs = [j for j in range(pb.n) if not st.ins[j]]
                for j in outs:
                    true = L.State(pb, st.active + [j]).cost - st.cost
                    dv = L.delta_add(st, j)
                    self._check(dv, true)
                for a in st.active:
                    dv = L.delta_drop(st, a)
                    if len(st.active) == 1:
                        self.assertIsNone(dv)
                        continue
                    true = L.State(pb, [x for x in st.active if x != a]).cost - st.cost
                    self._check(dv, true)
                    for j in outs:
                        true = L.State(pb, [x for x in st.active if x != a] + [j]).cost - st.cost
                        self._check(L.delta_swap(st, a, j), true)

    def _check(self, dv, true):
        if dv is None:
            self.assertGreaterEqual(true, -1e-7)  # a pruned move never improves
        else:
            self.assertAlmostEqual(dv, true, places=7)

    def test_search_reaches_bruteforce_optimum(self):
        for seed in (11, 12, 13):
            pb = L.Problem(make_inst(15, 8, seed))
            opt = brute_opt(pb)
            s = L.Search(pb, seed, time.time() + 1.5)
            best = s.run()
            self.assertAlmostEqual(best.cost, opt[0], places=7, msg="seed %d: %r vs %r" % (seed, best.active, opt))

    def test_single_hub_instance(self):
        pb = L.Problem(make_inst(6, 1, 9))
        best = L.Search(pb, 1, time.time() + 0.3).run()
        sol = L.build_solution(pb, best.active)
        self.assertEqual(sol["active_steiner_nodes"], [0])
        self.assertEqual(sol["steiner_tree_edges"], [])
        self.assertTrue(L.verify(pb, sol)[0])


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.pb = L.Problem(make_inst(12, 9, 21))
        self.sol = L.build_solution(self.pb, [1, 4, 6, 8])
        ok, why, _ = L.verify(self.pb, self.sol)
        self.assertTrue(ok, why)

    def bad(self, mutate, word):
        sol = json.loads(json.dumps(self.sol))
        mutate(sol)
        ok, why, _ = L.verify(self.pb, sol)
        self.assertFalse(ok)
        self.assertIn(word, why)

    def test_self_loop_forest_rejected(self):
        # the shape the official checker accepts (a forest padded with a self-loop): ours must refuse it
        def m(sol):
            e = sol["steiner_tree_edges"].pop()
            sol["steiner_tree_edges"].append([e[0], e[0]])
        self.bad(m, "self-loop")

    def test_disconnected_rejected(self):
        def m(sol):
            sol["steiner_tree_edges"] = [[1, 4], [1, 6], [4, 6]]
        self.bad(m, "not connected")

    def test_repeated_edge_rejected(self):
        def m(sol):
            sol["steiner_tree_edges"][-1] = list(sol["steiner_tree_edges"][0])
        self.bad(m, "repeated edge")

    def test_inactive_assignment_rejected(self):
        self.bad(lambda s: s["assignments"].__setitem__("0", 0), "not an active hub")

    def test_missing_target_rejected(self):
        self.bad(lambda s: s["assignments"].pop("3"), "cover")

    def test_wrong_objective_rejected(self):
        self.bad(lambda s: s.__setitem__("objective_value", s["objective_value"] * 0.9995), "recomputed")

    def test_edge_to_inactive_rejected(self):
        self.bad(lambda s: s["steiner_tree_edges"].__setitem__(0, [1, 2]), "inactive")

    def test_empty_active_rejected(self):
        self.bad(lambda s: s.__setitem__("active_steiner_nodes", []), "active")


class TestCli(unittest.TestCase):
    def run_cli(self, inst, tl):
        td = tempfile.mkdtemp()
        ip, op = os.path.join(td, "inst.json"), os.path.join(td, "out.json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        env = dict(os.environ, MV2_LEE_LOG="1")
        t0 = time.time()
        p = subprocess.run([sys.executable, SOLVE, "--problem", "lee1996", "--instance", ip, "--output", op,
                            "--time-limit", str(tl)], capture_output=True, text=True, timeout=60, env=env)
        wall = time.time() - t0
        self.assertEqual(p.returncode, 0, p.stderr[-500:])
        return ip, op, wall

    def test_cli_writes_verified_solution_in_time(self):
        inst = make_inst(60, 25, 31)
        ip, op, wall = self.run_cli(inst, 8)
        self.assertLess(wall, 8.0)
        with open(op, encoding="utf-8") as f:
            sol = json.load(f)
        ok, why, obj = L.verify(L.Problem(inst), sol)
        self.assertTrue(ok, why)
        with open(op + ".log.json", encoding="utf-8") as f:
            log = json.load(f)
        self.assertEqual(log["verify_failures"], [])
        self.assertAlmostEqual(log["best"], obj, places=6)
        official = os.environ.get("LEE_OFFICIAL")
        if official:
            rp = op + ".official.json"
            subprocess.run([sys.executable, official, "--instance_path", ip, "--solution_path", op,
                            "--result_path", rp], capture_output=True, text=True, timeout=120)
            with open(rp, encoding="utf-8") as f:
                r = json.load(f)
            self.assertTrue(r.get("feasible"), r)


if __name__ == "__main__":
    unittest.main()

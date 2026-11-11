"""Offline tests for the hoffman1993 set-partitioning solver v0.4.0 (exact-cover search). MV2 of Munim, Inc.
Apache-2.0. Made with AI agents working in MV2's name. No network. Needs numpy and scipy (and ortools only for the
end-to-end test, which is skipped without it)."""
import importlib.util
import json
import os
import random
import shutil
import sys
import tempfile
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if "frontier_runtime" not in sys.modules:  # solve.py imports it at load time; the tests bring their own clock
    sys.modules["frontier_runtime"] = types.ModuleType("frontier_runtime")
_spec = importlib.util.spec_from_file_location("t_spp040", os.path.join(HERE, "spp", "hoffman1993", "solve.py"))
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


class Clock:
    def __init__(self, seconds=60.0):
        self.t0 = time.monotonic()
        self.seconds = seconds

    def elapsed(self):
        return time.monotonic() - self.t0

    def remaining(self):
        return max(0.0, self.seconds - self.elapsed())

    def share(self, f):
        return self.remaining() * f


class Inc:
    def __init__(self):
        self.value, self.solution, self.history = None, None, []

    def offer(self, value, solution, source=""):
        if self.value is not None and not value < self.value - 1e-9:
            return False
        self.value, self.solution = float(value), solution
        self.history.append((0.0, float(value), source))
        return True


def random_instance(seed, m=6, n=12, plant=True, neg=False):
    rng = random.Random(seed)
    cols = [sorted(rng.sample(range(m), rng.randint(1, 3))) for _ in range(n)]
    if plant:
        legs = list(range(m))
        rng.shuffle(legs)
        k, chunks = 0, []
        while k < m:
            s = rng.randint(1, 3)
            chunks.append(sorted(legs[k:k + s]))
            k += s
        for t, ch in enumerate(chunks):
            cols[t] = ch
        rng.shuffle(cols)
    lo = -3 if neg else 1
    cost = [rng.randint(lo, 9) for _ in range(n)]
    return {"dimensions": {"num_rows": m, "num_cols": n}, "cost_vector": cost,
            "constraint_matrix_A": {"columns": cols}, "has_base_constraints": False}


def brute(P):
    best = None
    for mask in range(1 << P["n"]):
        chosen = [j for j in range(P["n"]) if mask >> j & 1]
        if S.check(P, chosen):
            c = sum(P["cost"][j] for j in chosen)
            if best is None or c < best:
                best = c
    return best


def search(P, y=None, with_filter=False):
    inc = Inc()
    clock = Clock()
    L = rc = None
    if y is not None:
        L, rc, y = S.best_lagrangian(P, y)
        if not with_filter:
            L = rc = None
    ec = S.ExactCover(P, inc, clock, clock.elapsed() + 60.0, y=y, L=L, rc=rc)
    done = ec.run()
    return done, inc


class TestExactCover(unittest.TestCase):
    def test_matches_brute_force_plain(self):
        for seed in range(40):
            inst = random_instance(seed, plant=seed % 3 != 0, neg=seed % 2 == 0)
            P = S.load(inst)
            done, inc = search(P)
            self.assertTrue(done, seed)
            self.assertEqual(inc.value, brute(P), seed)

    def test_any_y_keeps_the_bound_valid(self):
        import numpy as np
        for seed in range(40):
            inst = random_instance(100 + seed, plant=seed % 3 != 0, neg=seed % 2 == 1)
            P = S.load(inst)
            y = np.random.RandomState(seed).normal(0.0, 4.0, P["m"])
            want = brute(P)
            for with_filter in (False, True):
                done, inc = search(P, y=y, with_filter=with_filter)
                self.assertTrue(done, (seed, with_filter))
                self.assertEqual(inc.value, want, (seed, with_filter))

    def test_lp_duals(self):
        for seed in range(20):
            P = S.load(random_instance(300 + seed, m=7, n=13))
            lp = S.run_lp(P, 10.0)
            if lp is None or lp["y"] is None:
                continue
            done, inc = search(P, y=lp["y"], with_filter=True)
            self.assertTrue(done, seed)
            self.assertEqual(inc.value, brute(P), seed)

    def test_infeasible(self):
        inst = {"dimensions": {"num_rows": 3, "num_cols": 3}, "cost_vector": [1, 1, 1],
                "constraint_matrix_A": {"columns": [[0, 1], [1, 2], [0, 2]]}}
        P = S.load(inst)
        done, inc = search(P)
        self.assertTrue(done)
        self.assertIsNone(inc.value)

    def test_empty_negative_column_is_added(self):
        inst = {"dimensions": {"num_rows": 2, "num_cols": 4}, "cost_vector": [2, 2, 3, -5],
                "constraint_matrix_A": {"columns": [[0], [1], [0, 1], []]}}
        P = S.load(inst)
        self.assertEqual(brute(P), -2.0)  # {2, 3}: 3 - 5
        done, inc = search(P)
        self.assertTrue(done)
        self.assertEqual(inc.value, -2.0)
        self.assertEqual(inc.solution["selected_rotations"], [2, 3])

    def test_base_rows_are_respected(self):
        # cheapest partition {0, 1} (cost 2) breaks the base row; next best {2} (cost 5) keeps it
        inst = {"dimensions": {"num_rows": 2, "num_cols": 3}, "cost_vector": [1, 1, 5],
                "constraint_matrix_A": {"columns": [[0], [1], [0, 1]]}, "has_base_constraints": True,
                "base_constraints": {"num_bases": 1, "num_constraints": 1, "D_matrix": {"rows": [[2.0, 2.0, 1.0]]},
                                     "lower_bounds_d1": [0.5], "upper_bounds_d2": [3.0]}}
        P = S.load(inst)
        self.assertEqual(brute(P), 5.0)
        done, inc = search(P)
        self.assertTrue(done)
        self.assertEqual(inc.value, 5.0)

    def test_dense_planted(self):
        # 40 legs, 600 dense rotations (8-14 legs each) and one planted partition of 4 rotations: the search must
        # find a partition and prove it optimal well inside a minute
        rng = random.Random(7)
        m, n = 40, 600
        cols = [sorted(rng.sample(range(m), rng.randint(8, 14))) for _ in range(n)]
        legs = list(range(m))
        rng.shuffle(legs)
        for t in range(4):
            cols[t] = sorted(legs[10 * t:10 * t + 10])
        cost = [rng.randint(5, 60) for _ in range(n)]
        P = S.load({"dimensions": {"num_rows": m, "num_cols": n}, "cost_vector": cost,
                    "constraint_matrix_A": {"columns": cols}})
        done, inc = search(P)
        self.assertTrue(done)
        self.assertIsNotNone(inc.value)
        self.assertLessEqual(inc.value, sum(cost[:4]))


class TestConfig(unittest.TestCase):
    def test_config_file(self):
        d = tempfile.mkdtemp()
        try:
            self.assertEqual(S.load_config(d), S.DEFAULT_CONFIG)
            with open(os.path.join(d, "spp_config.json"), "w") as f:
                json.dump({"phase2": "dfs", "dfs_share": 0.9}, f)
            self.assertEqual(S.load_config(d), {"phase2": "dfs", "dfs_share": 0.9, "log_file": False})
            with open(os.path.join(d, "spp_config.json"), "w") as f:
                json.dump({"phase2": "gurobi", "dfs_share": 7, "log_file": "yes"}, f)
            self.assertEqual(S.load_config(d), S.DEFAULT_CONFIG)
        finally:
            shutil.rmtree(d)


class TestSolveEndToEnd(unittest.TestCase):
    def test_solve_small(self):
        for seed in range(6):
            inst = random_instance(500 + seed, m=7, n=12)
            P = S.load(inst)
            inc = Inc()
            log = S.solve(inst, Clock(20.0), inc)
            self.assertEqual(inc.value, brute(P), (seed, log))
            if inc.value is not None:
                self.assertIn("proven", log, log)


if __name__ == "__main__":
    unittest.main()

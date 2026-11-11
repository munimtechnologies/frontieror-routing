"""Tests for MV2's fischetti1998 (orienteering) solver v0.3.0.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Run AFTER op_v030.py has built the solver folder (default /tmp/mv2-op030/solvers/op-v030, which holds solve.py and
op_core.py = the published v1 from the repository); override with MV2_OP030_DIR. Needs numpy and ortools.
- every mode returns a valid tour (closed at the depot, distinct cities, >= 3 cities, length <= t0, stated objective =
  prize sum) on random 40-city instances, and the official feasibility_check.py accepts it when the FrontierOR task
  folder is at /data/hf/tasks/fischetti1998 (MV2_FROC_TASK to override);
- on 10 random 8-city instances the prize never exceeds the brute-force optimum (Held-Karp over all subsets), and
  OR-Tools mode reaches it on at least 8 of 10;
- the parallel mode never returns less prize than the greedy seed.
"""
import importlib.util
import json
import math
import os
import random
import sys
import time
import unittest

SOLVER_DIR = os.environ.get("MV2_OP030_DIR", "/tmp/mv2-op030/solvers/op-v030")
TASK_DIR = os.environ.get("MV2_FROC_TASK", "/data/hf/tasks/fischetti1998")
T_LIMIT = 8.0


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def solver():
    sys.path.insert(0, SOLVER_DIR)
    return load(os.path.join(SOLVER_DIR, "solve.py"), "mv2_op030_solve")


def make_instance(n, seed, frac):
    """n cities (1 = depot), integer rounded Euclidean times, integer prizes; t0 = frac * (sum of depot round trips
    / n), at least the cheapest triangle through the depot."""
    rng = random.Random(seed)
    pts = {i: (rng.randint(0, 100), rng.randint(0, 100)) for i in range(1, n + 1)}
    tt = {}
    for i in range(1, n + 1):
        for j in range(i + 1, n + 1):
            tt[(i, j)] = int(round(math.dist(pts[i], pts[j])))
    prizes = {i: (0 if i == 1 else rng.randint(1, 100)) for i in range(1, n + 1)}

    def t(a, b):
        return 0 if a == b else tt[(min(a, b), max(a, b))]

    tri = min(t(1, a) + t(a, b) + t(b, 1) for a in range(2, n + 1) for b in range(2, n + 1) if a != b)
    t0 = max(tri, int(frac * sum(2 * t(1, v) for v in range(2, n + 1)) / max(1, n - 1)))
    inst = {"n": n, "depot": 1, "t0": t0, "prizes": {str(k): v for k, v in prizes.items()},
            "travel_times": {"(%d,%d)" % k: v for k, v in tt.items()}}
    return inst, t, prizes


def brute_force(n, t, prizes, t0):
    """Best prize over all closed tours through depot 1 with >= 3 cities and length <= t0 (Held-Karp)."""
    others = list(range(2, n + 1))
    k = len(others)
    INF = float("inf")
    dp = [[INF] * k for _ in range(1 << k)]
    for j in range(k):
        dp[1 << j][j] = t(1, others[j])
    for mask in range(1, 1 << k):
        for j in range(k):
            if dp[mask][j] == INF or not (mask >> j) & 1:
                continue
            for q in range(k):
                if (mask >> q) & 1:
                    continue
                nm = mask | (1 << q)
                v = dp[mask][j] + t(others[j], others[q])
                if v < dp[nm][q]:
                    dp[nm][q] = v
    best = None
    for mask in range(1, 1 << k):
        if bin(mask).count("1") < 2:
            continue
        L = min(dp[mask][j] + t(others[j], 1) for j in range(k) if (mask >> j) & 1)
        if L <= t0:
            p = sum(prizes[others[j]] for j in range(k) if (mask >> j) & 1)
            best = p if best is None else max(best, p)
    return best


def check_tour(tc, inst, t, prizes, sol):
    tour = sol["tour"]
    tc.assertEqual(tour[0], 1)
    tc.assertEqual(tour[-1], 1)
    inner = tour[1:-1]
    tc.assertNotIn(1, inner)
    tc.assertEqual(len(set(inner)), len(inner))
    tc.assertGreaterEqual(len(inner), 2)
    L = sum(t(a, b) for a, b in zip(tour[:-1], tour[1:]))
    tc.assertLessEqual(L, inst["t0"] + 1e-6)
    tc.assertEqual(sol["objective_value"], sum(prizes[v] for v in set(tour)))
    tc.assertEqual(sorted(sol["visited_nodes"]), sorted(set(tour)))
    tc.assertEqual(len(sol["edges"]), len(tour) - 1)


def official(inst, sol):
    p = os.path.join(TASK_DIR, "feasibility_check.py")
    if not os.path.exists(p):
        return None
    fc = load(p, "froc_fischetti_check")
    travel = {}
    for k, v in inst["travel_times"].items():
        i, j = fc.parse_edge_key(k)
        travel[fc.canonical_edge(i, j)] = v
    prizes = {int(k): v for k, v in inst["prizes"].items()}
    return fc.check_feasibility(list(range(1, inst["n"] + 1)), inst["depot"], inst["t0"], prizes, travel, sol)


class TestOp030(unittest.TestCase):
    S = None

    @classmethod
    def setUpClass(cls):
        assert os.path.exists(os.path.join(SOLVER_DIR, "op_core.py")), "build the solver folder first (op_v030.py)"
        cls.S = solver()

    def run_mode(self, inst, mode):
        return self.S.solve(inst, T_LIMIT, start=time.time(), output=None, cfg={"mode": mode})

    def test_valid_all_modes_40(self):
        checked = 0
        for seed in (1, 2, 3):
            inst, t, prizes = make_instance(40, 100 + seed, 3.0)
            for mode in ("parallel", "ortools", "ils"):
                t_s = time.time()
                sol = self.run_mode(inst, mode)
                self.assertLess(time.time() - t_s, T_LIMIT, mode)
                check_tour(self, inst, t, prizes, sol)
                r = official(inst, sol)
                if r is not None:
                    checked += 1
                    self.assertTrue(r["feasible"], (mode, r["violations"][:3]))
        print("official checks", checked)

    def test_brute_force_8(self):
        hits = {"parallel": 0, "ortools": 0}
        for seed in range(10):
            inst, t, prizes = make_instance(8, 500 + seed, 2.0)
            opt = brute_force(8, t, prizes, inst["t0"])
            self.assertIsNotNone(opt)
            for mode in hits:
                sol = self.run_mode(inst, mode)
                check_tour(self, inst, t, prizes, sol)
                self.assertLessEqual(sol["objective_value"], opt)
                hits[mode] += int(sol["objective_value"] == opt)
        print("brute-force optimum reached", json.dumps(hits))
        self.assertGreaterEqual(hits["ortools"], 8)

    def test_parallel_not_below_seed(self):
        inst, t, prizes = make_instance(60, 77, 4.0)
        labels, D, P, d, t0 = self.S.C.parse_instance(inst)
        self.S.C.HARD[0] = time.time() + 30
        seed = self.S.initial(D, P, d, t0)
        sp = self.S.C.score_of(P, seed)
        sol = self.run_mode(inst, "parallel")
        check_tour(self, inst, t, prizes, sol)
        self.assertGreaterEqual(sol["objective_value"], sp)


if __name__ == "__main__":
    unittest.main()

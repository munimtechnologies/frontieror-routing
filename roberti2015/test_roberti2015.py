"""Tests for solve.py (FrontierOR roberti2015, fixed charge transportation). Standard library only.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Run from this folder: python -m unittest -v test_roberti2015
"""
import importlib.util
import itertools
import json
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


def make_instance(m, n, seed, B=20, delta=0.5):
    """Random balanced FCTP instance in the task's schema (integer supplies/demands, int fixed, float unit costs)."""
    rng = random.Random(seed)
    a = [rng.randint(1, B) for _ in range(m)]
    total = sum(a)
    while total < n:
        a[rng.randrange(m)] += 1
        total = sum(a)
    cuts = sorted(rng.sample(range(1, total), n - 1)) if n > 1 else []
    b = [hi - lo for lo, hi in zip([0] + cuts, cuts + [total])]
    f = [[rng.randint(10, 200) for _ in range(n)] for _ in range(m)]
    c = [[round(rng.uniform(0.0, 200.0 * delta / max(1, B // 2)), 4) for _ in range(n)] for _ in range(m)]
    cap = [[min(a[i], b[j]) for j in range(n)] for i in range(m)]
    return {"num_sources": m, "num_sinks": n, "B": B, "delta": delta, "total_supply": total, "supply": a,
            "demand": b, "fixed_cost": f, "variable_cost": c, "capacity": cap}


def tree_flows(m, n, a, b, cells):
    """Flows of the basic solution whose basic arcs are `cells` (must be a spanning tree), by leaf peeling."""
    N = m + n
    rem = list(a) + list(b)
    adj = [set() for _ in range(N)]
    for e, (i, j) in enumerate(cells):
        adj[i].add(e)
        adj[m + j].add(e)
    alive = set(range(len(cells)))
    deg = [len(adj[v]) for v in range(N)]
    x = {}
    leaves = [v for v in range(N) if deg[v] == 1]
    while leaves:
        v = leaves.pop()
        if deg[v] != 1:
            continue
        e = [e for e in adj[v] if e in alive][0]
        i, j = cells[e]
        other = m + j if v < m else i
        x[e] = rem[v]
        rem[other] -= rem[v]
        rem[v] = 0
        alive.discard(e)
        deg[v] -= 1
        deg[other] -= 1
        if deg[other] == 1:
            leaves.append(other)
    return x, rem


def is_spanning_tree(m, n, cells):
    parent = list(range(m + n))

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u
    if len(cells) != m + n - 1:
        return False
    for (i, j) in cells:
        r1, r2 = find(i), find(m + j)
        if r1 == r2:
            return False
        parent[r1] = r2
    return True


def brute_force(pb):
    """Exact optimum: the best vertex of the transportation polytope (all spanning-tree bases)."""
    m, n = pb.m, pb.n
    allc = [(i, j) for i in range(m) for j in range(n)]
    best = float("inf")
    for comb in itertools.combinations(allc, m + n - 1):
        if not is_spanning_tree(m, n, comb):
            continue
        x, _ = tree_flows(m, n, pb.a, pb.b, comb)
        if any(v < 0 for v in x.values()):
            continue
        X = [[0] * n for _ in range(m)]
        for e, v in x.items():
            i, j = comb[e]
            X[i][j] = v
        best = min(best, pb.objective(X))
    return best


def check_state(tc, s):
    """The search's basis is a spanning tree and its flows are the tree's flows, non-negative and feasible."""
    pb = s.pb
    tc.assertTrue(is_spanning_tree(pb.m, pb.n, s.basis))
    x, rem = tree_flows(pb.m, pb.n, pb.a, pb.b, s.basis)
    for e, (i, j) in enumerate(s.basis):
        tc.assertEqual(s.X[i][j], x[e])
        tc.assertGreaterEqual(s.X[i][j], 0)
    tc.assertTrue(all(abs(r) < 1e-9 for r in rem))
    for i in range(pb.m):
        for j in range(pb.n):
            if not s.inB[i][j]:
                tc.assertEqual(s.X[i][j], 0)
    ok, why, cost = S.verify(pb, S.solution_dict(pb, s.X))
    tc.assertTrue(ok, why)
    tc.assertAlmostEqual(cost, s.cost(), places=6)


class TestProblem(unittest.TestCase):
    def test_unbalanced_raises(self):
        inst = make_instance(3, 4, 1)
        inst["supply"][0] += 1
        with self.assertRaises(ValueError):
            S.Problem(inst)

    def test_bad_shape_raises(self):
        inst = make_instance(3, 4, 2)
        inst["fixed_cost"][1].pop()
        with self.assertRaises(ValueError):
            S.Problem(inst)


class TestBasis(unittest.TestCase):
    def test_greedy_gives_feasible_tree(self):
        for seed, (m, n) in enumerate([(1, 1), (1, 5), (5, 1), (3, 4), (6, 7), (10, 10), (20, 15)]):
            pb = S.Problem(make_instance(m, n, 100 + seed))
            s = S.Search(pb, seed, time.time() + 60)
            for noise in (0.0, 0.3):
                s.load(s.greedy(noise))
                check_state(self, s)

    def test_degenerate_instance(self):
        inst = make_instance(4, 4, 7)
        inst["supply"] = [5, 5, 5, 5]
        inst["demand"] = [5, 5, 5, 5]
        inst["capacity"] = [[5] * 4 for _ in range(4)]
        pb = S.Problem(inst)
        s = S.Search(pb, 1, time.time() + 60)
        s.load(s.greedy())
        check_state(self, s)
        s.local_search()
        check_state(self, s)
        self.assertGreaterEqual(s.cost(), brute_force(pb) - 1e-6)

    def test_pivot_delta_is_exact(self):
        for seed in range(4):
            pb = S.Problem(make_instance(6, 7, 200 + seed))
            s = S.Search(pb, seed, time.time() + 60)
            s.load(s.greedy())
            rng = random.Random(seed)
            done = 0
            for _ in range(400):
                i, j = rng.randrange(pb.m), rng.randrange(pb.n)
                if s.inB[i][j]:
                    continue
                before = s.cost()
                d, theta, su, sw = s.evaluate(i, j, pb.C, pb.F)
                if theta > 0 or rng.random() < 0.3:
                    if theta == 0:
                        # a degenerate pivot: delta 0, flows unchanged
                        self.assertEqual(d, 0.0)
                    s.apply(i, j, theta, su, sw)
                    self.assertAlmostEqual(s.cost() - before, d, places=6)
                    done += 1
                    if done % 25 == 0:
                        check_state(self, s)
            check_state(self, s)
            self.assertGreater(done, 20)

    def test_snapshot_round_trip(self):
        pb = S.Problem(make_instance(8, 9, 5))
        s = S.Search(pb, 3, time.time() + 60)
        s.load(s.greedy())
        snap = s.snapshot()
        c0 = s.cost()
        s.kick(5)
        s.load(snap)
        check_state(self, s)
        self.assertAlmostEqual(s.cost(), c0, places=9)


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.pb = S.Problem(make_instance(4, 5, 9))
        s = S.Search(self.pb, 1, time.time() + 60)
        s.load(s.greedy())
        self.X = [row[:] for row in s.X]

    def test_accepts_valid(self):
        sol = S.solution_dict(self.pb, self.X)
        ok, why, cost = S.verify(self.pb, sol)
        self.assertTrue(ok, why)
        self.assertAlmostEqual(cost, sol["objective_value"], places=6)

    def test_rejections(self):
        pb, X = self.pb, self.X
        good = S.solution_dict(pb, X)
        bad = []
        b = dict(good)
        del b["objective_value"]
        bad.append(b)
        b = dict(good)
        b["objective_value"] = good["objective_value"] * 1.01 + 1
        bad.append(b)
        b = json.loads(json.dumps(good))
        i, j = next((i, j) for i in range(pb.m) for j in range(pb.n) if X[i][j] > 0)
        b["arcs_used"][i][j] = 0
        bad.append(b)
        b = json.loads(json.dumps(good))
        b["flow"][i][j] += 1
        bad.append(b)
        b = json.loads(json.dumps(good))
        b["flow"].pop()
        bad.append(b)
        b = json.loads(json.dumps(good))
        b["objective_value"] = True
        bad.append(b)
        for k, b in enumerate(bad):
            ok, why, _ = S.verify(pb, b)
            self.assertFalse(ok, k)


class TestSearch(unittest.TestCase):
    def test_local_search_never_worsens(self):
        for seed in range(4):
            pb = S.Problem(make_instance(12, 14, 300 + seed))
            s = S.Search(pb, seed, time.time() + 60)
            s.load(s.greedy(0.5))
            c0 = s.cost()
            s.local_search()
            self.assertLessEqual(s.cost(), c0 + 1e-9)
            check_state(self, s)
            # a local optimum: no improving pivot left
            for i in range(pb.m):
                for j in range(pb.n):
                    if not s.inB[i][j]:
                        self.assertGreaterEqual(s.evaluate(i, j, pb.C, pb.F)[0], -S.EPS)

    def test_search_finds_brute_force_optimum(self):
        hits = 0
        for seed, (m, n) in enumerate([(3, 3), (3, 4), (4, 3), (3, 4), (4, 4), (2, 5)]):
            pb = S.Problem(make_instance(m, n, 400 + seed))
            opt = brute_force(pb)
            s = S.Search(pb, seed, time.time() + 1.0)
            best, bc = s.run()
            sol = S.solution_dict(pb, S.matrix(pb, best))
            ok, why, cost = S.verify(pb, sol)
            self.assertTrue(ok, why)
            self.assertAlmostEqual(cost, bc, places=6)
            self.assertGreaterEqual(bc, opt - 1e-6)
            hits += abs(bc - opt) < 1e-6
        self.assertGreaterEqual(hits, 5)


@unittest.skipUnless(os.path.exists(os.environ.get("ROBERTI_OFFICIAL", "")), "official checker not available")
class TestAgainstOfficialChecker(unittest.TestCase):
    """verify() and the official feasibility_check.py must agree on valid and broken solutions."""

    def test_agreement(self):
        spec = importlib.util.spec_from_file_location("official_roberti", os.environ["ROBERTI_OFFICIAL"])
        off = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(off)
        agree = 0
        for seed in range(5):
            inst = make_instance(5, 6, 500 + seed)
            pb = S.Problem(inst)
            s = S.Search(pb, seed, time.time() + 60)
            s.load(s.greedy())
            X = [row[:] for row in s.X]
            good = S.solution_dict(pb, X)
            cases = [good]
            b = json.loads(json.dumps(good))
            b["objective_value"] = good["objective_value"] * 1.0005  # inside the 0.1% tolerance
            cases.append(b)
            b = json.loads(json.dumps(good))
            b["objective_value"] = good["objective_value"] * 1.01 + 1
            cases.append(b)
            i, j = next((i, j) for i in range(pb.m) for j in range(pb.n) if X[i][j] > 0)
            b = json.loads(json.dumps(good))
            b["arcs_used"][i][j] = 0
            cases.append(b)
            b = json.loads(json.dumps(good))
            b["flow"][i][j] += 1
            cases.append(b)
            k0, l0 = next((k, l) for k in range(pb.m) for l in range(pb.n) if X[k][l] == 0)
            b = json.loads(json.dumps(good))
            b["arcs_used"][k0][l0] = 1  # an opened but unused arc: feasible, costs its fixed charge
            b["objective_value"] = good["objective_value"] + pb.F[k0][l0]
            cases.append(b)
            b = json.loads(json.dumps(good))
            b["swapped"] = True
            b["flow"] = [[good["flow"][r][q] for r in range(pb.m)] for q in range(pb.n)]
            b["arcs_used"] = [[good["arcs_used"][r][q] for r in range(pb.m)] for q in range(pb.n)]
            cases.append(b)
            for k, sol in enumerate(cases):
                r = off.check_feasibility(inst, sol)
                ok = S.verify(pb, sol)[0]
                self.assertEqual(bool(r["feasible"]), ok, (seed, k, r.get("violations")))
                agree += 1
        self.assertGreaterEqual(agree, 35)


class TestCLI(unittest.TestCase):
    def run_cli(self, inst, T, env_extra):
        d = tempfile.mkdtemp()
        ip = os.path.join(d, "inst.json")
        op = os.path.join(d, "sol.json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        env = dict(os.environ)
        env.update(env_extra)
        env["MV2_FCTP_LOG"] = "1"
        t0 = time.time()
        p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "roberti2015",
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
        inst = make_instance(30, 30, 50)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 6, {})
        self.assertLess(wall, 6.0)
        ok, why, cost = S.verify(pb, sol)
        self.assertTrue(ok, why)
        self.assertAlmostEqual(cost, log["best"], places=6)
        self.assertIn(log["best_source"], ("parent", "child"))
        self.assertLessEqual(log["best"], log["parent"]["construction"] + 1e-6)
        if hasattr(os, "fork"):
            self.assertIn("child", log)

    def test_one_worker(self):
        inst = make_instance(20, 25, 51)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 5, {"MV2_FCTP_WORKERS": "1"})
        self.assertLess(wall, 5.0)
        self.assertTrue(S.verify(pb, sol)[0])
        self.assertNotIn("child", log)
        self.assertEqual(log["best_source"], "parent")

    def test_tiny_budget_still_answers(self):
        inst = make_instance(40, 40, 52)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 3, {})
        self.assertLess(wall, 3.0)
        self.assertTrue(S.verify(pb, sol)[0])


if __name__ == "__main__":
    unittest.main()

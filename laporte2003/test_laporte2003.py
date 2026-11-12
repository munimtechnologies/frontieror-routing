"""Tests for solve.py (FrontierOR laporte2003, travelling purchaser). Standard library only.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Run from this folder: python -m unittest -v test_laporte2003
With LAPORTE_OFFICIAL=<path to the task's feasibility_check.py>, verify() is also compared with the official checker.
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


def make_instance(n_markets, n_products, seed, unlimited=False, euclid=True, depot=0):
    """An instance in the task's JSON layout, keyed the way the official checker reads it."""
    rng = random.Random(seed)
    nv = n_markets + 1
    markets = [v for v in range(nv) if v != depot]
    tc = {}
    coords = None
    if euclid:
        coords = [[rng.randint(0, 1000), rng.randint(0, 1000)] for _ in range(nv)]
        for i in range(nv):
            for j in range(i + 1, nv):
                tc["%d,%d" % (i, j)] = int(round(math.hypot(coords[i][0] - coords[j][0],
                                                            coords[i][1] - coords[j][1])))
    else:
        for i in range(nv):
            for j in range(i + 1, nv):
                tc["%d,%d" % (i, j)] = rng.randint(1, 500)
    dem, pmk, pcs, sup = [], {}, {}, {}
    for k in range(n_products):
        cnt = rng.randint(1, max(1, n_markets // 2))
        mk = sorted(rng.sample(markets, cnt))
        d = rng.randint(1, 15)
        dem.append(d)
        pmk[str(k)] = mk
        for m in mk:
            pcs["%d,%d" % (m, k)] = rng.randint(1, 60)  # "market,product"
        if not unlimited:
            qs = {m: rng.randint(1, d) for m in mk}
            while sum(qs.values()) < d:
                m = rng.choice(mk)
                qs[m] = min(d, qs[m] + 1)
            for m in mk:
                sup["%d,%d" % (k, m)] = qs[m]  # "product,market"
    inst = {"num_vertices": nv, "num_markets": n_markets, "num_products": n_products, "depot": depot,
            "supply_type": "unlimited" if unlimited else "limited", "coordinates": coords,
            "tau": None if euclid else 500, "travel_costs": tc, "product_demands": dem, "product_markets": pmk,
            "purchase_costs": pcs}
    if not unlimited:
        inst["supplies"] = sup
    return inst


def brute_force(pb):
    """Exact optimum by enumerating market sets (with every mandatory market) and tours."""
    D = pb.D
    best = math.inf
    free = [m for m in pb.markets if not pb.mand[m]]
    for r in range(len(free) + 1):
        for extra in itertools.combinations(free, r):
            sel = list(pb.mand_markets) + list(extra)
            if len(sel) < 2:
                continue
            sol = S.build_solution(pb, [pb.depot] + sel)
            if sol is None:
                continue
            pc = sol["purchase_cost"]
            if pc >= best:
                continue
            tb = math.inf
            for perm in itertools.permutations(sel):
                if perm[0] > perm[-1]:
                    continue  # each cycle once per direction is enough
                route = [pb.depot] + list(perm)
                c = 0
                prev = route[-1]
                for v in route:
                    c += D[prev][v]
                    prev = v
                tb = min(tb, c)
            best = min(best, pc + tb)
    return best


class TestProblem(unittest.TestCase):
    def test_key_conventions(self):
        inst = make_instance(8, 4, 1)
        pb = S.Problem(inst)
        for key, c in inst["purchase_costs"].items():
            m, k = (int(s) for s in key.split(","))
            self.assertEqual(pb.price[k][m], c)
        for key, q in inst["supplies"].items():
            k, m = (int(s) for s in key.split(","))
            self.assertEqual(pb.supply[k][m], q)
        for key, c in inst["travel_costs"].items():
            i, j = (int(s) for s in key.split(","))
            self.assertEqual(pb.D[i][j], c)
            self.assertEqual(pb.D[j][i], c)

    def test_unlimited_supply_is_demand(self):
        inst = make_instance(8, 4, 2, unlimited=True)
        pb = S.Problem(inst)
        for k in range(pb.P):
            for m in inst["product_markets"][str(k)]:
                self.assertEqual(pb.supply[k][m], inst["product_demands"][k])

    def test_mandatory_matches_checker_rule(self):
        for seed in range(6):
            inst = make_instance(10, 6, 10 + seed)
            pb = S.Problem(inst)
            for i in pb.markets:
                want = False
                for k in range(pb.P):
                    mk = pb.pm.get(k, [])
                    if i in mk and sum(pb.supply[k].get(j, 0) for j in mk if j != i) < pb.dem[k]:
                        want = True
                self.assertEqual(pb.mand[i], want, (seed, i))

    def test_depot_not_zero(self):
        inst = make_instance(7, 3, 3, depot=4)
        pb = S.Problem(inst)
        self.assertEqual(pb.depot, 4)
        self.assertNotIn(4, pb.markets)
        s = S.Search(pb, 1, time.time() + 1.0)
        best, bc = s.run()
        sol = S.build_solution(pb, best)
        self.assertEqual(sol["tour"][0], 4)
        self.assertTrue(S.verify(pb, sol)[0])


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.pb = S.Problem(make_instance(12, 5, 4))
        pb = self.pb
        self.route = [pb.depot] + list(pb.useful)
        self.sol = S.build_solution(pb, self.route)

    def test_accepts_valid(self):
        ok, why, obj = S.verify(self.pb, self.sol)
        self.assertTrue(ok, why)
        self.assertAlmostEqual(obj, self.sol["objective_value"], places=6)

    def test_rejections(self):
        pb, sol = self.pb, self.sol
        bad = []
        b = dict(sol)
        del b["tour_edges"]
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["objective_value"] = sol["objective_value"] + 5
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["visited_markets"] = b["visited_markets"][:-1]
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["tour_edges"] = b["tour_edges"][:-1]
        bad.append(b)
        b = json.loads(json.dumps(sol))
        k0 = next(k for k in b["purchases"] if b["purchases"][k])
        m0 = next(iter(b["purchases"][k0]))
        b["purchases"][k0][m0] += 1
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["tour"] = []
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["objective_value"] = True
        bad.append(b)
        for x in bad:
            self.assertFalse(S.verify(pb, x)[0], x.get("objective_value"))

    def test_two_cycles_rejected(self):
        pb = self.pb
        sol = json.loads(json.dumps(self.sol))
        r = sol["tour"]
        if len(r) >= 6:
            a, b2 = r[:3], r[3:]
            sol["tour_edges"] = [[a[i], a[(i + 1) % 3]] for i in range(3)] + \
                [[b2[i], b2[(i + 1) % len(b2)]] for i in range(len(b2))]
            rc = sum(pb.D[e[0]][e[1]] for e in sol["tour_edges"])
            sol["objective_value"] = float(rc + sol["purchase_cost"])  # consistent objective, two cycles
            ok, why, _ = S.verify(pb, sol)
            self.assertFalse(ok)
            self.assertIn("not connected", why)


class TestDeltas(unittest.TestCase):
    """Incremental purchase and route deltas must equal a full recomputation."""

    def check_state(self, s):
        pb = s.pb
        fresh = S.Search(pb, 0, time.time() + 60)
        fresh.set_route(s.t)
        self.assertEqual(fresh.pcost, s.pcost)
        self.assertEqual(fresh.marg, s.marg)
        for m in range(pb.n):
            self.assertEqual(fresh.usedby[m], s.usedby[m], m)

    def test_add_drop_swap_deltas(self):
        for seed in range(4):
            for unl in (False, True):
                pb = S.Problem(make_instance(25, 8, 40 + seed, unlimited=unl, euclid=(seed % 2 == 0)))
                rng = random.Random(seed)
                s = S.Search(pb, seed, time.time() + 60)
                s.construct("add", noisy=True)
                self.assertTrue(s.is_feasible())
                for _ in range(40):
                    before = s.total()
                    outs = [j for j in pb.markets if not s.inS[j]]
                    ins_ = [v for v in s.t if not pb.mand[v]]
                    op = rng.choice(["add", "drop", "swap"])
                    if op == "add" and outs:
                        j = rng.choice(outs)
                        pd = s.add_purchase_delta(j)
                        ins, idx = s.best_insertion(j)
                        s.apply_add(j, idx)
                        self.assertAlmostEqual(s.total() - before, pd + ins, places=6)
                    elif op == "drop" and ins_ and len(s.t) >= 4:
                        v = rng.choice(ins_)
                        pd = s.drop_purchase_delta(v)
                        if pd == math.inf:
                            continue
                        g = s.removal_gain(s.t.index(v))
                        s.apply_drop(v)
                        self.assertAlmostEqual(s.total() - before, pd - g, places=6)
                    elif op == "swap" and ins_ and outs:
                        i = rng.choice(ins_)
                        j = rng.choice(outs)
                        pd = s.swap_purchase_delta(i, j)
                        if pd == math.inf:
                            continue
                        idx = s.t.index(i)
                        p, q = s.t[idx - 1], s.t[(idx + 1) % len(s.t)]
                        rd = pb.D[p][j] + pb.D[j][q] - pb.D[p][i] - pb.D[i][q]
                        s.apply_swap(i, j)
                        self.assertAlmostEqual(s.total() - before, pd + rd, places=6)
                    self.check_state(s)
                    if s.is_feasible():
                        sol = S.build_solution(pb, s.t)
                        self.assertIsNotNone(sol)
                        self.assertAlmostEqual(sol["objective_value"], s.total(), places=6)
                        self.assertTrue(S.verify(pb, sol)[0])

    def test_local_search_never_worsens(self):
        for seed in range(4):
            pb = S.Problem(make_instance(40, 12, 60 + seed, unlimited=(seed % 2 == 1), euclid=(seed < 2)))
            s = S.Search(pb, seed, time.time() + 60)
            s.construct("drop", noisy=False)
            c0 = s.total()
            s.local_search()
            self.assertLessEqual(s.total(), c0 + 1e-9)
            self.check_state(s)
            self.assertTrue(S.verify(pb, S.build_solution(pb, s.t))[0])


class TestOptimum(unittest.TestCase):
    def test_search_finds_brute_force_optimum(self):
        cases = [(7, 4, 80, False, True), (7, 4, 81, True, True), (7, 5, 82, False, False),
                 (8, 4, 83, False, True), (7, 3, 84, True, False)]
        for nm, npd, seed, unl, euc in cases:
            pb = S.Problem(make_instance(nm, npd, seed, unlimited=unl, euclid=euc))
            opt = brute_force(pb)
            s = S.Search(pb, seed, time.time() + 1.5)
            best, bc = s.run()
            self.assertAlmostEqual(bc, opt, places=6, msg=(nm, npd, seed))
            sol = S.build_solution(pb, best)
            ok, why, obj = S.verify(pb, sol)
            self.assertTrue(ok, why)
            self.assertAlmostEqual(obj, opt, places=6)


@unittest.skipUnless(os.path.exists(os.environ.get("LAPORTE_OFFICIAL", "")), "official checker not available")
class TestAgainstOfficialChecker(unittest.TestCase):
    """verify() and the official feasibility_check.py must agree on valid and broken solutions."""

    def test_agreement(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("official_laporte", os.environ["LAPORTE_OFFICIAL"])
        off = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(off)
        d = tempfile.mkdtemp()
        agree = 0
        for seed in range(6):
            inst = make_instance(20, 6, 90 + seed, unlimited=(seed % 2 == 1), euclid=(seed % 3 != 2))
            pb = S.Problem(inst)
            ip = os.path.join(d, "i%d.json" % seed)
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            oinst = off.load_instance(ip)
            s = S.Search(pb, seed, time.time() + 0.5)
            best, _ = s.run()
            good = S.build_solution(pb, best)
            allr = S.build_solution(pb, [pb.depot] + pb.markets)
            cases = [good, allr]
            b = json.loads(json.dumps(good))
            b["objective_value"] += 0.5 + 0.002 * abs(b["objective_value"])
            cases.append(b)
            b = json.loads(json.dumps(good))
            b["objective_value"] += 0.0004 * abs(b["objective_value"])
            cases.append(b)  # inside the 0.1% tolerance
            b = json.loads(json.dumps(good))
            b["visited_markets"] = b["visited_markets"][1:]
            cases.append(b)
            b = json.loads(json.dumps(good))
            k0 = next(k for k in b["purchases"] if b["purchases"][k])
            m0 = next(iter(b["purchases"][k0]))
            b["purchases"][k0][m0] = b["purchases"][k0][m0] - 1
            cases.append(b)
            b = json.loads(json.dumps(good))
            outside = [m for m in pb.markets if m not in good["visited_markets"]]
            if outside:
                b["purchases"]["0"][str(outside[0])] = 0.5
                cases.append(b)
            b = json.loads(json.dumps(good))
            b["tour_edges"] = list(reversed(b["tour_edges"]))
            cases.append(b)
            for k, sol in enumerate(cases):
                c = off._frontieror_validate_solution_contract(sol)
                if c is None:
                    try:
                        c = off.check_feasibility(oinst, sol)
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
        env["MV2_TPP_LOG"] = "1"
        t0 = time.time()
        p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "laporte2003",
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
        inst = make_instance(150, 50, 100)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 6, {})
        self.assertLess(wall, 6.0)
        ok, why, obj = S.verify(pb, sol)
        self.assertTrue(ok, why)
        self.assertAlmostEqual(obj, log["best"], places=6)
        self.assertIn(log["best_source"], ("parent", "child"))
        if hasattr(os, "fork"):
            self.assertIn("child", log)

    def test_one_worker_random_costs(self):
        inst = make_instance(120, 40, 101, unlimited=True, euclid=False)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 5, {"MV2_TPP_WORKERS": "1"})
        self.assertLess(wall, 5.0)
        self.assertTrue(S.verify(pb, sol)[0])
        self.assertNotIn("child", log)
        self.assertEqual(log["best_source"], "parent")

    def test_tiny_budget_still_answers(self):
        inst = make_instance(100, 30, 102)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 3, {})
        self.assertLess(wall, 3.0)
        self.assertTrue(S.verify(pb, sol)[0])


if __name__ == "__main__":
    unittest.main()

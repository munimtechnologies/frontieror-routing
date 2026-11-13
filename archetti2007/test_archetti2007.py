"""Tests for solve.py (FrontierOR archetti2007, inventory routing with the order-up-to policy). Standard library only.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Run from this folder: python -m unittest -v test_archetti2007
With ARCH_OFFICIAL=<path to the task's feasibility_check.py>, verify() is also compared with the official checker.
"""
import copy
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


def make_instance(n, H, seed, cap=1.5, sup=1.0, metric="manhattan", high=False, low_start=False):
    rng = random.Random(seed)
    pts = [(rng.randint(0, 100), rng.randint(0, 100)) for _ in range(n + 1)]

    def d(a, b):
        if metric == "manhattan":
            return abs(a[0] - b[0]) + abs(a[1] - b[1])
        return int(round(math.hypot(a[0] - b[0], a[1] - b[1])))
    D = [[d(pts[i], pts[j]) for j in range(n + 1)] for i in range(n + 1)]
    rets = []
    for s in range(1, n + 1):
        r = rng.randint(10, 100)
        U = r * rng.choice((2, 3))
        I0 = U - r - (rng.choice((0, r // 2)) if low_start else 0)
        h = round(rng.uniform(0.1, 0.5), 3) if high else round(rng.uniform(0.01, 0.05), 3)
        rets.append({"id": s, "x": pts[s][0], "y": pts[s][1], "demand": r, "max_inventory": U,
                     "starting_inventory": I0, "inventory_cost": h})
    sr = sum(x["demand"] for x in rets)
    return {"num_retailers": n, "time_horizon": H,
            "supplier": {"id": 0, "x": pts[0][0], "y": pts[0][1], "starting_inventory": int(sup * sr),
                         "production_rate": sr, "inventory_cost": 0.3 if high else 0.03},
            "retailers": rets, "vehicle_capacity": int(cap * sr), "distance_matrix": D}


def all_masks(pb, s):
    """Every stockout-free visit set, including visits that ship nothing: (mask, x, inventories)."""
    out = []
    for mask in range(1 << pb.H):
        inv = pb.I0[s]
        xs, invs, ok = [], [inv], True
        for t in range(pb.H):
            if mask >> t & 1:
                x = pb.U[s] - inv
                inv = pb.U[s]
            else:
                x = 0
            xs.append(x)
            inv -= pb.r[s]
            if inv < 0:
                ok = False
                break
            invs.append(inv)
        if ok:
            out.append((mask, xs, invs))
    return out


def tsp(D, nodes, cache):
    key = tuple(sorted(nodes))
    if key not in cache:
        best = 0
        if key:
            best = min(sum(D[a][b] for a, b in zip((0,) + p, p + (0,))) for p in itertools.permutations(key))
        cache[key] = best
    return cache[key]


def brute_force(pb):
    """Exact optimum over every combination of visit sets (None if no plan is feasible)."""
    opts = [all_masks(pb, s) for s in range(1, pb.n + 1)]
    cache = {}
    best = None
    for combo in itertools.product(*opts):
        q = [sum(c[1][t] for c in combo) for t in range(pb.H)]
        if any(qt > pb.C for qt in q):
            continue
        B = [pb.B0]
        for t in range(pb.H):
            if q[t] > B[-1]:
                break
            B.append(B[-1] + pb.r0 - q[t])
        if len(B) != pb.H + 1:
            continue
        cost = pb.h0 * sum(B) + sum(pb.h[s] * sum(combo[s - 1][2]) for s in range(1, pb.n + 1))
        for t in range(pb.H):
            cost += tsp(pb.D, [s for s in range(1, pb.n + 1) if combo[s - 1][0] >> t & 1], cache)
        if best is None or cost < best:
            best = cost
    return best


def random_plan(pb, rng):
    pat = [0] + [rng.randrange(len(pb.pats[s])) for s in range(1, pb.n + 1)]
    tours = []
    for t in range(pb.H):
        m = [s for s in range(1, pb.n + 1) if pb.pats[s][pat[s]].mask >> t & 1]
        rng.shuffle(m)
        tours.append(m)
    return pat, tours


class TestModel(unittest.TestCase):
    def test_patterns_are_exactly_the_useful_stockout_free_visit_sets(self):
        for seed in range(12):
            pb = S.Problem(make_instance(5, 2 + seed % 5, 10 + seed, low_start=(seed % 2 == 0)))
            for s in range(1, pb.n + 1):
                want = {}
                for mask, xs, invs in all_masks(pb, s):
                    if all(xs[t] > 0 for t in range(pb.H) if mask >> t & 1):
                        want[mask] = (tuple(xs), tuple(invs))
                got = dict((p.mask, (p.x, p.inv)) for p in pb.pats[s])
                self.assertEqual(got, want, (seed, s))
                for p in pb.pats[s]:
                    hc = pb.h[s] * sum(p.inv) - pb.h0 * sum(p.x[k] * (pb.H - k) for k in range(pb.H))
                    self.assertAlmostEqual(p.hc, hc, places=9)

    def test_cost_decomposition_matches_the_checker_objective(self):
        rng = random.Random(4)
        for seed in range(10):
            pb = S.Problem(make_instance(7, 2 + seed % 5, 30 + seed, cap=50, sup=50, metric="euclid",
                                         high=(seed % 2 == 1)))
            plan = random_plan(pb, rng)
            sol = S.build_solution(pb, *plan)
            ok, why, obj = S.verify(pb, sol)
            self.assertTrue(ok, why)
            self.assertAlmostEqual(obj, S.plan_cost(pb, plan), places=6)
            self.assertAlmostEqual(obj, sol["objective_value"], places=6)


class TestOptimum(unittest.TestCase):
    def test_search_matches_brute_force(self):
        cases = [(3, 3, 1, 1.5, 1.0, False, False), (4, 3, 2, 1.2, 1.0, False, True), (4, 2, 3, 1.5, 0.6, True, False),
                 (3, 3, 4, 1.0, 1.0, False, True), (4, 3, 5, 1.5, 1.0, True, True), (4, 3, 6, 0.9, 2.0, False, False),
                 (3, 4, 7, 1.3, 1.0, True, True)]
        feasible = 0
        for n, H, seed, cap, sup, high, low in cases:
            pb = S.Problem(make_instance(n, H, seed, cap=cap, sup=sup, high=high, low_start=low))
            opt = brute_force(pb)
            best = S.Search(pb, seed, time.time() + 1.5).run()
            if opt is None:
                self.assertIsNone(best, (n, H, seed))
                continue
            feasible += 1
            self.assertIsNotNone(best, (n, H, seed))
            sol = S.build_solution(pb, *best)
            ok, why, obj = S.verify(pb, sol)
            self.assertTrue(ok, why)
            self.assertLessEqual(abs(obj - opt), 1e-6 * max(1.0, abs(opt)), (n, H, seed, obj, opt))
        self.assertGreaterEqual(feasible, 4)

    def test_tight_capacity_is_repaired(self):
        found = 0
        for seed in range(6):
            pb = S.Problem(make_instance(12, 6, 60 + seed, cap=1.25, sup=1.0, metric="euclid", low_start=True))
            best = S.Search(pb, seed, time.time() + 1.0).run()
            if best is None:
                continue
            found += 1
            ok, why, _ = S.verify(pb, S.build_solution(pb, *best))
            self.assertTrue(ok, why)
        self.assertGreaterEqual(found, 3)


def base_solution(seed=8):
    inst = make_instance(10, 3, seed, cap=3.0, sup=3.0, metric="euclid")
    pb = S.Problem(inst)
    best = S.Search(pb, 1, time.time() + 0.8).run()
    return inst, pb, S.build_solution(pb, *best)


def recost(pb, b):
    """Set objective_value to the checker's formula for b's own numbers, so only the edit itself can be wrong."""
    H = pb.H
    obj = pb.h0 * sum(float(b["supplier_inventory"][str(t)]) for t in range(1, H + 2))
    obj += sum(pb.h[s] * float(b["retailer_inventory"][str(s)][str(t)]) for s in range(1, pb.n + 1)
               for t in range(1, H + 2))
    for edges in b["routes"].values():
        obj += sum(pb.dist[max(e[0], e[1])][min(e[0], e[1])] * e[2] for e in edges)
    b["objective_value"] = float(obj)
    return b


def mutations(inst, pb, sol):
    """(name, instance, solution) cases; every one but 'valid' and 'objective_within_tolerance' must be rejected."""
    out = [("valid", inst, sol)]
    b = copy.deepcopy(sol)
    b["objective_value"] *= 1.0004
    out.append(("objective_within_tolerance", inst, b))
    for k in ("deliveries", "objective_value", "retailer_inventory", "routes", "supplier_inventory"):
        b = copy.deepcopy(sol)
        del b[k]
        out.append(("missing_" + k, inst, b))
    b = copy.deepcopy(sol)
    b["objective_value"] *= 1.01
    out.append(("objective_off_1pct", inst, b))
    b = copy.deepcopy(sol)
    b["objective_value"] = True
    out.append(("objective_bool", inst, b))
    busiest = max(sol["routes"], key=lambda t: len(sol["routes"][t]))
    b = copy.deepcopy(sol)
    s0 = next(iter(b["deliveries"][busiest]))
    b["deliveries"][busiest][s0] -= 1
    out.append(("delivery_minus_one", inst, b))
    b = copy.deepcopy(sol)
    del b["routes"][busiest]
    out.append(("route_dropped", inst, b))
    b = copy.deepcopy(sol)
    b["retailer_inventory"]["1"][str(pb.H + 1)] -= 1
    out.append(("inventory_edited", inst, b))
    members = sorted(int(s) for s in sol["deliveries"][busiest])
    if len(members) >= 4:
        a, rest = members[0], members[1:]
        b = copy.deepcopy(sol)
        edges = [[0, a, 2]] + [[min(u, v), max(u, v), 1] for u, v in zip(rest, rest[1:] + rest[:1])]
        b["routes"][busiest] = edges
        out.append(("subtour", inst, recost(pb, b)))
    if len(members) >= 2:
        b = copy.deepcopy(sol)
        b["routes"][busiest] = [[0, s, 2] for s in members]
        out.append(("two_depot_cycles", inst, recost(pb, b)))
        b = copy.deepcopy(sol)
        u, v = members[0], members[1]
        b["routes"][busiest] = [[0, u, 1], [0, v, 1], [u, v, 2]] if len(members) == 2 else \
            [[u, v, 2]] + [[0, s, 2] for s in members[2:]]
        out.append(("retailer_segment_twice", inst, recost(pb, b)))
    loads = [sum(sol["deliveries"][str(t + 1)].values()) for t in range(pb.H)]
    tight = copy.deepcopy(inst)
    tight["vehicle_capacity"] = max(loads) - 1
    out.append(("capacity_exceeded", tight, sol))
    return out


class TestVerify(unittest.TestCase):
    def test_accepts_and_rejects(self):
        inst, pb, sol = base_solution()
        for name, ins, cand in mutations(inst, pb, sol):
            ok, why, _ = S.verify(S.Problem(ins), cand)
            if name in ("valid", "objective_within_tolerance"):
                self.assertTrue(ok, (name, why))
            else:
                self.assertFalse(ok, name)

    def test_single_retailer_round_trip_uses_two(self):
        inst, pb, sol = base_solution()
        one = [t for t, e in sol["routes"].items() if len(e) == 1]
        for t in one:
            self.assertEqual(sol["routes"][t][0][0], 0)
            self.assertEqual(sol["routes"][t][0][2], 2)


@unittest.skipUnless(os.path.exists(os.environ.get("ARCH_OFFICIAL", "")), "official checker not available")
class TestAgainstOfficialChecker(unittest.TestCase):
    def test_agreement(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("official_archetti", os.environ["ARCH_OFFICIAL"])
        off = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(off)
        agree = 0
        for seed in range(4):
            inst, pb, sol = base_solution(20 + seed)
            for name, ins, cand in mutations(inst, pb, sol):
                c = off._frontieror_validate_solution_contract(cand)
                if c is None:
                    try:
                        c = off.check_feasibility(ins, cand)
                    except Exception as e:  # noqa: BLE001 - the official CLI turns a crash into a rejection
                        c = {"feasible": False, "violations": [repr(e)]}
                ok = S.verify(S.Problem(ins), cand)[0]
                self.assertEqual(bool(c["feasible"]), ok, (seed, name, str(c.get("violations"))[:300]))
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
        env["MV2_IRP_LOG"] = "1"
        t0 = time.time()
        p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "archetti2007",
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
        inst = make_instance(20, 6, 500, cap=2.0, sup=2.0, metric="euclid")
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 6, {})
        self.assertLess(wall, 6.0)
        ok, why, obj = S.verify(pb, sol)
        self.assertTrue(ok, why)
        self.assertAlmostEqual(obj, log["best"], places=6)
        self.assertGreater(log["parent"]["iterations"], 100)
        if hasattr(os, "fork"):
            self.assertIn("child", log)

    def test_one_worker(self):
        inst = make_instance(30, 6, 501, cap=2.0, sup=2.0, metric="euclid", high=True)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 5, {"MV2_IRP_WORKERS": "1"})
        self.assertLess(wall, 5.0)
        self.assertTrue(S.verify(pb, sol)[0])
        self.assertNotIn("child", log)

    def test_fifty_retailers_tiny_budget_still_answers(self):
        inst = make_instance(50, 6, 502, cap=1.5, sup=1.0, metric="euclid", low_start=True)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 5, {})
        self.assertLess(wall, 5.0)
        self.assertTrue(S.verify(pb, sol)[0])


if __name__ == "__main__":
    unittest.main()

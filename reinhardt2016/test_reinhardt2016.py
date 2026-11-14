"""Tests for MV2's reinhardt2016 (ESVRPTW) engine. Standard library only.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python -m unittest -v test_reinhardt2016
With MV2_FROC_HF=<Hugging Face frontieror/FrontierOR copy>, TestContestWay also runs the official checker.
"""
import copy
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import solve as S  # noqa: E402


def make_inst(n, seed, n_sets=3, p_set=0.5, H=400, Q=25, first_id=0, K=None):
    rng = random.Random(seed)
    pts = [(rng.randint(0, 60), rng.randint(0, 60)) for _ in range(n + 1)]
    dm = [[round(math.hypot(a[0] - b[0], a[1] - b[1]), 1) for b in pts] for a in pts]
    nodes = [{"id": 0, "x": pts[0][0], "y": pts[0][1], "demand": 0, "time_window_start": 0,
              "time_window_end": H, "service_time": 0}]
    for i in range(1, n + 1):
        s = rng.randint(0, 10)
        lo, hi = int(math.ceil(dm[0][i])), int(math.floor(H - s - dm[0][i]))
        a = rng.randint(lo, hi)
        nodes.append({"id": i, "x": pts[i][0], "y": pts[i][1], "demand": rng.randint(1, 10),
                      "time_window_start": max(0, a - rng.randint(0, 60)),
                      "time_window_end": min(hi, a + rng.randint(0, 60)), "service_time": s})
    sets = [{"id": first_id + k, "access_cost": float(rng.randint(5, 40)), "edges": []} for k in range(n_sets)]
    free = []
    for i in range(n + 1):
        for j in range(i + 1, n + 1):
            if n_sets and rng.random() < p_set:
                sets[rng.randrange(n_sets)]["edges"].append([i, j])
            else:
                free.append([i, j])
    return {"num_customers": n, "num_vehicles": n if K is None else K, "vehicle_capacity": Q,
            "num_edge_sets": n_sets, "schedule_horizon": H, "nodes": nodes, "edge_sets": sets,
            "free_edges": free, "distance_matrix": dm}


# ---- independent re-implementations (raw instance dict, no solve.py code) --------------------------------------------
def simulate(inst, r):
    nodes = {x["id"]: x for x in inst["nodes"]}
    d = inst["distance_matrix"]
    if sum(nodes[c]["demand"] for c in r) > inst["vehicle_capacity"]:
        return False
    t, prev = nodes[0]["time_window_start"], 0
    for c in r:
        t = max(t + d[prev][c] + nodes[prev]["service_time"], nodes[c]["time_window_start"])
        if t > nodes[c]["time_window_end"] + 1e-9:
            return False
        prev = c
    return t + d[prev][0] + nodes[prev]["service_time"] <= inst["schedule_horizon"] + 1e-9


def arc_sets(inst):
    m = {}
    for es in inst["edge_sets"]:
        for a, b in es["edges"]:
            m[(a, b)] = es["id"]
            m[(b, a)] = es["id"]
    return m


def cost(inst, routes, zero=()):
    d = inst["distance_matrix"]
    m = arc_sets(inst)
    c = {es["id"]: es["access_cost"] for es in inst["edge_sets"]}
    used = set()
    t = 0.0
    for r in routes:
        seq = [0] + list(r) + [0]
        for a, b in zip(seq, seq[1:]):
            t += d[a][b]
            if (a, b) in m:
                used.add(m[(a, b)])
    return t + sum(0.0 if u in zero else c[u] for u in used), used


def all_arrangements(nodes):
    out = []

    def rec(k, routes):
        if k == len(nodes):
            out.append([list(r) for r in routes])
            return
        v = nodes[k]
        for ri in range(len(routes)):
            r = routes[ri]
            for pos in range(len(r) + 1):
                r.insert(pos, v)
                rec(k + 1, routes)
                del r[pos]
        routes.append([v])
        rec(k + 1, routes)
        routes.pop()

    rec(0, [])
    return out


def brute_optimum(inst):
    best = math.inf
    for routes in all_arrangements(list(range(1, inst["num_customers"] + 1))):
        if len(routes) <= inst["num_vehicles"] and all(simulate(inst, r) for r in routes):
            best = min(best, cost(inst, routes)[0])
    return best


def random_feasible_routes(inst, rng):
    cust = list(range(1, inst["num_customers"] + 1))
    rng.shuffle(cust)
    routes = []
    for c in cust:
        opts = []
        for ri, r in enumerate(routes):
            for pos in range(len(r) + 1):
                if simulate(inst, r[:pos] + [c] + r[pos:]):
                    opts.append((ri, pos))
        if opts and rng.random() < 0.85:
            ri, pos = rng.choice(opts)
            routes[ri].insert(pos, c)
        else:
            routes.append([c])
    return routes


class TestInsertion(unittest.TestCase):
    def check_one(self, inst, seed, banned_id=None, free_id=None):
        rng = random.Random(seed)
        P = S.Problem(inst)
        routes = random_feasible_routes(inst, rng)
        u = rng.choice([c for r in routes for c in r])
        rest = [[c for c in r if c != u] for r in routes]
        rest = [r for r in rest if r]
        if not all(simulate(inst, r) for r in rest):
            return 0  # rounded distances can break the triangle inequality; not this test's subject
        P.K = len(rest)  # no new route: only positions in existing routes
        st = S.State(P, rest)
        idx = {P.set_ids[x]: x for x in range(P.R)}
        banned = {idx[banned_id]} if banned_id is not None else None
        free = {idx[free_id]} if free_id is not None else None
        options = []
        for ri, r in enumerate(rest):
            for pos in range(len(r) + 1):
                cand = [list(x) for x in rest]
                cand[ri] = r[:pos] + [u] + r[pos:]
                if simulate(inst, cand[ri]):
                    c, used = cost(inst, cand, zero=(free_id,) if free_id is not None else ())
                    ms = arc_sets(inst)
                    seq = [0] + cand[ri] + [0]
                    k = seq.index(u)
                    makes_banned = banned_id is not None and banned_id in (ms.get((seq[k - 1], u)),
                                                                           ms.get((u, seq[k + 1])))
                    options.append((c, makes_banned))
        ok = S.recreate(P, st, [u], random.Random(0), blink=0.0, banned=banned, free=free)
        self.assertEqual(ok, bool(options), "feasibility of inserting %s" % u)
        if not ok:
            return 0
        allowed = [c for c, mb in options if not mb] or [c for c, _ in options]
        got, _ = cost(inst, st.routes, zero=(free_id,) if free_id is not None else ())
        self.assertAlmostEqual(got, min(allowed), places=6)
        self.assertTrue(all(simulate(inst, r) for r in st.routes))
        cnt = list(st.cnt)
        st.recount(P)
        self.assertEqual(cnt, st.cnt)
        self.assertAlmostEqual(st.total(P), cost(inst, st.routes)[0], places=6)
        return 1

    def test_cheapest_feasible_insertion_matches_brute_force(self):
        done = 0
        for t in range(150):
            inst = make_inst(7, 300 + t, n_sets=3, p_set=0.6, Q=random.Random(t).randint(15, 40))
            done += self.check_one(inst, t)
        self.assertGreater(done, 60)

    def test_banned_and_free_sets(self):
        for t in range(120):
            inst = make_inst(7, 900 + t, n_sets=3, p_set=0.7, first_id=5)
            ids = [es["id"] for es in inst["edge_sets"]]
            self.check_one(inst, t, banned_id=ids[t % 3])
            self.check_one(inst, t + 1000, free_id=ids[(t + 1) % 3])

    def test_latest_start_rule(self):
        rng = random.Random(4)
        for t in range(100):
            inst = make_inst(6, 50 + t)
            P = S.Problem(inst)
            r = [c for c in random_feasible_routes(inst, rng)[0]]
            E, L = P.forward(r), P.latest(r)
            self.assertIsNotNone(E)
            for k in range(len(r)):
                self.assertLessEqual(E[k], L[k] + 1e-9)


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.inst = make_inst(8, 7, n_sets=2, p_set=1.0, H=600, Q=60)
        self.P = S.Problem(self.inst)
        self.routes = random_feasible_routes(self.inst, random.Random(2))
        self.sol = S.build_solution(self.P, self.routes)

    def test_accepts_built_solution(self):
        r = S.verify(self.inst, self.sol)
        self.assertTrue(r["feasible"], r)
        self.assertAlmostEqual(r["objective"], self.sol["objective_value"], places=9)
        self.assertAlmostEqual(self.sol["objective_value"], cost(self.inst, self.routes)[0], places=6)
        self.assertTrue(self.sol["edge_sets_used"])

    def test_rejections(self):
        sol = self.sol
        unpaid = dict(sol, edge_sets_used=sol["edge_sets_used"][1:])
        self.assertFalse(S.verify(self.inst, unpaid)["feasible"])
        self.assertFalse(S.verify(self.inst, dict(sol, objective_value=sol["objective_value"] + 2.0))["feasible"])
        self.assertTrue(S.verify(self.inst, dict(sol, objective_value=sol["objective_value"] + 0.5))["feasible"])
        self.assertFalse(S.verify(self.inst, dict(sol, objective_value=None))["feasible"])
        self.assertFalse(S.verify(self.inst, dict(sol, status="infeasible"))["feasible"])
        drop = copy.deepcopy(sol)
        drop["routes"][0]["sequence"] = [0, 0]
        self.assertFalse(S.verify(self.inst, drop)["feasible"])
        dup = copy.deepcopy(sol)
        dup["routes"][0]["sequence"] = dup["routes"][0]["sequence"][:-1] + [dup["routes"][-1]["sequence"][1], 0]
        self.assertFalse(S.verify(self.inst, dup)["feasible"])
        neg = copy.deepcopy(sol)
        neg["routes"][0]["visit_times"]["0"] = -5
        self.assertFalse(S.verify(self.inst, neg)["feasible"])
        tight = copy.deepcopy(self.inst)
        c = sol["routes"][0]["sequence"][1]
        tight["nodes"][c]["time_window_start"] = 0
        tight["nodes"][c]["time_window_end"] = -1
        self.assertFalse(S.verify(tight, sol)["feasible"])
        small = dict(self.inst, vehicle_capacity=1)
        self.assertFalse(S.verify(small, sol)["feasible"])
        fleet = dict(self.inst, num_vehicles=len(sol["routes"]) - 1)
        if len(sol["routes"]) > 1:
            self.assertFalse(S.verify(fleet, sol)["feasible"])


class TestSearch(unittest.TestCase):
    def test_finds_brute_force_optimum_tiny(self):
        for seed in range(6):
            inst = make_inst(5, 40 + seed, n_sets=2 + seed % 2, p_set=0.6, Q=random.Random(seed).randint(12, 30),
                             first_id=seed)
            opt = brute_optimum(inst)
            sol = S.solve(inst, seed=seed, budget=1.5)
            chk = S.verify(inst, sol)
            self.assertTrue(chk["feasible"], chk)
            self.assertAlmostEqual(sol["objective_value"], opt, places=6, msg="seed %d" % seed)

    def test_fleet_limit(self):
        inst = make_inst(5, 77, n_sets=2, Q=15, K=3, H=800)
        opt = brute_optimum(inst)
        sol = S.solve(inst, seed=1, budget=1.0)
        if math.isinf(opt):
            self.assertIsNone(sol)
        else:
            self.assertLessEqual(len(sol["routes"]), 3)
            self.assertAlmostEqual(sol["objective_value"], opt, places=6)

    def test_no_edge_sets(self):
        inst = make_inst(5, 12, n_sets=0)
        sol = S.solve(inst, seed=3, budget=1.0)
        self.assertTrue(S.verify(inst, sol)["feasible"])
        self.assertEqual(sol["edge_sets_used"], [])
        self.assertAlmostEqual(sol["objective_value"], brute_optimum(inst), places=6)

    def test_medium_feasible_and_improves(self):
        inst = make_inst(40, 5, n_sets=6, p_set=0.5, Q=60, H=500)
        P = S.Problem(inst)
        st = S.State(P)
        start = S.recreate_fixed(P, st, list(P.cust), None, None)
        log = {}
        sol = S.solve(inst, seed=1, budget=3.0, log=log)
        self.assertTrue(S.verify(inst, sol)["feasible"])
        if start:
            self.assertLessEqual(sol["objective_value"], st.total(P) + 1e-6)
        self.assertGreater(log["iterations"], 10)

    def test_main_contest_way(self):
        inst = make_inst(25, 21, n_sets=4, Q=50)
        with tempfile.TemporaryDirectory() as d:
            ip, op = os.path.join(d, "i.json"), os.path.join(d, "o.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "reinhardt2016",
                                "--instance", ip, "--output", op, "--time-limit", "5"], capture_output=True,
                               text=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stderr[-800:])
            with open(op, encoding="utf-8") as f:
                sol = json.load(f)
            self.assertTrue(S.verify(inst, sol)["feasible"])


HF = os.environ.get("MV2_FROC_HF")


@unittest.skipUnless(HF and os.path.isdir(os.path.join(HF or "", "tasks", "reinhardt2016")), "needs MV2_FROC_HF")
class TestContestWay(unittest.TestCase):
    def setUp(self):
        tdir = os.path.join(HF, "tasks", "reinhardt2016")
        spec = importlib.util.spec_from_file_location("esv_official", os.path.join(tdir, "feasibility_check.py"))
        self.off = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.off)
        with open(os.path.join(tdir, "instance", "tiny_instance.json"), encoding="utf-8") as f:
            self.tiny = json.load(f)
        self.gp = os.path.join(tdir, "gurobi_solution", "tiny_solution.json")

    def official(self, inst, sol):
        if self.off._frontieror_validate_solution_contract(sol) is not None:
            return False
        try:
            return bool(self.off.check_feasibility(inst, sol)["feasible"])
        except Exception:  # noqa: BLE001 - the official program turns exceptions into a rejection
            return False

    def test_gurobi_tiny_both_checkers(self):
        with open(self.gp, encoding="utf-8") as f:
            g = json.load(f)
        self.assertEqual(self.official(self.tiny, g), S.verify(self.tiny, g)["feasible"])

    def test_tiny_official_and_mirror_agree_on_mutations(self):
        sol = S.solve(self.tiny, seed=1, budget=2.0)
        self.assertTrue(self.official(self.tiny, sol))
        self.assertTrue(S.verify(self.tiny, sol)["feasible"])
        costs = {es["id"]: es["access_cost"] for es in self.tiny["edge_sets"]}
        d = self.tiny["distance_matrix"]
        rng = random.Random(3)
        agree = 0
        for t in range(100):
            cand = copy.deepcopy(sol)
            routes = cand["routes"]
            kind = t % 5
            ri = rng.randrange(len(routes))
            seq = routes[ri]["sequence"]
            if kind == 0 and len(seq) > 3:
                a, b = rng.sample(range(1, len(seq) - 1), 2)
                seq[a], seq[b] = seq[b], seq[a]
            elif kind == 1 and len(seq) > 3:
                v = seq.pop(rng.randrange(1, len(seq) - 1))
                other = routes[rng.randrange(len(routes))]["sequence"]
                other.insert(rng.randrange(1, len(other)), v)
            elif kind == 2 and len(routes) > 1:
                o = routes.pop((ri + 1) % len(routes))
                routes[ri if ri < len(routes) else 0]["sequence"][-1:] = o["sequence"][1:]
            elif kind == 3 and len(seq) > 3:
                seq.pop(rng.randrange(1, len(seq) - 1))
            elif kind == 4 and cand["edge_sets_used"]:
                cand["edge_sets_used"].pop(rng.randrange(len(cand["edge_sets_used"])))
            for r in routes:
                r["arcs"] = [[a, b] for a, b in zip(r["sequence"], r["sequence"][1:])]
            cand["objective_value"] = float(sum(d[a][b] for r in routes for a, b in zip(r["sequence"],
                                                                                         r["sequence"][1:])) +
                                            sum(costs[x] for x in set(cand["edge_sets_used"])))
            agree += self.official(self.tiny, cand) == S.verify(self.tiny, cand)["feasible"]
        self.assertEqual(agree, 100)


if __name__ == "__main__":
    unittest.main()

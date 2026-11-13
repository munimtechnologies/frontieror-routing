"""Tests for solve.py (FrontierOR bode2012, capacitated arc routing). Standard library only.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Run from this folder: python -m unittest -v test_bode2012
With CARP_OFFICIAL=<path to the task's feasibility_check.py>, verify() is also compared with the official checker.
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


def make_instance(N, extra, R, K, seed, slack=0.1, loops=0, parallel=0, depot=0):
    """A connected instance in the task's JSON layout. The capacity comes from a random partition of the required
    edges into K groups, so a feasible answer with K vehicles always exists (slack 0 = as tight as that partition)."""
    rng = random.Random(seed)
    pairs = []
    for i in range(1, N):
        pairs.append((rng.randrange(i), i))
    tries = 0
    while len(pairs) < N - 1 + extra and tries < 10000:
        tries += 1
        u, v = rng.randrange(N), rng.randrange(N)
        if u != v and (u, v) not in pairs and (v, u) not in pairs:
            pairs.append((u, v))
    for _ in range(parallel):
        u, v = rng.choice(pairs[:N - 1 + extra])
        pairs.append((u, v))
    for _ in range(loops):
        x = rng.randrange(N)
        pairs.append((x, x))
    rng.shuffle(pairs)
    E = len(pairs)
    R = min(R, E)
    req = set(rng.sample(range(E), R))
    loop_ids = [k for k, (u, v) in enumerate(pairs) if u == v]
    for k in loop_ids[:1]:  # make sure a loop is required when there is one
        if k not in req and req:
            req.discard(next(iter(req)))
            req.add(k)
    edges = []
    for k, (u, v) in enumerate(pairs):
        c = rng.randint(1, 20)
        r = k in req
        edges.append({"edge_id": k, "endpoints": [u, v], "cost": c, "is_required": r,
                      "demand": rng.randint(1, 10) if r else 0, "service_cost": (c + rng.randint(0, 3)) if r else 0})
    rids = sorted(req)
    rng.shuffle(rids)
    groups = [rids[k::K] for k in range(K)]
    dem = {e["edge_id"]: e["demand"] for e in edges}
    Q = int(math.ceil(max([sum(dem[i] for i in g) for g in groups] + [1]) * (1.0 + slack)))
    return {"graph": {"num_nodes": N, "num_edges": E, "type": "undirected"}, "depot": depot,
            "fleet": {"num_vehicles": K, "vehicle_capacity": Q, "type": "homogeneous"},
            "num_required_edges": len(req), "total_demand": sum(dem.values()), "edges": edges}


def floyd(pb):
    N = pb.N
    D = [[S.BIG] * N for _ in range(N)]
    for i in range(N):
        D[i][i] = 0
    for eid, (u, v, c, _r, _q, _s) in pb.edges.items():
        if u != v:
            D[u][v] = min(D[u][v], c)
            D[v][u] = min(D[v][u], c)
    for k in range(N):
        for i in range(N):
            for j in range(N):
                if D[i][k] + D[k][j] < D[i][j]:
                    D[i][j] = D[i][k] + D[k][j]
    return D


def brute_force(pb):
    """Exact optimum of the arc-sequence model: every assignment of tasks to K labelled routes, best order and
    directions for each route."""
    memo = {}

    def best_route(group):
        key = tuple(sorted(group))
        if key in memo:
            return memo[key]
        if not key:
            memo[key] = 0
            return 0
        b = math.inf
        for perm in itertools.permutations(key):
            for dirs in itertools.product((0, 1), repeat=len(perm)):
                b = min(b, pb.route_cost([2 * t + d for t, d in zip(perm, dirs)]))
        memo[key] = b
        return b
    best = math.inf
    for lab in itertools.product(range(pb.K), repeat=pb.R):
        groups = [[] for _ in range(pb.K)]
        for t, r in enumerate(lab):
            groups[r].append(t)
        if any(sum(pb.dem[t] for t in g) > pb.Q for g in groups):
            continue
        best = min(best, sum(best_route(g) for g in groups))
    return pb.service_total + best


class TestShortestPaths(unittest.TestCase):
    def test_dijkstra_matches_floyd_and_paths_are_walks(self):
        for seed in range(8):
            inst = make_instance(14, 8, 10, 2, 10 + seed, loops=seed % 2, parallel=seed % 3)
            pb = S.Problem(inst)
            F = floyd(pb)
            for a in range(pb.N):
                for b in range(pb.N):
                    self.assertEqual(pb.D[a][b], F[a][b], (seed, a, b))
                    p = pb.path(a, b)
                    self.assertIsNotNone(p)
                    x = a
                    tot = 0
                    for eid in p:
                        u, v, c = pb.edges[eid][0], pb.edges[eid][1], pb.edges[eid][2]
                        self.assertIn(x, (u, v))
                        x = v if x == u else u
                        tot += c
                    self.assertEqual(x, b)
                    self.assertEqual(tot, pb.D[a][b])


class TestState(unittest.TestCase):
    def check(self, s):
        fresh = S.Sol(s.pb, s.routes)
        for f in ("rcost", "ld", "exc"):
            self.assertEqual(getattr(fresh, f), getattr(s, f), f)
        tasks = sorted(a >> 1 for r in s.routes for a in r)
        self.assertEqual(tasks, list(range(s.pb.R)))
        for t in range(s.pb.R):
            self.assertTrue(any((a >> 1) == t for a in s.routes[s.where[t]]))
        self.assertEqual(len(s.routes), s.pb.K)

    def test_ruin_recreate_keeps_caches_exact(self):
        rng = random.Random(9)
        for t in range(6):
            pb = S.Problem(make_instance(30, 20, 35, 4, 200 + t, loops=t % 2, parallel=t % 2))
            s = S.initial(pb, rng, "demand")
            self.check(s)
            for _ in range(200):
                rem = S.ruin(s, rng, 10.0, 10.0)
                self.assertTrue(rem)
                self.assertEqual(len(rem), len(set(rem)))
                S.insert_all(s, S.sort_removed(pb, rem, rng), rng)
                self.check(s)

    def test_insertion_delta_is_exact(self):
        rng = random.Random(4)
        pb = S.Problem(make_instance(20, 10, 20, 3, 77))
        s = S.initial(pb, rng, "random")
        for _ in range(50):
            rem = S.ruin(s, rng, 10.0, 10.0)
            before = s.penalised()
            t = rem[0]
            S.insert_all(s, [t], rng, blink=0.0)
            after = s.penalised()
            # the chosen insertion is the cheapest over every route, position and direction
            best = math.inf
            r0 = s.where[t]
            for r in range(pb.K):
                seq = [a for a in s.routes[r] if (a >> 1) != t]
                for p in range(len(seq) + 1):
                    for arc in (2 * t, 2 * t + 1):
                        trial = seq[:p] + [arc] + seq[p:]
                        old = pb.route_cost(seq) + pb.LAM * max(0, pb.load(seq) - pb.Q)
                        new = pb.route_cost(trial) + pb.LAM * max(0, pb.load(trial) - pb.Q)
                        best = min(best, new - old)
            self.assertAlmostEqual(after - before, best, places=6)
            self.assertGreaterEqual(r0, 0)
            S.insert_all(s, rem[1:], rng)

    def test_polish_never_worsens(self):
        rng = random.Random(11)
        for t in range(4):
            pb = S.Problem(make_instance(25, 15, 30, 3, 300 + t))
            s = S.initial(pb, rng, "random")
            d0 = s.deadhead()
            S.polish(s)
            self.assertLessEqual(s.deadhead(), d0)
            self.check(s)


class TestBuildAndVerify(unittest.TestCase):
    def setUp(self):
        self.inst = make_instance(20, 12, 22, 3, 7, loops=1, parallel=1)
        self.pb = S.Problem(self.inst)
        s = S.Search(self.pb, 1, time.time() + 0.8).run()
        self.assertTrue(s.feasible())
        self.s = s
        self.sol = S.build_solution(self.pb, s)

    def test_accepts_valid(self):
        ok, why, obj = S.verify(self.pb, self.sol)
        self.assertTrue(ok, why)
        self.assertAlmostEqual(obj, self.sol["objective_value"], places=6)
        self.assertAlmostEqual(obj, self.s.distance(), places=6)
        self.assertEqual(len(self.sol["routes"]), self.pb.K)
        for rt in self.sol["routes"]:
            self.assertLessEqual(rt["total_demand"], self.pb.Q)

    def test_rejections(self):
        pb, sol = self.pb, self.sol
        busy = [k for k, rt in enumerate(sol["routes"]) if rt["serviced_edges"]]
        self.assertTrue(busy)
        k0 = busy[0]
        bad = []
        b = json.loads(json.dumps(sol))
        del b["routes"]
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["objective_value"] += 5 + 0.01 * b["objective_value"]
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["objective_value"] = True
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["routes"][k0]["serviced_edges"] = b["routes"][k0]["serviced_edges"][1:]
        bad.append(b)  # a required edge not serviced
        b = json.loads(json.dumps(sol))
        b["routes"][k0]["serviced_edges"].append(b["routes"][k0]["serviced_edges"][0])
        bad.append(b)  # serviced twice
        nonreq = [eid for eid, e in pb.edges.items() if not e[3]]
        if nonreq:
            b = json.loads(json.dumps(sol))
            b["routes"][k0]["serviced_edges"].append(nonreq[0])
            bad.append(b)
        b = json.loads(json.dumps(sol))
        b["routes"][k0]["serviced_edges"].append(10 ** 6)
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["routes"][k0]["deadheaded_edges"].append({"edge_id": b["routes"][k0]["serviced_edges"][0], "times": 1})
        u, v = pb.edges[b["routes"][k0]["serviced_edges"][0]][:2]
        if u != v:
            b["objective_value"] += pb.edges[b["routes"][k0]["serviced_edges"][0]][2]
            bad.append(b)  # parity broken (objective made consistent)
        b = json.loads(json.dumps(sol))
        b["routes"][k0]["deadheaded_edges"].append({"edge_id": 0, "times": -2})
        bad.append(b)
        b = json.loads(json.dumps(sol))
        b["status_str"] = "NO_SOLUTION_FOUND"
        bad.append(b)
        # everything on one vehicle with the same walks: over capacity (objective unchanged = consistent)
        b = json.loads(json.dumps(sol))
        if pb.load(list(range(0, 2 * pb.R, 2))) > pb.Q:
            allr = {"vehicle": 0, "serviced_edges": [e for rt in b["routes"] for e in rt["serviced_edges"]],
                    "deadheaded_edges": [d for rt in b["routes"] for d in rt["deadheaded_edges"]]}
            b["routes"] = [allr]
            bad.append(b)
        for x in bad:
            self.assertFalse(S.verify(pb, x)[0], str(x)[:300])

    def test_fleet_rule(self):
        pb = self.pb
        b = json.loads(json.dumps(self.sol))
        # an extra EMPTY route is harmless: no more vehicles do any work
        b["routes"].append({"vehicle": pb.K, "serviced_edges": [], "deadheaded_edges": []})
        self.assertTrue(S.verify(pb, b)[0])
        busy = [rt for rt in self.sol["routes"] if rt["serviced_edges"]]
        if len(busy) >= 2:
            inst2 = json.loads(json.dumps(self.inst))
            inst2["fleet"]["num_vehicles"] = len(busy) - 1
            inst2["fleet"]["vehicle_capacity"] = 10 ** 6
            pb2 = S.Problem(inst2)
            self.assertFalse(S.verify(pb2, self.sol)[0])  # more working vehicles than the fleet has
            self.assertTrue(S.verify(pb2, self.sol, strict_fleet=False)[0])  # what the official checker sees

    def test_no_required_edges(self):
        inst = make_instance(6, 2, 0, 2, 3)
        for e in inst["edges"]:
            e["is_required"], e["demand"], e["service_cost"] = False, 0, 0
        pb = S.Problem(inst)
        best = S.Search(pb, 1, time.time() + 0.2).run()
        sol = S.build_solution(pb, best)
        ok, why, obj = S.verify(pb, sol)
        self.assertTrue(ok, why)
        self.assertEqual(obj, 0.0)


class TestOptimum(unittest.TestCase):
    def test_search_finds_brute_force_optimum(self):
        cases = [(8, 4, 5, 2, 1, 0.1), (7, 3, 5, 2, 2, 0.0), (9, 5, 6, 2, 3, 0.0), (6, 3, 4, 3, 4, 0.0),
                 (8, 6, 5, 1, 5, 0.5), (10, 3, 6, 3, 6, 0.0)]
        for N, extra, R, K, seed, slack in cases:
            inst = make_instance(N, extra, R, K, seed, slack=slack, loops=seed % 2, depot=seed % N)
            pb = S.Problem(inst)
            opt = brute_force(pb)
            best = S.Search(pb, seed, time.time() + 2.0).run()
            self.assertTrue(best.feasible(), (N, R, K, seed))
            self.assertAlmostEqual(best.distance(), opt, places=6, msg=(N, R, K, seed))
            sol = S.build_solution(pb, best)
            ok, why, obj = S.verify(pb, sol)
            self.assertTrue(ok, why)
            self.assertAlmostEqual(obj, opt, places=6)
            self.assertEqual(len(sol["routes"]), K)

    def test_tight_capacity_found(self):
        for seed in (21, 22, 23):
            pb = S.Problem(make_instance(30, 20, 40, 5, seed, slack=0.0))
            best = S.Search(pb, seed, time.time() + 2.0).run()
            self.assertTrue(best.feasible(), seed)
            self.assertTrue(S.verify(pb, S.build_solution(pb, best))[0])


@unittest.skipUnless(os.path.exists(os.environ.get("CARP_OFFICIAL", "")), "official checker not available")
class TestAgainstOfficialChecker(unittest.TestCase):
    """verify() (strict_fleet=False) and the official feasibility_check.py must agree on valid and broken answers."""

    def test_agreement(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("official_bode", os.environ["CARP_OFFICIAL"])
        off = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(off)
        agree = 0
        for seed in range(6):
            inst = make_instance(18, 10, 20, 3, 400 + seed, slack=0.05 * (seed % 3), loops=seed % 2,
                                 parallel=seed % 2, depot=seed % 5)
            pb = S.Problem(inst)
            best = S.Search(pb, seed, time.time() + 0.5).run()
            good = S.build_solution(pb, best)
            busy = [k for k, rt in enumerate(good["routes"]) if rt["serviced_edges"]]
            k0 = busy[0]
            cases = [good]
            b = json.loads(json.dumps(good))
            b["objective_value"] += 0.5 + 0.002 * abs(b["objective_value"])
            cases.append(b)
            b = json.loads(json.dumps(good))
            b["objective_value"] += 0.0004 * abs(b["objective_value"])
            cases.append(b)  # inside the 0.1% tolerance
            b = json.loads(json.dumps(good))
            b["routes"] = [rt for k, rt in enumerate(b["routes"]) if k != k0]
            cases.append(b)  # a vehicle's edges dropped
            b = json.loads(json.dumps(good))
            if len(busy) >= 2:
                moved = b["routes"][busy[1]]["serviced_edges"].pop()
                b["routes"][k0]["serviced_edges"].append(moved)
            cases.append(b)  # moved without its walk: parity/connectivity/capacity break (or not)
            b = json.loads(json.dumps(good))
            if b["routes"][k0]["deadheaded_edges"]:
                d = b["routes"][k0]["deadheaded_edges"][0]
                d["times"] += 2
                b["objective_value"] += 2 * pb.edges[d["edge_id"]][2]
            cases.append(b)  # an extra back-and-forth crossing: still valid
            b = json.loads(json.dumps(good))
            if b["routes"][k0]["deadheaded_edges"]:
                b["routes"][k0]["deadheaded_edges"].pop()
            cases.append(b)
            b = json.loads(json.dumps(good))
            allr = {"vehicle": 0, "serviced_edges": [e for rt in b["routes"] for e in rt["serviced_edges"]],
                    "deadheaded_edges": [d for rt in b["routes"] for d in rt["deadheaded_edges"]]}
            b["routes"] = [allr]
            cases.append(b)  # one vehicle, all walks merged: over capacity, or valid if it fits
            b = json.loads(json.dumps(good))
            b["routes"][k0]["deadheaded_edges"].append({"edge_id": 0, "times": 1.5})
            cases.append(b)
            for k, sol in enumerate(cases):
                c = off._frontieror_validate_solution_contract(sol)
                if c is None:
                    try:
                        c = off.check_feasibility(inst, sol)
                    except Exception as e:  # noqa: BLE001 - the official CLI turns a crash into a rejection
                        c = {"feasible": False, "violations": [repr(e)]}
                ok = S.verify(pb, sol, strict_fleet=False)[0]
                self.assertEqual(bool(c["feasible"]), ok, (seed, k, c.get("violations")))
                agree += 1
        self.assertGreaterEqual(agree, 50)


class TestCLI(unittest.TestCase):
    def run_cli(self, inst, T, env_extra):
        d = tempfile.mkdtemp()
        ip = os.path.join(d, "inst.json")
        op = os.path.join(d, "sol.json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump(inst, f)
        env = dict(os.environ)
        env.update(env_extra)
        env["MV2_CARP_LOG"] = "1"
        t0 = time.time()
        p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "bode2012",
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
        inst = make_instance(60, 40, 80, 6, 500, slack=0.05)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 6, {})
        self.assertLess(wall, 6.0)
        ok, why, obj = S.verify(pb, sol)
        self.assertTrue(ok, why)
        self.assertAlmostEqual(obj, log["best"], places=6)
        self.assertIn(log["best_source"], ("parent", "child"))
        self.assertGreater(log["parent"]["iterations"], 50)
        if hasattr(os, "fork"):
            self.assertIn("child", log)

    def test_one_worker(self):
        inst = make_instance(40, 25, 50, 4, 501, loops=2, parallel=2)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 5, {"MV2_CARP_WORKERS": "1"})
        self.assertLess(wall, 5.0)
        self.assertTrue(S.verify(pb, sol)[0])
        self.assertNotIn("child", log)

    def test_tiny_budget_still_answers(self):
        inst = make_instance(100, 60, 140, 10, 502, slack=0.1)
        pb = S.Problem(inst)
        sol, log, wall = self.run_cli(inst, 4, {})
        self.assertLess(wall, 4.0)
        self.assertTrue(S.verify(pb, sol)[0])


if __name__ == "__main__":
    unittest.main()

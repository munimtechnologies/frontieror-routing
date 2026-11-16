"""Tests for MV2's roberti2018 (2E-CVRPGC) solver. MV2 of Munim, Inc. Made with AI agents working in MV2's name.
License: Apache-2.0.

  python -m unittest -v test_roberti2018
If ROBERTI_OFFICIAL points to the benchmark's feasibility_check.py, solver outputs are also judged by it, and our
verify() is compared with it on mutated solutions. If MV2_FROC_HF points to a FrontierOR download, TestContestWay
runs solve.py the contest way on the public tiny instance under the official checker.
"""
import importlib.util
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
_spec = importlib.util.spec_from_file_location("mv2_roberti2018_solve", os.path.join(HERE, "solve.py"))
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)
INF = float("inf")


# ------------------------------------------------------------------------------------------------ instances
def make_instance(depot, sats, custs, groups, Q1, Q2, T1, T2):
    """depot (id, x, y); sats [(id, x, y, cap, maxv, h)]; custs [(id, x, y, demand, group)]; groups {gid: [ids]}."""
    return {
        "num_satellites": len(sats), "num_customers": len(custs), "num_groups": len(groups),
        "Q1": Q1, "Q2": Q2, "T1": T1, "T2": T2,
        "depot": {"id": depot[0], "x": depot[1], "y": depot[2]},
        "satellites": [{"id": i, "x": x, "y": y, "capacity": c, "max_vehicles": m, "handling_cost": h}
                       for (i, x, y, c, m, h) in sats],
        "customers": [{"id": i, "x": x, "y": y, "demand": d, "group": g} for (i, x, y, d, g) in custs],
        "groups": [{"group_id": g, "customer_ids": list(ids)} for g, ids in sorted(groups.items())],
    }


def random_instance(seed, ns=2, nc=5, ng=3, maxv=2, T2=None, odd_ids=False):
    rng = random.Random(seed)
    ids = list(range(1 + ns + nc))
    if odd_ids:
        ids = rng.sample(range(10, 500), 1 + ns + nc)
    depot = (ids[0], rng.randint(0, 100), rng.randint(0, 100))
    dems = [rng.randint(1, 10) for _ in range(nc)]
    total = sum(dems)
    sats = []
    for s in range(ns):
        cap = total if s == 0 else max(max(dems) * 3, int(total * 0.6))
        sats.append((ids[1 + s], rng.randint(20, 80), rng.randint(20, 80), cap, maxv, round(rng.uniform(0.2, 2.0), 2)))
    gof = [g for g in range(ng)] + [rng.randrange(ng) for _ in range(nc - ng)]
    rng.shuffle(gof)
    custs = []
    groups = {}
    for i in range(nc):
        cid = ids[1 + ns + i]
        custs.append((cid, rng.randint(0, 100), rng.randint(0, 100), dems[i], gof[i]))
        groups.setdefault(gof[i], []).append(cid)
    Q2 = max(max(dems), int(total * 0.45))
    Q1 = max(max(dems), int(math.ceil(total * 0.6)))
    T1 = 3
    if T2 is None:
        T2 = nc
    return make_instance(depot, sats, custs, groups, Q1, Q2, T1, T2)


# ------------------------------------------------------------------------------- independent exact solution
def _xy(inst):
    pts = {inst["depot"]["id"]: (inst["depot"]["x"], inst["depot"]["y"])}
    for s in inst["satellites"]:
        pts[s["id"]] = (s["x"], s["y"])
    for c in inst["customers"]:
        pts[c["id"]] = (c["x"], c["y"])
    return pts


def _dist(pts, a, b):
    (xa, ya), (xb, yb) = pts[a], pts[b]
    return math.sqrt((xa - xb) ** 2 + (ya - yb) ** 2)


def _tour(pts, home, stops):
    best = INF
    for perm in itertools.permutations(stops):
        c = 0.0
        prev = home
        for x in perm:
            c += _dist(pts, prev, x)
            prev = x
        c += _dist(pts, prev, home)
        best = min(best, c)
    return best


def exact_e1(inst, loads):
    """Exact first-echelon cost for {satellite id: load}: cheapest multiset of truck tours satisfying Hall's
    condition (every satellite set A: load(A) <= Q1 * number of tours visiting A), at most T1 tours."""
    pts = _xy(inst)
    dep = inst["depot"]["id"]
    Q1, T1 = inst["Q1"], inst["T1"]
    pos = [s for s, l in loads.items() if l > 0]
    if not pos:
        return 0.0
    subsets = [c for r in range(1, len(pos) + 1) for c in itertools.combinations(pos, r)]
    cost = {sub: _tour(pts, dep, sub) for sub in subsets}
    best = INF
    for K in range(1, T1 + 1):
        for combo in itertools.combinations_with_replacement(subsets, K):
            c = sum(cost[x] for x in combo)
            if c >= best:
                continue
            ok = True
            for A in subsets:
                need = sum(loads[s] for s in A)
                hit = sum(1 for x in combo if set(x) & set(A))
                if need > Q1 * hit + 1e-9:
                    ok = False
                    break
            if ok:
                best = c
    return best


def brute_force(inst):
    """Exact optimum of a tiny 2E-CVRPGC instance (independent of solve.py)."""
    pts = _xy(inst)
    sats = inst["satellites"]
    dem = {c["id"]: c["demand"] for c in inst["customers"]}
    groups = [g["customer_ids"] for g in inst["groups"]]
    Q2, T2 = inst["Q2"], inst["T2"]
    tables = {}

    def table(s, members):
        key = (s["id"], tuple(sorted(members)))
        if key in tables:
            return tables[key]
        n = len(members)
        kmax = min(s["max_vehicles"], n)
        rc = {}
        for mask in range(1, 1 << n):
            ms = [members[i] for i in range(n) if mask >> i & 1]
            if sum(dem[x] for x in ms) <= Q2:
                rc[mask] = _tour(pts, s["id"], ms)
        f = [[INF] * (kmax + 1) for _ in range(1 << n)]
        f[0][0] = 0.0
        for mask in range(1, 1 << n):
            low = mask & -mask
            rest = mask ^ low
            sub = rest
            while True:
                part = sub | low
                if part in rc:
                    for k in range(1, kmax + 1):
                        v = rc[part] + f[mask ^ part][k - 1]
                        if v < f[mask][k]:
                            f[mask][k] = v
                if sub == 0:
                    break
                sub = (sub - 1) & rest
        tables[key] = f[(1 << n) - 1]
        return tables[key]

    best = INF
    for choice in itertools.product(range(len(sats)), repeat=len(groups)):
        members = [[] for _ in sats]
        for g, si in zip(groups, choice):
            members[si].extend(g)
        loads = {sats[i]["id"]: sum(dem[x] for x in members[i]) for i in range(len(sats))}
        if any(loads[s["id"]] > s["capacity"] for s in sats):
            continue
        # second echelon: per satellite cost by route count, combined under T2
        comb = {0: 0.0}
        for i, s in enumerate(sats):
            if not members[i]:
                continue
            if s["max_vehicles"] < 1:
                comb = {}
                break
            f = table(s, members[i])
            nxt = {}
            for used, c0 in comb.items():
                for k in range(1, len(f)):
                    if f[k] < INF and used + k <= T2:
                        v = c0 + f[k]
                        if v < nxt.get(used + k, INF):
                            nxt[used + k] = v
            comb = nxt
        if not comb:
            continue
        e2 = min(comb.values())
        hand = sum(s["handling_cost"] * loads[s["id"]] for s in sats)
        e1 = exact_e1(inst, loads)
        best = min(best, e2 + hand + e1)
    return best


# --------------------------------------------------------------------------------------------------- helpers
def official():
    p = os.environ.get("ROBERTI_OFFICIAL")
    if not p or not os.path.exists(p):
        return None
    spec = importlib.util.spec_from_file_location("roberti_official", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(inst, tl=6.0, workers=1, seed=1):
    sol, log = S.solve(inst, None, tl, seed=seed, workers=workers, t0=time.monotonic())
    return sol, log


def checker_objective(inst, sol):
    """The checker's objective formula (arc sets, handling from deliveries), written out independently."""
    pts = _xy(inst)
    x = set()
    for r in sol["first_echelon_routes"]:
        for a, b in zip(r["route"], r["route"][1:]):
            x.add((a, b, r["vehicle"]))
    y = set()
    for r in sol["second_echelon_routes"]:
        for a, b in zip(r["route"], r["route"][1:]):
            y.add((a, b))
    h = {s["id"]: s["handling_cost"] for s in inst["satellites"]}
    hand = sum(h[int(k)] * float(v) for r in sol["first_echelon_routes"] for k, v in r["deliveries"].items())
    return sum(_dist(pts, a, b) for a, b, _ in x) + hand + sum(_dist(pts, a, b) for a, b in y)


class TestFirstEchelon(unittest.TestCase):
    def check_plan(self, P, loads, cost, routes):
        got = [0] * P.S
        for r in routes:
            self.assertLessEqual(sum(a for _, a in r), P.Q1 + 1e-9)
            self.assertEqual(len({s for s, _ in r}), len(r))
            for s, a in r:
                self.assertGreater(a, 0)
                got[s] += a
        self.assertEqual(got, list(loads))
        self.assertLessEqual(len(routes), P.T1)
        tot = 0.0
        for r in routes:
            m = 0
            for s, _ in r:
                m |= 1 << s
            tot += P.tsp(m)[0]
        self.assertAlmostEqual(tot, cost, places=6)

    def test_exact_up_to_two_loaded_satellites(self):
        # with at most two loaded satellites the partition-and-cut plan is provably optimal; compare by brute force
        for seed in range(25):
            rng = random.Random(seed)
            inst = random_instance(seed, ns=2, nc=4, ng=2)
            inst["Q1"] = rng.randint(5, 30)
            inst["T1"] = 12
            P = S.Problem(inst)
            loads = tuple(rng.randint(0, 40) for _ in range(P.S))
            if math.ceil(sum(loads) / P.Q1) > P.T1:
                continue
            cost, routes = P.e1_solve(loads, plan=True)
            self.check_plan(P, loads, cost, routes)
            ex = exact_e1(inst, {P.sat_id[s]: loads[s] for s in range(P.S)})
            self.assertAlmostEqual(cost, ex, places=6, msg="seed %d loads %s" % (seed, loads))

    def test_three_satellites_never_below_exact(self):
        worst = 0.0
        for seed in range(15):
            rng = random.Random(100 + seed)
            inst = random_instance(100 + seed, ns=3, nc=4, ng=2)
            inst["Q1"] = rng.randint(8, 30)
            inst["T1"] = 5
            P = S.Problem(inst)
            loads = tuple(rng.randint(0, 25) for _ in range(P.S))
            if math.ceil(sum(loads) / P.Q1) > P.T1:
                continue
            cost, routes = P.e1_solve(loads, plan=True)
            self.check_plan(P, loads, cost, routes)
            ex = exact_e1(inst, {P.sat_id[s]: loads[s] for s in range(P.S)})
            self.assertGreaterEqual(cost, ex - 1e-6)
            worst = max(worst, (cost - ex) / ex if ex > 0 else 0.0)
        print("three satellites: worst gap of the first-echelon plan to the exact optimum %.4f%%" % (100 * worst))

    def test_many_satellites_fallback_plan_valid(self):
        rng = random.Random(5)
        inst = random_instance(5, ns=9, nc=12, ng=4)
        inst["Q1"] = 20
        inst["T1"] = 30
        P = S.Problem(inst)
        for _ in range(5):
            loads = tuple(rng.randint(0, 30) for _ in range(P.S))
            cost, routes = P.e1_solve(loads, plan=True)
            self.check_plan(P, loads, cost, routes)
            self.assertAlmostEqual(cost, P.e1_cost(loads), places=9)


class TestSolver(unittest.TestCase):
    def check_sol(self, inst, sol):
        v = S.verify(inst, sol)
        self.assertTrue(v["feasible"], v["reason"])
        self.assertAlmostEqual(sol["objective_value"], v["objective"], places=6)
        self.assertAlmostEqual(sol["objective_value"], checker_objective(inst, sol), places=6)
        off = official()
        if off is not None:
            self.assertIsNone(off._frontieror_validate_solution_contract(sol))
            r = off.check_feasibility(inst, sol)
            self.assertTrue(r["feasible"], r.get("violations"))

    def test_brute_force_optimum(self):
        # the first three seeds whose instance is feasible (seeds are fixed, so the instances are too)
        done = 0
        for seed in range(1, 30):
            inst = random_instance(seed, ns=2, nc=5, ng=3)
            opt = brute_force(inst)
            if opt == INF:
                continue
            sol, log = run(inst, tl=6.0)
            self.assertIsNotNone(sol, "seed %d: no answer" % seed)
            self.check_sol(inst, sol)
            obj = sol["objective_value"]
            self.assertGreaterEqual(obj, opt - 1e-6)
            self.assertLessEqual(obj, opt + 1e-6, "seed %d: %s vs optimum %s" % (seed, obj, opt))
            done += 1
            if done == 3:
                break
        self.assertEqual(done, 3)

    def test_tight_fleet(self):
        # T2 = 2 routes in all, two satellites, every customer its own group
        inst = random_instance(11, ns=2, nc=5, ng=5, T2=2)
        inst["Q2"] = int(math.ceil(0.6 * sum(c["demand"] for c in inst["customers"])))
        opt = brute_force(inst)
        if opt == INF:
            self.skipTest("instance infeasible")
        sol, log = run(inst, tl=6.0)
        self.check_sol(inst, sol)
        self.assertLessEqual(sum(1 for _ in sol["second_echelon_routes"]), 2)
        self.assertLessEqual(sol["objective_value"], opt + 1e-6)

    def test_random_instances_odd_ids(self):
        for seed in (21, 22):
            inst = random_instance(seed, ns=4, nc=30, ng=8, maxv=4, odd_ids=True)
            inst["Q2"] = 30
            sol, log = run(inst, tl=5.0)
            self.assertIsNotNone(sol)
            self.check_sol(inst, sol)
            if log["construction"]["feasible"]:
                self.assertLessEqual(log["final_objective"], log["construction"]["cost"] + 1e-3)

    def test_two_workers(self):
        inst = random_instance(31, ns=3, nc=15, ng=5, maxv=3)
        sol, log = run(inst, tl=5.0, workers=2)
        self.assertIsNotNone(sol)
        self.check_sol(inst, sol)

    def test_cli(self):
        inst = random_instance(41, ns=3, nc=12, ng=4, maxv=3)
        with tempfile.TemporaryDirectory() as td:
            ip = os.path.join(td, "inst.json")
            op = os.path.join(td, "sol.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            t = time.monotonic()
            p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "roberti2018",
                                "--instance", ip, "--output", op, "--time-limit", "6"],
                               capture_output=True, text=True, timeout=60)
            wall = time.monotonic() - t
            print(p.stderr.strip()[-400:])
            self.assertEqual(p.returncode, 0, p.stderr[-500:])
            self.assertLess(wall, 6.0)
            with open(op, encoding="utf-8") as f:
                sol = json.load(f)
        self.check_sol(inst, sol)


class TestVerify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inst = random_instance(51, ns=3, nc=14, ng=5, maxv=3)
        cls.inst["Q2"] = 25
        cls.sol, _ = run(cls.inst, tl=4.0)

    def fresh(self):
        return json.loads(json.dumps(self.sol))

    def reobj(self, sol):
        sol["objective_value"] = checker_objective(self.inst, sol)
        return sol

    def test_accepts_own(self):
        self.assertTrue(S.verify(self.inst, self.sol)["feasible"])

    def test_rejects_missing_customer(self):
        sol = self.fresh()
        r = max(sol["second_echelon_routes"], key=lambda r: len(r["route"]))
        del r["route"][1]
        self.assertFalse(S.verify(self.inst, self.reobj(sol))["feasible"])

    def test_rejects_delivery_mismatch(self):
        sol = self.fresh()
        r = sol["first_echelon_routes"][0]
        k = next(iter(r["deliveries"]))
        r["deliveries"][k] += 1
        self.assertFalse(S.verify(self.inst, self.reobj(sol))["feasible"])

    def test_rejects_objective(self):
        sol = self.fresh()
        sol["objective_value"] *= 1.01
        self.assertFalse(S.verify(self.inst, sol)["feasible"])

    def test_rejects_group_split(self):
        sol = self.fresh()
        gsize = {g["group_id"]: len(g["customer_ids"]) for g in self.inst["groups"]}
        gof = {c["id"]: c["group"] for c in self.inst["customers"]}
        sats = [s["id"] for s in self.inst["satellites"]]
        for r in sol["second_echelon_routes"]:
            for c in r["route"][1:-1]:
                if gsize[gof[c]] >= 2:
                    other = [s for s in sats if s != r["satellite"]][0]
                    r["route"].remove(c)
                    sol["second_echelon_routes"].append({"satellite": other, "route": [other, c, other]})
                    sol["second_echelon_routes"] = [x for x in sol["second_echelon_routes"] if len(x["route"]) > 2]
                    self.assertFalse(S.verify(self.inst, self.reobj(sol))["feasible"])
                    return
        self.skipTest("no group of two or more")

    def test_agrees_with_official_on_mutations(self):
        off = official()
        if off is None:
            self.skipTest("official checker not available (set ROBERTI_OFFICIAL)")
        rng = random.Random(7)
        agree = 0
        kinds = {}
        for t in range(200):
            sol = self.fresh()
            kind = rng.randrange(9)
            r1 = sol["first_echelon_routes"]
            r2 = sol["second_echelon_routes"]
            if kind == 0:      # drop a customer
                r = rng.choice(r2)
                del r["route"][rng.randrange(1, len(r["route"]) - 1)]
                sol["second_echelon_routes"] = [x for x in r2 if len(x["route"]) > 2]
            elif kind == 1:    # merge two routes of one satellite
                by = {}
                for x in r2:
                    by.setdefault(x["satellite"], []).append(x)
                many = [v for v in by.values() if len(v) >= 2]
                if not many:
                    continue
                a, b = rng.sample(rng.choice(many), 2)
                a["route"] = a["route"][:-1] + b["route"][1:]
                r2.remove(b)
            elif kind == 2:    # split a route in two
                r = rng.choice([x for x in r2 if len(x["route"]) >= 4] or r2)
                if len(r["route"]) < 4:
                    continue
                cut = rng.randrange(2, len(r["route"]) - 1)
                s = r["satellite"]
                r2.append({"satellite": s, "route": [s] + r["route"][cut:-1] + [s]})
                r["route"] = r["route"][:cut] + [s]
            elif kind == 3:    # move one unit of freight between trucks
                a = rng.choice(r1)
                k = rng.choice(list(a["deliveries"]))
                b = rng.choice(r1)
                a["deliveries"][k] -= 1
                b["deliveries"][k] = b["deliveries"].get(k, 0) + 1
            elif kind == 4:    # one extra unit of freight
                a = rng.choice(r1)
                k = rng.choice(list(a["deliveries"]))
                a["deliveries"][k] += 1
            elif kind == 5:    # reverse a truck tour
                a = rng.choice(r1)
                a["route"] = a["route"][::-1]
            elif kind == 6:    # drop a satellite from a truck tour, keep the deliveries
                a = rng.choice([x for x in r1 if len(x["route"]) >= 4] or r1)
                if len(a["route"]) < 4:
                    continue
                del a["route"][rng.randrange(1, len(a["route"]) - 1)]
            elif kind == 7:    # move a customer to another route of the same satellite
                r = rng.choice(r2)
                same = [x for x in r2 if x["satellite"] == r["satellite"] and x is not r]
                if not same or len(r["route"]) < 3:
                    continue
                c = r["route"].pop(rng.randrange(1, len(r["route"]) - 1))
                o = rng.choice(same)
                o["route"].insert(rng.randrange(1, len(o["route"])), c)
                sol["second_echelon_routes"] = [x for x in r2 if len(x["route"]) > 2]
            else:              # swap two customers between satellites
                if len({x["satellite"] for x in r2}) < 2:
                    continue
                a, b = rng.sample(r2, 2)
                if a["satellite"] == b["satellite"]:
                    continue
                i = rng.randrange(1, len(a["route"]) - 1)
                j = rng.randrange(1, len(b["route"]) - 1)
                a["route"][i], b["route"][j] = b["route"][j], a["route"][i]
            self.reobj(sol)
            mine = S.verify(self.inst, sol, loose=True)["feasible"]
            theirs = off.check_feasibility(self.inst, sol)["feasible"]
            kinds.setdefault(kind, [0, 0, 0])
            kinds[kind][0] += 1
            kinds[kind][1] += int(theirs)
            if mine == theirs:
                agree += 1
                kinds[kind][2] += 1
            else:
                self.fail("kind %d: ours %s, official %s" % (kind, mine, theirs))
        print("mutations by kind [tried, official accepts, agree]:", json.dumps(kinds, sort_keys=True))
        self.assertGreater(agree, 100)


class TestContestWay(unittest.TestCase):
    def test_tiny_official(self):
        hf = os.environ.get("MV2_FROC_HF")
        if not hf:
            self.skipTest("set MV2_FROC_HF to a FrontierOR download")
        tdir = os.path.join(hf, "tasks", "roberti2018")
        ip = os.path.join(tdir, "instance", "tiny_instance.json")
        checker = os.path.join(tdir, "feasibility_check.py")
        with open(ip, encoding="utf-8") as f:
            inst = json.load(f)
        with tempfile.TemporaryDirectory() as td:
            op = os.path.join(td, "tiny.solution.json")
            rp = os.path.join(td, "tiny.result.json")
            p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "roberti2018",
                                "--instance", ip, "--output", op, "--time-limit", "10"],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 0, p.stderr[-500:])
            subprocess.run([sys.executable, checker, "--instance_path", ip, "--solution_path", op,
                            "--result_path", rp], capture_output=True, text=True, timeout=600, cwd=td)
            with open(rp, encoding="utf-8") as f:
                res = json.load(f)
            with open(op, encoding="utf-8") as f:
                sol = json.load(f)
            self.assertTrue(res.get("feasible"), str(res.get("violations"))[:500])
            self.assertTrue(S.verify(inst, sol)["feasible"])
        gp = os.path.join(tdir, "gurobi_solution", "tiny_solution.json")
        if os.path.exists(gp):
            with open(gp, encoding="utf-8") as f:
                g = json.load(f)
            v = S.verify(inst, g, loose=True)
            self.assertTrue(v["feasible"], v["reason"])


if __name__ == "__main__":
    unittest.main()

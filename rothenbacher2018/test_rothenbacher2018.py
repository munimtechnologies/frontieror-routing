"""Tests for MV2's rothenbacher2018 (truck-and-trailer routing with time windows) engine. Standard library only.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python -m unittest -v test_rothenbacher2018
With MV2_FROC_HF=<Hugging Face frontieror/FrontierOR copy>, TestContestWay also runs the official checker.
"""
import copy
import importlib.util
import itertools
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


def make_inst(n_nl, n_nh, n_t, seed, tw=True, H=600, svc=5, fleet="small"):
    """A random instance in the benchmark's layout: depot 0, truck customers, trailer customers, transshipment."""
    rng = random.Random(seed)
    n0 = 1 + n_nl + n_nh + n_t
    pts = [(rng.randint(0, 50), rng.randint(0, 50)) for _ in range(n0)]
    dm = [[round(math.hypot(a[0] - b[0], a[1] - b[1]), 2) for b in pts] for a in pts]
    tm = [[round(v * 1.0, 2) for v in row] for row in dm]
    ids = list(range(1, n0))
    nl, nh, tr = ids[:n_nl], ids[n_nl:n_nl + n_nh], ids[n_nl + n_nh:]

    def cust(i):
        c = {"id": i, "x": pts[i][0], "y": pts[i][1], "supply": rng.randint(1, 8), "service_time": svc}
        if tw:
            lo = int(math.ceil(tm[0][i]))
            hi = int(H - svc - tm[i][0]) - 1
            a = rng.randint(lo, max(lo, hi))
            c["time_window"] = [max(0, a - rng.randint(0, 150)), min(H, a + rng.randint(20, 150))]
        return c

    if fleet == "small":
        trucks = [{"id": 1, "capacity": 12, "fixed_cost": 40.0, "cost_factor": 1.0, "num_available": 2},
                  {"id": 2, "capacity": 9, "fixed_cost": 25.0, "cost_factor": 0.8, "num_available": 1}]
        trailers = [{"id": 1, "capacity": 10, "towing_cost_multiplier": 0.6, "num_available": 1}]
    else:
        trucks = [{"id": 1, "capacity": 15, "fixed_cost": 50.0, "cost_factor": 1.0, "num_available": 8},
                  {"id": 2, "capacity": 10, "fixed_cost": 30.0, "cost_factor": 0.9, "num_available": 6}]
        trailers = [{"id": 1, "capacity": 15, "towing_cost_multiplier": 0.5, "num_available": 5}]
    classes = []
    cid = 1
    for t in trucks:
        classes.append({"class_id": cid, "truck_type_id": t["id"], "trailer_type_id": 0,
                        "truck_capacity": t["capacity"], "trailer_capacity": 0, "total_capacity": t["capacity"],
                        "truck_fixed_cost": t["fixed_cost"], "truck_cost_factor": t["cost_factor"],
                        "trailer_towing_cost_multiplier": 0, "num_available": t["num_available"],
                        "description": "solo %d" % t["id"]})
        cid += 1
    for h in trailers:
        t = trucks[0]
        classes.append({"class_id": cid, "truck_type_id": t["id"], "trailer_type_id": h["id"],
                        "truck_capacity": t["capacity"], "trailer_capacity": h["capacity"],
                        "total_capacity": t["capacity"] + h["capacity"], "truck_fixed_cost": t["fixed_cost"],
                        "truck_cost_factor": t["cost_factor"],
                        "trailer_towing_cost_multiplier": h["towing_cost_multiplier"],
                        "num_available": min(t["num_available"], h["num_available"]),
                        "description": "truck %d + trailer %d" % (t["id"], h["id"])})
        cid += 1
    return {"parameters": {"max_route_duration": H, "service_time": svc, "coupling_time": 4.0,
                           "decoupling_time": 3.0, "transfer_time": 2.0, "coupling_cost": 2.5,
                           "decoupling_cost": 1.5, "transfer_cost": 0.0, "planning_horizon": [0, H]},
            "fleet": {"truck_types": trucks, "trailer_types": trailers, "vehicle_classes": classes},
            "depot": {"id": 0, "x": pts[0][0], "y": pts[0][1]},
            "truck_customers": [cust(i) for i in nl], "trailer_customers": [cust(i) for i in nh],
            "transshipment_locations": [{"id": i, "x": pts[i][0], "y": pts[i][1]} for i in tr],
            "distance_matrix": dm, "travel_time_matrix": tm}


# ---- independent re-implementation from the raw instance (no solve.py code) -------------------------------------------
def parks_of(inst):
    return sorted({c["id"] for c in inst["trailer_customers"]} | {t["id"] for t in inst["transshipment_locations"]})


def expand(inst, main, sub, p, pos):
    dep = inst["depot"]["id"]
    if p is None:
        return [dep] + list(main) + [dep]
    n0 = len(inst["distance_matrix"])
    pk = parks_of(inst)
    i = pk.index(p)
    return [dep] + list(main[:pos]) + [n0 + i] + list(sub) + [n0 + len(pk) + i] + list(main[pos:]) + [dep]


def ind_eval(inst, vc, net):
    """(feasible, cost) of one expanded route by the stated rules, written separately from solve.py."""
    par = inst["parameters"]
    dep = inst["depot"]["id"]
    n0 = len(inst["distance_matrix"])
    pk = parks_of(inst)
    cust = {c["id"]: (c, "NL") for c in inst["truck_customers"]}
    cust.update({c["id"]: (c, "NH") for c in inst["trailer_customers"]})

    def kind_phys(x):
        if x == dep:
            return "D", dep
        if x < n0:
            return cust[x][1], x
        off = x - n0
        return ("DC" if off < len(pk) else "CP"), pk[off % len(pk)]

    has_tr = vc["trailer_type_id"] != 0
    QL, QH = vc["truck_capacity"], (vc["trailer_capacity"] if has_tr else 0)
    H0, H1 = par["planning_horizon"]
    end_lim = min(H1, H0 + par.get("max_route_duration", H1 - H0))
    t = H0
    truck = trailer = 0.0
    on = has_tr
    parked = None
    cost = vc["truck_fixed_cost"]
    prev_k, prev_p = "D", dep
    for x in net[1:]:
        k, p = kind_phys(x)
        tow = has_tr and prev_k in ("D", "NH", "CP") and k in ("D", "NH", "DC")
        cost += (vc["truck_cost_factor"] + (vc["trailer_towing_cost_multiplier"] if tow else 0.0)) * \
            inst["distance_matrix"][prev_p][p]
        t += inst["travel_time_matrix"][prev_p][p]
        if k == "D":
            if t > end_lim + 1e-9:
                return False, None
            break
        win = None
        hold = 0.0
        if k in ("NL", "NH"):
            win = cust[p][0].get("time_window")
            hold = cust[p][0].get("service_time", par["service_time"])
        else:
            if not has_tr:
                return False, None
            if p in cust:  # the benchmark's model: a copy at a customer keeps its window and service time
                win = cust[p][0].get("time_window")
                hold = cust[p][0].get("service_time", par["service_time"])
            hold += par["decoupling_time"] if k == "DC" else par["coupling_time"]
        if win is not None:
            t = max(t, win[0])
            if t > win[1] + 1e-9:
                return False, None
        t += hold
        if k == "NL":
            if on:
                return False, None
            truck += cust[p][0]["supply"]
        elif k == "NH":
            q = cust[p][0]["supply"]
            if on:
                a = min(q, QH - trailer)
                trailer += a
                truck += q - a
            else:
                truck += q
        elif k == "DC":
            if not on:
                return False, None
            on, parked = False, p
            cost += par["decoupling_cost"]
        else:
            if on or parked != p:
                return False, None
            on, parked = True, None
            a = min(truck, QH - trailer)
            truck -= a
            trailer += a
            cost += par["coupling_cost"]
        if truck > QL + 1e-9 or trailer > QH + 1e-9:
            return False, None
        prev_k, prev_p = k, p
    if has_tr and not on:
        return False, None
    return True, cost


def class_by_index(inst, ci):
    return inst["fleet"]["vehicle_classes"][ci]


def structures(inst, P, ci, custs):
    """Every (main, sub, p, pos) layout of a set of customers for class ci (at most one parking)."""
    vc = class_by_index(inst, ci)
    out = []
    if vc["trailer_type_id"] == 0:
        for perm in itertools.permutations(custs):
            out.append((list(perm), [], None, 0))
        return out
    nh = [c for c in custs if P.is_nh[c]]
    for perm in itertools.permutations(custs):
        if all(P.is_nh[c] for c in perm):
            out.append((list(perm), [], None, 0))
    others = [c for c in custs]
    for mask in range(1, 1 << len(others)):
        sub_set = [others[i] for i in range(len(others)) if mask >> i & 1]
        main_set = [c for c in others if c not in sub_set]
        if any(not P.is_nh[c] for c in main_set):
            continue
        for sp in itertools.permutations(sub_set):
            for mp in itertools.permutations(main_set):
                for pos in range(len(mp) + 1):
                    for p in parks_of(inst):
                        out.append((list(mp), list(sp), p, pos))
    del nh
    return out


def random_solution(inst, P, rng):
    st = S.construct(P, rng)
    return st


class TestRoute(unittest.TestCase):
    def test_make_route_matches_independent_rules(self):
        checked = feas = 0
        for t in range(60):
            inst = make_inst(3, 3, 2, 100 + t, tw=(t % 3 != 0))
            P = S.Problem(inst, near_park=None)
            rng = random.Random(t)
            for ci in range(len(P.classes)):
                cs = rng.sample(P.cust, rng.randint(1, 4))
                for main, sub, p, pos in rng.sample(structures(inst, P, ci, cs),
                                                    min(40, len(structures(inst, P, ci, cs)))):
                    r = S.make_route(P, ci, main, sub, p, pos)
                    ok, c = ind_eval(inst, class_by_index(inst, ci), expand(inst, main, sub, p, pos))
                    self.assertEqual(r is not None, ok, (t, ci, main, sub, p, pos))
                    checked += 1
                    if ok:
                        feas += 1
                        self.assertAlmostEqual(r.cost, c, places=6)
                        self.assertEqual(r.net, expand(inst, main, sub, p, pos))
        self.assertGreater(checked, 500)
        self.assertGreater(feas, 50)


class TestInsertion(unittest.TestCase):
    def check_one(self, inst, seed):
        rng = random.Random(seed)
        P = S.Problem(inst, near_park=None)
        st = S.construct(P, rng)
        if st is None or not st.routes:
            return 0
        u = rng.choice(P.cust)
        S.remove_customers(P, st, [u])
        if sorted(x for r in st.routes for x in r.custs()) != [c for c in P.cust if c != u]:
            return 0  # a route fell apart on removal (rounding); not this test's subject
        olds = [ind_eval(inst, class_by_index(inst, r.c), r.net)[1] for r in st.routes]
        options = []
        for ri, r in enumerate(st.routes):
            vc = class_by_index(inst, r.c)
            lays = []
            if vc["trailer_type_id"] == 0:
                for i in range(len(r.main) + 1):
                    lays.append((r.main[:i] + [u] + r.main[i:], [], None, 0))
            elif r.p is None:
                if P.is_nh[u]:
                    for i in range(len(r.main) + 1):
                        lays.append((r.main[:i] + [u] + r.main[i:], [], None, 0))
                for pos in range(len(r.main) + 1):
                    for p in parks_of(inst):
                        lays.append((list(r.main), [u], p, pos))
            else:
                if P.is_nh[u]:
                    for i in range(len(r.main) + 1):
                        variants = [r.pos + 1] if i < r.pos else ([r.pos] if i > r.pos else [r.pos + 1, r.pos])
                        for npos in variants:
                            lays.append((r.main[:i] + [u] + r.main[i:], list(r.sub), r.p, npos))
                for j in range(len(r.sub) + 1):
                    lays.append((list(r.main), r.sub[:j] + [u] + r.sub[j:], r.p, r.pos))
            for main, sub, p, pos in lays:
                ok, c = ind_eval(inst, vc, expand(inst, main, sub, p, pos))
                if ok:
                    options.append(c - olds[ri])
        for ci in range(len(P.classes)):
            if not st.can_open(P, ci):
                continue
            for main, sub, p, pos in structures(inst, P, ci, [u]):
                ok, c = ind_eval(inst, class_by_index(inst, ci), expand(inst, main, sub, p, pos))
                if ok:
                    options.append(c)
        res = S.best_insert(P, st, u, random.Random(0), blink=0.0)
        self.assertEqual(res is not None, bool(options), "feasibility of inserting %s" % u)
        if res is None:
            return 0
        self.assertAlmostEqual(res[0], min(options), places=6)
        before = st.total()
        ok = S.recreate(P, st, [u], random.Random(0), blink=0.0, keep_order=True, repark_p=0.0)
        self.assertTrue(ok)
        self.assertAlmostEqual(st.total(), before + min(options), places=6)
        for r in st.routes:
            okr, c = ind_eval(inst, class_by_index(inst, r.c), r.net)
            self.assertTrue(okr)
            self.assertAlmostEqual(c, r.cost, places=6)
        return 1

    def test_cheapest_feasible_insertion_matches_brute_force(self):
        done = 0
        for t in range(120):
            inst = make_inst(3 + t % 3, 4 + t % 4, 1 + t % 2, 500 + t, tw=(t % 4 != 0), fleet="big")
            done += self.check_one(inst, t)
        self.assertGreater(done, 60)


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.inst = make_inst(4, 6, 2, 9, fleet="big")
        self.P = S.Problem(self.inst)
        st = S.construct(self.P, random.Random(1))
        self.routes = st.routes
        self.sol = S.build_solution(self.P, self.routes)

    def test_accepts_built_solution(self):
        r = S.verify(self.inst, self.sol)
        self.assertTrue(r["feasible"], r)
        self.assertAlmostEqual(r["objective"], self.sol["objective_value"], places=9)
        tot = sum(ind_eval(self.inst, class_by_index(self.inst, x.c), x.net)[1] for x in self.routes)
        self.assertAlmostEqual(self.sol["objective_value"], tot, places=6)
        self.assertNotIn("solver", self.sol)
        self.assertNotIn("algorithm", self.sol)

    def test_rejections(self):
        sol = self.sol
        inst = self.inst
        self.assertFalse(S.verify(inst, dict(sol, objective_value=sol["objective_value"] + 1.0))["feasible"])
        self.assertFalse(S.verify(inst, dict(sol, objective_value=None))["feasible"])
        drop = copy.deepcopy(sol)
        drop["routes"][0]["customers_served"] = drop["routes"][0]["customers_served"][1:]
        self.assertFalse(S.verify(inst, drop)["feasible"])
        nt = copy.deepcopy(sol)
        del nt["routes"][0]["arrival_times"]
        self.assertFalse(S.verify(inst, nt)["feasible"])
        late = copy.deepcopy(inst)
        c = sol["routes"][0]["customers_served"][0]
        for grp in ("truck_customers", "trailer_customers"):
            for x in late[grp]:
                if x["id"] == c:
                    x["time_window"] = [0, -1]
        self.assertFalse(S.verify(late, sol)["feasible"])
        small = copy.deepcopy(inst)
        for vc in small["fleet"]["vehicle_classes"]:
            vc["truck_capacity"] = 1
            vc["trailer_capacity"] = 0 if vc["trailer_type_id"] == 0 else 1
        self.assertFalse(S.verify(small, sol)["feasible"])
        fleet = copy.deepcopy(inst)
        for t in fleet["fleet"]["truck_types"]:
            t["num_available"] = 0
        self.assertFalse(S.verify(fleet, sol)["feasible"])
        # a truck customer moved into the attached part of a complete vehicle's route
        cvs = [i for i, r in enumerate(self.routes) if self.P.classes[r.c].cv]
        nls = [x for x in self.P.NL]
        if cvs and nls:
            bad = copy.deepcopy(sol)
            r = bad["routes"][cvs[0]]
            v = nls[0]
            for other in bad["routes"]:
                if v in other["customers_served"]:
                    other["customers_served"].remove(v)
                    i = other["route_sequence"].index(v)
                    del other["route_sequence"][i]
                    del other["route_sequence_physical"][i]
            r["route_sequence"].insert(1, v)
            r["route_sequence_physical"].insert(1, v)
            r["customers_served"].append(v)
            r["arrival_times"][str(v)] = 0.0
            chk = S.verify(inst, bad)
            bad["objective_value"] = chk["objective"] if chk["objective"] is not None else 0.0
            self.assertFalse(S.verify(inst, bad)["feasible"])


def brute_optimum(inst):
    P = S.Problem(inst, near_park=None)
    opts = {}

    def block_opts(block):
        key = tuple(block)
        if key not in opts:
            lst = []
            for ci in range(len(P.classes)):
                best = None
                for main, sub, p, pos in structures(inst, P, ci, list(block)):
                    ok, c = ind_eval(inst, class_by_index(inst, ci), expand(inst, main, sub, p, pos))
                    if ok and (best is None or c < best):
                        best = c
                if best is not None:
                    lst.append((best, ci))
            opts[key] = lst
        return opts[key]

    def partitions(items):
        if not items:
            yield []
            return
        first, rest = items[0], items[1:]
        for part in partitions(rest):
            yield [[first]] + part
            for i in range(len(part)):
                yield part[:i] + [[first] + part[i]] + part[i + 1:]

    best = math.inf
    for part in partitions(list(P.cust)):
        lists = [block_opts(sorted(b)) for b in part]
        if any(not x for x in lists):
            continue
        for combo in itertools.product(*lists):
            c = sum(x[0] for x in combo)
            if c >= best:
                continue
            st = S.State(P)
            ok = True
            for _, ci in combo:
                if not st.can_open(P, ci):
                    ok = False
                    break
                st.add(P, ci, 1)
            if ok:
                best = c
    return best


class TestSearch(unittest.TestCase):
    def test_finds_brute_force_optimum_tiny(self):
        for seed in range(5):
            inst = make_inst(1 + seed % 2, 2 + (seed + 1) % 2, 1, 70 + seed, tw=(seed % 2 == 0), fleet="big")
            opt = brute_optimum(inst)
            sol = S.solve(inst, seed=seed, budget=1.5, near_park=None)
            if math.isinf(opt):
                self.assertIsNone(sol)
                continue
            chk = S.verify(inst, sol)
            self.assertTrue(chk["feasible"], chk)
            self.assertAlmostEqual(sol["objective_value"], opt, places=6, msg="seed %d" % seed)

    def test_medium_feasible_and_improves(self):
        inst = make_inst(10, 25, 4, 5, fleet="big", H=900)
        P = S.Problem(inst)
        st = S.construct(P, random.Random(1))
        log = {}
        sol = S.solve(inst, seed=1, budget=4.0, log=log)
        self.assertIsNotNone(sol)
        self.assertTrue(S.verify(inst, sol)["feasible"])
        self.assertLessEqual(sol["objective_value"], st.total() + 1e-6)
        self.assertGreater(log["iterations"], 10)

    def test_main_contest_way(self):
        inst = make_inst(6, 14, 3, 21, fleet="big", H=900)
        with tempfile.TemporaryDirectory() as d:
            ip, op = os.path.join(d, "i.json"), os.path.join(d, "o.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "rothenbacher2018",
                                "--instance", ip, "--output", op, "--time-limit", "5"], capture_output=True,
                               text=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stderr[-800:])
            with open(op, encoding="utf-8") as f:
                sol = json.load(f)
            self.assertTrue(S.verify(inst, sol)["feasible"])


HF = os.environ.get("MV2_FROC_HF")


@unittest.skipUnless(HF and os.path.isdir(os.path.join(HF or "", "tasks", "rothenbacher2018")), "needs MV2_FROC_HF")
class TestContestWay(unittest.TestCase):
    def setUp(self):
        tdir = os.path.join(HF, "tasks", "rothenbacher2018")
        spec = importlib.util.spec_from_file_location("ttr_official", os.path.join(tdir, "feasibility_check.py"))
        self.off = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.off)
        with open(os.path.join(tdir, "instance", "tiny_instance.json"), encoding="utf-8") as f:
            self.tiny = json.load(f)
        self.gp = os.path.join(tdir, "gurobi_solution", "tiny_solution.json")

    def official(self, inst, sol):
        if self.off._frontieror_validate_solution_contract(sol) is not None:
            return False
        try:
            return bool(self.off.check_feasibility(inst, sol)[0])
        except Exception:  # noqa: BLE001 - the official program turns exceptions into a rejection
            return False

    def test_gurobi_tiny_both_checkers(self):
        with open(self.gp, encoding="utf-8") as f:
            g = json.load(f)
        self.assertEqual(self.official(self.tiny, g), S.verify(self.tiny, g)["feasible"])

    def test_synthetic_official_accepts(self):
        for t in range(4):
            inst = make_inst(5, 12, 3, 800 + t, fleet="big", H=900, tw=(t % 2 == 0))
            sol = S.solve(inst, seed=t, budget=1.5)
            self.assertIsNotNone(sol)
            self.assertTrue(self.official(inst, sol), t)
            self.assertTrue(S.verify(inst, sol)["feasible"], t)

    def test_tiny_official_and_mirror_agree_on_mutations(self):
        sol = S.solve(self.tiny, seed=1, budget=2.0)
        self.assertIsNotNone(sol)
        self.assertTrue(self.official(self.tiny, sol))
        self.assertTrue(S.verify(self.tiny, sol)["feasible"])
        classes = [vc["class_id"] for vc in self.tiny["fleet"]["vehicle_classes"]]
        rng = random.Random(3)
        agree = 0
        for t in range(100):
            cand = copy.deepcopy(sol)
            routes = cand["routes"]
            kind = t % 6
            ri = rng.randrange(len(routes))
            r = routes[ri]
            rs, ps = r["route_sequence"], r["route_sequence_physical"]
            if kind == 0 and len(rs) > 3:
                a, b = rng.sample(range(1, len(rs) - 1), 2)
                rs[a], rs[b] = rs[b], rs[a]
                ps[a], ps[b] = ps[b], ps[a]
            elif kind == 1 and r["customers_served"]:
                v = r["customers_served"].pop(rng.randrange(len(r["customers_served"])))
                i = rs.index(v)
                del rs[i]
                del ps[i]
            elif kind == 2:
                r["vehicle_class"] = rng.choice(classes)
            elif kind == 3 and r["arrival_times"]:
                k = rng.choice(sorted(r["arrival_times"]))
                r["arrival_times"][k] = float(r["arrival_times"][k]) + rng.choice([-50.0, 50.0, 500.0])
            elif kind == 4 and len(routes) > 1:
                o = routes.pop((ri + 1) % len(routes))
                tgt = routes[ri if ri < len(routes) else 0]
                tgt["customers_served"] += o["customers_served"]
                tgt["route_sequence"] = tgt["route_sequence"][:-1] + o["route_sequence"][1:]
                tgt["route_sequence_physical"] = tgt["route_sequence_physical"][:-1] + \
                    o["route_sequence_physical"][1:]
                tgt["arrival_times"] = dict(o["arrival_times"], **tgt["arrival_times"])
            elif kind == 5:
                r["decouple_locations"] = list(reversed(r["decouple_locations"])) + ([ps[1]] if len(ps) > 2 else [])
            chk = S.verify(self.tiny, cand)
            if chk["objective"] is not None and rng.random() < 0.8:
                cand["objective_value"] = chk["objective"]
            agree += self.official(self.tiny, cand) == S.verify(self.tiny, cand)["feasible"]
        self.assertEqual(agree, 100)


if __name__ == "__main__":
    unittest.main()

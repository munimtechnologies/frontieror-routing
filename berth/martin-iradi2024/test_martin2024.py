"""Tests for MV2's martin-iradi2024 berth solver (MV2 of Munim, Inc.; made with AI agents working in MV2's name;
Apache-2.0).

Checked against independent brute force on small synthetic instances: the whole optimum of one ship (every speed
combination enumerated), the placement of one call among fixed ships (a 0.25 m grid of quay positions with an
independent earliest-free-time search), the exact label dominance, and verify() against hand-made broken solutions.
If MV2_FROC_HF points at a FrontierOR download, the official checker also judges a solver output.
"""
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

SPEEDS = [17.0, 18.5, 20.0]


def make_instance(n_ships=5, seed=0, externals=True, ports=("A", "B", "C"), quay=600, calls=3,
                  costs=(500, 200, 1000, 100, 5000), beta=0.001, spread=10.0):
    rng = random.Random(seed)
    dist = {}
    for p in ports:
        for q in ports:
            dist["%s_%s" % (p, q)] = 0 if p == q else rng.randint(100, 400)
    ships = []
    for i in range(n_ships):
        if i == 0 and len(ports) >= 2:
            route = [ports[0], ports[1], ports[0]][:calls]
        else:
            route = [rng.choice(ports) for _ in range(calls)]
        length = rng.choice([150, 200, 250])
        t = rng.uniform(0, spread)
        pvs = []
        for c, p in enumerate(route, start=1):
            h0 = round(rng.uniform(5, 15), 3)
            pvs.append({"port_call_index": c, "port_id": p,
                        "ideal_berthing_position": float(rng.randint(0, quay - length)),
                        "min_handling_time_hours": h0, "max_handling_time_hours": 2 * h0,
                        "earliest_start_time_hours": round(t, 3), "expected_finish_time_hours": round(t, 3) + h0,
                        "latest_finish_time_hours": round(t, 3) + h0 + 0.5 * h0})
            t += h0 + rng.uniform(8, 25)
        fuel = {str(s): 0.05 * (s / 18.0) ** 3 for s in SPEEDS}
        ships.append({"id": i + 1, "type": "feeder", "length_meters": length, "design_speed_knots": 18.0,
                      "fuel_consumption_at_design_speed_tonnes_per_day": 30.0,
                      "fuel_consumption_per_nm_by_speed": fuel, "route": route, "port_visits": pvs})
    ext = []
    if externals:
        ext = [{"port_id": ports[0], "ships": [
            {"id": 1, "berthing_position": 100.0, "length_meters": 200, "start_time_hours": 0.0,
             "handling_time_hours": 20.0, "end_time_hours": 20.0},
            {"id": 2, "berthing_position": 350.0, "length_meters": 180, "start_time_hours": 5.0,
             "handling_time_hours": 12.0, "end_time_hours": 17.0}]}]
    F, H, D, I, U = costs
    return {"planning_horizon_hours": 300,
            "cost_parameters": {"fuel_price_usd_per_tonne": F, "handling_cost_usd_per_hour": H,
                                "delay_cost_usd_per_hour": D, "waiting_cost_usd_per_hour": I, "lft_penalty_usd": U},
            "handling_time_deviation_factor_beta_per_meter": beta,
            "ports": [{"id": p, "quay_length_meters": quay} for p in ports],
            "distances_nautical_miles": dist, "speeds_knots": list(SPEEDS),
            "travel_time_hours_per_nm_by_speed": {str(s): 1.0 / s for s in SPEEDS},
            "ships": ships, "external_ships": ext}


def brute_single_ship(inst, mode):
    """Optimum of a one-ship instance without other ships: every speed combination, ideal position, earliest start."""
    cp = inst["cost_parameters"]
    I, H, D, U, F = (cp["waiting_cost_usd_per_hour"], cp["handling_cost_usd_per_hour"],
                     cp["delay_cost_usd_per_hour"], cp["lft_penalty_usd"], cp["fuel_price_usd_per_tonne"])
    s = inst["ships"][0]
    pvs = sorted(s["port_visits"], key=lambda p: p["port_call_index"])
    best = None
    for combo in itertools.product(inst["speeds_knots"], repeat=len(pvs) - 1):
        cost, end = 0.0, None
        for c, pv in enumerate(pvs):
            if c == 0:
                y = pv["earliest_start_time_hours"]
                a = y if mode == "desc" else pv["earliest_start_time_hours"]
            else:
                d = inst["distances_nautical_miles"]["%s_%s" % (pvs[c - 1]["port_id"], pv["port_id"])]
                a = end + inst["travel_time_hours_per_nm_by_speed"][str(combo[c - 1])] * d
                y = max(a, pv["earliest_start_time_hours"])
                cost += F * s["fuel_consumption_per_nm_by_speed"][str(combo[c - 1])] * d
            h = pv["min_handling_time_hours"]
            end = y + h
            cost += I * (y - a) + H * h + D * max(0.0, end - pv["expected_finish_time_hours"]) + \
                U * max(0.0, end - pv["latest_finish_time_hours"])
        best = cost if best is None else min(best, cost)
    return best


def overlaps(xl, xr, ys, ye, o):
    return not (xr <= o[2] + 1e-9 or o[3] <= xl + 1e-9 or ye <= o[0] + 1e-9 or o[1] <= ys + 1e-9)


class TestSingleShip(unittest.TestCase):
    def test_plan_matches_brute_force(self):
        for seed in range(8):
            for mode in ("desc", "est"):
                inst = make_instance(n_ships=1, seed=seed, externals=False, calls=4)
                P = S.Problem(inst, mode)
                cost, calls, speeds = P.plan(P.ships[0], {}, K=10000)
                self.assertAlmostEqual(cost, brute_single_ship(inst, mode), places=6, msg=(seed, mode))
                sol = S.build_solution(P, [calls], [speeds])
                v = S.verify(inst, sol)
                self.assertTrue(v["feasible"], v)
                self.assertAlmostEqual(sol["objective_value"], cost, places=6)

    def test_default_labels_still_optimal_on_small(self):
        for seed in range(4):
            inst = make_instance(n_ships=1, seed=seed, externals=False, calls=4)
            sol = S.solve(inst, time_limit=1.0, seed=seed)
            self.assertLessEqual(sol["objective_value"], brute_single_ship(inst, "desc") + 1e-6)


class TestPlacement(unittest.TestCase):
    def test_place_vs_grid(self):
        rng = random.Random(7)
        for trial in range(40):
            inst = make_instance(n_ships=1, seed=trial, externals=False, calls=1)
            P = S.Problem(inst, "est")
            sh = P.ships[0]
            v = sh.visits[0]
            obst = []
            for _ in range(rng.randint(1, 6)):
                x = float(rng.randint(0, 500))
                t = rng.uniform(-5, 30)
                obst.append((t, t + rng.uniform(2, 15), x, x + rng.choice([80, 120, 200]), 99))
            obst.sort()
            a = v.est + rng.uniform(-5, 10)
            cands = P.candidates(sh, v, obst)
            got = P.place(sh, v, a, obst, cands, False)
            cost, x, y, e, h, r = got
            self.assertTrue(0.0 <= x <= v.maxx)
            self.assertGreaterEqual(y, max(a, v.est) - 1e-9)
            for o in obst:
                self.assertFalse(overlaps(x, x + sh.l, y, e, o), (trial, got, o))
            # independent brute force on a 0.25 m grid
            best = None
            t0 = max(a, v.est)
            steps = int(v.maxx / 0.25)
            for k in range(steps + 1):
                xg = k * 0.25
                hg = (1.0 + P.beta * abs(xg - v.x0)) * v.h0
                for yg in sorted([t0] + [o[1] for o in obst if o[1] >= t0]):
                    if not any(overlaps(xg, xg + sh.l, yg, yg + hg, o) for o in obst):
                        break
                eg = yg + hg
                cg = P.H * hg + P.I * (yg - a) + P.D * max(0.0, eg - v.eft) + P.U * max(0.0, eg - v.lft)
                best = cg if best is None else min(best, cg)
            self.assertLessEqual(cost, best + 1e-7, (trial, got))


class TestThin(unittest.TestCase):
    def test_exact_waiting_dominance(self):
        labs = [(10.0, 100.0, "a"), (12.0, 250.0, "b"), (12.0, 90.0, "c"), (15.0, 395.0, "d"), (15.0, 380.0, "e")]
        out = S.thin(list(labs), 99, 100.0)
        # adjusted cost c - 100 t: a -900, c -1110, b -950 (dominated by c), e -1120, d -1105
        self.assertEqual([t[2] for t in out], ["a", "c", "e"])

    def test_cap_keeps_cheapest(self):
        labs = [(float(t), 1000.0 - 50.0 * t + (t % 3), str(t)) for t in range(30)]
        out = S.thin(list(labs), 5, 10.0)
        self.assertLessEqual(len(out), 5)
        self.assertIn(min(labs, key=lambda t: t[1])[2], [t[2] for t in out])


class TestWhole(unittest.TestCase):
    def test_feasible_both_modes(self):
        for seed in range(6):
            inst = make_instance(n_ships=6, seed=seed, spread=4.0)
            for mode in ("desc", "est"):
                log = {}
                sol = S.solve(inst, time_limit=1.0, seed=seed, first_arrival=mode, log=log)
                v = S.verify(inst, sol)
                self.assertTrue(v["feasible"], (seed, mode, v))
                self.assertEqual(sol["objective_value"], v["objective"])
                self.assertAlmostEqual(log["best_internal"], log["objective"],
                                       delta=1e-6 * max(1.0, abs(log["objective"])))
                for s_inst, s_sol in zip(inst["ships"], sol["ships"]):
                    first = min(s_sol["port_visits"], key=lambda p: p["port_call_index"])
                    est = min(s_inst["port_visits"], key=lambda p: p["port_call_index"])["earliest_start_time_hours"]
                    if mode == "est":
                        self.assertEqual(first["arrival_time"], est)
                    else:
                        self.assertEqual(first["arrival_time"], first["start_time"])

    def test_speed_pruning_is_exact(self):
        # (travel h, fuel $, speed); waiting costs 100 $/h
        opts = [(10.0, 500.0, 20.0), (12.0, 400.0, 18.0), (12.0, 450.0, 18.5), (13.0, 390.0, 17.0),
                (11.0, 600.0, 19.0)]
        kept = [o[2] for o in S.pareto_speeds(opts, 100.0)]
        # adjusted fuel - 100*travel: 20 -> -500, 19 -> -500 (not better), 18 -> -800, 18.5 -> -750, 17 -> -910
        self.assertEqual(kept, [20.0, 18.0, 17.0])
        # a slower option that costs more fuel is still kept when waiting is expensive enough
        kept = [o[2] for o in S.pareto_speeds([(10.0, 100.0, 20.0), (12.0, 150.0, 17.0)], 100.0)]
        self.assertEqual(kept, [20.0, 17.0])


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.inst = make_instance(n_ships=4, seed=3, spread=2.0)
        self.sol = S.solve(self.inst, time_limit=1.0, seed=1)
        self.assertTrue(S.verify(self.inst, self.sol)["feasible"])

    def test_overlap_rejected(self):
        bad = json.loads(json.dumps(self.sol))
        a = bad["ships"][0]["port_visits"][0]
        port = a["port_id"]
        other = None
        for s in bad["ships"][1:]:
            for pv in s["port_visits"]:
                if pv["port_id"] == port:
                    other = pv
                    break
            if other:
                break
        if other is None:   # put ship 1's first call on top of the external ship at port A ([100, 300] m, 0-20 h)
            a["berthing_position"] = 100.0
            a["start_time"] = 1.0
        else:
            other["berthing_position"] = a["berthing_position"]
            other["start_time"] = a["start_time"]
        self.assertIn(4, S.verify(self.inst, bad)["violated"])

    def test_objective_and_speed_rejected(self):
        bad = json.loads(json.dumps(self.sol))
        bad["objective_value"] += 1.0
        self.assertIn(18, S.verify(self.inst, bad)["violated"])
        bad = json.loads(json.dumps(self.sol))
        bad["ships"][0]["speed_selections"][0]["speed_knots"] = 19.25
        self.assertIn(16, S.verify(self.inst, bad)["violated"])
        bad = json.loads(json.dumps(self.sol))
        bad["ships"][0]["port_visits"][1]["arrival_time"] += 0.5
        self.assertIn(5, S.verify(self.inst, bad)["violated"])


class TestContestWay(unittest.TestCase):
    def run_cli(self, inst, tl, extra_env=None):
        d = tempfile.mkdtemp()
        ip, op = os.path.join(d, "inst.json"), os.path.join(d, "out.json")
        with open(ip, "w") as f:
            json.dump(inst, f)
        env = dict(os.environ, MV2_BERTH_LOG="1", **(extra_env or {}))
        t0 = time.monotonic()
        p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "martin-iradi2024",
                            "--instance", ip, "--output", op, "--time-limit", str(tl)],
                           capture_output=True, text=True, env=env, timeout=tl + 30)
        wall = time.monotonic() - t0
        return d, ip, op, p, wall

    def test_cli(self):
        inst = make_instance(n_ships=8, seed=11, spread=3.0)
        d, ip, op, p, wall = self.run_cli(inst, 4)
        self.assertEqual(p.returncode, 0, p.stderr[-800:])
        self.assertLess(wall, 4.0)
        with open(op) as f:
            sol = json.load(f)
        self.assertTrue(S.verify(inst, sol)["feasible"])
        self.assertTrue(os.path.exists(op + ".log.json"))

    def test_official_checker(self):
        hf = os.environ.get("MV2_FROC_HF", "")
        chk = os.path.join(hf, "tasks", "martin-iradi2024", "feasibility_check.py")
        if not hf or not os.path.exists(chk):
            self.skipTest("official checker not available (set MV2_FROC_HF)")
        for seed, mode in ((11, "desc"), (12, "est")):
            inst = make_instance(n_ships=8, seed=seed, spread=3.0)
            d, ip, op, p, wall = self.run_cli(inst, 3, {"MV2_BERTH_FIRST_ARRIVAL": mode})
            self.assertEqual(p.returncode, 0, p.stderr[-800:])
            rp = os.path.join(d, "res.json")
            subprocess.run([sys.executable, chk, "--instance_path", ip, "--solution_path", op, "--result_path", rp],
                           capture_output=True, text=True, timeout=120)
            with open(rp) as f:
                res = json.load(f)
            self.assertTrue(res["feasible"], res)
            with open(op) as f:
                sol = json.load(f)
            sol["objective_value"] += 5.0
            with open(op, "w") as f:
                json.dump(sol, f)
            subprocess.run([sys.executable, chk, "--instance_path", ip, "--solution_path", op, "--result_path", rp],
                           capture_output=True, text=True, timeout=120)
            with open(rp) as f:
                self.assertFalse(json.load(f)["feasible"])


if __name__ == "__main__":
    unittest.main()

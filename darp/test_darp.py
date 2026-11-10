"""Tests for the cordeau2006 (DARP) solver and its calibration harness.

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.
"""
import json
import math
import os
import random
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "cordeau2006"))

import darp_eval as E  # noqa: E402
import solve as S  # noqa: E402


def random_valid_seq(rng, users, n):
    """A random order of the given users' pickups and drop-offs with each pickup before its drop-off."""
    seq = []
    waiting = list(users)
    onboard = []
    while waiting or onboard:
        if waiting and (not onboard or rng.random() < 0.5):
            u = waiting.pop(rng.randrange(len(waiting)))
            seq.append(u)
            onboard.append(u)
        else:
            u = onboard.pop(rng.randrange(len(onboard)))
            seq.append(u + n)
    return seq


def brute_best(I, u, seq):
    """Cheapest feasible insertion of user u by trying every (pickup, drop-off) position pair."""
    p, d = I.P[u], I.Dr[u]
    base = I.route_info(seq)[4]
    best = None
    for i in range(len(seq) + 1):
        for j in range(i, len(seq) + 1):
            new = S.insert_seq(seq, p, d, i, j)
            if not I.load_ok(new) or I.schedule(new) is None:
                continue
            delta = I.route_info(new)[4] - base
            if best is None or delta < best:
                best = delta
    return best


class Parse(unittest.TestCase):
    ROWS = ["0 0.0 0.0 0 0 0 100", "1 1.0 0.0 3 1 0 100", "2 2.0 0.0 3 1 20 35",
            "3 3.0 0.0 3 -1 10 25", "4 4.0 0.0 3 -1 0 100"]

    def test_both_header_layouts(self):
        a = E.parse_cordeau("\n".join(["1 4 100 3 30"] + self.ROWS))
        b = E.parse_cordeau("\n".join(["1 2 100 3 30"] + self.ROWS + ["5 0.0 0.0 0 0 0 100"]))
        for inst in (a, b):
            self.assertEqual(inst["num_users"], 2)
            self.assertEqual(inst["num_nodes"], 6)
            self.assertEqual([r["node_type"] for r in inst["nodes"]],
                             ["origin_depot", "pickup", "pickup", "dropoff", "dropoff", "destination_depot"])
            self.assertEqual(inst["nodes"][1]["paired_node"], 3)
            self.assertEqual(inst["nodes"][4]["paired_node"], 2)
            self.assertEqual(inst["nodes"][1]["request_type"], "outbound")
            self.assertEqual(inst["nodes"][2]["request_type"], "inbound")
            self.assertEqual(inst["maximum_route_duration"], 100.0)
        self.assertEqual(a["nodes"], b["nodes"])

    def test_bad_row_count(self):
        with self.assertRaises(ValueError):
            E.parse_cordeau("\n".join(["1 3 100 3 30"] + self.ROWS))


class Timing(unittest.TestCase):
    def test_schedule_agrees_with_bellman_ford(self):
        rng = random.Random(7)
        agree = feasible = 0
        for seed in range(30):
            inst = E.random_instance(100 + seed, 4, m=2, horizon=150.0)
            I = S.Darp(inst)
            for _ in range(12):
                users = rng.sample(range(1, 5), rng.randint(1, 4))
                seq = random_valid_seq(rng, users, 4)
                mine = I.schedule(seq) is not None
                ref = E.route_feasible(inst, seq)
                self.assertEqual(mine, ref, "seed %d seq %s" % (seed, seq))
                agree += 1
                feasible += ref
        self.assertGreater(feasible, 10)
        self.assertLess(feasible, agree)

    def test_written_schedule_passes_checker(self):
        done = 0
        for seed in range(12):
            inst = E.random_instance(200 + seed, 4, m=2, horizon=200.0)
            I = S.Darp(inst)
            routes, cost, bank, _ = S.Search(I, seed, time.time() + 0.3).run()
            if bank:
                continue
            for seq in routes:
                self.assertIsNotNone(I.schedule(seq))
            sol, used = S.build_output(I, routes)
            self.assertGreaterEqual(used, 1)
            ok, why, obj = E.check(inst, sol)
            self.assertTrue(ok, why)
            self.assertAlmostEqual(obj, cost, places=6)
            done += 1
        self.assertGreater(done, 0)

    def test_ride_time_limit_is_enforced(self):
        inst = E.random_instance(1, 2, m=1, horizon=500.0)
        for r in inst["nodes"]:
            r["earliest_time"], r["latest_time"] = 0.0, 500.0
            if r["node_type"] != "origin_depot" and r["node_type"] != "destination_depot":
                r["x"], r["y"] = 0.0, 0.0
        # user 1 at the origin, user 2 far away: carrying user 1 to user 2's stops breaks the 30-minute limit
        inst["nodes"][2].update({"x": 20.0, "y": 0.0})
        inst["nodes"][4].update({"x": 20.0, "y": 0.0})
        I = S.Darp(inst)
        self.assertIsNone(I.schedule([1, 2, 4, 3]))
        self.assertFalse(E.route_feasible(inst, [1, 2, 4, 3]))
        self.assertIsNotNone(I.schedule([1, 3, 2, 4]))

    def test_duration_limit_is_enforced(self):
        inst = E.random_instance(5, 2, m=1, horizon=500.0)
        for r in inst["nodes"]:
            r["earliest_time"], r["latest_time"] = 0.0, 500.0
        inst["maximum_route_duration"] = 1.0
        I = S.Darp(inst)
        self.assertIsNone(I.schedule([1, 3]))
        self.assertFalse(E.route_feasible(inst, [1, 3]))


class Insertion(unittest.TestCase):
    def test_best_insert_is_feasible_and_priced_right(self):
        rng = random.Random(11)
        checked = 0
        for seed in range(25):
            inst = E.random_instance(300 + seed, 4, m=2, horizon=200.0)
            I = S.Darp(inst)
            seq = random_valid_seq(rng, [1, 2], 4)
            if I.schedule(seq) is None:
                continue
            info = I.route_info(seq)
            for u in (2, 3):  # user index (0-based) of users 3 and 4
                res = I.best_insert(u, info)
                if res is None:
                    continue
                delta, i, j = res
                new = S.insert_seq(seq, I.P[u], I.Dr[u], i, j)
                self.assertIsNotNone(I.schedule(new))
                self.assertTrue(I.load_ok(new))
                self.assertAlmostEqual(I.route_info(new)[4] - info[4], delta, places=9)
                checked += 1
        self.assertGreater(checked, 2)

    def test_best_insert_matches_brute_force(self):
        """With every candidate checked, best_insert must find exactly the cheapest feasible insertion.

        This is the test v0.1.0 lacked: its adjacent-insertion pruning rejected feasible positions."""
        rng = random.Random(23)
        compared = found = 0
        for seed in range(40):
            inst = E.random_instance(400 + seed, 4, m=2, horizon=200.0)
            I = S.Darp(inst)
            users = rng.sample([1, 2, 3, 4], rng.randint(0, 2))
            seq = random_valid_seq(rng, users, 4)
            if seq and (I.schedule(seq) is None or not I.load_ok(seq)):
                continue
            info = I.route_info(seq)
            for u in range(4):
                if (u + 1) in users:
                    continue
                res = I.best_insert(u, info, None)
                bf = brute_best(I, u, seq)
                self.assertEqual(res is None, bf is None, "seed %d user %d seq %s: %s vs %s" % (
                    400 + seed, u, seq, res, bf))
                if bf is not None:
                    self.assertAlmostEqual(res[0], bf, places=7)
                    found += 1
                compared += 1
        self.assertGreater(compared, 40)
        self.assertGreater(found, 10)

    def test_outbound_user_opens_an_empty_route(self):
        """The v0.1.0 bug: an outbound user whose drop-off window opens late could not be inserted next to its own
        pickup, because the ride time was measured from the earliest pickup start (no waiting)."""
        inst = E.random_instance(1, 2, m=1, horizon=200.0)
        inst["nodes"][1].update({"x": 1.0, "y": 0.0, "earliest_time": 0.0, "latest_time": 200.0})
        inst["nodes"][3].update({"x": 2.0, "y": 0.0, "earliest_time": 60.0, "latest_time": 75.0})
        I = S.Darp(inst)
        self.assertIsNotNone(I.schedule([1, 3]))
        res = I.best_insert(0, I.route_info([]))
        self.assertIsNotNone(res)
        self.assertEqual(res[1:], (0, 0))
        B = I.schedule([1, 3])
        self.assertLessEqual(B[2] - (B[1] + 3.0), 30.0)  # the written schedule waits before the pickup


class Harness(unittest.TestCase):
    def test_heartbeat_sees_a_long_gap(self):
        with E.Heartbeat(tick=0.05) as hb:
            time.sleep(0.3)
        self.assertGreater(hb.max_gap, 0.0)
        self.assertLess(hb.max_gap, E.PAUSE_GAP_S)


class EndToEnd(unittest.TestCase):
    def test_cli_tiny_is_optimal_and_checked(self):
        hits = 0
        for seed in (2, 8):
            n = 3 if seed <= 6 else 4
            inst = E.random_instance(seed, n)
            opt = E.exact(inst)
            r = E.solve_and_check(inst, 4)
            if math.isinf(opt):
                self.assertFalse(r.get("feasible"))
                continue
            self.assertTrue(r.get("feasible"), r)
            self.assertLessEqual(r["objective"], opt + 1e-6)
            self.assertAlmostEqual(r["objective"], opt, places=6)
            hits += 1
        self.assertGreater(hits, 0)

    def test_output_keys(self):
        inst = E.random_instance(4, 3)
        with tempfile.TemporaryDirectory() as td:
            ip, op = os.path.join(td, "i.json"), os.path.join(td, "o.json")
            with open(ip, "w") as f:
                json.dump(inst, f)
            S.main(["--instance", ip, "--output", op, "--time-limit", "3", "--workers", "1"])
            with open(op) as f:
                sol = json.load(f)
        self.assertEqual(set(sol), {"objective_value", "routes", "service_times", "ride_times"})
        for k, rt in sol["routes"].items():
            self.assertEqual(rt[0], 0)
            self.assertEqual(rt[-1], 2 * 3 + 1)
            self.assertIn("depot_start_%s" % k, sol["service_times"])
            self.assertIn("depot_end_%s" % k, sol["service_times"])


if __name__ == "__main__":
    unittest.main()

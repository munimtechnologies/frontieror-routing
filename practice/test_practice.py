"""Offline tests for practice_real.py and the v0.3.0 / v3 output fixes. MV2 of Munim, Inc. Apache-2.0.
Made with AI agents working in MV2's name. No network: nothing here downloads anything."""
import importlib.util
import math
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DARP = load(os.path.join("postfix", "cordeau2006", "solve.py"), "t_darp_wrapper")
NAGY = load(os.path.join("postfix", "nagy2015", "solve.py"), "t_nagy_wrapper")
PR = load("practice_real.py", "t_practice_real")
if "frontier_runtime" not in sys.modules:  # spp solve.py imports it at load time; only load() is tested here
    sys.modules["frontier_runtime"] = types.ModuleType("frontier_runtime")
SPP = load(os.path.join("spp", "hoffman1993", "solve.py"), "t_spp_solve")


def darp_instance(K=3):
    # 2 users; pickups 1, 2; drop-offs 3, 4; depots 0 and 5 at the origin. user_id deliberately 0-based.
    pts = {0: (0, 0), 1: (1, 0), 2: (0, 2), 3: (3, 0), 4: (0, 5), 5: (0, 0)}
    types_ = {0: "origin_depot", 1: "pickup", 2: "pickup", 3: "dropoff", 4: "dropoff", 5: "destination_depot"}
    nodes = []
    for i in range(6):
        r = {"node_id": i, "x": pts[i][0], "y": pts[i][1], "earliest_time": 0.0, "latest_time": 1000.0,
             "service_duration": 1.0 if 1 <= i <= 4 else 0.0, "load": {1: 1, 2: 1, 3: -1, 4: -1}.get(i, 0),
             "node_type": types_[i]}
        if 1 <= i <= 4:
            r.update(user_id=(i - 1) % 2, paired_node=i + 2 if i <= 2 else i - 2)
        nodes.append(r)
    return {"num_vehicles": K, "num_users": 2, "vehicle_capacity": 3, "maximum_ride_time": 100,
            "num_nodes": 6, "nodes": nodes, "maximum_route_duration": 500}


def darp_v2_solution():
    # one vehicle serves both users: 0 -> 1 -> 3 -> 2 -> 4 -> 5, as v0.2.0 writes it (only used routes, user_id keys)
    st = {"depot_start_0": 0.0, "1": 1.0, "3": 4.0, "2": 5.0 + math.sqrt(13), "4": 9.0 + math.sqrt(13),
          "depot_end_0": 10.0 + math.sqrt(13) + 5.0}
    return {"objective_value": 0.0, "routes": {"0": [0, 1, 3, 2, 4, 5]}, "service_times": st,
            "ride_times": {"0": 2.0, "1": 3.0}}


class TestDarpWrapper(unittest.TestCase):
    def test_every_vehicle_listed_and_keys(self):
        inst = darp_instance(3)
        out = DARP.normalise(inst, darp_v2_solution())
        self.assertEqual(sorted(out["routes"]), ["0", "1", "2"])
        self.assertEqual(out["routes"]["1"], [0, 5])
        self.assertEqual(out["routes"]["2"], [0, 5])
        for k in ("0", "1", "2"):
            self.assertIn("depot_start_" + k, out["service_times"])
            self.assertIn("depot_end_" + k, out["service_times"])
        self.assertEqual(sorted(out["ride_times"]), ["1", "2"])  # pickup node ids, not user_id 0/1
        st = out["service_times"]
        self.assertAlmostEqual(out["ride_times"]["1"], st["3"] - (st["1"] + 1.0))
        self.assertAlmostEqual(out["ride_times"]["2"], st["4"] - (st["2"] + 1.0))

    def test_objective_counts_every_arc(self):
        inst = darp_instance(2)
        out = DARP.normalise(inst, darp_v2_solution())
        want = 1 + 2 + math.sqrt(13) + 3 + 5  # 0-1, 1-3, 3-2, 2-4, 4-5; the empty route 0-5 has length 0
        self.assertAlmostEqual(out["objective_value"], want, places=9)

    def test_empty_schedule_respects_duration(self):
        inst = darp_instance(1)
        inst["nodes"][5]["earliest_time"] = 800.0  # destination opens late; the limit is 500
        s, e = DARP.empty_schedule(inst, {int(r["node_id"]): r for r in inst["nodes"]})
        self.assertLessEqual(e - s, 500 + 1e-9)
        self.assertGreaterEqual(e, 800.0)

    def test_renumbers_sparse_keys(self):
        inst = darp_instance(3)
        sol = darp_v2_solution()
        sol["routes"] = {"2": sol["routes"].pop("0")}
        st = sol["service_times"]
        st["depot_start_2"], st["depot_end_2"] = st.pop("depot_start_0"), st.pop("depot_end_0")
        out = DARP.normalise(inst, sol)
        self.assertEqual(out["routes"]["0"], [0, 1, 3, 2, 4, 5])
        self.assertEqual(out["service_times"]["depot_start_0"], 0.0)


def nagy_instance():
    # 2 customers; node 1 = linehaul of customer 1, node 3 = its backhaul (n + 1)
    return {"num_customers": 2, "vehicle_capacity": 10,
            "customers": [{"id": 1, "delivery_demand": 4, "pickup_demand": 5},
                          {"id": 2, "delivery_demand": 3, "pickup_demand": 2}],
            "distance_matrix": [[0, 5, 7], [5, 0, 4], [7, 4, 0]]}


class TestNagyWrapper(unittest.TestCase):
    def test_swaps_backhaul_then_linehaul(self):
        inst = nagy_instance()
        det = [[{"node": v} for v in (0, 3, 1, 2, 4, 0)]]
        sol = {"objective_value": 16.0, "routes": [[0, 3, 1, 2, 4, 0]], "routes_detailed": det}
        out, swaps = NAGY.normalise(inst, sol)
        self.assertEqual(swaps, 1)
        self.assertEqual(out["routes"], [[0, 1, 3, 2, 4, 0]])
        self.assertEqual([d["node"] for d in out["routes_detailed"][0]], [0, 1, 3, 2, 4, 0])
        self.assertEqual(out["objective_value"], 5 + 0 + 4 + 0 + 7)

    def test_leaves_good_routes_alone(self):
        inst = nagy_instance()
        sol = {"objective_value": 24.0, "routes": [[0, 1, 3, 0], [0, 2, 4, 0]], "routes_detailed": None}
        out, swaps = NAGY.normalise(inst, sol)
        self.assertEqual(swaps, 0)
        self.assertEqual(out["routes"], [[0, 1, 3, 0], [0, 2, 4, 0]])
        self.assertEqual(out["objective_value"], 5 + 0 + 5 + 7 + 0 + 7)
        self.assertEqual(len(out["routes_detailed"]), 2)
        self.assertEqual(out["routes_detailed"][0][1]["role"], "linehaul")

    def test_route_with_only_the_pair(self):
        inst = nagy_instance()
        sol = {"objective_value": 14.0, "routes": [[0, 4, 2, 0]], "routes_detailed": []}
        out, swaps = NAGY.normalise(inst, sol)
        self.assertEqual(swaps, 1)
        self.assertEqual(out["routes"], [[0, 2, 4, 0]])
        self.assertEqual(out["objective_value"], 14.0)


def spp_instance():
    # 3 legs; columns list is longer than num_cols and holds a stale index 7 >= num_rows
    return {"dimensions": {"num_rows": 3, "num_cols": 4}, "cost_vector": [3, 4, 2, 5],
            "constraint_matrix_A": {"columns": [[0, 1], [2, 7], [0], [1, 2], [0, 1, 2]]},
            "has_base_constraints": False}


class TestSppV030(unittest.TestCase):
    def test_load_mirrors_official_reading(self):
        P = SPP.load(spp_instance())
        self.assertEqual(P["n"], 4)
        self.assertEqual(P["cols"], [[0, 1], [2], [0], [1, 2]])
        self.assertEqual(P["extra_columns_ignored"], 1)
        self.assertEqual(P["row_indices_ignored"], 1)
        self.assertTrue(SPP.check(P, [0, 1]))
        self.assertFalse(SPP.check(P, [0, 3]))

    def test_short_cost_and_columns(self):
        inst = {"dimensions": {"num_rows": 1, "num_cols": 3}, "cost_vector": [1, 2],
                "constraint_matrix_A": {"columns": [[0], [0]]}}
        P = SPP.load(inst)
        self.assertEqual(P["cost"], [1.0, 2.0, 0.0])
        self.assertEqual(P["cols"], [[0], [0], []])
        self.assertEqual(P["short_columns"], 1)

    def test_solution_format(self):
        P = SPP.load(spp_instance())
        obj, sol = SPP.solution(P, [1, 0])
        self.assertEqual(obj, 7.0)
        self.assertEqual(sol["selected_rotations"], [0, 1])
        self.assertEqual(sol["variable_values"], {"0": 1.0, "1": 1.0, "2": 0.0, "3": 0.0})
        r = PR.spp_check(spp_instance(), sol)
        self.assertTrue(r["feasible"], r)
        self.assertEqual(r["objective"], 7.0)


class TestSppCheck(unittest.TestCase):
    def test_rejects_double_cover(self):
        sol = {"objective_value": 8.0, "selected_rotations": [0, 3],
               "variable_values": {"0": 1.0, "1": 0.0, "2": 0.0, "3": 1.0}}
        self.assertFalse(PR.spp_check(spp_instance(), sol)["feasible"])

    def test_rejects_out_of_range_rotation(self):
        sol = {"objective_value": 7.0, "selected_rotations": [0, 1, 4],
               "variable_values": {"0": 1.0, "1": 1.0}}
        self.assertFalse(PR.spp_check(spp_instance(), sol)["feasible"])

    def test_missing_field(self):
        self.assertFalse(PR.spp_check(spp_instance(), {"objective_value": 1.0})["feasible"])


class FakeH:
    @staticmethod
    def contest_score(obj, ref, sense):
        if sense == "min":
            return min(2.0, ref / obj)
        return min(2.0, obj / ref)


class TestOfficialScore(unittest.TestCase):
    def test_only_official_accepts_count(self):
        row = {"official_feasible": True, "status": "infeasible", "stated": 110.0, "reference": 100.0}
        self.assertAlmostEqual(PR.official_score(row, "min", FakeH), 100.0 / 110.0, places=6)
        row["official_feasible"] = False
        self.assertEqual(PR.official_score(row, "min", FakeH), 0.0)
        row.update(official_feasible=True, status="overtime")
        self.assertEqual(PR.official_score(row, "min", FakeH), 0.0)

    def test_max_sense(self):
        row = {"official_feasible": True, "status": "ok", "stated": 90.0, "reference": 100.0}
        self.assertAlmostEqual(PR.official_score(row, "max", FakeH), 0.9, places=6)


class TestVariants(unittest.TestCase):
    def test_variant_table(self):
        names = [v[0] for v in PR.VARIANTS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual({v[1] for v in PR.VARIANTS}, {"hoffman1993", "cordeau2006", "nagy2015", "fischetti1998"})


if __name__ == "__main__":
    unittest.main()

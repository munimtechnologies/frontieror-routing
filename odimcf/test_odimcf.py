"""Tests for the barnhart2000 (ODIMCF) solver, checker, generator and exact references.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Needs numpy and scipy for the MIP, LP and solver tests.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOLVER_DIR = os.path.join(HERE, "barnhart2000")
KIT = os.path.join(ROOT, "kit")
for p in (KIT, HERE, SOLVER_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import frontier_runtime as R  # noqa: E402
import odimcf_check as C  # noqa: E402
import odimcf_exact as E  # noqa: E402
import odimcf_gen as G  # noqa: E402
import solve as S  # noqa: E402


def hand_instance():
    return {"network": {"num_nodes": 3, "num_arcs": 3, "nodes": [1, 2, 3], "arcs": [
        {"arc_id": 10, "from_node": 1, "to_node": 2, "capacity": 5, "cost": 1},
        {"arc_id": 11, "from_node": 2, "to_node": 3, "capacity": 5, "cost": 0},
        {"arc_id": 12, "from_node": 1, "to_node": 3, "capacity": 3, "cost": 2}]},
        "commodities": {"num_commodities": 2, "commodity_list": [
            {"commodity_id": 1, "origin": 1, "destination": 3, "demand": 4, "revenue": 40,
             "artificial_arc_cost": 10},
            {"commodity_id": 2, "origin": 1, "destination": 2, "demand": 2, "revenue": 10,
             "artificial_arc_cost": 5}]},
        "objective": "minimize"}


def arc(i, a, b):
    return {"from": a, "to": b, "arc_id": i}


def sol(c1, c2):
    out = []
    for cid, p in ((1, c1), (2, c2)):
        out.append({"commodity_id": cid, "rejected": p is None, "path_arcs": p or []})
    return {"objective_value": 0.0, "commodities": out}


class Checker(unittest.TestCase):
    def test_feasible_and_objective(self):
        r = C.check(hand_instance(), sol([arc(10, 1, 2), arc(11, 2, 3)], None))
        self.assertTrue(r["feasible"], r)
        self.assertEqual(r["mode"], "per_unit")
        self.assertAlmostEqual(r["objective"], 4 * 1 + 2 * 5)
        r = C.check(hand_instance(), sol(None, [arc(10, 1, 2)]))
        self.assertTrue(r["feasible"])
        self.assertAlmostEqual(r["objective"], 40 + 2)

    def test_violations(self):
        inst = hand_instance()
        bad = [
            sol([arc(10, 1, 2), arc(11, 2, 3)], [arc(10, 1, 2)]),  # arc 10 load 6 > 5
            sol([arc(12, 1, 3)], None),  # demand 4 > capacity 3
            sol([arc(11, 2, 3)], None),  # does not start at the origin
            sol([arc(10, 1, 2)], None),  # ends at 2, not 3
            sol([arc(10, 1, 3)], None),  # from/to do not match arc 10
            sol([arc(99, 1, 3)], None),  # unknown arc
        ]
        for s in bad:
            self.assertFalse(C.check(inst, s)["feasible"], s)
        s = sol(None, None)
        s["commodities"].pop()
        self.assertFalse(C.check(inst, s)["feasible"])
        s = sol(None, None)
        s["commodities"].append(dict(s["commodities"][0]))
        self.assertFalse(C.check(inst, s)["feasible"])
        s = sol(None, None)
        s["commodities"][0]["path_arcs"] = [arc(12, 1, 3)]
        self.assertFalse(C.check(inst, s)["feasible"])

    def test_revisit_rejected(self):
        inst = hand_instance()
        inst["network"]["arcs"] += [{"arc_id": 13, "from_node": 2, "to_node": 1, "capacity": 9, "cost": 0}]
        s = sol([arc(10, 1, 2), arc(13, 2, 1), arc(12, 1, 3)], None)
        self.assertFalse(C.check(inst, s)["feasible"])

    def test_penalty_modes(self):
        self.assertEqual(C.penalty({"artificial_arc_cost": 10, "demand": 4}, "total"), 10.0)
        self.assertEqual(C.penalty({"artificial_arc_cost": 10, "demand": 4}, "per_unit"), 40.0)
        tot = [{"artificial_arc_cost": 40, "revenue": 40, "demand": 4}]
        per = [{"artificial_arc_cost": 10, "revenue": 40, "demand": 4}]
        odd = [{"artificial_arc_cost": 7, "revenue": 40, "demand": 4}]
        self.assertEqual(C.penalty_mode(tot), "total")
        self.assertEqual(C.penalty_mode(per), "per_unit")
        self.assertEqual(C.penalty_mode(odd), "per_unit")
        for seed in range(10):
            coms = G.tiny(seed)["commodities"]["commodity_list"]
            self.assertEqual(S.penalty_mode(coms), C.penalty_mode(coms))
        for row in G.CASES[:6]:
            coms = G.case_instance(row)["commodities"]["commodity_list"]
            self.assertEqual(C.penalty_mode(coms), row[5])
            self.assertEqual(S.penalty_mode(coms), row[5])


class Generator(unittest.TestCase):
    def test_deterministic_and_well_formed(self):
        for row in G.CASES:
            a = json.dumps(G.case_instance(row), sort_keys=True)
            b = json.dumps(G.case_instance(row), sort_keys=True)
            self.assertEqual(a, b, row[0])
            inst = json.loads(a)
            nodes = set(inst["network"]["nodes"])
            arcs = inst["network"]["arcs"]
            self.assertEqual(len(arcs), inst["network"]["num_arcs"])
            self.assertEqual(len({x["arc_id"] for x in arcs}), len(arcs))
            for x in arcs:
                self.assertIn(x["from_node"], nodes)
                self.assertIn(x["to_node"], nodes)
                self.assertGreaterEqual(x["capacity"], 10)
            coms = inst["commodities"]["commodity_list"]
            self.assertEqual(len(coms), inst["commodities"]["num_commodities"])
            self.assertEqual(len({c["commodity_id"] for c in coms}), len(coms))
            for c in coms:
                self.assertNotEqual(c["origin"], c["destination"])
        self.assertEqual(len(G.CASES), 20)


class Exact(unittest.TestCase):
    def test_extract_path_cuts_cycles(self):
        a12 = {"arc_id": 1, "from_node": 1, "to_node": 2}
        a24 = {"arc_id": 2, "from_node": 2, "to_node": 4}
        a42 = {"arc_id": 3, "from_node": 4, "to_node": 2}
        a23 = {"arc_id": 4, "from_node": 2, "to_node": 3}
        p = E.extract_path(1, 3, [a12, a24, a42, a23])
        self.assertEqual([x["arc_id"] for x in p], [1, 4])

    def test_brute_force_equals_arc_mip(self):
        for seed in range(8):
            inst = G.tiny(seed)
            bf = E.brute_force(inst)
            self.assertTrue(C.check(inst, bf)["feasible"])
            mip = E.arc_mip(inst, 30)
            self.assertTrue(mip["proven"], (seed, mip["status"]))
            self.assertAlmostEqual(mip["objective"], bf["objective_value"], places=6, msg=str(seed))
            self.assertAlmostEqual(C.check(inst, bf)["objective"], bf["objective_value"], places=6)


def run_inprocess(inst, limit=2.0):
    d = tempfile.mkdtemp()
    try:
        clock = R.Clock(limit, margin=0.5, start=time.monotonic())
        inc = R.Incumbent(os.path.join(d, "o.json"), "min")
        S.solve(copy.deepcopy(inst), clock, inc, types.SimpleNamespace(seed=0))
        return inc.value, inc.solution
    finally:
        shutil.rmtree(d, ignore_errors=True)


class Solver(unittest.TestCase):
    def test_state_undo(self):
        m = S.Model(hand_instance())
        st = S.State(m)
        obj0, res0 = st.obj, list(st.res)
        mark = st.mark()
        st.add(0, (0, 1))
        self.assertAlmostEqual(st.obj, obj0 - 40 + 4)
        st.remove(0)
        st.add(1, (0,))
        st.undo(mark)
        self.assertAlmostEqual(st.obj, obj0)
        self.assertEqual(st.res, res0)
        self.assertEqual(st.route, [None, None])

    def test_tiny_against_brute_force(self):
        at_opt = 0
        for seed in range(8):
            inst = G.tiny(seed)
            bf = E.brute_force(inst)["objective_value"]
            val, s = run_inprocess(inst)
            chk = C.check(inst, s)
            self.assertTrue(chk["feasible"], (seed, chk))
            self.assertAlmostEqual(chk["objective"], s["objective_value"], places=6)
            self.assertGreaterEqual(val, bf - 1e-6)
            self.assertLessEqual(val, S.greedy_best(inst) + 1e-6)
            if abs(val - bf) <= 1e-6:
                at_opt += 1
        self.assertGreaterEqual(at_opt, 6)

    def test_bound_is_valid(self):
        for seed in range(8):
            inst = G.tiny(seed)
            bf = E.brute_force(inst)["objective_value"]
            lb = S.lagrangian_bound(inst, 1.0)
            self.assertLessEqual(lb["lb"], bf + 1e-6, seed)
            if lb["converged"]:
                self.assertLessEqual(lb["lp"], bf + 1e-6, seed)

    def test_uncongested_is_zero_and_proved(self):
        inst = G.generate(5, "grid", (5, 5), 40, "per_unit", False, 100.0)
        t0 = time.monotonic()
        val, s = run_inprocess(inst, limit=8.0)
        self.assertEqual(val, 0.0)
        self.assertTrue(C.check(inst, s)["feasible"])
        self.assertLess(time.monotonic() - t0, 7.5)

    def test_small_case_beats_or_ties_greedy(self):
        inst = G.case_instance(G.CASES[0])
        val, s = run_inprocess(inst, limit=4.0)
        chk = C.check(inst, s)
        self.assertTrue(chk["feasible"], chk)
        self.assertLessEqual(val, S.greedy_best(inst) + 1e-6)

    def test_cli_contest_style(self):
        with tempfile.TemporaryDirectory() as d:
            sd = os.path.join(d, "s")
            os.makedirs(sd)
            shutil.copy(os.path.join(SOLVER_DIR, "solve.py"), sd)
            rt = os.path.join(SOLVER_DIR, "frontier_runtime.py")
            shutil.copy(rt if os.path.exists(rt) else os.path.join(KIT, "frontier_runtime.py"), sd)
            inst = G.case_instance(G.CASES[1])
            ip, op = os.path.join(d, "in.json"), os.path.join(d, "out.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            t0 = time.monotonic()
            p = subprocess.run([sys.executable, "solve.py", "--problem", "barnhart2000", "--instance", ip,
                                "--output", op, "--time-limit", "5"], cwd=sd, capture_output=True, text=True,
                               timeout=20)
            wall = time.monotonic() - t0
            self.assertEqual(p.returncode, 0, p.stderr[-1500:])
            self.assertLess(wall, 5.0)
            with open(op, encoding="utf-8") as f:
                s = json.load(f)
            chk = C.check(inst, s)
            self.assertTrue(chk["feasible"], chk)
            self.assertAlmostEqual(chk["objective"], s["objective_value"], places=6)


if __name__ == "__main__":
    unittest.main()

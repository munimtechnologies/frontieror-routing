"""Tests for MV2's borndorfer2007 (line planning) solver. MV2 of Munim, Inc. Made with AI agents. Apache-2.0.

  python -m unittest -v test_borndorfer2007
Optional: BORN_OFFICIAL=<path to the task's feasibility_check.py> runs the official checker on every output and
mutation; MV2_FROC_HF=<hf dir> adds the real tiny instance.
"""
import copy
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("mv2_borndorfer2007_solve", os.path.join(HERE, "solve.py"))
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)
OFFICIAL = os.environ.get("BORN_OFFICIAL")
HF = os.environ.get("MV2_FROC_HF")


def official(inst, sol):
    """Official verdict (True/False) or None when the checker is not available."""
    if not OFFICIAL or not os.path.exists(OFFICIAL):
        return None
    with tempfile.TemporaryDirectory() as d:
        ip, sp, rp = (os.path.join(d, n) for n in ("i.json", "s.json", "r.json"))
        with open(ip, "w") as f:
            json.dump(inst, f)
        with open(sp, "w") as f:
            json.dump(sol, f)
        subprocess.run([sys.executable, OFFICIAL, "--instance_path", ip, "--solution_path", sp, "--result_path", rp],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        with open(rp) as f:
            return bool(json.load(f).get("feasible"))


def make(nodes, edges, modes, od, lam=0.5, L=None, F=None):
    """edges: (u, v, time, edge_capacity, operating_cost); modes: (name, kappa, fixed, terminals, edge ids)."""
    E = [{"id": i, "endpoints": [u, v], "traveling_time_seconds": float(t), "edge_capacity": float(c),
          "operating_cost": float(oc), "length_km": 1.0} for i, (u, v, t, c, oc) in enumerate(edges)]
    M = [{"name": nm, "vehicle_capacity": k, "speed_kmh": 30.0, "fixed_cost_per_line": float(C),
          "operating_cost_per_edge": 1.0, "terminals": list(T), "edge_indices": list(el), "num_edges": len(el),
          "num_terminals": len(T)} for nm, k, C, T, el in modes]
    return {"global_parameters": {"lambda": lam, "fixed_cost_per_line": 0.0, "operating_cost_per_edge": 0.0,
                                  "max_line_length_edges": L if L is not None else len(edges) + 1,
                                  "frequency_upper_bound_F": F if F is not None else max(e[3] for e in edges),
                                  "traveling_times_unit": "seconds", "coordinates_unit": "km"},
            "network": {"num_nodes": nodes, "num_edges": len(E), "num_od_nodes": nodes, "area_km": 10.0,
                        "nodes": [{"id": i, "x": float(i), "y": 0.0, "is_od_node": True} for i in range(nodes)],
                        "edges": E},
            "modes": M,
            "od_matrix": [{"origin": o, "destination": d, "demand": q} for o, d, q in od],
            "od_summary": {"num_od_pairs": len(od), "total_demand": sum(q for _, _, q in od), "num_od_nodes": nodes}}


def grid(rows, cols, seed, lam=0.5, pairs=20):
    rng = random.Random(seed)
    idx = lambda r, c: r * cols + c  # noqa: E731
    edges, hor, ver = [], [], []
    for r in range(rows):
        for c in range(cols - 1):
            hor.append(len(edges))
            edges.append((idx(r, c), idx(r, c + 1), rng.randint(60, 180), rng.randint(4, 12), rng.randint(1, 5)))
    for r in range(rows - 1):
        for c in range(cols):
            ver.append(len(edges))
            edges.append((idx(r, c), idx(r + 1, c), rng.randint(60, 180), rng.randint(4, 12), rng.randint(1, 5)))
    bus_T = [idx(r, 0) for r in range(rows)] + [idx(r, cols - 1) for r in range(rows)]
    tram_T = [idx(0, c) for c in range(cols)] + [idx(rows - 1, c) for c in range(cols)]
    modes = [("bus", 40, rng.randint(50, 400), bus_T, hor), ("tram", 90, rng.randint(100, 800), tram_T, ver)]
    n = rows * cols
    od, seen = [], set()
    while len(od) < pairs:
        o, d = rng.randrange(n), rng.randrange(n)
        if o != d and (o, d) not in seen:
            seen.add((o, d))
            od.append((o, d, rng.randint(1, 30)))
    return make(n, edges, modes, od, lam=lam, L=max(rows, cols))


def run(inst, tl=2.0, seed=1):
    sol, log = S.solve(inst, None, tl, seed=seed, workers=1, t0=time.monotonic())
    return sol, log


class TestExact(unittest.TestCase):
    def test_chain_one_line(self):
        # 0-1-2-3, terminals 0 and 3: the only line is 0-1-2-3; need 10 / kappa 5 = frequency 2
        inst = make(4, [(0, 1, 10, 10, 1), (1, 2, 20, 10, 2), (2, 3, 30, 10, 3)],
                    [("bus", 5, 100, [0, 3], [0, 1, 2])], [(0, 3, 10), (3, 0, 5)], lam=0.5)
        sol, log = run(inst)
        v = S.verify(inst, sol)
        self.assertTrue(v["feasible"], v["reason"])
        self.assertAlmostEqual(v["objective"], 0.5 * (100 + 2 * 6) + 0.5 * (15 * 60), places=6)
        self.assertEqual(len(sol["active_lines"]), 1)
        self.assertNotEqual(official(inst, sol), False)

    def test_split_by_edge_capacity(self):
        # two routes 0-1-3 (time 20) and 0-2-3 (time 30); frequency cap 6 per edge, kappa 1, demand 10
        inst = make(4, [(0, 1, 10, 6, 1), (1, 3, 10, 6, 1), (0, 2, 15, 6, 1), (2, 3, 15, 6, 1)],
                    [("bus", 1, 1, [0, 3], [0, 1, 2, 3])], [(0, 3, 10)], lam=0.5)
        sol, log = run(inst)
        v = S.verify(inst, sol)
        self.assertTrue(v["feasible"], v["reason"])
        self.assertAlmostEqual(v["objective"], 0.5 * (2 + 6 * 2 + 4 * 2) + 0.5 * (6 * 20 + 4 * 30), places=6)
        self.assertNotEqual(official(inst, sol), False)

    def test_edge_without_valid_line_is_avoided(self):
        # shortcut 1-3 belongs to a mode with a single terminal: no line can use it, so no passenger may
        inst = make(5, [(0, 1, 10, 9, 1), (1, 2, 10, 9, 1), (2, 3, 10, 9, 1), (3, 4, 10, 9, 1), (1, 3, 1, 9, 1)],
                    [("bus", 10, 5, [0, 4], [0, 1, 2, 3]), ("tram", 10, 5, [1], [4])], [(0, 4, 7)], lam=0.3)
        sol, log = run(inst)
        v = S.verify(inst, sol)
        self.assertTrue(v["feasible"], v["reason"])
        for ap in sol["active_passenger_paths"]:
            self.assertFalse({8, 9} & set(ap["arcs"]))
        self.assertNotEqual(official(inst, sol), False)

    def test_max_length_respected(self):
        # 0-1-2-3-4 with terminals 0, 2, 4 and max 2 edges: lines 0-1-2 and 2-3-4, never 0-...-4
        inst = make(5, [(0, 1, 10, 9, 1), (1, 2, 10, 9, 1), (2, 3, 10, 9, 1), (3, 4, 10, 9, 1)],
                    [("bus", 10, 50, [0, 2, 4], [0, 1, 2, 3])], [(0, 4, 20)], lam=0.5, L=2)
        sol, log = run(inst)
        v = S.verify(inst, sol)
        self.assertTrue(v["feasible"], v["reason"])
        self.assertTrue(all(len(al["edges"]) <= 2 for al in sol["active_lines"]))
        self.assertEqual(len(sol["active_lines"]), 2)


class TestGrid(unittest.TestCase):
    def test_grids_feasible_and_agree(self):
        for seed in range(4):
            inst = grid(4, 5, seed, lam=[0.2, 0.5, 0.8, 0.95][seed])
            sol, log = run(inst, tl=3.0, seed=seed + 1)
            self.assertIsNotNone(sol, "seed %d: no solution (%s)" % (seed, log.get("search")))
            v = S.verify(inst, sol)
            self.assertTrue(v["feasible"], "seed %d: %s" % (seed, v["reason"]))
            self.assertAlmostEqual(v["objective"], sol["objective_value"], delta=1e-6 * abs(v["objective"]) + 1e-6)
            self.assertNotEqual(official(inst, sol), False, "seed %d: official checker rejects" % seed)
            print("grid seed %d lambda %s objective %.4f lines %d events %d" % (
                seed, inst["global_parameters"]["lambda"], v["objective"], len(sol["active_lines"]),
                len(log["events"])))

    def test_search_never_worse_than_first_start(self):
        inst = grid(5, 6, 11, lam=0.6, pairs=40)
        sol, log = run(inst, tl=4.0)
        first = log["search"]["starts"][0][1]          # rounded to 4 decimals in the log
        self.assertLessEqual(S.verify(inst, sol)["objective"], first * (1 + 1e-9) + 1e-3)


class TestMutations(unittest.TestCase):
    def setUp(self):
        self.inst = grid(4, 4, 5, lam=0.5, pairs=15)
        self.sol, _ = run(self.inst, tl=2.0)
        self.assertTrue(S.verify(self.inst, self.sol)["feasible"])

    def _both_reject(self, mut, label):
        self.assertFalse(S.verify(self.inst, mut, loose=True)["feasible"], label + ": ours accepts")
        self.assertNotEqual(official(self.inst, mut), True, label + ": official accepts")

    def test_mutations(self):
        s = self.sol
        m = copy.deepcopy(s)
        m["active_passenger_paths"][0]["flow"] += 1.0
        self._both_reject(m, "extra flow")
        m = copy.deepcopy(s)
        busiest = max(range(len(m["active_lines"])), key=lambda i: m["active_lines"][i]["frequency"])
        m["active_lines"][busiest]["frequency"] = 0.0
        P = S.Problem(self.inst)
        lines = [[P.mindex[al["mode"]], al["nodes"], al["edges"], al["frequency"],
                  sum(P.opc[e] for e in al["edges"])] for al in m["active_lines"]]
        paths = {}
        for ap in m["active_passenger_paths"]:
            paths.setdefault((ap["origin"], ap["destination"]), {})[tuple(ap["arcs"])] = ap["flow"]
        m = S.build_solution(P, lines, paths)     # consistent objective, but the busiest line carries nothing
        self._both_reject(m, "line removed")
        m = copy.deepcopy(s)
        m["objective_value"] *= 1.01
        self._both_reject(m, "objective off by 1%")
        m = copy.deepcopy(s)
        p = next((ap for ap in m["active_passenger_paths"] if len(ap["arcs"]) >= 2), None)
        if p is not None:
            p["arcs"] = p["arcs"][::-1]
            self._both_reject(m, "arcs reversed")
        m = copy.deepcopy(s)
        m["active_lines"][0]["frequency"] = P.cap[m["active_lines"][0]["edges"][0]] + 5.0
        self._both_reject(m, "frequency above edge capacity")
        m = copy.deepcopy(s)
        m["active_lines"] = []
        self._both_reject(m, "no lines")

    def test_line_rules_strict_only(self):
        # split one line in two at a non-terminal node, same frequency: capacity and edge loads are unchanged and the
        # objective is recomputed, but both pieces break the model's line rule (a line joins two terminals).
        # Ours (strict) must reject; the checker's own rules (loose) still hold; the official verdict is printed.
        P = S.Problem(self.inst)
        lines, done = [], False
        for al in self.sol["active_lines"]:
            mi = P.mindex[al["mode"]]
            ed, nd, f = al["edges"], al["nodes"], al["frequency"]
            if not done and len(ed) >= 2:
                k = len(ed) // 2
                lines.append([mi, nd[:k + 1], ed[:k], f, sum(P.opc[e] for e in ed[:k])])
                lines.append([mi, nd[k:], ed[k:], f, sum(P.opc[e] for e in ed[k:])])
                done = True
            else:
                lines.append([mi, nd, ed, f, sum(P.opc[e] for e in ed)])
        if not done:
            self.skipTest("no line with two edges")
        paths = {}
        for ap in self.sol["active_passenger_paths"]:
            paths.setdefault((ap["origin"], ap["destination"]), {})[tuple(ap["arcs"])] = ap["flow"]
        m = S.build_solution(P, lines, paths)
        self.assertFalse(S.verify(self.inst, m)["feasible"])
        self.assertTrue(S.verify(self.inst, m, loose=True)["feasible"])
        print("PROBE line-rules (a line split at a non-terminal node): ours strict=False, ours loose=True, "
              "official=%s" % official(self.inst, m))


class TestReal(unittest.TestCase):
    def test_real_tiny(self):
        if not HF:
            self.skipTest("MV2_FROC_HF not set")
        tdir = os.path.join(HF, "tasks", "borndorfer2007")
        ip = os.path.join(tdir, "instance", "tiny_instance.json")
        if not os.path.exists(ip):
            self.skipTest("tiny instance not downloaded")
        with open(ip) as f:
            inst = json.load(f)
        sol, log = run(inst, tl=8.0)
        v = S.verify(inst, sol)
        self.assertTrue(v["feasible"], v["reason"])
        off = official(inst, sol)
        self.assertNotEqual(off, False)
        g = json.load(open(os.path.join(tdir, "gurobi_solution", "tiny_solution.json")))
        gv = S.verify(inst, g, loose=True)
        print("TINY ours=%.4f gurobi=%.4f gap%%=%.3f official=%s gurobi_ours_loose=%s" % (
            v["objective"], g["objective_value"], 100 * (v["objective"] - g["objective_value"]) /
            g["objective_value"], off, gv["feasible"]))


if __name__ == "__main__":
    unittest.main()

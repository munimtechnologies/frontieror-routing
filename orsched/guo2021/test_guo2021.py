"""Tests for the guo2021 solver (MV2 of Munim, Inc.; made with AI agents working in MV2's name; Apache-2.0).

Everything is checked against independent brute force on small synthetic instances: the per-OR expected recourse,
the checker-style objective, and the whole optimum of a 4-patient instance (all assignments enumerated).
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


def make_instance(P=6, H=2, D=2, R=2, NS=4, seed=0, B=300, mand=None):
    rng = random.Random(seed)
    mand = P // 2 if mand is None else mand
    patients = []
    for p in range(P):
        patients.append({
            "patient_id": p, "alpha_p": 10, "rho_p": 1, "omega_p": 1.0, "is_mandatory": p < mand,
            "c_sched_per_day": {str(d + 1): -float(rng.randint(10, 60) * (D - d)) for d in range(D)},
            "c_unsched": float(rng.randint(50, 200)), "c_cancel": float(rng.randint(100, 400))})
    hospitals = [{"hospital_id": h, "num_ors": R,
                  "days": [{"day_id": d, "day_label": d + 1, "B_hd": B, "F_hd": rng.randint(20, 80),
                            "G_hd": rng.randint(50, 150)} for d in range(D)]} for h in range(H)]
    scenarios = [{"scenario_id": s,
                  "surgery_durations_minutes": [round(rng.uniform(60, 200), 2) for _ in range(P)]}
                 for s in range(NS)]
    return {"instance_id": "synthetic-%d" % seed, "num_patients": P, "num_hospitals": H, "num_days": D,
            "num_ors_per_hospital": R, "num_mandatory_patients": mand, "num_scenarios": NS,
            "global_parameters": {}, "patients": patients, "hospitals": hospitals, "scenarios": scenarios}


def brute_rec(inst, members, cap):
    """Expected optimal cancellation cost of one OR, by enumerating every kept subset in every scenario."""
    cc = {pt["patient_id"]: pt["c_cancel"] for pt in inst["patients"]}
    NS = inst["num_scenarios"]
    total = 0.0
    for sc in inst["scenarios"]:
        T = sc["surgery_durations_minutes"]
        best = 0.0
        for mask in range(1 << len(members)):
            chosen = [members[i] for i in range(len(members)) if mask >> i & 1]
            if sum(T[p] for p in chosen) <= cap + 1e-6:
                best = max(best, sum(cc[p] for p in chosen))
        total += sum(cc[p] for p in members) - best
    return total / NS


def brute_cost(inst, assign):
    """assign: {patient: (h, d, r) or None (postponed)} -> total cost, written from the problem statement."""
    hd_data = {(h["hospital_id"], dd["day_id"]): dd for h in inst["hospitals"] for dd in h["days"]}
    pts = {pt["patient_id"]: pt for pt in inst["patients"]}
    cost = 0.0
    bins = {}
    for p, a in assign.items():
        if a is None:
            if not pts[p]["is_mandatory"]:
                cost += pts[p]["c_unsched"]
            continue
        bins.setdefault(a, []).append(p)
        cost += pts[p]["c_sched_per_day"][str(a[1] + 1)]
    for (h, d, r), ms in bins.items():
        cost += hd_data[(h, d)]["F_hd"] + brute_rec(inst, sorted(ms), hd_data[(h, d)]["B_hd"])
    for (h, d) in {(h, d) for (h, d, r) in bins}:
        cost += hd_data[(h, d)]["G_hd"]
    return cost


def loc_to_assign(pb, loc):
    out = {}
    for p in range(pb.P):
        l = loc[p]
        out[p] = None if l == S.POSTPONED or l is None else (l[0] // pb.D, l[0] % pb.D, l[1])
    return out


class TestRecourse(unittest.TestCase):
    def test_pareto_matches_bruteforce(self):
        rng = random.Random(3)
        for _ in range(200):
            k = rng.randint(0, 7)
            items = [(round(rng.uniform(10, 200), 2), float(rng.randint(1, 50))) for _ in range(k)]
            cap = rng.uniform(0, 500)
            best = 0.0
            for mask in range(1 << k):
                w = sum(items[i][0] for i in range(k) if mask >> i & 1)
                if w <= cap + 1e-6:
                    best = max(best, sum(items[i][1] for i in range(k) if mask >> i & 1))
            self.assertAlmostEqual(S.pareto_kept(items, cap), best, places=9)

    def test_rec_matches_bruteforce(self):
        inst = make_instance(P=9, H=1, D=2, R=3, NS=7, seed=5, B=330)
        pb = S.Problem(inst)
        rng = random.Random(1)
        for _ in range(60):
            m = tuple(sorted(rng.sample(range(9), rng.randint(1, 7))))
            hd = rng.randrange(pb.HD)
            self.assertAlmostEqual(pb.rec(hd, m), brute_rec(inst, list(m), 330.0), places=9)

    def test_rec_dp_branch_matches_enumeration(self):
        # more than KMAX patients in one OR uses the Pareto DP; compare with the enumeration branch
        P = S.KMAX + 2
        inst = make_instance(P=P, H=1, D=1, R=1, NS=3, seed=8, B=700)
        pb = S.Problem(inst)
        m = tuple(range(P))
        got = pb.rec(0, m)
        want = brute_rec(inst, list(m), 700.0)
        self.assertAlmostEqual(got, want, places=7)


class TestSearch(unittest.TestCase):
    def test_tiny_optimum_by_enumeration(self):
        inst = make_instance(P=4, H=1, D=2, R=2, NS=3, seed=11, B=300, mand=2)
        pts = {pt["patient_id"]: pt for pt in inst["patients"]}
        options = []
        for p in range(4):
            o = [(0, d, r) for d in range(2) for r in range(2)]
            if not pts[p]["is_mandatory"]:
                o.append(None)
            options.append(o)
        opt = min(brute_cost(inst, dict(enumerate(c))) for c in itertools.product(*options))
        pb = S.Problem(inst)
        found = []
        for seed in (1, 2, 3):
            st = pb.construct()
            best, loc = S.search(pb, st, seed, time.monotonic() + 1.0)
            self.assertAlmostEqual(brute_cost(inst, loc_to_assign(pb, loc)), best, places=6)
            found.append(best)
        self.assertAlmostEqual(min(found), opt, places=6)

    def test_model_cost_equals_checker_objective(self):
        inst = make_instance(P=10, H=2, D=3, R=2, NS=6, seed=21, B=320)
        pb = S.Problem(inst)
        st = pb.construct()
        best, loc = S.search(pb, st, 4, time.monotonic() + 1.0)
        sol = pb.solution(loc)
        self.assertAlmostEqual(sol["objective_value"], best, places=6)
        self.assertAlmostEqual(S.checker_objective(inst, sol), brute_cost(inst, loc_to_assign(pb, loc)), places=6)

    def test_solution_contract(self):
        inst = make_instance(P=10, H=2, D=3, R=2, NS=6, seed=22, B=320)
        pb = S.Problem(inst)
        st = pb.construct()
        _best, loc = S.search(pb, st, 5, time.monotonic() + 0.5)
        sol = pb.solution(loc)
        for k in ("objective_value", "u", "y", "x", "w"):
            self.assertIn(k, sol)
        self.assertTrue(sol["w"])
        x, y, u, w = sol["x"], sol["y"], sol["u"], sol["w"]
        for p in range(10):
            n = sum(v for k, v in x.items() if int(k.split(",")[2]) == p)
            if inst["patients"][p]["is_mandatory"]:
                self.assertEqual(n, 1)
            else:
                self.assertEqual(n + w[str(p)], 1)
        for k, v in x.items():
            h, d, p, r = k.split(",")
            self.assertEqual(v, 1)
            self.assertEqual(y["%s,%s,%s" % (h, d, r)], 1)
        for k, v in y.items():
            h, d, r = k.split(",")
            self.assertLessEqual(v, u["%s,%s" % (h, d)])
            if int(r) > 0:   # ORs opened in index order (the paper's symmetry rule; not required by the checker)
                self.assertLessEqual(v, y["%s,%s,%d" % (h, d, int(r) - 1)])

    def test_all_mandatory_keeps_w_nonempty(self):
        inst = make_instance(P=5, H=1, D=2, R=2, NS=3, seed=30, B=300, mand=5)
        pb = S.Problem(inst)
        st = pb.construct()
        sol = pb.solution(st.loc)
        self.assertTrue(sol["w"])
        self.assertTrue(all(v == 0 for v in sol["w"].values()))
        self.assertEqual(len(sol["x"]), 5)


class TestCli(unittest.TestCase):
    def test_cli_in_time(self):
        inst = make_instance(P=30, H=3, D=3, R=3, NS=20, seed=40, B=420)
        with tempfile.TemporaryDirectory() as d:
            ip = os.path.join(d, "inst.json")
            op = os.path.join(d, "sol.json")
            with open(ip, "w", encoding="utf-8") as f:
                json.dump(inst, f)
            t0 = time.monotonic()
            p = subprocess.run([sys.executable, os.path.join(HERE, "solve.py"), "--problem", "guo2021", "--instance",
                                ip, "--output", op, "--time-limit", "6"], capture_output=True, text=True, timeout=30)
            wall = time.monotonic() - t0
            self.assertEqual(p.returncode, 0, p.stderr[-800:])
            self.assertLess(wall, 6.0)
            with open(op, encoding="utf-8") as f:
                sol = json.load(f)
            self.assertAlmostEqual(sol["objective_value"], S.checker_objective(inst, sol), places=6)
            self.assertFalse(os.path.exists(op + ".tmp"))


if __name__ == "__main__":
    unittest.main()

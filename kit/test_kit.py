"""Tests for frontier_runtime and harness (standard library only).

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import frontier_runtime as R  # noqa: E402
import harness as H  # noqa: E402

STUCK = """import time, frontier_runtime as R
def solve(inst, clock, inc, args):
    inc.offer(7.0, {"objective_value": 7.0, "x": inst["x"]}, "first")
    while True:
        time.sleep(0.01)
R.main(solve, "min")
"""

RAISES_AFTER = """import frontier_runtime as R
def solve(inst, clock, inc, args):
    inc.offer(3.0, {"objective_value": 3.0}, "first")
    raise RuntimeError("boom")
R.main(solve, "max")
"""

RAISES_BEFORE = """import frontier_runtime as R
def solve(inst, clock, inc, args):
    raise RuntimeError("boom")
R.main(solve, "min")
"""

PLAIN = """import json, sys, time
a = sys.argv
out = a[a.index("--output") + 1]
mode = json.load(open(a[a.index("--instance") + 1]))["mode"]
if mode == "sleep":
    time.sleep(30)
json.dump({"objective_value": 5.0 if mode == "ok" else 4.0, "v": 5.0}, open(out, "w"))
"""


def make_solver(d, text):
    os.makedirs(d, exist_ok=True)
    shutil.copy(os.path.join(HERE, "frontier_runtime.py"), os.path.join(d, "frontier_runtime.py"))
    with open(os.path.join(d, "solve.py"), "w", encoding="utf-8") as f:
        f.write(text)
    return os.path.join(d, "solve.py")


def run_cli(solve_py, inst, limit, tmp):
    ipath = os.path.join(tmp, "in.json")
    opath = os.path.join(tmp, "out.json")
    with open(ipath, "w", encoding="utf-8") as f:
        json.dump(inst, f)
    t0 = time.monotonic()
    p = subprocess.run([sys.executable, "solve.py", "--problem", "t", "--instance", ipath, "--output", opath,
                        "--time-limit", str(limit)], cwd=os.path.dirname(solve_py), capture_output=True,
                       timeout=limit + 10)
    return p.returncode, time.monotonic() - t0, opath


class Runtime(unittest.TestCase):
    def test_margin(self):
        self.assertEqual(R.default_margin(10), 1.5)
        self.assertAlmostEqual(R.default_margin(60), 4.8)
        self.assertEqual(R.default_margin(300), 20.0)
        c = R.Clock(60, start=time.monotonic())
        self.assertAlmostEqual(c.deadline(), 55.2)
        self.assertGreater(c.remaining(), 54.0)
        self.assertLessEqual(c.share(0.5), c.remaining())

    def test_incumbent_keeps_best_and_writes(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "o.json")
            inc = R.Incumbent(p, "min")
            self.assertTrue(inc.offer(10, {"objective_value": 10}))
            self.assertFalse(inc.offer(11, {"objective_value": 11}))
            self.assertFalse(inc.offer(10, {"objective_value": 10}))
            sol = {"objective_value": 8}
            self.assertTrue(inc.offer(8, sol))
            sol["objective_value"] = 6  # the same dict, changed and offered again, must still be written
            self.assertTrue(inc.offer(6, sol))
            with open(p, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["objective_value"], 6)
            self.assertEqual([h[1] for h in inc.history], [10.0, 8.0, 6.0])
            self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(d)))
            mx = R.Incumbent(os.path.join(d, "m.json"), "max")
            mx.offer(1, {"objective_value": 1})
            self.assertTrue(mx.offer(2, {"objective_value": 2}))
            self.assertFalse(mx.offer(1.5, {"objective_value": 1.5}))
            with self.assertRaises(ValueError):
                R.Incumbent(p, "best")

    def test_watchdog_ends_a_stuck_solver_before_the_limit(self):
        with tempfile.TemporaryDirectory() as d:
            sp = make_solver(os.path.join(d, "s"), STUCK)
            code, wall, out = run_cli(sp, {"x": 42}, 3, d)
            self.assertEqual(code, 0)
            self.assertLess(wall, 3.0)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"objective_value": 7.0, "x": 42})

    def test_exception_after_a_solution_keeps_it(self):
        with tempfile.TemporaryDirectory() as d:
            sp = make_solver(os.path.join(d, "s"), RAISES_AFTER)
            code, wall, out = run_cli(sp, {}, 5, d)
            self.assertEqual(code, 0)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["objective_value"], 3.0)

    def test_exception_before_any_solution_fails(self):
        with tempfile.TemporaryDirectory() as d:
            sp = make_solver(os.path.join(d, "s"), RAISES_BEFORE)
            code, wall, out = run_cli(sp, {}, 5, d)
            self.assertEqual(code, 1)
            self.assertFalse(os.path.exists(out))


def plain_checker(inst, sol):
    return {"feasible": inst["mode"] != "infeasible", "objective": sol["v"], "reason": "test"}


class Harness(unittest.TestCase):
    def test_contest_score(self):
        self.assertEqual(H.contest_score(100, 90, "min"), 0.9)
        self.assertEqual(H.contest_score(40, 90, "min"), 2.0)
        self.assertEqual(H.contest_score(45, 90, "max"), 0.5)
        self.assertEqual(H.contest_score(None, 90, "max"), 0.0)
        self.assertEqual(H.contest_score(0, 0, "min"), 2.0)

    def _case(self, d, mode, ref=5.0):
        ip = os.path.join(d, mode + ".json")
        with open(ip, "w", encoding="utf-8") as f:
            json.dump({"mode": mode}, f)
        return {"name": mode, "instance_path": ip, "reference": ref}

    def test_statuses(self):
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "solve.py")
            with open(sp, "w", encoding="utf-8") as f:
                f.write(PLAIN)
            hb = H.Heartbeat()
            ok = H.evaluate_case(self._case(d, "ok", 4.0), sp, "t", 5, plain_checker, "min", d, hb=hb)
            self.assertEqual(ok["status"], "ok")
            self.assertEqual(ok["score"], 0.8)
            self.assertEqual(ok["gap_pct"], 25.0)
            self.assertFalse(ok["paused"])
            bad = H.evaluate_case(self._case(d, "mismatch"), sp, "t", 5, plain_checker, "min", d, hb=hb)
            self.assertEqual(bad["status"], "rejected_objective_mismatch")
            self.assertEqual(bad["score"], 0.0)
            inf = H.evaluate_case(self._case(d, "infeasible"), sp, "t", 5, plain_checker, "min", d, hb=hb)
            self.assertEqual(inf["status"], "infeasible")
            slow = H.evaluate_case(self._case(d, "sleep"), sp, "t", 1, plain_checker, "min", d, hb=hb)
            self.assertEqual(slow["status"], "overtime")
            self.assertEqual(slow["score"], 0.0)
            t = H.summarise([ok, bad, inf, slow], 5)
            self.assertEqual(t["ok"], 1)
            self.assertEqual(t["by_status"]["overtime"], 1)
            self.assertAlmostEqual(t["mean_score"], 0.2)
            H.write_report(os.path.join(d, "rep"), "t", "intro", [ok, bad, inf, slow], t)
            self.assertTrue(os.path.exists(os.path.join(d, "rep", "results.md")))
            hb.stop()

    def test_heartbeat_sees_a_gap(self):
        hb = H.Heartbeat(tick=10.0)  # the thread sleeps 10 s, so the gap since reset grows
        hb.reset()
        time.sleep(0.3)
        self.assertGreaterEqual(hb.max_gap(), 0.25)
        hb.stop()


if __name__ == "__main__":
    unittest.main()

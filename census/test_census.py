"""Tests for the FrontierOR checker census (trace_run.py, trace_census.py). Apache-2.0.
MV2 of Munim, Inc.; made with AI agents working in MV2's name.

  python census/test_census.py -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(os.path.dirname(HERE), "kit")
for p in (KIT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import trace_census as TC  # noqa: E402

TOY_CHECKER = '''
import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance_path")
    ap.add_argument("--solution_path")
    ap.add_argument("--result_path")
    a = ap.parse_args()
    with open(a.instance_path) as f:
        inst = json.load(f)
    with open(a.solution_path) as f:
        sol = json.load(f)
    rho = inst.get("rho_top", 0.0)
    n = inst["n"]
    again = inst.get("n", 5)
    w = inst["items"][0].get("w", 1)
    flag = "opt" in sol
    try:
        inst["nokey"]
    except KeyError:
        pass
    ok = sol["x"] == n and rho == 0.0 and again == 3 and w == 1 and not flag
    with open(a.result_path, "w") as f:
        json.dump({"feasible": ok, "violated_constraints": [], "violations": []}, f)


if __name__ == "__main__":
    main()
'''


class TestTraceRun(unittest.TestCase):
    def test_records_only_absent_keys(self):
        with tempfile.TemporaryDirectory() as td:
            paths = {k: os.path.join(td, k) for k in ("checker.py", "inst.json", "sol.json", "res.json", "tr.json")}
            with open(paths["checker.py"], "w", encoding="utf-8") as f:
                f.write(TOY_CHECKER)
            with open(paths["inst.json"], "w", encoding="utf-8") as f:
                json.dump({"n": 3, "items": [{"v": 1}]}, f)
            with open(paths["sol.json"], "w", encoding="utf-8") as f:
                json.dump({"x": 3}, f)
            subprocess.run([sys.executable, os.path.join(HERE, "trace_run.py"), "--checker", paths["checker.py"],
                            "--instance", paths["inst.json"], "--solution", paths["sol.json"], "--result",
                            paths["res.json"], "--trace", paths["tr.json"]], check=True, timeout=60, cwd=td)
            with open(paths["res.json"], encoding="utf-8") as f:
                self.assertTrue(json.load(f)["feasible"])
            with open(paths["tr.json"], encoding="utf-8") as f:
                tr = json.load(f)
        self.assertEqual(tr["status"], "ok")
        got = {(e["src"], e["kind"], e["key"], e["default"]) for e in tr["events"]}
        self.assertIn(("instance", "get", "'rho_top'", "0.0"), got)
        self.assertIn(("instance", "get", "'w'", "1"), got)
        self.assertIn(("solution", "in", "'opt'", ""), got)
        self.assertIn(("instance", "getitem", "'nokey'", ""), got)
        self.assertFalse(any(e["key"] == "'n'" for e in tr["events"]))
        ctx = [e["context"] for e in tr["events"] if e["key"] == "'w'"]
        self.assertEqual(ctx, ["v"])


class TestAggregate(unittest.TestCase):
    def test_summary_counts(self):
        ev = {"src": "instance", "kind": "get", "key": "'rho'", "default": "0.0", "context": "a,b", "count": 1}
        rows = [
            {"task": "t1", "name": "tiny", "status": "ran", "stored_feasible": True, "feasible": True,
             "reproduced": True, "instance_events": [ev], "solution_events": []},
            {"task": "t1", "name": "large_1", "status": "ran", "stored_feasible": True, "feasible": False,
             "reproduced": False, "violated": [7], "violations": "x", "instance_events": [ev],
             "solution_events": []},
            {"task": "t2", "name": "tiny", "status": "too_big"},
            {"task": "t3", "name": "tiny", "status": "checker_failed", "trace_status": "timeout",
             "plain_status": "timeout"},
        ]
        with tempfile.TemporaryDirectory() as td:
            s = TC.aggregate(rows, "rev", td)
            for name in ("by_task.json", "summary.json", "defaults.md", "verdicts.md"):
                self.assertTrue(os.path.exists(os.path.join(td, name)), name)
            with open(os.path.join(td, "defaults.md"), encoding="utf-8") as f:
                text = f.read()
        self.assertEqual(s["ran"], 2)
        self.assertEqual(s["reproduced"], 1)
        self.assertEqual(s["mismatches"], 1)
        self.assertEqual(s["checker_failed"], 1)
        self.assertEqual(s["skipped"], {"too_big": 1})
        self.assertEqual(s["tasks_with_instance_default_reads_list"], ["t1"])
        self.assertIn("| t1 | 'rho' | get | 0.0 | 2/2 | 2 |", text)

    def test_stored_verdict_missing(self):
        self.assertEqual(TC.stored_verdict("/nonexistent/x.json"), (None, None))


if __name__ == "__main__":
    unittest.main()

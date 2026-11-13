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

# A checker that, like FrontierOR's solverless ones, imports a module shipped next to it and reads a data file from
# a task subfolder relative to its own location.
HELPER_CHECKER = '''
import argparse
import json
import os

import helper_mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance_path")
    ap.add_argument("--solution_path")
    ap.add_argument("--result_path")
    a = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "models", "m.txt")) as f:
        tag = f.read().strip()
    with open(a.instance_path) as f:
        inst = json.load(f)
    with open(a.solution_path) as f:
        sol = json.load(f)
    ok = helper_mod.ok() and tag == "x" and inst["n"] == 1 and sol["x"] == 1
    with open(a.result_path, "w") as f:
        json.dump({"feasible": ok, "violated_constraints": [], "violations": []}, f)


if __name__ == "__main__":
    main()
'''

TOY_TASK = {
    "tasks/t1/feasibility_check.py": HELPER_CHECKER,
    "tasks/t1/helper_mod.py": "def ok():\n    return True\n",
    "tasks/t1/models/m.txt": "x\n",
    "tasks/t1/problem_description.txt": "toy\n",
    "tasks/t1/instance/tiny_instance.json": json.dumps({"n": 1}),
    "tasks/t1/gurobi_solution/tiny_solution.json": json.dumps({"x": 1}),
    "tasks/t1/gurobi_solution_log/tiny_log.jsonl": "{}\n",
    "tasks/t1/gurobi_feasi_result/tiny_feasi_result.json": json.dumps({"feasible": True}),
}


class FakeHF:
    """Stands in for frontieror_hf (tree, download) with an in-memory task folder; no network."""

    def __init__(self, files):
        self.files = files
        self.downloaded = []

    def tree(self, path, rev, recursive=False):
        out = [{"type": "directory", "path": "tasks/t1/instance"}]
        for p, body in sorted(self.files.items()):
            if p.startswith(path + "/"):
                out.append({"type": "file", "path": p, "size": len(body.encode("utf-8"))})
        return out

    def download(self, path, rev, dest, expect_size=None):
        body = self.files[path].encode("utf-8")
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(body)
        self.downloaded.append(path)
        return {"path": path, "bytes": len(body)}


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
        self.assertEqual(s["census_version"], TC.__version__)
        self.assertIn("| t1 | 'rho' | get | 0.0 | 2/2 | 2 |", text)

    def test_stored_verdict_missing(self):
        self.assertEqual(TC.stored_verdict("/nonexistent/x.json"), (None, None))


class TestHelpers(unittest.TestCase):
    def test_helper_files_selection(self):
        files = [
            {"type": "directory", "path": "tasks/t1/solverless_models"},
            {"type": "file", "path": "tasks/t1/feasibility_check.py", "size": 10},
            {"type": "file", "path": "tasks/t1/solverless_witness.py", "size": 20},
            {"type": "file", "path": "tasks/t1/solverless_models/abc.npz", "size": 300},
            {"type": "file", "path": "tasks/t1/instance/tiny_instance.json", "size": 5},
            {"type": "file", "path": "tasks/t1/gurobi_solution/tiny_solution.json", "size": 5},
            {"type": "file", "path": "tasks/t1/gurobi_solution_log/tiny_log.jsonl", "size": 5},
            {"type": "file", "path": "tasks/t1/gurobi_feasi_result/tiny_feasi_result.json", "size": 5},
            {"type": "file", "path": "tasks/t1/instance_schema.json", "size": 7},
            {"type": "file", "path": "tasks/t10/other.py", "size": 1},
        ]
        got = TC.helper_files(files, "t1")
        self.assertEqual([rel for _, rel, _ in got],
                         ["instance_schema.json", "solverless_models/abc.npz", "solverless_witness.py"])
        self.assertEqual(sum(s for _, _, s in got), 327)

    def _run(self, with_helpers, max_helper_bytes=200000000):
        fake = FakeHF(TOY_TASK)
        old_tree, old_dl = TC.HF.tree, TC.HF.download
        TC.HF.tree, TC.HF.download = fake.tree, fake.download
        try:
            with tempfile.TemporaryDirectory() as td:
                rows_p = os.path.join(td, "rows.jsonl")
                rows = TC.census_task("t1", "rev", os.path.join(td, "scratch"), 5000000, 60, set(), rows_p,
                                      with_helpers=with_helpers, max_helper_bytes=max_helper_bytes)
                self.assertFalse(os.path.exists(os.path.join(td, "scratch", "t1")))
        finally:
            TC.HF.tree, TC.HF.download = old_tree, old_dl
        return {r["name"]: r for r in rows}, fake

    def test_census_task_with_helpers_runs_checker(self):
        rows, fake = self._run(True)
        tiny = rows["tiny"]
        self.assertEqual(tiny["status"], "ran")
        self.assertIs(tiny["feasible"], True)
        self.assertTrue(tiny["reproduced"])
        self.assertEqual(tiny["helpers"]["mode"], "on")
        self.assertEqual(tiny["helpers"]["files"], 3)
        self.assertIn("tasks/t1/helper_mod.py", fake.downloaded)
        self.assertIn("tasks/t1/models/m.txt", fake.downloaded)
        self.assertNotIn("tasks/t1/gurobi_solution_log/tiny_log.jsonl", fake.downloaded)
        self.assertEqual(rows["large_1"]["status"], "no_instance")

    def test_census_task_without_helpers_fails_like_v1(self):
        rows, fake = self._run(False)
        self.assertEqual(rows["tiny"]["status"], "checker_failed")
        self.assertIn("ModuleNotFoundError", str(rows["tiny"].get("trace_status")))
        self.assertNotIn("tasks/t1/helper_mod.py", fake.downloaded)

    def test_census_task_helpers_over_cap_are_skipped(self):
        rows, fake = self._run(True, max_helper_bytes=3)
        self.assertEqual(rows["tiny"]["helpers"]["mode"], "too_big")
        self.assertEqual(rows["tiny"]["status"], "checker_failed")
        self.assertNotIn("tasks/t1/helper_mod.py", fake.downloaded)


if __name__ == "__main__":
    unittest.main()

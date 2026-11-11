"""Tests for schema_drift.py (MV2 of Munim, Inc.; made with AI agents working in MV2's name; Apache-2.0).

Offline: the Hugging Face calls are replaced by an in-memory fake.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import schema_drift as SD  # noqa: E402


def run_walk(schema, inst):
    out = {"missing": set(), "extra": set()}
    SD.walk(schema, inst, "", out)
    return out


class FakeHF:
    def __init__(self, files):
        self.files = {p: (b if isinstance(b, bytes) else b.encode("utf-8")) for p, b in files.items()}

    def tree(self, path, rev, recursive=False):
        return [{"type": "file", "path": p, "size": len(b)} for p, b in sorted(self.files.items())
                if p.startswith(path + "/")]

    def download(self, path, rev, dest, expect_size=None):
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(self.files[path])
        return {"path": path, "bytes": len(self.files[path])}


class TestWalk(unittest.TestCase):
    def test_extra_and_nested(self):
        out = run_walk({"a": "<int>", "b": {"c": "<int>"}}, {"a": 1, "b": {"c": 2, "d": 3}, "e": 4})
        self.assertEqual(out["missing"], set())
        self.assertEqual(out["extra"], {"b.d", "e"})

    def test_missing(self):
        out = run_walk({"a": "<int>", "b": "<int>"}, {"a": 1})
        self.assertEqual(out["missing"], {"b"})
        self.assertEqual(out["extra"], set())

    def test_list_items(self):
        out = run_walk({"items": [{"id": "", "w": ""}]}, {"items": [{"id": 1, "w": 2}, {"id": 2, "w": 3, "z": 1}]})
        self.assertEqual(out["extra"], {"items[].z"})
        self.assertEqual(out["missing"], set())

    def test_list_sample_limit(self):
        items = [{"id": k} for k in range(SD.SAMPLE)] + [{"id": 99, "late": 1}]
        out = run_walk({"items": [{"id": ""}]}, {"items": items})
        self.assertEqual(out["extra"], set())

    def test_map_schema(self):
        out = run_walk({"m": {"{i}": {"x": ""}}}, {"m": {"0": {"x": 1}, "1": {"x": 2, "y": 3}}})
        self.assertEqual(out["extra"], {"m{}.y"})
        self.assertEqual(out["missing"], set())

    def test_many_extras_collapse(self):
        inst = {"a": 1}
        inst.update({"k%d" % i: i for i in range(SD.MANY + 5)})
        out = run_walk({"a": ""}, inst)
        self.assertEqual(out["extra"], {"{20+ undocumented keys}"})

    def test_leaf_string_does_not_descend(self):
        out = run_walk({"cov": "<dict, key: '{facility_index}'>"}, {"cov": {"0": [1], "1": [2]}})
        self.assertEqual(out, {"missing": set(), "extra": set()})

    def test_leaf_and_mentions(self):
        self.assertEqual(SD.leaf("customers[].demand"), "demand")
        self.assertEqual(SD.leaf("a{}"), "a")
        self.assertEqual(SD.leaf("items[]"), "items")
        self.assertEqual(SD.leaf("x"), "x")
        self.assertTrue(SD.mentions('d = inst.get("seed", 42)', "seed"))
        self.assertTrue(SD.mentions("d = inst['seed']", "seed"))
        self.assertFalse(SD.mentions("seeds = 1", "seed"))
        self.assertFalse(SD.mentions("", "seed"))

    def test_get_regex(self):
        text = 'x = instance.get("p", 0)\ny = data.get(\'q\', 1)\nz = sol.get("r")\nw = inst.get( "s" )\n'
        self.assertEqual(sorted(SD.GET_RE.findall(text)), ["p", "q", "s"])

    def test_case_name(self):
        self.assertEqual(SD.case_name("tiny_instance.json"), "tiny")
        self.assertEqual(SD.case_name("large_instance_3.json"), "large_3")


class TestTask(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake(self):
        big = json.dumps({"n": 1, "items": [], "pad": "x" * 200})
        return FakeHF({
            "tasks/t1/instance_schema.json": json.dumps({"n": "<int>", "items": [{"w": "<int>"}]}),
            "tasks/t1/feasibility_check.py": 'n = instance["n"]\nseed = instance.get("seed", 42)\n',
            "tasks/t1/gurobi_code.py": "x = 1\n",
            "tasks/t1/instance/tiny_instance.json": json.dumps({"n": 2, "items": [{"w": 1}, {"w": 2, "v": 3}],
                                                               "seed": 7}),
            "tasks/t1/instance/large_instance_1.json": json.dumps({"items": []}),
            "tasks/t1/instance/large_instance_2.json": big,
        })

    def test_drift_task(self):
        fk = self.fake()
        with mock.patch.object(SD.HF, "tree", fk.tree), mock.patch.object(SD.HF, "download", fk.download):
            row = SD.drift_task("t1", "rev", self.tmp, 120)
        self.assertEqual(row["cases"], ["tiny", "large_1"])
        self.assertEqual(row["skipped"]["large_2"], "too_big")
        for k in (3, 4, 5):
            self.assertEqual(row["skipped"]["large_%d" % k], "no_instance")
        extra = {e["path"]: e for e in row["extra_info"]}
        self.assertEqual(sorted(extra), ["items[].v", "seed"])
        self.assertEqual(extra["seed"]["cases"], ["tiny"])
        self.assertTrue(extra["seed"]["checker_mentions"])
        self.assertFalse(extra["seed"]["gurobi_mentions"])
        self.assertFalse(extra["items[].v"]["checker_mentions"])
        missing = {e["path"]: e for e in row["missing_info"]}
        self.assertEqual(sorted(missing), ["n"])
        self.assertEqual(missing["n"]["cases"], ["large_1"])
        self.assertTrue(missing["n"]["checker_mentions"])
        self.assertEqual(row["checker_get_keys"], ["seed"])
        self.assertEqual(row["get_absent"], {"seed": ["large_1"]})
        self.assertEqual(row["top_keys"]["tiny"], ["items", "n", "seed"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "t1")))

    def test_aggregate(self):
        rows = [
            {"task": "vidal2011", "cases": ["tiny"], "skipped": {"large_1": "too_big"},
             "top_keys": {"tiny": ["n", "t"]}, "get_absent": {"p": ["tiny"]}, "checker_get_keys": ["p"],
             "missing_info": [],
             "extra_info": [{"path": "x", "cases": ["tiny"], "checker_mentions": True, "gurobi_mentions": False}]},
            {"task": "other", "cases": [], "skipped": {"tiny": "no_instance"}, "top_keys": {}, "get_absent": {},
             "checker_get_keys": [], "missing_info": [], "extra_info": [], "schema_error": "no schema object"},
        ]
        s = SD.aggregate(rows, "rev", self.tmp)
        self.assertEqual(s["tasks"], 2)
        self.assertEqual(s["tasks_scanned"], 1)
        self.assertEqual(s["cases_scanned"], 1)
        self.assertEqual(s["cases_skipped"], {"too_big": 1, "no_instance": 1})
        self.assertEqual(s["tasks_with_extra"], 1)
        self.assertEqual(s["tasks_with_extra_checker_mentions"], 1)
        self.assertEqual(s["tasks_with_missing"], 0)
        self.assertEqual(s["tasks_with_checker_get_absent"], ["vidal2011"])
        self.assertEqual(s["schema_errors"], ["other"])
        self.assertEqual(s["watch"], {"vidal2011": {"p": "0/1", "t": "1/1"}})
        with open(os.path.join(self.tmp, "drift.md"), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("| vidal2011 | extra | `x` | 1/1 | yes | - |", md)
        self.assertIn("| vidal2011 | `p` | 1/1 (tiny) |", md)
        with open(os.path.join(self.tmp, "summary.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["tasks_scanned"], 1)


if __name__ == "__main__":
    unittest.main()

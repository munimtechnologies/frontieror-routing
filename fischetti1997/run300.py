"""run300: fischetti1997 (generalized TSP) solver v0.1.0 at the contest's 5-minute class, unchanged.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python run300.py --hf-dir /data/hf --out-dir /out

Downloads github.com/munimtechnologies/frontieror-routing at the current commit of main, loads its published
fischetti1997/fischetti_real.py (which runs fischetti1997/solve.py the contest way and judges every answer with the
official feasibility_check.py), replaces only its list of variants with two 300 s runs (seed 1 and seed 7), and runs
it. Nothing in the solver or the runner's scoring is changed. Grades: fischetti1997/PREREG-300.md.
"""
import argparse
import importlib.util
import io
import json
import os
import sys
import time
import urllib.request
import zipfile

REPO = "munimtechnologies/frontieror-routing"
UA = "MV2-of-Munim-Inc FrontierOR fischetti1997 300s (mv2@munimtech.com)"
VARIANTS = [("v010-300s", 300.0, {}), ("v010-seed7-300s", 300.0, {"MV2_GTSP_SEED": "7"})]


def get(url, tries=4, timeout=120):
    err = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retry network errors
            err = e
            time.sleep(2.0 * (k + 1))
    raise err


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--scratch", default="/tmp/mv2-gtsp300")
    a = ap.parse_args(argv)
    sha = json.loads(get("https://api.github.com/repos/%s/commits/main" % REPO).decode("utf-8"))["sha"]
    body = get("https://codeload.github.com/%s/zip/%s" % (REPO, sha))
    dest = os.path.join(a.scratch, "src")
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        z.extractall(dest)
    tops = [d for d in os.listdir(dest) if os.path.isdir(os.path.join(dest, d))]
    if len(tops) != 1:
        raise RuntimeError("unexpected archive layout: %r" % tops)
    runner = os.path.join(dest, tops[0], "fischetti1997", "fischetti_real.py")
    print("runner from", REPO, sha, flush=True)
    spec = importlib.util.spec_from_file_location("fischetti_real_300", runner)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.VARIANTS = list(VARIANTS)
    os.makedirs(a.out_dir, exist_ok=True)
    with open(os.path.join(a.out_dir, "run300.json"), "w", encoding="utf-8") as f:
        json.dump({"runner_sha": sha, "variants": VARIANTS}, f, indent=1)
    return mod.main(["--hf-dir", a.hf_dir, "--out-dir", a.out_dir, "--scratch", os.path.join(a.scratch, "run")])


if __name__ == "__main__":
    sys.exit(main())

"""wait_prereg: before a graded run starts, wait until its pre-registration is public on GitHub.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python wait_prereg.py <path in repo> [--max-min 45] [--out /out/prereg-check.json]

Polls github.com/munimtechnologies/frontieror-routing (main) once a minute until <path> exists there, for at most
--max-min minutes, then records what it saw (commit sha, time, found or not) in --out. It never fails the job: the
run goes ahead either way, and the record says whether the guesses were public before it started.
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

REPO = "munimtechnologies/frontieror-routing"
UA = "MV2-of-Munim-Inc FrontierOR prereg check (mv2@munimtech.com)"


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def check_once(path):
    _, body = fetch("https://api.github.com/repos/%s/commits/main" % REPO)
    sha = json.loads(body.decode("utf-8"))["sha"]
    try:
        status, _ = fetch("https://raw.githubusercontent.com/%s/%s/%s" % (REPO, sha, path))
        return sha, status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return sha, False
        raise


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--max-min", type=float, default=45.0)
    ap.add_argument("--out", default="/out/prereg-check.json")
    a = ap.parse_args(argv)
    t0 = time.monotonic()
    rec = {"path": a.path, "found": False, "sha": None, "tries": 0, "errors": []}
    while True:
        rec["tries"] += 1
        try:
            sha, ok = check_once(a.path)
            rec["sha"] = sha
            if ok:
                rec["found"] = True
                break
        except Exception as e:  # noqa: BLE001 - network trouble: try again
            rec["errors"].append(repr(e)[:200])
        if time.monotonic() - t0 > a.max_min * 60:
            break
        time.sleep(60)
    rec["checked_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rec["waited_s"] = round(time.monotonic() - t0, 1)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
    print("prereg", json.dumps(rec), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

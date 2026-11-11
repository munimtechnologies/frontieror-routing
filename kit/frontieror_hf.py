"""frontieror_hf: read the public FrontierOR benchmark on Hugging Face (dataset frontieror/FrontierOR, CC BY 4.0).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

FrontierOR (arXiv 2605.25246; code github.com/Minw913/FrontierOR) publishes 180 literature-grounded optimisation
tasks. Each has a problem description, a formulation, instance and solution schemas, a standalone
feasibility_check.py, instances (tiny + large) and Gurobi reference solutions. Every file is fetched from the dataset
at one pinned revision, and its size and sha256 are recorded.

  python frontieror_hf.py catalog --out DIR     the small text files of every task (no instances) + metadata/
  python frontieror_hf.py task SLUG --dest DIR  every file of one task (instances and Gurobi solutions included)

Standard library only. Polite: one request at a time, a short pause between tasks, a named User-Agent.
"""
import argparse
import csv
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://huggingface.co"
REPO = "frontieror/FrontierOR"
UA = "MV2-of-Munim-Inc FrontierOR practice (mv2@munimtech.com)"
TEXT_FILES = {"problem_description.txt", "mathematical_formulation.md", "instance_schema.json",
              "solution_schema.json", "feasibility_check.py", "gurobi_code.py", "solution_logger.py"}
MAX_SMALL = 400000


def get(url, tries=4, timeout=180):
    err = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), r.headers
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise
            err = e
        except Exception as e:  # noqa: BLE001 - retry network errors
            err = e
        time.sleep(2.0 * (k + 1))
    raise err


def q(path):
    return urllib.parse.quote(path, safe="/")


def revision():
    body, _ = get("%s/api/datasets/%s" % (BASE, REPO))
    return json.loads(body.decode("utf-8")).get("sha")


def _next_link(link):
    if not link:
        return None
    for part in link.split(","):
        if 'rel="next"' in part:
            return part[part.find("<") + 1:part.find(">")]
    return None


def tree(path, rev, recursive=False):
    url = "%s/api/datasets/%s/tree/%s/%s" % (BASE, REPO, rev, q(path))
    if recursive:
        url += "?recursive=true"
    out = []
    while url:
        body, hd = get(url)
        out.extend(json.loads(body.decode("utf-8")))
        url = _next_link(hd.get("Link"))
    return out


def download(path, rev, dest, expect_size=None):
    if expect_size is not None and os.path.exists(dest) and os.path.getsize(dest) == expect_size:
        with open(dest, "rb") as f:
            body = f.read()
        cached = True
    else:
        body, _ = get("%s/datasets/%s/resolve/%s/%s" % (BASE, REPO, rev, q(path)))
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, dest)
        cached = False
    return {"path": path, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "cached": cached}


def catalog(out, delay=0.2, only=None):
    os.makedirs(out, exist_ok=True)
    rev = revision()
    print("revision", rev, flush=True)
    manifest = {"repo": REPO, "revision": rev, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "files": [], "errors": []}
    for e in tree("metadata", rev, recursive=True):
        if e.get("type") == "file" and int(e.get("size") or 0) <= 20000000:
            try:
                manifest["files"].append(download(e["path"], rev, os.path.join(out, e["path"])))
            except Exception as ex:  # noqa: BLE001
                manifest["errors"].append({"path": e["path"], "error": repr(ex)})
    tasks = sorted(e["path"].split("/")[-1] for e in tree("tasks", rev) if e.get("type") == "directory")
    print("tasks", len(tasks), flush=True)
    rows = []
    for tid in tasks:
        if only and tid not in only:
            continue
        try:
            files = tree("tasks/" + tid, rev, recursive=True)
        except Exception as ex:  # noqa: BLE001
            manifest["errors"].append({"path": "tasks/" + tid, "error": repr(ex)})
            continue
        tdir = os.path.join(out, "tasks", tid)
        os.makedirs(tdir, exist_ok=True)
        listing = [{"path": e["path"], "type": e.get("type"), "size": e.get("size")} for e in files]
        with open(os.path.join(tdir, "listing.json"), "w", encoding="utf-8") as f:
            json.dump(listing, f, indent=1)
        inst = [e for e in files if e.get("type") == "file" and "/instance/" in e["path"]]
        for e in files:
            if e.get("type") != "file":
                continue
            name = e["path"].split("/")[-1]
            small = int(e.get("size") or 0) <= MAX_SMALL
            if small and (name in TEXT_FILES or "/gurobi_feasi_result/" in e["path"]):
                rel = e["path"][len("tasks/" + tid) + 1:]
                try:
                    manifest["files"].append(download(e["path"], rev, os.path.join(tdir, rel)))
                except Exception as ex:  # noqa: BLE001
                    manifest["errors"].append({"path": e["path"], "error": repr(ex)})
        names = {e["path"].split("/")[-1] for e in files if e.get("type") == "file"}
        rows.append({"task": tid, "files": sum(1 for e in files if e.get("type") == "file"),
                     "bytes": sum(int(e.get("size") or 0) for e in files if e.get("type") == "file"),
                     "instances": len(inst),
                     "instance_names": " ".join(sorted(e["path"].split("/")[-1] for e in inst)),
                     "largest_instance_bytes": max((int(e.get("size") or 0) for e in inst), default=0),
                     "has_checker": "feasibility_check.py" in names,
                     "has_description": "problem_description.txt" in names})
        print("task", tid, rows[-1]["files"], rows[-1]["instances"], rows[-1]["largest_instance_bytes"], flush=True)
        time.sleep(delay)
    with open(os.path.join(out, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    if rows:
        with open(os.path.join(out, "catalog.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    print("catalog done", len(rows), "tasks,", len(manifest["files"]), "files,", len(manifest["errors"]), "errors",
          flush=True)
    return manifest


def task(tid, dest, rev=None):
    """Every file of one task into dest/tasks/<tid>/...; returns a manifest (also written next to it)."""
    rev = rev or revision()
    files = tree("tasks/" + tid, rev, recursive=True)
    man = {"repo": REPO, "revision": rev, "task": tid, "files": []}
    for e in files:
        if e.get("type") != "file":
            continue
        d = os.path.join(dest, e["path"])
        man["files"].append(download(e["path"], rev, d, expect_size=int(e.get("size") or -1)))
    with open(os.path.join(dest, "tasks", tid, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1)
    print("task", tid, "revision", rev, "files", len(man["files"]), flush=True)
    return man


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("catalog")
    c.add_argument("--out", required=True)
    c.add_argument("--delay", type=float, default=0.2)
    c.add_argument("--only", nargs="*", default=None)
    t = sub.add_parser("task")
    t.add_argument("slug")
    t.add_argument("--dest", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "catalog":
        catalog(a.out, a.delay, a.only)
    else:
        task(a.slug, a.dest)


if __name__ == "__main__":
    sys.exit(main())

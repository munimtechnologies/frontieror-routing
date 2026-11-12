"""Download gpshim 0.2.0 and its census tools from MV2's public repository at a pinned commit.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python fetch_base.py <dest_dir>

Writes <dest_dir>/{gpshim.py, gp_solve.py, gpshim_census.py, test_gpshim.py} and gpshim_base.json naming the commit.
All four files come from munimtechnologies/frontieror-routing, folder gpshim/next/, at commit PINNED (the commit the
froc-gpshim02-v1 census and the CP-SAT A/B ran). If that commit cannot be read, the newest commit touching
gpshim/next/gpshim.py is used instead and reported, so a result always names the exact source it ran.
"""
import json
import os
import sys
import time
import urllib.request

REPO = "munimtechnologies/frontieror-routing"
FOLDER = "gpshim/next"
FILES = ("gpshim.py", "gp_solve.py", "gpshim_census.py", "test_gpshim.py")
PINNED = "0bea743ade89ee77bae0058bceaad18b93cc5e77"
UA = "MV2-of-Munim-Inc gpshim 0.2.1 test (mv2@munimtech.com)"


def get(url, tries=4):
    err = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retry network errors
            err = e
            time.sleep(2.0 * (k + 1))
    raise err


def fetch_all(sha):
    return {name: get("https://raw.githubusercontent.com/%s/%s/%s/%s" % (REPO, sha, FOLDER, name)) for name in FILES}


def main(argv):
    dest = argv[1] if len(argv) > 1 else "."
    used, bodies = PINNED, None
    try:
        bodies = fetch_all(PINNED)
    except Exception as e:  # noqa: BLE001
        print("pinned commit unreadable: %r" % (e,), flush=True)
    if bodies is None:
        commits = json.loads(get("https://api.github.com/repos/%s/commits?path=%s/gpshim.py&per_page=1"
                                 % (REPO, FOLDER)))
        used = commits[0]["sha"]
        bodies = fetch_all(used)
    text = bodies["gpshim.py"].decode("utf-8")
    if '__version__ = "0.2.0"' not in text or "def _gp_rows(self, rowsdef" not in text:
        raise SystemExit("unexpected gpshim.py at %s" % used)
    os.makedirs(dest, exist_ok=True)
    for name, body in bodies.items():
        with open(os.path.join(dest, name), "wb") as f:
            f.write(body)
    with open(os.path.join(dest, "gpshim_base.json"), "w", encoding="utf-8") as f:
        json.dump({"repo": REPO, "folder": FOLDER, "commit": used,
                   "bytes": {k: len(v) for k, v in bodies.items()}}, f)
    print("gpshim base", used, {k: len(v) for k, v in bodies.items()}, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

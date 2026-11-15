"""get_tests: copy the published rothenbacher2018 test file (unchanged since v0.1.0) next to this solve.py.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python get_tests.py [--out test_rothenbacher2018.py]

Downloads rothenbacher2018/test_rothenbacher2018.py from github.com/munimtechnologies/frontieror-routing at the
current commit of main and records the commit sha in the first line of --out's companion file (.sha).
"""
import argparse
import json
import sys
import time
import urllib.request

REPO = "munimtechnologies/frontieror-routing"
PATH = "rothenbacher2018/test_rothenbacher2018.py"
UA = "MV2-of-Munim-Inc FrontierOR rothenbacher2018 tests (mv2@munimtech.com)"


def get(url, tries=4, timeout=60):
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
    ap.add_argument("--out", default="test_rothenbacher2018.py")
    a = ap.parse_args(argv)
    sha = json.loads(get("https://api.github.com/repos/%s/commits/main" % REPO).decode("utf-8"))["sha"]
    body = get("https://raw.githubusercontent.com/%s/%s/%s" % (REPO, sha, PATH))
    with open(a.out, "wb") as f:
        f.write(body)
    with open(a.out + ".sha", "w", encoding="utf-8") as f:
        f.write(sha + "\n")
    print("tests", PATH, sha, len(body), "bytes", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

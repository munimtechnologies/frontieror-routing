"""Download gpshim 0.2.0 (the base this backend plugs into) from MV2's public repository at a pinned commit.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python fetch_base.py <dest_dir>

Writes <dest_dir>/gpshim.py and prints the commit used. The file is the published 0.2.0 candidate
(munimtechnologies/frontieror-routing, gpshim/next/gpshim.py, commit PINNED). If that commit cannot be read, the newest
commit touching the file is used instead, and that is reported, so a result always names the exact source it ran.
"""
import json
import os
import sys
import time
import urllib.request

REPO = "munimtechnologies/frontieror-routing"
PATH = "gpshim/next/gpshim.py"
PINNED = "0bea743ade89ee77bae0058bceaad18b93cc5e77"
UA = "MV2-of-Munim-Inc gpshim backend test (mv2@munimtech.com)"


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


def main(argv):
    dest = argv[1] if len(argv) > 1 else "."
    used, body = PINNED, None
    try:
        body = get("https://raw.githubusercontent.com/%s/%s/%s" % (REPO, PINNED, PATH))
    except Exception as e:  # noqa: BLE001
        print("pinned commit unreadable: %r" % (e,), flush=True)
    if body is None:
        commits = json.loads(get("https://api.github.com/repos/%s/commits?path=%s&per_page=1" % (REPO, PATH)))
        used = commits[0]["sha"]
        body = get("https://raw.githubusercontent.com/%s/%s/%s" % (REPO, used, PATH))
    text = body.decode("utf-8")
    if '__version__ = "0.2.0"' not in text or "def _solve_highspy(" not in text:
        raise SystemExit("unexpected gpshim.py at %s" % used)
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "gpshim.py"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(dest, "gpshim_base.json"), "w", encoding="utf-8") as f:
        json.dump({"repo": REPO, "path": PATH, "commit": used, "bytes": len(body)}, f)
    print("gpshim base", used, len(body), "bytes", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

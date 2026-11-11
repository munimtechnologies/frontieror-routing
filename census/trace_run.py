"""trace_run: run one FrontierOR feasibility_check.py unchanged and record every read of a key that is NOT there.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python trace_run.py --checker C --instance I --solution S --result R --trace T

json.load / json.loads are wrapped so that every JSON object the checker loads becomes a TDict (a dict subclass)
labelled "instance", "solution" or "other" by the file it came from. A TDict behaves exactly like a dict and only
records, when the key is absent: d.get(key[, default]) ("get"), key in d ("in"), d[key] raising KeyError
("getitem") and d.setdefault(key, default) ("setdefault"). Present keys are never recorded. The checker then runs as
__main__ with its usual arguments (--instance_path, --solution_path, --result_path), and writes its own result file.
Limits: a dict the checker copies (dict(d), d.copy(), {**d}) is a plain dict and is no longer traced; values that
are not JSON objects (lists, numbers) are not traced.
T gets {"status", "events": [{"src", "kind", "key", "default", "context", "count"}], "seconds"}.
"""
import argparse
import json
import os
import runpy
import sys
import time

_EVENTS = {}
_LABELS = {}
_orig_loads = json.loads


def _short(v, n=80):
    try:
        s = repr(v)
    except Exception:  # noqa: BLE001
        s = "<unrepr>"
    return s if len(s) <= n else s[:n] + "..."


def _rec(d, kind, key, default):
    src = getattr(d, "_src", "?")
    ctx = ",".join(sorted(str(k) for k in dict.keys(d))[:12])
    k = (src, kind, _short(key), _short(default) if kind in ("get", "setdefault") else "", ctx)
    _EVENTS[k] = _EVENTS.get(k, 0) + 1


class TDict(dict):
    def get(self, key, default=None):
        if not dict.__contains__(self, key):
            _rec(self, "get", key, default)
        return dict.get(self, key, default)

    def __contains__(self, key):
        r = dict.__contains__(self, key)
        if not r:
            _rec(self, "in", key, None)
        return r

    def __getitem__(self, key):
        try:
            return dict.__getitem__(self, key)
        except KeyError:
            _rec(self, "getitem", key, None)
            raise

    def setdefault(self, key, default=None):
        if not dict.__contains__(self, key):
            _rec(self, "setdefault", key, default)
        return dict.setdefault(self, key, default)


def _hook_for(label):
    def hook(d):
        t = TDict(d)
        t._src = label
        return t
    return hook


def traced_loads(s, *args, **kw):
    label = kw.pop("_label", "other")
    if args or "object_hook" in kw or "object_pairs_hook" in kw:
        return _orig_loads(s, *args, **kw)
    return _orig_loads(s, object_hook=_hook_for(label), **kw)


def traced_load(fp, *args, **kw):
    name = getattr(fp, "name", None)
    label = "other"
    if isinstance(name, str):
        label = _LABELS.get(os.path.realpath(name), "other")
    return traced_loads(fp.read(), *args, _label=label, **kw)


def install(instance, solution):
    _LABELS[os.path.realpath(instance)] = "instance"
    _LABELS[os.path.realpath(solution)] = "solution"
    json.load = traced_load
    json.loads = traced_loads


def events():
    return [{"src": k[0], "kind": k[1], "key": k[2], "default": k[3], "context": k[4], "count": c}
            for k, c in sorted(_EVENTS.items(), key=lambda kv: (kv[0][0], kv[0][2], kv[0][1]))]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--checker", required=True)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--solution", required=True)
    ap.add_argument("--result", required=True)
    ap.add_argument("--trace", required=True)
    a = ap.parse_args(argv)
    install(a.instance, a.solution)
    sys.argv = [a.checker, "--instance_path", a.instance, "--solution_path", a.solution, "--result_path", a.result]
    sys.path.insert(0, os.path.dirname(os.path.abspath(a.checker)))
    t0 = time.monotonic()
    status = "ok"
    try:
        runpy.run_path(a.checker, run_name="__main__")
    except SystemExit as e:
        status = "exit %s" % (e.code,)
    except BaseException as e:  # noqa: BLE001
        status = "error %s" % (_short(e, 300),)
    finally:
        json.loads = _orig_loads
        out = {"status": status, "seconds": round(time.monotonic() - t0, 3), "events": events()}
        with open(a.trace, "w", encoding="utf-8") as f:
            f.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

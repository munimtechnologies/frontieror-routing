#!/usr/bin/env python3
"""FrontierOR entry point (gp_solve) with gpshim_objfix and memory stage marks, for measurement runs.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python solve.py --problem <slug> --instance in.json --output out.json --time-limit 60

Same as gp_solve.py (the task's gurobi_code.py from the public FrontierOR benchmark runs unchanged, with gpshim
standing in for gurobipy, on HiGHS), plus:
- MV2_OBJFIX=1 (default) installs gpshim_objfix, so ObjVal is the original objective's value at the solution.
- If MV2_MEM_LOG names a file, JSON lines with this process's VmRSS / VmHWM (MB, from /proc/self/status) are
  appended at: start, after imports, every optimize() entry and exit, HiGHS entry (after the matrix is assembled in
  Python) and exit, normal exit, and once a second from a sampler thread together with the number of variables and
  constraints added so far. If the process is killed, the lines written up to then remain.
No OR-Tools is imported here (highspy and OR-Tools cannot share a process in the contest image).
"""
import argparse
import atexit
import json
import os
import runpy
import sys
import threading
import time
import weakref

T_START = time.time()
HERE = os.path.dirname(os.path.abspath(__file__))
_MODELS = []
_LOCK = threading.Lock()


def _proc():
    out = {}
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith(("VmRSS:", "VmHWM:")):
                    k, v = line.split(":", 1)
                    out[k.strip()] = round(int(v.split()[0]) / 1024.0, 1)
    except (OSError, ValueError):
        pass
    return out


def _counts():
    nv = nc = 0
    for r in list(_MODELS):
        m = r()
        if m is None:
            continue
        try:
            nv += len(object.__getattribute__(m, "_gpv"))
            nc += len(object.__getattribute__(m, "_gpc"))
        except Exception:  # noqa: BLE001
            pass
    return nv, nc


def mark(stage, **kw):
    p = os.environ.get("MV2_MEM_LOG")
    if not p:
        return
    rec = {"stage": stage, "t": round(time.time() - T_START, 3)}
    rec.update(_proc())
    rec.update(kw)
    with _LOCK:
        try:
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass


def _sampler(stop):
    while not stop.wait(1.0):
        nv, nc = _counts()
        mark("sample", vars=nv, constrs=nc)


def _hook(gp):
    orig_init = gp.Model.__init__

    def __init__(self, *a, **k):
        orig_init(self, *a, **k)
        _MODELS.append(weakref.ref(self))

    gp.Model.__init__ = __init__
    orig_opt = gp.Model.optimize
    calls = [0]

    def optimize(self, *a, **k):
        calls[0] += 1
        n = calls[0]
        mark("optimize_enter", call=n, vars=len(self._gpv), constrs=len(self._gpc))
        try:
            return orig_opt(self, *a, **k)
        finally:
            mark("optimize_exit", call=n)

    gp.Model.optimize = optimize
    orig_highs = gp._solve_highspy

    def _solve_highspy(n, m, cost, lb, ub, integ, rlo, rhi, rows, cols, vals, *rest, **kw):
        mark("highs_enter", n=n, m=m, nnz=len(vals))
        try:
            return orig_highs(n, m, cost, lb, ub, integ, rlo, rhi, rows, cols, vals, *rest, **kw)
        finally:
            mark("highs_exit")

    gp._solve_highspy = _solve_highspy


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    a = ap.parse_args(argv)
    mark("start")
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import gpshim
    if os.environ.get("MV2_OBJFIX", "1") != "0" and os.path.exists(os.path.join(HERE, "gpshim_objfix.py")):
        import gpshim_objfix
        gpshim_objfix.install(gpshim)
    if os.environ.get("MV2_MEM_LOG"):
        _hook(gpshim)
        stop = threading.Event()
        threading.Thread(target=_sampler, args=(stop,), daemon=True).start()
        atexit.register(lambda: (stop.set(), mark("exit")))
    mark("imported")
    T = float(a.time_limit)
    margin = max(2.0, 0.1 * T)
    gpshim.set_deadline(T_START + T - margin)
    sys.modules["gurobipy"] = gpshim
    code = os.path.join(HERE, "gurobi_code.py")
    sys.argv = [code, "--instance_path", os.path.abspath(a.instance), "--solution_path", os.path.abspath(a.output),
                "--time_limit", str(max(1, int(T - margin)))]
    runpy.run_path(code, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""gpshim_cpsat: an OR-Tools CP-SAT backend for gpshim (MV2's gurobipy-compatible layer on open-source solvers).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Not affiliated with or endorsed by Gurobi Optimization or Google. Uses OR-Tools (Apache-2.0) when it is installed.

    import gpshim, gpshim_cpsat
    gpshim_cpsat.install(gpshim)          # once; then run gurobipy-style code through gpshim as usual
    gpshim_cpsat.set_backend("cpsat")     # or MV2_GPSHIM_BACKEND=cpsat, or a file gpshim_backend.txt next to this one

0.3.1 (2026-11-12): CP-SAT now runs in a separate, long-lived worker process (gpshim_cpsat_worker.py, which must sit
next to this file). Reason: on Linux, highspy 1.15.x and OR-Tools 9.14/9.15 both ship a HiGHS shared library under the
same name, and whichever is imported second in a process fails with "undefined symbol" (google/or-tools issue 5246).
In 0.3.0 this silently sent every model back to HiGHS once gpshim had loaded highspy (FrontierOR A/B run
froc-gpshim-cpsat-v1: 0 of 180 tasks reached CP-SAT). This module itself never imports OR-Tools.

What it does: gpshim builds every model as one linear (MI)LP and normally hands it to HiGHS. With the backend set to
"cpsat", a model whose columns are all integer or binary goes to CP-SAT instead:
- each row is multiplied by the smallest power of ten (1 .. 10^6) that makes all its coefficients integral; its
  sides are then rounded inward (ceil the lower, floor the upper), which is exact because an integer row's activity
  is an integer; a row that needs more than 6 decimals keeps the model on HiGHS;
- variable bounds are rounded inward; an infinite bound becomes +-MV2_GPSHIM_CPSAT_CAP (default 10^9) and is counted
  in the log note ("capped"), because CP-SAT needs finite domains;
- the objective is scaled to integers the same way (up to 10^6); if that is impossible it is rounded at a scale that
  keeps about nine significant digits, and the note says so. ObjVal is always recomputed from the solution with the
  model's own (unrounded) costs;
- Var.Start values become CP-SAT hints; TimeLimit, MIPGap and Seed are passed on; the number of workers is
  MV2_GPSHIM_CPSAT_WORKERS (default 2, the contest sandbox's vCPU count) and the memory cap MV2_GPSHIM_CPSAT_MEM_MB
  (default 2500).
Anything else (continuous columns, quadratic objectives, too many nonzeros, a coefficient CP-SAT cannot hold, OR-Tools
missing in the worker, the worker crashing or overrunning) falls back to HiGHS in this process, and the reason is added
to gpshim's log note as "cpsat_skip: ...".
"""
import atexit
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

__version__ = "0.3.1"
_MODE = [None]
_SCALES = [10 ** k for k in range(7)]
_HUGE = 4.0e18  # stay well inside int64 for any activity CP-SAT has to represent
_WORKER = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "gpshim_cpsat_worker.py")]
_PREFIX = "MV2CPSAT "
_CHILD = {"p": None, "q": None, "dir": None, "err": None, "starts": 0}
_GRACE_S = 3.0


def set_backend(mode):
    """'highs' (default), 'cpsat', or None to go back to the environment / file setting."""
    _MODE[0] = None if mode is None else str(mode).strip().lower()


def backend_mode():
    if _MODE[0]:
        return _MODE[0]
    env = os.environ.get("MV2_GPSHIM_BACKEND")
    if env:
        return env.strip().lower()
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gpshim_backend.txt")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return (f.read().strip().lower() or "highs")
        except OSError:
            pass
    return "highs"


def _env_num(name, default, cast=float):
    try:
        return cast(os.environ.get(name, default))
    except ValueError:
        return cast(default)


def install(gp):
    """Route gpshim's core solve through CP-SAT when the backend is 'cpsat' and the model qualifies."""
    if getattr(gp.Model, "_mv2_cpsat_installed", False):
        return
    orig = gp.Model._gp_core

    def _gp_core(self, base, cost, objcon, sense, extra, hterms, limit):
        mode = backend_mode()
        reason = None
        if mode == "cpsat":
            if hterms:
                reason = "quadratic objective"
            else:
                t0 = time.time()
                rlo, rhi, ri, ci, va = base["rlo"], base["rhi"], base["ri"], base["ci"], base["va"]
                if extra:
                    rlo, rhi, ri, ci, va = list(rlo), list(rhi), list(ri), list(ci), list(va)
                    self._gp_rows(extra, rlo, rhi, ri, ci, va, len(base["rlo"]))
                try:
                    res, reason = solve_cpsat(gp, base["n"], cost, base["lb"], base["ub"], base["integ"], rlo, rhi,
                                              ri, ci, va, sense, objcon, max(0.05, limit), base["gap"], base["seed"],
                                              base.get("starts"))
                except Exception as e:  # noqa: BLE001 - never lose the model to a backend bug: HiGHS takes over
                    res, reason = None, "cpsat_error %r" % (e,)
                if res is not None:
                    return res
                limit = max(0.05, limit - (time.time() - t0))
        res = orig(self, base, cost, objcon, sense, extra, hterms, limit)
        if reason:
            res["note"] = ("%s; " % res["note"] if res.get("note") else "") + "cpsat_skip: " + str(reason)[:200]
        return res

    gp.Model._gp_core = _gp_core
    gp.Model._mv2_cpsat_installed = True
    gp.CPSAT_BACKEND_VERSION = __version__


def _int_scale(v):
    """Smallest 10^k (k <= 6) that makes every value in v integral (within 1e-9 relative), or None."""
    import numpy as np
    for s in _SCALES:
        w = v * s
        if not (np.abs(w - np.round(w)) > 1e-9 * np.maximum(1.0, np.abs(w))).any():
            return s
    return None


# ---------------------------------------------------------------- worker process
def _err_tail():
    p = _CHILD.get("err")
    if not p or not os.path.exists(p):
        return ""
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()[-300:].strip().replace("\n", " | ")
    except OSError:
        return ""


def stop_worker():
    """Stop the CP-SAT worker process (it is restarted on the next CP-SAT solve)."""
    p = _CHILD.get("p")
    _CHILD["p"] = None
    if p is not None:
        try:
            if p.poll() is None:
                try:
                    p.stdin.write(json.dumps({"quit": True}) + "\n")
                    p.stdin.flush()
                    p.stdin.close()
                except (OSError, ValueError):
                    pass
                try:
                    p.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=2.0)
        except Exception:  # noqa: BLE001 - shutting down
            pass
    d = _CHILD.get("dir")
    _CHILD["dir"] = None
    if d:
        shutil.rmtree(d, ignore_errors=True)


atexit.register(stop_worker)


def _wait_s(deadline_abs, floor):
    """Seconds to wait for the worker: time left (at least floor, at most ~11 days) plus a grace period."""
    left = deadline_abs - time.time()
    if not left == left:  # NaN
        left = floor
    return min(1e6, max(floor, left)) + _GRACE_S


def _reader(stream, q):
    try:
        for line in stream:
            if line.startswith(_PREFIX):
                try:
                    q.put(json.loads(line[len(_PREFIX):]))
                except ValueError:
                    pass
    finally:
        q.put(None)


def _worker(deadline_abs):
    """The live worker (Popen, queue), started if needed; or (None, reason)."""
    p = _CHILD.get("p")
    if p is not None and p.poll() is None:
        return p, _CHILD["q"]
    stop_worker()
    if not os.path.exists(_WORKER[0]):
        return None, "worker file missing (%s)" % os.path.basename(_WORKER[0])
    d = tempfile.mkdtemp(prefix="gpshim-cpsat-")
    _CHILD["dir"] = d
    _CHILD["err"] = os.path.join(d, "worker.err")
    errf = open(_CHILD["err"], "w", encoding="utf-8")
    try:
        p = subprocess.Popen([sys.executable, _WORKER[0], "--serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=errf, text=True, bufsize=1, cwd=d)
    except OSError as e:
        return None, "worker did not start (%r)" % (e,)
    finally:
        errf.close()
    q = queue.Queue()
    threading.Thread(target=_reader, args=(p.stdout, q), daemon=True).start()
    _CHILD["p"], _CHILD["q"] = p, q
    _CHILD["starts"] += 1
    try:
        hello = q.get(timeout=_wait_s(deadline_abs, 1.0))
    except queue.Empty:
        hello = None
    if not hello or not hello.get("ready"):
        why = "worker did not answer (exit %s) %s" % (p.poll(), _err_tail())
        stop_worker()
        return None, why
    return p, q


def _run_in_worker(arrays, deadline_abs):
    """Send one model to the worker. Returns (result dict, solution array or None) or (None, reason)."""
    import numpy as np
    p, q = _worker(deadline_abs)
    if p is None:
        return None, q
    d = _CHILD["dir"]
    _CHILD["seq"] = _CHILD.get("seq", 0) + 1
    inp = os.path.join(d, "m%d.npz" % _CHILD["seq"])
    outp = os.path.join(d, "r%d" % _CHILD["seq"])
    np.savez(inp, **arrays)
    try:
        p.stdin.write(json.dumps({"in": inp, "out": outp}) + "\n")
        p.stdin.flush()
    except (OSError, ValueError) as e:
        stop_worker()
        return None, "worker pipe closed (%r) %s" % (e, _err_tail())
    try:
        reply = q.get(timeout=_wait_s(deadline_abs, 0.5))
    except queue.Empty:
        reply = "timeout"
    if reply == "timeout" or reply is None:
        tail = _err_tail()
        stop_worker()
        return None, ("worker overran the time limit" if reply == "timeout" else "worker died %s" % tail)
    try:
        os.remove(inp)
    except OSError:
        pass
    if not reply.get("ok"):
        return None, "worker error %s" % reply.get("error")
    try:
        with open(outp + ".json", encoding="utf-8") as f:
            res = json.load(f)
    except (OSError, ValueError) as e:
        return None, "worker result unreadable (%r)" % (e,)
    sol = None
    if os.path.exists(outp + ".npy"):
        sol = np.load(outp + ".npy", allow_pickle=False)
        os.remove(outp + ".npy")
    os.remove(outp + ".json")
    return (res, sol), None


# ---------------------------------------------------------------- model translation
def solve_cpsat(gp, n, cost, lb, ub, integ, rlo, rhi, rows, cols, vals, sense, objcon, limit, gap, seed, starts):
    """Solve one gpshim core model with CP-SAT. Returns (result dict, None) or (None, reason to use HiGHS)."""
    import numpy as np
    t0 = time.time()
    deadline_abs = t0 + float(limit)
    GRB = gp.GRB
    if n == 0:
        return None, "empty model"
    nonint = sum(1 for t in integ if t not in ("B", "I"))
    if nonint:
        return None, "%d non-integer columns" % nonint
    nnz = len(vals)
    if nnz > _env_num("MV2_GPSHIM_CPSAT_MAX_NNZ", 3000000, int):
        return None, "too large (%d nonzeros)" % nnz
    cap = _env_num("MV2_GPSHIM_CPSAT_CAP", 1e9, float)
    infeasible = {"status": GRB.INFEASIBLE, "backend": "cpsat"}

    # variable domains, rounded inward
    lo = np.empty(n, dtype=np.int64)
    hi = np.empty(n, dtype=np.int64)
    capped = 0
    for j in range(n):
        l, h = float(lb[j]), float(ub[j])
        if integ[j] == "B":
            l, h = max(l, 0.0), min(h, 1.0)
        if not l > -1e30:
            l, capped = -cap, capped + 1
        if not h < 1e30:
            h, capped = cap, capped + 1
        if abs(l) > 2.0 ** 52 or abs(h) > 2.0 ** 52:
            return None, "a variable bound beyond 2^52"
        li, hi_ = math.ceil(l - 1e-6), math.floor(h + 1e-6)
        if li > hi_:
            infeasible["note"] = "cpsat: empty integer domain"
            return infeasible, None
        lo[j], hi[j] = li, hi_
    absmax = np.maximum(np.abs(lo), np.abs(hi)).astype(float)

    # rows: per-row power-of-ten scaling to integers
    m = len(rlo)
    ri = np.asarray(rows, dtype=np.int64)
    ci = np.asarray(cols, dtype=np.int64)
    va = np.asarray(vals, dtype=float)
    scale = np.ones(m)
    unresolved = np.ones(m, dtype=bool)
    for s in _SCALES:
        if not unresolved.any():
            break
        w = va * s
        badterm = np.abs(w - np.round(w)) > 1e-9 * np.maximum(1.0, np.abs(w))
        badrow = np.zeros(m, dtype=bool)
        if badterm.any():
            badrow[ri[badterm]] = True
        scale[unresolved & ~badrow] = s
        unresolved &= badrow
    if unresolved.any():
        return None, "%d rows need more than 6 decimals" % int(unresolved.sum())
    coef = np.round(va * scale[ri]) if nnz else np.zeros(0)
    if nnz and np.abs(coef).max() >= 2.0 ** 52:
        return None, "a coefficient beyond 2^52 after scaling"
    if nnz:
        act = np.bincount(ri, weights=np.abs(coef) * absmax[ci], minlength=m)
        if (act > _HUGE).any():
            return None, "possible integer overflow in %d rows (capped=%d)" % (int((act > _HUGE).sum()), capped)
    rl = np.asarray(rlo, dtype=float) * scale
    rh = np.asarray(rhi, dtype=float) * scale

    # objective: integral at a power of ten if possible, else rounded to about nine significant digits
    c = np.asarray(cost, dtype=float)
    cmax = float(np.abs(c).max()) if n else 0.0
    oscale, obj_note, cs = 1.0, None, None
    if cmax > 0:
        s = _int_scale(c)
        if s is not None and cmax * s < 2.0 ** 52:
            oscale = float(s)
        else:
            oscale = 10.0 ** math.floor(math.log10(1e9 / cmax))
            obj_note = "objective rounded at scale %g" % oscale
        cs = np.round(c * oscale)
        while float((np.abs(cs) * absmax).sum()) > _HUGE and oscale > 1e-12:
            oscale /= 10.0
            cs = np.round(c * oscale)
            obj_note = "objective rounded at scale %g" % oscale
        if float((np.abs(cs) * absmax).sum()) > _HUGE:
            return None, "objective overflow (capped=%d)" % capped

    # rows kept for the worker (CSR), with integer sides
    order = np.argsort(ri, kind="stable") if nnz else np.zeros(0, dtype=np.int64)
    ri_s = ri[order]
    bounds = np.searchsorted(ri_s, np.arange(m + 1)).tolist() if m else [0]
    keep = np.zeros(m, dtype=bool)
    k_lo, k_hi, k_loinf, k_hiinf = [], [], [], []
    for r in range(m):
        a, b = bounds[r], bounds[r + 1]
        l, h = float(rl[r]), float(rh[r])
        linf, hinf = not l > -1e30, not h < 1e30
        li = 0 if linf else math.ceil(l - 1e-9 * max(1.0, abs(l)))
        hi_ = 0 if hinf else math.floor(h + 1e-9 * max(1.0, abs(h)))
        if not linf and li < -_HUGE:
            linf, li = True, 0
        if not hinf and hi_ > _HUGE:
            hinf, hi_ = True, 0
        if not linf and not hinf and li > hi_:
            infeasible["note"] = "cpsat: row %d has no integer value between its sides" % r
            return infeasible, None
        if a == b:
            if (not linf and li > 0) or (not hinf and hi_ < 0):
                infeasible["note"] = "cpsat: empty row %d is violated" % r
                return infeasible, None
            continue
        if linf and hinf:
            continue
        keep[r] = True
        k_lo.append(li)
        k_hi.append(hi_)
        k_loinf.append(linf)
        k_hiinf.append(hinf)
    emask = keep[ri_s] if nnz else np.zeros(0, dtype=bool)
    counts = np.bincount(ri_s[emask], minlength=m)[keep] if nnz else np.zeros(0, dtype=np.int64)
    k_starts = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
    k_cols = ci[order][emask].astype(np.int64) if nnz else np.zeros(0, dtype=np.int64)
    k_coefs = coef[order][emask].astype(np.int64) if nnz else np.zeros(0, dtype=np.int64)
    if cs is not None:
        nzj = np.nonzero(cs)[0]
        obj_idx, obj_coef = nzj.astype(np.int64), cs[nzj].astype(np.int64)
    else:
        obj_idx, obj_coef = np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    h_idx, h_val = [], []
    if starts and len(starts) == n and all(sv is not None for sv in starts):
        for j, sv in enumerate(starts):
            iv = int(round(float(sv)))
            if lo[j] <= iv <= hi[j]:
                h_idx.append(j)
                h_val.append(iv)
    workers = max(1, _env_num("MV2_GPSHIM_CPSAT_WORKERS", 2, int))
    mem_mb = max(256, _env_num("MV2_GPSHIM_CPSAT_MEM_MB", 2500, int))
    try:
        g = float(gap)
    except (TypeError, ValueError):
        g = float("nan")
    sd = -1.0 if seed is None else float(int(seed) % (2 ** 31))
    arrays = {"lo": lo, "hi": hi, "starts": k_starts, "cols": k_cols, "coefs": k_coefs,
              "rlo": np.asarray(k_lo, dtype=np.int64), "rhi": np.asarray(k_hi, dtype=np.int64),
              "rlo_inf": np.asarray(k_loinf, dtype=bool), "rhi_inf": np.asarray(k_hiinf, dtype=bool),
              "obj_idx": obj_idx, "obj_coef": obj_coef,
              "hint_idx": np.asarray(h_idx, dtype=np.int64), "hint_val": np.asarray(h_val, dtype=np.int64),
              "params": np.asarray([deadline_abs, workers, mem_mb, g, sd, 1.0 if sense == GRB.MAXIMIZE else 0.0],
                                   dtype=float)}
    prep_s = time.time() - t0
    got, why = _run_in_worker(arrays, deadline_abs)
    if got is None:
        return None, why
    res, sol = got
    st = res.get("status")
    if st == "IMPORT_ERROR":
        return None, "OR-Tools missing in worker (%s)" % res.get("error")
    if st in ("REFUSED", "MODEL_INVALID"):
        return None, "CP-SAT refused the model: %s" % (res.get("error") or st)
    note = "cpsat workers=%d rows=%d capped=%d hints=%d build_s=%.2f status=%s child_import_s=%s child_build_s=%s" % (
        workers, len(k_lo), capped, len(h_idx), prep_s, st, res.get("import_s"), res.get("build_s"))
    if obj_note:
        note += "; " + obj_note
    out = {"backend": "cpsat", "note": note, "nodes": int(res.get("branches") or 0), "iters": 0}
    if st == "INFEASIBLE":
        out["status"] = GRB.INFEASIBLE
        return out, None
    if st not in ("OPTIMAL", "FEASIBLE") or sol is None or len(sol) != n:
        out["status"] = GRB.TIME_LIMIT
        return out, None
    x = np.asarray(sol, dtype=float)
    obj = float(c @ x) + float(objcon)
    out["status"] = GRB.OPTIMAL if st == "OPTIMAL" else GRB.TIME_LIMIT
    out["x"] = x.tolist()
    out["obj"] = obj
    out["row_value"] = np.bincount(ri, weights=va * x[ci], minlength=m).tolist() if m else []
    if cs is not None and oscale > 0 and res.get("bound") is not None:
        bound = float(res["bound"]) / oscale + float(objcon)
    else:
        bound = obj
    out["bound"] = bound
    out["gap"] = abs(obj - bound) / max(1e-10, abs(obj))
    return out, None

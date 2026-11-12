"""gpshim_cpsat: an OR-Tools CP-SAT backend for gpshim (MV2's gurobipy-compatible layer on open-source solvers).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Not affiliated with or endorsed by Gurobi Optimization or Google. Uses OR-Tools (Apache-2.0) when it is installed.

    import gpshim, gpshim_cpsat
    gpshim_cpsat.install(gpshim)          # once; then run gurobipy-style code through gpshim as usual
    gpshim_cpsat.set_backend("cpsat")     # or MV2_GPSHIM_BACKEND=cpsat, or a file gpshim_backend.txt next to this one

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
missing or refusing the model) falls back to HiGHS unchanged, and the reason is added to gpshim's log note as
"cpsat_skip: ...". Lazy-constraint callbacks and multiple objectives work as in gpshim 0.2, because they call the same
core solve.
"""
import math
import os
import time

__version__ = "0.3.0"
_MODE = [None]
_SCALES = [10 ** k for k in range(7)]
_HUGE = 4.0e18  # stay well inside int64 for any activity CP-SAT has to represent


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
                except ImportError as e:
                    res, reason = None, "OR-Tools missing (%s)" % (e,)
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


def solve_cpsat(gp, n, cost, lb, ub, integ, rlo, rhi, rows, cols, vals, sense, objcon, limit, gap, seed, starts):
    """Solve one gpshim core model with CP-SAT. Returns (result dict, None) or (None, reason to use HiGHS)."""
    import numpy as np
    t0 = time.time()
    GRB = gp.GRB
    if n == 0:
        return None, "empty model"
    nonint = sum(1 for t in integ if t not in ("B", "I"))
    if nonint:
        return None, "%d non-integer columns" % nonint
    nnz = len(vals)
    if nnz > _env_num("MV2_GPSHIM_CPSAT_MAX_NNZ", 3000000, int):
        return None, "too large (%d nonzeros)" % nnz
    from ortools.sat.python import cp_model  # ImportError -> HiGHS
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

    # build
    M = cp_model.CpModel()
    lo_l, hi_l = lo.tolist(), hi.tolist()
    xs = [M.new_int_var(lo_l[j], hi_l[j], "") for j in range(n)]
    order = np.argsort(ri, kind="stable") if nnz else np.zeros(0, dtype=np.int64)
    ri_s = ri[order]
    ci_s = ci[order].tolist()
    co_s = coef[order].astype(np.int64).tolist() if nnz else []
    bounds = np.searchsorted(ri_s, np.arange(m + 1)).tolist() if m else [0]
    n_rows = 0
    for r in range(m):
        a, b = bounds[r], bounds[r + 1]
        l, h = float(rl[r]), float(rh[r])
        linf, hinf = not l > -1e30, not h < 1e30
        li = cp_model.INT_MIN if linf else math.ceil(l - 1e-9 * max(1.0, abs(l)))
        hi_ = cp_model.INT_MAX if hinf else math.floor(h + 1e-9 * max(1.0, abs(h)))
        if not linf and li < -_HUGE:
            li = cp_model.INT_MIN
        if not hinf and hi_ > _HUGE:
            hi_ = cp_model.INT_MAX
        if li > hi_:
            infeasible["note"] = "cpsat: row %d has no integer value between its sides" % r
            return infeasible, None
        if a == b:
            if li > 0 or hi_ < 0:
                infeasible["note"] = "cpsat: empty row %d is violated" % r
                return infeasible, None
            continue
        if linf and hinf:
            continue
        M.add_linear_constraint(cp_model.LinearExpr.weighted_sum([xs[j] for j in ci_s[a:b]], co_s[a:b]), li, hi_)
        n_rows += 1
    if cs is not None:
        nzj = np.nonzero(cs)[0].tolist()
        if nzj:
            expr = cp_model.LinearExpr.weighted_sum([xs[j] for j in nzj], [int(cs[j]) for j in nzj])
            if sense == GRB.MAXIMIZE:
                M.maximize(expr)
            else:
                M.minimize(expr)
    hints = 0
    if starts and len(starts) == n and all(sv is not None for sv in starts):
        for j, sv in enumerate(starts):
            iv = int(round(float(sv)))
            if lo_l[j] <= iv <= hi_l[j]:
                M.add_hint(xs[j], iv)
                hints += 1
    validate = getattr(M, "validate", None) or getattr(M, "Validate", None)
    if validate is not None:
        msg = validate()
        if msg:
            return None, "CP-SAT refused the model: %s" % str(msg)[:160]

    # solve
    build_s = time.time() - t0
    S = cp_model.CpSolver()
    p = S.parameters
    p.max_time_in_seconds = max(0.05, float(limit) - build_s)
    workers = max(1, _env_num("MV2_GPSHIM_CPSAT_WORKERS", 2, int))
    p.num_workers = workers
    p.max_memory_in_mb = max(256, _env_num("MV2_GPSHIM_CPSAT_MEM_MB", 2500, int))
    try:
        p.relative_gap_limit = float(gap)
    except (TypeError, ValueError):
        pass
    if seed is not None:
        p.random_seed = int(seed) % (2 ** 31)
    st = S.solve(M)
    note = "cpsat workers=%d rows=%d capped=%d hints=%d build_s=%.2f status=%s" % (
        workers, n_rows, capped, hints, build_s, S.status_name(st))
    if obj_note:
        note += "; " + obj_note
    out = {"backend": "cpsat", "note": note, "nodes": int(getattr(S, "num_branches", 0) or 0), "iters": 0}
    if st == cp_model.MODEL_INVALID:
        return None, "CP-SAT reported MODEL_INVALID"
    if st == cp_model.INFEASIBLE:
        out["status"] = GRB.INFEASIBLE
        return out, None
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        out["status"] = GRB.TIME_LIMIT
        return out, None
    sol = None
    try:
        sol = list(S.response_proto.solution)
    except Exception:  # noqa: BLE001
        sol = None
    if sol is None or len(sol) != n:
        sol = [S.value(x) for x in xs]
    x = np.asarray(sol, dtype=float)
    obj = float(c @ x) + float(objcon)
    out["status"] = GRB.OPTIMAL if st == cp_model.OPTIMAL else GRB.TIME_LIMIT
    out["x"] = x.tolist()
    out["obj"] = obj
    out["row_value"] = np.bincount(ri, weights=va * x[ci], minlength=m).tolist() if m else []
    if cs is not None and oscale > 0:
        bound = float(S.best_objective_bound) / oscale + float(objcon)
    else:
        bound = obj
    out["bound"] = bound
    out["gap"] = abs(obj - bound) / max(1e-10, abs(obj))
    return out, None

"""FrontierOR practice problem hoffman1993: set partitioning (airline crew scheduling), minimise cost.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Model: min c x  s.t.  A x = 1 (every flight leg covered exactly once),  d1 <= D x <= d2 (crew bases, if any),
x binary.

v0.2.0 (after v0.1.0 wrote no solution at all within 60 s on four large OR-Library instances, nw05/nw14/nw16/nw17):
1. LP relaxation with HiGHS (scipy.optimize.linprog). If its solution is integral and feasible, it is optimal.
2. Lagrangian bound from the LP duals y: L(y) = sum(y) + sum_j min(0, c_j - a_j.y). It is a valid lower bound for ANY
   y (the base rows are simply dropped, which only weakens it), so a wrong dual sign or a solver tolerance can make it
   weaker but never wrong. Both y and -y are tried and the stronger one is kept.
3. Restricted MIP: HiGHS on the columns with the smallest reduced cost (plus the LP support), growing x4 while it is
   infeasible. This gives a first incumbent within seconds.
4. Reduced-cost pruning: a column j can be in a solution strictly better than the incumbent only if
   L + max(0, rc_j) <= incumbent - 1 (integer costs). All other columns are dropped, exactly, and HiGHS solves the
   rest with the remaining time. If that problem is solved (or infeasible), the incumbent is proven optimal.
5. If time remains and the pruned problem is not too large, OR-Tools CP-SAT hinted with the incumbent.
If the LP route fails for any reason, the v0.1.0 portfolio runs (HiGHS on everything, then CP-SAT).
Every solution is checked here (exact cover, base bounds) before it is offered to the incumbent.

GUESSES, to be confirmed against tiny_instance.json and the official checker once the account exists:
- leg indices in constraint_matrix_A.columns may be 0- or 1-based: detected from the data (see leg_base);
- selected_rotations and the variable_values keys are taken to be 0-based positions in cost_vector (ROT_BASE).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import frontier_runtime as R  # noqa: E402  (imported first: its clock starts here)

VERSION = "0.2.0"
ROT_BASE = 0  # GUESS (see above)
FULL_VALUES_MAX_COLS = 400000  # above this, variable_values lists only the selected rotations (16 MB output cap)
HIGHS_SHARE = 0.65  # v0.1.0 fallback only
LP_SHARE = 0.35  # of the time left when the LP starts
HEUR_SHARE = 0.45  # of the time left when the restricted MIP starts
HEUR_K_MIN = 1000  # first restricted MIP: at least this many columns ...
HEUR_K_PER_ROW = 5  # ... or this many per row
CPSAT_MAX_COLS = 60000


def leg_base(columns, num_rows):
    lo = min((min(c) for c in columns if c), default=0)
    hi = max((max(c) for c in columns if c), default=0)
    if lo == 0:
        return 0
    if hi >= num_rows:
        return 1
    return 1 if lo >= 1 else 0


def load(inst):
    m = int(inst["dimensions"]["num_rows"])
    n = int(inst["dimensions"]["num_cols"])
    cost = [float(c) for c in inst["cost_vector"]]
    raw = inst["constraint_matrix_A"]["columns"]
    if len(cost) != n or len(raw) != n:
        raise ValueError("num_cols does not match cost_vector / columns")
    b = leg_base(raw, m)
    cols = [sorted(set(int(i) - b for i in c)) for c in raw]
    for c in cols:
        if c and (c[0] < 0 or c[-1] >= m):
            raise ValueError("leg index out of range")
    base = None
    bc = inst.get("base_constraints") or {}
    if inst.get("has_base_constraints") and bc.get("num_bases", 0):
        base = {"D": [[float(v) for v in row] for row in bc["D_matrix"]["rows"]],
                "lo": [float(v) for v in bc["lower_bounds_d1"]],
                "hi": [float(v) for v in bc["upper_bounds_d2"]]}
    return {"m": m, "n": n, "cost": cost, "cols": cols, "base": base, "leg_base": b,
            "int_costs": all(float(c).is_integer() for c in cost), "best": None}


def check(P, chosen, tol=1e-6):
    cover = [0] * P["m"]
    for j in chosen:
        for i in P["cols"][j]:
            cover[i] += 1
    if any(c != 1 for c in cover):
        return False
    if P["base"]:
        for row, lo, hi in zip(P["base"]["D"], P["base"]["lo"], P["base"]["hi"]):
            s = sum(row[j] for j in chosen)
            if s < lo - tol or s > hi + tol:
                return False
    return True


def solution(P, chosen):
    chosen = sorted(set(int(j) for j in chosen))
    obj = sum(P["cost"][j] for j in chosen)
    sel = set(chosen)
    if P["n"] <= FULL_VALUES_MAX_COLS:
        values = {str(j + ROT_BASE): (1.0 if j in sel else 0.0) for j in range(P["n"])}
    else:
        values = {str(j + ROT_BASE): 1.0 for j in chosen}
    return obj, {"objective_value": obj, "selected_rotations": [j + ROT_BASE for j in chosen],
                 "variable_values": values}


def offer(P, inc, chosen, source):
    chosen = [int(j) for j in chosen]
    if not check(P, chosen):
        return False
    obj, sol = solution(P, chosen)
    kept = inc.offer(obj, sol, source)
    if kept:
        P["best"] = sorted(set(chosen))
    return kept


# ------------------------------------------------------------------ matrices and HiGHS
def _arrays(P):
    """(A as a scipy CSC matrix m x n, c as a numpy vector, D as a dense numpy matrix or None), built once."""
    if P.get("_A") is None:
        import numpy as np
        from scipy.sparse import csc_matrix
        indptr, idx = [0], []
        for c in P["cols"]:
            idx.extend(c)
            indptr.append(len(idx))
        A = csc_matrix((np.ones(len(idx)), np.array(idx, dtype=np.int64), np.array(indptr, dtype=np.int64)),
                       shape=(P["m"], P["n"]))
        D = np.array(P["base"]["D"], dtype=float) if P["base"] else None
        P["_A"] = (A, np.array(P["cost"], dtype=float), D)
    return P["_A"]


def _milp(P, seconds, subset=None):
    """HiGHS branch-and-cut on all columns or on `subset` (column positions). Returns (chosen or None, code) with code
    'optimal' (proven within the subset), 'infeasible' (proven within the subset), 'limit' or 'other'."""
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    A, c, D = _arrays(P)
    idx = None
    if subset is not None:
        idx = np.asarray(subset, dtype=np.int64)
        if idx.size == 0:
            return None, ("optimal" if P["m"] == 0 else "infeasible")
        A, c = A[:, idx], c[idx]
        if D is not None:
            D = D[:, idx]
    n = A.shape[1]
    cons = [LinearConstraint(A, np.ones(P["m"]), np.ones(P["m"]))]
    if D is not None:
        from scipy.sparse import csr_matrix
        cons.append(LinearConstraint(csr_matrix(D), np.array(P["base"]["lo"], dtype=float),
                                     np.array(P["base"]["hi"], dtype=float)))
    res = milp(c=c, integrality=np.ones(n), bounds=Bounds(0, 1), constraints=cons,
               options={"time_limit": max(0.5, float(seconds)), "mip_rel_gap": 0.0, "disp": False})
    code = {0: "optimal", 1: "limit", 2: "infeasible"}.get(res.status, "other")
    if res.x is None:
        return None, code
    loc = np.flatnonzero(np.asarray(res.x) > 0.5)
    chosen = [int(idx[t]) for t in loc] if idx is not None else [int(t) for t in loc]
    return chosen, code


def run_highs(P, seconds):
    """HiGHS on the whole problem. Returns (chosen or None, proven_optimal)."""
    chosen, code = _milp(P, seconds)
    return chosen, code == "optimal"


def run_lp(P, seconds):
    """LP relaxation (with the base rows). Returns {"x", "y" (equality duals or None), "fun"} or None."""
    import numpy as np
    from scipy.optimize import linprog
    A, c, D = _arrays(P)
    from scipy.sparse import csr_matrix
    kw = {}
    if D is not None:
        kw["A_ub"] = csr_matrix(np.vstack([D, -D]))  # sparse like A_eq, so linprog never mixes the two kinds
        kw["b_ub"] = np.concatenate([np.array(P["base"]["hi"], dtype=float),
                                     -np.array(P["base"]["lo"], dtype=float)])
    res = linprog(c, A_eq=A, b_eq=np.ones(P["m"]), bounds=(0, 1), method="highs",
                  options={"time_limit": max(0.5, float(seconds))}, **kw)
    if res.status != 0 or res.x is None:
        return None
    y = None
    eq = getattr(res, "eqlin", None)
    if eq is not None:
        y = getattr(eq, "marginals", None)
    return {"x": np.asarray(res.x, dtype=float), "y": None if y is None else np.asarray(y, dtype=float),
            "fun": float(res.fun)}


# ------------------------------------------------------------------ bound and pruning
def lagrangian(P, y):
    """(L, rc) with rc = c - A^T y and L = sum(y) + sum_j min(0, rc_j): a lower bound on every feasible cost, for any
    y. A feasible x has c.x = sum(y) + rc.x, and rc.x >= sum_j min(0, rc_j) because 0 <= x <= 1."""
    import numpy as np
    A, c, _ = _arrays(P)
    y = np.asarray(y, dtype=float)
    rc = c - A.T.dot(y)
    return float(y.sum() + np.minimum(rc, 0.0).sum()), rc


def best_lagrangian(P, y):
    import numpy as np
    a = lagrangian(P, y)
    b = lagrangian(P, -np.asarray(y, dtype=float))
    return a if a[0] >= b[0] else b


def _threshold(P, ub):
    """Largest cost a strictly better solution can have, and a float tolerance that only ever keeps more."""
    thr = ub - 1.0 if P["int_costs"] else ub
    return thr, 1e-7 * max(1.0, abs(ub)) + 1e-6


def keep_columns(P, L, rc, ub):
    """Positions of the columns that can still be in a solution strictly better than ub. A solution that uses
    column j costs at least L + max(0, rc_j), so every other column is proven useless."""
    import numpy as np
    thr, eps = _threshold(P, ub)
    return np.flatnonzero(L + np.maximum(rc, 0.0) <= thr + eps)


def proven_by_bound(P, L, ub):
    thr, eps = _threshold(P, ub)
    return L > thr + eps


# ------------------------------------------------------------------ heuristic and exact phases
def restricted(P, inc, clock, rc, x, seconds):
    """HiGHS on the k columns of smallest reduced cost (plus the LP support), k growing x4 while infeasible.
    Returns (attempts, proven_global)."""
    import numpy as np
    n, m = P["n"], P["m"]
    t_end = clock.elapsed() + seconds
    order = np.argsort(rc, kind="stable")
    support = np.flatnonzero(x > 1e-6) if x is not None else np.zeros(0, dtype=np.int64)
    k = min(n, max(HEUR_K_MIN, HEUR_K_PER_ROW * m, 2 * int(support.size)))
    tried = []
    while True:
        left = min(t_end - clock.elapsed(), clock.remaining())
        if left < 0.3:
            break
        sub = np.union1d(order[:k], support).astype(np.int64)
        chosen, code = _milp(P, left, sub)
        tried.append([int(sub.size), code])
        if chosen is not None:
            offer(P, inc, chosen, "restricted")
            return tried, (code == "optimal" and int(sub.size) == n)
        if code != "limit" and k < n:  # infeasible (HiGHS may also say 'other') with too few columns: grow
            k = min(n, 4 * k)
            continue
        return tried, (code == "infeasible" and int(sub.size) == n)
    return tried, False


def lp_route(P, clock, inc, log):
    """Steps 1-5 of the module docstring. Returns False only if the LP could not be solved."""
    import numpy as np
    lp = run_lp(P, clock.share(LP_SHARE))
    if lp is None:
        log["lp"] = "failed"
        return False
    x = lp["x"]
    log["lp"] = round(lp["fun"], 6)
    log["lp_s"] = round(clock.elapsed(), 2)
    frac = np.minimum(np.abs(x), np.abs(1.0 - x))
    if x.size and float(frac.max()) < 1e-6:
        chosen = [int(j) for j in np.flatnonzero(x > 0.5)]
        if check(P, chosen):
            offer(P, inc, chosen, "lp")
            log["proven"] = "lp_integral"
            return True
    y = lp["y"] if lp["y"] is not None else np.zeros(P["m"])
    L, rc = best_lagrangian(P, y)
    log["L"] = round(L, 6)
    tried, proven = restricted(P, inc, clock, rc, x, clock.share(HEUR_SHARE))
    log["restricted"] = tried
    log["restricted_s"] = round(clock.elapsed(), 2)
    if proven:
        log["proven"] = "restricted_was_full"
        return True
    if inc.value is None:  # no first solution: give HiGHS the whole problem for the rest of the time
        if clock.remaining() >= 0.5:
            chosen, code = _milp(P, clock.remaining())
            if chosen is not None:
                offer(P, inc, chosen, "full")
            log["full"] = code
        return True
    if proven_by_bound(P, L, inc.value):
        log["proven"] = "bound"
        return True
    keep = keep_columns(P, L, rc, inc.value)
    log["kept"] = int(keep.size)
    if keep.size == 0:
        log["proven"] = "pruned_to_nothing"
        return True
    if clock.remaining() < 0.5:
        return True
    chosen, code = _milp(P, clock.remaining(), keep)
    if chosen is not None:
        offer(P, inc, chosen, "pruned")
    log["pruned"] = code
    if code in ("optimal", "infeasible"):
        log["proven"] = "pruned_" + code
        return True
    if clock.remaining() > 2.0 and keep.size <= CPSAT_MAX_COLS:
        try:
            run_cpsat(P, clock.remaining(), inc, hint=P.get("best"), subset=keep)
            log["cpsat"] = "ran"
        except Exception as e:  # noqa: BLE001 - keep what HiGHS found
            sys.stderr.write("cpsat failed: %r\n" % (e,))
    return True


# ------------------------------------------------------------------ CP-SAT
def _f(obj, *names):
    for nm in names:
        f = getattr(obj, nm, None)
        if f is not None:
            return f
    raise AttributeError(names[0])


def _integer_scale(values, max_pow=6):
    """Smallest 10^k (k <= max_pow) that makes every value an integer, else None."""
    for k in range(max_pow + 1):
        s = 10 ** k
        if all(abs(v * s - round(v * s)) < 1e-9 * max(1.0, abs(v * s)) for v in values):
            return s
    return None


def run_cpsat(P, seconds, inc, hint=None, workers=2, subset=None):
    """CP-SAT on all columns or on `subset`. Returns True if it proved optimality (within the subset)."""
    from ortools.sat.python import cp_model
    J = list(range(P["n"])) if subset is None else [int(j) for j in subset]
    rows = [[] for _ in range(P["m"])]
    for t, j in enumerate(J):
        for i in P["cols"][j]:
            rows[i].append(t)
    if any(not r for r in rows):
        return False  # some leg has no column left: nothing to search
    md = cp_model.CpModel()
    wsum = _f(cp_model.LinearExpr, "weighted_sum", "WeightedSum")
    nb = _f(md, "new_bool_var", "NewBoolVar")
    x = [nb("x%d" % j) for j in J]
    exactly_one = _f(md, "add_exactly_one", "AddExactlyOne")
    for r in rows:
        exactly_one([x[t] for t in r])
    if P["base"]:
        flat = [v for row in P["base"]["D"] for v in row] + P["base"]["lo"] + P["base"]["hi"]
        s = _integer_scale(flat)
        if s is None:
            return False  # weights not exact in CP-SAT's integers: leave base-constrained cases to HiGHS
        for row, lo, hi in zip(P["base"]["D"], P["base"]["lo"], P["base"]["hi"]):
            ts = [t for t, j in enumerate(J) if row[j]]
            expr = wsum([x[t] for t in ts], [int(round(row[J[t]] * s)) for t in ts])
            _f(md, "add", "Add")(expr >= int(round(lo * s)))
            _f(md, "add", "Add")(expr <= int(round(hi * s)))
    cs = _integer_scale(P["cost"]) or 1
    ts = [t for t, j in enumerate(J) if P["cost"][j]]
    _f(md, "minimize", "Minimize")(wsum([x[t] for t in ts], [int(round(P["cost"][J[t]] * cs)) for t in ts]))
    if hint:
        hs = set(hint)
        add_hint = _f(md, "add_hint", "AddHint")
        for t, j in enumerate(J):
            add_hint(x[t], 1 if j in hs else 0)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.5, seconds)
    solver.parameters.num_workers = workers

    class CB(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.val = _f(self, "boolean_value", "BooleanValue")

        def on_solution_callback(self):
            chosen = [J[t] for t in range(len(J)) if self.val(x[t])]
            offer(P, inc, chosen, "cpsat")

    cb = CB()
    status = _f(solver, "solve", "Solve")(md, cb)
    return status == cp_model.OPTIMAL


# ------------------------------------------------------------------ entry
def solve(instance, clock, inc, args=None):
    P = load(instance)
    log = {"version": VERSION, "m": P["m"], "n": P["n"]}
    if P["m"] == 0:
        offer(P, inc, [], "empty")
        return log
    if P["n"] == 0:
        return log
    done = False
    try:
        done = lp_route(P, clock, inc, log)
    except Exception as e:  # noqa: BLE001 - fall back to the v0.1.0 portfolio
        sys.stderr.write("lp route failed: %r\n" % (e,))
        log["lp_route_error"] = repr(e)[:200]
    if not done and clock.remaining() >= 1.0:
        chosen, proven = None, False
        try:
            chosen, proven = run_highs(P, clock.share(HIGHS_SHARE))
        except Exception as e:  # noqa: BLE001 - fall through to CP-SAT
            sys.stderr.write("highs failed: %r\n" % (e,))
        if chosen is not None:
            offer(P, inc, chosen, "highs")
        if not proven and clock.remaining() >= 1.0:
            try:
                run_cpsat(P, clock.remaining(), inc, hint=P.get("best"))
            except Exception as e:  # noqa: BLE001 - keep what HiGHS found
                sys.stderr.write("cpsat failed: %r\n" % (e,))
        log["fallback"] = "v0.1.0"
    log["value"] = inc.value
    log["s"] = round(clock.elapsed(), 2)
    sys.stderr.write("spp log %s\n" % json.dumps(log, default=str))
    return log


if __name__ == "__main__":
    R.main(solve, "min")

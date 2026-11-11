"""FrontierOR practice problem hoffman1993: set partitioning (airline crew scheduling), minimise cost.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Model: min c x  s.t.  A x = 1 (every flight leg covered exactly once),  d1 <= D x <= d2 (crew bases, if any),
x binary.

v0.4.0 (2026-11-11): adds an exact-cover depth-first search (ExactCover below) between the LP and the MIP phases.
On the public FrontierOR instances (100 legs x 15,000 dense rotations) v0.3.0 wrote NOTHING on 3 of 5: its
restricted HiGHS MIP on 1,000 columns hit its time slice without a first solution, and so did HiGHS on all columns,
while Gurobi solved the same three in under a second. A partition of a dense instance needs only a few columns,
so a search that picks the leg with the fewest compatible rotations, tries those rotations cheapest-bound first, and
drops every rotation that overlaps the legs already covered, finds feasible partitions quickly. Its bounds:
- ratio bound: a partition of the open legs U costs sum_i (y_i + rc_j(i)/|S_j(i)|) >= sum_{i in U} (y_i + min over
  compatible j containing i of rc_j/|S_j|), with rc_j = c_j - sum_{i in S_j} y_i. It holds for ANY y; y = 0 (plain
  cost per leg) and y = the LP duals are both used and the larger is kept;
- Lagrangian column filter (as in v0.3.0): a solution using rotation j costs at least L + max(0, rc_j), so once an
  incumbent exists every rotation that cannot beat it is dropped.
If the search ends inside its time slice, it has proved the incumbent optimal (or the problem infeasible). Otherwise
phase 2 runs on the columns the Lagrangian filter keeps: OR-Tools CP-SAT hinted with the incumbent (default), or
HiGHS. An optional spp_config.json next to this file ({"phase2": "cpsat" | "highs" | "dfs", "dfs_share": 0.5,
"log_file": false}) selects the variant (log_file: also write the run log to <output>.log.json); the contest folder
has no such file and uses the defaults.

v0.3.0: the instance is read exactly the way the official FrontierOR feasibility_check.py and gurobi_code.py read it
(Hugging Face frontieror/FrontierOR, tasks/hoffman1993, CC BY 4.0): 0-based legs, indices outside [0, num_rows)
ignored, only the first num_cols columns, missing costs = 0, base rows when has_base_constraints is true.
selected_rotations and the variable_values keys are 0-based positions in cost_vector.
v0.2.0 method (kept): LP relaxation (HiGHS), Lagrangian bound from its duals, restricted MIP, reduced-cost pruning,
HiGHS on the pruned problem, CP-SAT. Every solution is checked here (exact cover, base bounds) before it is offered.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import frontier_runtime as R  # noqa: E402  (imported first: its clock starts here)

VERSION = "0.4.0"
ROT_BASE = 0  # confirmed by the official checker: rotation indices lie in [0, num_cols)
FULL_VALUES_MAX_COLS = 400000  # above this, variable_values lists only the selected rotations (16 MB output cap)
HIGHS_SHARE = 0.65  # v0.1.0 fallback only
LP_SHARE = 0.35  # of the time left when the LP starts
HEUR_SHARE = 0.45  # of the time left when the restricted MIP starts
HEUR_K_MIN = 1000  # first restricted MIP: at least this many columns ...
HEUR_K_PER_ROW = 5  # ... or this many per row
CPSAT_MAX_COLS = 60000
DFS_SHARE = 0.5  # of the time left after the LP, for the exact-cover search (unless phase2 == "dfs": all of it)
DFS_MAX_CELLS = 60000000  # rows x columns above this: no exact-cover search (its boolean matrix would be too big)
DEFAULT_CONFIG = {"phase2": "cpsat", "dfs_share": DFS_SHARE, "log_file": False}


def load_config(folder=HERE):
    cfg = dict(DEFAULT_CONFIG)
    p = os.path.join(folder, "spp_config.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                got = json.load(f)
            if got.get("phase2") in ("cpsat", "highs", "dfs"):
                cfg["phase2"] = got["phase2"]
            if isinstance(got.get("dfs_share"), (int, float)) and 0.0 < float(got["dfs_share"]) <= 1.0:
                cfg["dfs_share"] = float(got["dfs_share"])
            if isinstance(got.get("log_file"), bool):
                cfg["log_file"] = got["log_file"]
        except Exception:  # noqa: BLE001 - a broken config file must never cost the run
            pass
    return cfg


def load(inst):
    """Read the instance the way the official checker does (see the module docstring)."""
    m = int(inst["dimensions"]["num_rows"])
    n = int(inst["dimensions"]["num_cols"])
    raw_cost = inst.get("cost_vector") or []
    raw = inst["constraint_matrix_A"]["columns"]
    cost = [float(raw_cost[j]) if j < len(raw_cost) else 0.0 for j in range(n)]
    cols = []
    dropped = 0
    for j in range(n):
        c = raw[j] if j < len(raw) else []
        idx = [int(i) for i in c]
        keep = sorted(set(i for i in idx if 0 <= i < m))
        dropped += sum(1 for i in idx if not 0 <= i < m)
        cols.append(keep)
    base = None
    bc = inst.get("base_constraints")
    if inst.get("has_base_constraints", False) and bc is not None:
        rows = bc["D_matrix"]["rows"]
        k = int(bc.get("num_constraints", len(rows)))
        if k > 0:
            base = {"D": [[float(row[j]) if j < len(row) else 0.0 for j in range(n)] for row in rows[:k]],
                    "lo": [float(v) for v in bc["lower_bounds_d1"][:k]],
                    "hi": [float(v) for v in bc["upper_bounds_d2"][:k]]}
    return {"m": m, "n": n, "cost": cost, "cols": cols, "base": base,
            "extra_columns_ignored": max(0, len(raw) - n), "row_indices_ignored": dropped,
            "short_columns": max(0, n - len(raw)),
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
    """(L, rc, y_used): the stronger of y and -y (the dual sign convention of the LP solver does not matter)."""
    import numpy as np
    y = np.asarray(y, dtype=float)
    a = lagrangian(P, y)
    b = lagrangian(P, -y)
    return (a[0], a[1], y) if a[0] >= b[0] else (b[0], b[1], -y)


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


# ------------------------------------------------------------------ exact-cover search (v0.4.0)
class _Stop(Exception):
    pass


class ExactCover:
    """Depth-first exact-cover branch and bound (see the module docstring). `run()` returns True when the whole tree
    was searched (the incumbent is then optimal, or the problem has no partition), False when time ran out."""

    def __init__(self, P, inc, clock, t_end, y=None, L=None, rc=None):
        import numpy as np
        self.np = np
        self.P, self.inc, self.clock, self.t_end = P, inc, clock, float(t_end)
        m, n = P["m"], P["n"]
        B = np.zeros((n, m), dtype=bool)
        for j, c in enumerate(P["cols"]):
            if c:
                B[j, c] = True
        self.B = B
        self.cols = [np.asarray(c, dtype=np.int64) for c in P["cols"]]
        self.cost = np.asarray(P["cost"], dtype=float)
        size = B.sum(axis=1)
        nonempty = size > 0
        # A rotation that covers no leg never changes the partition. Without base rows, every optimal solution takes
        # each such rotation of negative cost, so they are added at every leaf and their sum is a constant.
        self.extra, self.const = [], 0.0
        if P["base"] is None:
            self.extra = [int(j) for j in np.flatnonzero((~nonempty) & (self.cost < 0))]
            self.const = float(self.cost[self.extra].sum()) if self.extra else 0.0
        self.cand0 = np.flatnonzero(nonempty).astype(np.int64)
        safe = np.where(nonempty, size, 1).astype(float)
        self.weights = [(self.cost / safe, np.zeros(m))]
        if y is not None:
            yv = np.asarray(y, dtype=float)
            if yv.shape == (m,) and bool(np.all(np.isfinite(yv))):
                colsum = np.array([float(yv[c].sum()) if c.size else 0.0 for c in self.cols])
                self.weights.append(((self.cost - colsum) / safe, yv))
        self.L, self.rc = L, rc
        self.alive = None
        self.alive_for = None
        self.nodes = 0
        self.leaves = 0

    def _pruned(self, lb):
        if self.inc.value is None:
            return False
        thr, eps = _threshold(self.P, self.inc.value)
        return lb + self.const > thr + eps

    def _filter(self, cand):
        """Drop the rotations the Lagrangian filter rules out against the current incumbent."""
        if self.L is None or self.rc is None or self.inc.value is None:
            return cand
        if self.alive_for != self.inc.value:
            thr, eps = _threshold(self.P, self.inc.value)
            self.alive = (self.L + self.np.maximum(self.rc, 0.0)) <= thr + eps
            self.alive_for = self.inc.value
        return cand[self.alive[cand]]

    def _leaf(self, chosen):
        self.leaves += 1
        offer(self.P, self.inc, list(chosen) + self.extra, "dfs")

    def node(self, cand, U, cso, chosen):
        np = self.np
        self.nodes += 1
        if (self.nodes & 15) == 0 and self.clock.elapsed() > self.t_end:
            raise _Stop()
        if U.size == 0:
            self._leaf(chosen)
            return
        cand = self._filter(cand)
        if cand.size == 0:
            return
        sub = self.B[np.ix_(cand, U)]  # compatible rotations x open legs
        counts = sub.sum(axis=0)
        if int(counts.min()) == 0:
            return  # some open leg can no longer be covered
        rowlbs, lbs = [], []
        for w, yrow in self.weights:
            M = np.where(sub, w[cand][:, None], np.inf)
            rl = M.min(axis=0) + yrow[U]
            rowlbs.append(rl)
            lbs.append(float(rl.sum()))
        if self._pruned(cso + max(lbs)):
            return
        t = int(np.argmin(counts))  # the open leg with the fewest compatible rotations
        mask = sub[:, t]
        kids = cand[mask]
        subk = sub[mask].astype(float)
        child = np.max(np.stack([lbs[k] - subk.dot(rowlbs[k]) for k in range(len(lbs))]), axis=0)
        child = cso + self.cost[kids] + child
        order = np.argsort(child, kind="stable")
        for q in order:
            if self._pruned(float(child[q])):
                break  # sorted ascending, and the incumbent only gets better
            j = int(kids[q])
            S = self.cols[j]
            keep = ~self.B[np.ix_(cand, S)].any(axis=1)
            chosen.append(j)
            self.node(cand[keep], np.setdiff1d(U, S, assume_unique=True), cso + float(self.cost[j]), chosen)
            chosen.pop()

    def run(self):
        np = self.np
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old, 4 * self.P["m"] + 1000))
        try:
            self.node(self.cand0, np.arange(self.P["m"], dtype=np.int64), 0.0, [])
            return True
        except _Stop:
            return False
        finally:
            sys.setrecursionlimit(old)


def run_dfs(P, inc, clock, seconds, y=None, L=None, rc=None, log=None):
    """Exact-cover search for `seconds`. Returns True if it searched the whole tree."""
    if P["m"] * P["n"] > DFS_MAX_CELLS:
        if log is not None:
            log["dfs"] = "too_big"
        return False
    t_end = clock.elapsed() + max(0.0, float(seconds))
    ec = ExactCover(P, inc, clock, t_end, y=y, L=L, rc=rc)
    done = ec.run()
    if log is not None:
        log["dfs"] = {"complete": done, "nodes": ec.nodes, "leaves": ec.leaves, "s": round(clock.elapsed(), 2),
                      "value": inc.value}
    return done


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


def phase2(P, inc, clock, L, rc, cfg, log):
    """After the search: improve the incumbent on the columns the Lagrangian filter keeps."""
    if proven_by_bound(P, L, inc.value):
        log["proven"] = "bound"
        return
    keep = keep_columns(P, L, rc, inc.value)
    log["kept"] = int(keep.size)
    if keep.size == 0:
        log["proven"] = "pruned_to_nothing"
        return
    if clock.remaining() < 0.5 or cfg["phase2"] == "dfs":
        return
    if cfg["phase2"] == "cpsat" and keep.size <= CPSAT_MAX_COLS:
        try:
            if run_cpsat(P, clock.remaining(), inc, hint=P.get("best"), subset=keep):
                log["proven"] = "cpsat_optimal"
            log["phase2"] = "cpsat"
            return
        except Exception as e:  # noqa: BLE001 - fall through to HiGHS with the time left
            sys.stderr.write("cpsat failed: %r\n" % (e,))
            log["cpsat_error"] = repr(e)[:200]
    if clock.remaining() < 0.5:
        return
    chosen, code = _milp(P, clock.remaining(), keep)
    if chosen is not None:
        offer(P, inc, chosen, "pruned")
    log["phase2"] = "highs:" + code
    if code in ("optimal", "infeasible"):
        log["proven"] = "pruned_" + code


def lp_route(P, clock, inc, log, cfg):
    """LP, exact-cover search, then phase 2. Returns False only if the LP could not be solved."""
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
    L, rc, y_used = best_lagrangian(P, y)
    log["L"] = round(L, 6)
    share = 1.0 if cfg["phase2"] == "dfs" else cfg["dfs_share"]
    try:
        if run_dfs(P, inc, clock, clock.share(share), y=y_used, L=L, rc=rc, log=log):
            log["proven"] = "dfs_complete" if inc.value is not None else "dfs_no_partition"
            return True
    except Exception as e:  # noqa: BLE001 - the search is an extra; the v0.3.0 route still runs
        sys.stderr.write("dfs failed: %r\n" % (e,))
        log["dfs_error"] = repr(e)[:200]
    if inc.value is None:  # no first solution yet: the v0.3.0 route (restricted MIP, then HiGHS on everything)
        tried, proven = restricted(P, inc, clock, rc, x, clock.share(HEUR_SHARE))
        log["restricted"] = tried
        if proven:
            log["proven"] = "restricted_was_full"
            return True
        if inc.value is None:
            if clock.remaining() >= 0.5:
                chosen, code = _milp(P, clock.remaining())
                if chosen is not None:
                    offer(P, inc, chosen, "full")
                log["full"] = code
            return True
    phase2(P, inc, clock, L, rc, cfg, log)
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
    cfg = load_config()
    log = {"version": VERSION, "config": cfg, "m": P["m"], "n": P["n"],
           "extra_columns_ignored": P["extra_columns_ignored"], "row_indices_ignored": P["row_indices_ignored"],
           "short_columns": P["short_columns"]}
    if P["m"] == 0:
        offer(P, inc, [j for j in range(P["n"]) if P["cost"][j] < 0], "empty")
        return log
    if P["n"] == 0:
        return log
    done = False
    try:
        done = lp_route(P, clock, inc, log, cfg)
    except Exception as e:  # noqa: BLE001 - fall back to the v0.1.0 portfolio
        sys.stderr.write("lp route failed: %r\n" % (e,))
        log["lp_route_error"] = repr(e)[:200]
    if not done and clock.remaining() >= 1.0:
        if inc.value is None:
            try:
                run_dfs(P, inc, clock, clock.share(0.5), log=log)
            except Exception as e:  # noqa: BLE001
                sys.stderr.write("dfs failed: %r\n" % (e,))
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
    log["history"] = [list(h) for h in getattr(inc, "history", [])][-8:]
    log["s"] = round(clock.elapsed(), 2)
    sys.stderr.write("spp log %s\n" % json.dumps(log, default=str))
    out = getattr(args, "output", None)
    if cfg["log_file"] and out:  # test runs only (spp_config.json); the contest folder writes nothing extra
        try:
            with open(out + ".log.json", "w", encoding="utf-8") as f:
                json.dump(log, f, default=str)
        except Exception:  # noqa: BLE001
            pass
    return log


if __name__ == "__main__":
    R.main(solve, "min")

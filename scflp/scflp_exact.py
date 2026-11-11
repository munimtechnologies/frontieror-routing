"""Reference solvers for bodur2017 (SCFLP), separate from the contest solver.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

- `eval_open_lp(inst, open_ids)`: opening + expected transport cost of a fixed open set, one HiGHS LP per scenario.
- `brute_force(inst)`: every open set that meets the aggregate capacity rule (tiny instances only).
- `ext_mip(inst, time_limit)`: the whole extensive form as one MIP (HiGHS through SciPy), with the strong linking
  rows y_sij <= min(d_sj, cap_i) x_i when the model is small enough. Returns the objective of the open set it finds,
  re-evaluated with eval_open_lp, whether HiGHS proved it optimal, and HiGHS's dual bound.
Written without the solver's code, so it can check it.
"""
import itertools
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import coo_matrix


def _arrays(inst):
    F, m = len(inst["facilities"]), len(inst["customers"])
    fac = {int(f["id"]): f for f in inst["facilities"]}
    f = np.array([float(fac[i]["opening_cost"]) for i in range(F)])
    cap = np.array([float(fac[i]["capacity"]) for i in range(F)])
    C = np.array(inst["transportation_costs"], dtype=float)
    sc = sorted(inst["scenarios"], key=lambda s: int(s["id"]))
    D = np.array([s["demands"] for s in sc], dtype=float)
    S = len(sc)
    p = np.array([float(s["probability"]) if s.get("probability") is not None else 1.0 / S for s in sc])
    return F, m, S, f, cap, C, D, p


def transport_lp(C_open, cap_open, d):
    q, m = C_open.shape
    A = np.zeros((m + q, q * m))
    for a in range(q):
        for j in range(m):
            A[j, a * m + j] = -1.0
            A[m + a, a * m + j] = 1.0
    b = np.concatenate([-d, cap_open])
    r = linprog(C_open.ravel(), A_ub=A, b_ub=b, bounds=(0, None), method="highs")
    return None if r.status != 0 else float(r.fun)


def eval_open_lp(inst, open_ids):
    F, m, S, f, cap, C, D, p = _arrays(inst)
    o = sorted(int(i) for i in open_ids)
    if cap[o].sum() < D.sum(axis=1).max() - 1e-9:
        return None
    tot = float(f[o].sum())
    for s in range(S):
        v = transport_lp(C[o], cap[o], D[s])
        if v is None:
            return None
        tot += p[s] * v
    return tot


def brute_force(inst):
    F = len(inst["facilities"])
    best, arg = None, None
    for r in range(1, F + 1):
        for o in itertools.combinations(range(F), r):
            v = eval_open_lp(inst, o)
            if v is not None and (best is None or v < best):
                best, arg = v, o
    return best, arg


def ext_mip(inst, time_limit, strong_limit=130000):
    t0 = time.monotonic()
    F, m, S, f, cap, C, D, p = _arrays(inst)
    nY = S * F * m
    strong = nY <= strong_limit
    n = F + nY
    obj = np.concatenate([f, (p[:, None, None] * C[None, :, :]).ravel()])
    rows, cols, vals, lo, hi = [], [], [], [], []
    r = 0
    idx = np.arange(nY, dtype=np.int64).reshape(S, F, m)
    # demand: sum_i y[s,i,j] >= D[s,j]
    for s in range(S):
        for j in range(m):
            rows.append(np.full(F, r, dtype=np.int64)); cols.append(F + idx[s, :, j]); vals.append(np.ones(F))
            lo.append(D[s, j]); hi.append(np.inf); r += 1
    # capacity: sum_j y[s,i,j] - cap_i x_i <= 0
    for s in range(S):
        for i in range(F):
            rows.append(np.full(m + 1, r, dtype=np.int64))
            cols.append(np.concatenate([F + idx[s, i, :], [i]]).astype(np.int64))
            vals.append(np.concatenate([np.ones(m), [-cap[i]]]))
            lo.append(-np.inf); hi.append(0.0); r += 1
    # aggregate capacity
    rows.append(np.full(F, r, dtype=np.int64)); cols.append(np.arange(F, dtype=np.int64)); vals.append(cap.copy())
    lo.append(float(D.sum(axis=1).max())); hi.append(np.inf); r += 1
    if strong:
        e = np.arange(nY, dtype=np.int64)
        s_, i_, j_ = e // (F * m), (e // m) % F, e % m
        rows.append(r + e); cols.append(F + e); vals.append(np.ones(nY))
        rows.append(r + e); cols.append(i_); vals.append(-np.minimum(D[s_, j_], cap[i_]))
        lo.extend([-np.inf] * nY); hi.extend([0.0] * nY); r += nY
    A = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(r, n)).tocsr()
    integ = np.concatenate([np.ones(F), np.zeros(nY)])
    ub = np.concatenate([np.ones(F), np.full(nY, np.inf)])
    res = milp(obj, constraints=[LinearConstraint(A, np.array(lo, dtype=float), np.array(hi, dtype=float))],
               integrality=integ, bounds=Bounds(np.zeros(n), ub),
               options={"time_limit": float(time_limit), "disp": False, "mip_rel_gap": 1e-6})
    out = {"status": int(res.status), "proven": int(res.status) == 0, "bound": res.get("mip_dual_bound"),
           "mip_objective": float(res.fun) if res.x is not None else None, "strong": strong, "vars": n,
           "rows": r, "objective": None, "open": None}
    if res.x is not None:
        o = [i for i in range(F) if res.x[i] > 0.5]
        out["open"] = o
        out["objective"] = eval_open_lp(inst, o)
    out["time_s"] = round(time.monotonic() - t0, 2)
    return out

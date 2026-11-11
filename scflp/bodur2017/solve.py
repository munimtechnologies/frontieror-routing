"""bodur2017: two-stage stochastic capacitated facility location (SCFLP) for the FrontierOR Main track. v0.1.0

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

`python solve.py --problem bodur2017 --instance in.json --output out.json --time-limit 60`

The first-stage decision is which facilities to open. Once that is fixed, every scenario is an independent
transportation problem, so the search works on open sets and evaluates each one exactly:
1. Quick start: open facilities in order of cost per unit of capacity until the aggregate capacity rule holds,
   evaluate on every scenario, write at once.
2. If the whole extensive form is small, solve it as one MIP (HiGHS through SciPy); a proven optimum ends the run.
3. Sample-average MIPs: the mean-demand problem, then stratified samples of scenarios (the largest-demand scenario
   plus one per demand stratum, weighted by the stratum's probability). Every open set they return is evaluated on
   all scenarios; the aggregate capacity rule always uses the true largest demand, so each one is feasible.
4. For the rest of the time, local search over drop / add / swap moves. Moves are screened on a stratified
   scenario sample and the best few are confirmed on all scenarios; when stuck, a random kick from the best set.

Transportation problems are min-cost flows (OR-Tools SimpleMinCostFlow) in integer units of 10^-k with demands
rounded up and capacities rounded down, so every flow written is exactly feasible. Costs are scaled to integers only
inside the flow solver; the objective written is recomputed from the written quantities. Without OR-Tools, SciPy's
HiGHS LP is used instead (slower).

Output keys follow the public page: objective_value, open_facilities, x {"<facility>": 0/1},
y {"<scenario>": {"<facility>": {"<customer>": quantity}}}. Small instances get every key (zeros included); larger
ones get only open facilities, and the largest only nonzero quantities, to stay far below the 16 MB limit. The
official checker (public in the FrontierOR benchmark dataset) reads missing y entries as 0, uses a 1e-5 tolerance
and accepts an objective within max(1e-3, 1e-3 x |true objective|).
"""
import os
import random
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import frontier_runtime as FR  # noqa: E402

try:
    from ortools.graph.python import min_cost_flow as _MCF
except Exception:  # noqa: BLE001 - fall back to the LP
    _MCF = None

VERSION = "0.1.0"
EXT_FULL_LIMIT = 40000      # S*F*m up to which the full extensive MIP is tried first
DENSE_FULL_LIMIT = 300000   # S*F*m up to which y lists every facility and customer
DENSE_OPEN_LIMIT = 300000   # S*|open|*m up to which y lists every customer of every open facility
SAA_TARGET = 8000           # k*F*m aimed at by one sample-average MIP


class Problem:
    def __init__(self, inst):
        fac = sorted(inst["facilities"], key=lambda f: int(f["id"]))
        cus = sorted(inst["customers"], key=lambda c: int(c["id"]))
        sc = sorted(inst["scenarios"], key=lambda s: int(s["id"]))
        self.F, self.m, self.S = len(fac), len(cus), len(sc)
        self.fid = [int(f["id"]) for f in fac]
        self.cid = [int(c["id"]) for c in cus]
        self.sid = [int(s["id"]) for s in sc]
        self.f = np.array([float(f["opening_cost"]) for f in fac], dtype=float)
        self.cap = np.array([float(f["capacity"]) for f in fac], dtype=float)
        C = np.array(inst["transportation_costs"], dtype=float)
        # rows and columns of the cost matrix follow the facility / customer ids
        self.C = C[np.array(self.fid)][:, np.array(self.cid)]
        D = np.array([[float(v) for v in s["demands"]] for s in sc], dtype=float).reshape(self.S, -1)
        self.D = D[:, np.array(self.cid)]
        p = [s.get("probability") for s in sc]
        if any(v is None for v in p):
            p = [1.0 / self.S] * self.S
        self.p = np.array([float(v) for v in p], dtype=float)
        self.Dtot = self.D.sum(axis=1)
        self.Dmax = float(self.Dtot.max()) if self.S else 0.0
        self.mean_d = (self.p[:, None] * self.D).sum(axis=0) / max(1e-12, float(self.p.sum()))
        big = max(float(self.cap.sum()), self.Dmax, 1.0)
        k = 6
        while k > 0 and big * 10 ** k > 1e12:
            k -= 1
        self.unit = float(10 ** k)
        cmax = float(self.C.max()) if self.C.size else 0.0
        self.cscale = 1e6 / cmax if cmax > 0 else 1.0
        self.Cint = np.rint(self.C * self.cscale).astype(np.int64)
        self.capint = np.floor(self.cap * self.unit).astype(np.int64)
        self.Dint = np.maximum(0, np.ceil(self.D * self.unit - 1e-6)).astype(np.int64)
        self.Dint_tot = self.Dint.sum(axis=1)
        self.Dint_max = int(self.Dint_tot.max()) if self.S else 0
        self.order_tot = np.argsort(self.Dtot, kind="stable")
        # facilities that serve similar customers cheaply: swap neighbourhoods
        if self.F > 1:
            prof = self.C / max(1e-12, float(self.C.mean()))
            dd = np.abs(prof[:, None, :] - prof[None, :, :]).mean(axis=2) if self.F * self.F * self.m <= 4e6 else \
                np.array([np.abs(prof - prof[i]).mean(axis=1) for i in range(self.F)])
            np.fill_diagonal(dd, np.inf)
            self.near = np.argsort(dd, axis=1)[:, :min(8, self.F - 1)]
        else:
            self.near = np.zeros((self.F, 0), dtype=np.int64)

    def capacity_ok(self, mask):
        return float(self.cap[mask].sum()) >= self.Dmax - 1e-9 and int(self.capint[mask].sum()) >= self.Dint_max


class Transport:
    """The transportation problems of one open set; `solve(s)` returns the shipped quantities (q x m, float)."""

    def __init__(self, P, open_idx):
        self.P = P
        self.open = np.asarray(open_idx, dtype=np.int64)
        self.q = q = len(self.open)
        m = P.m
        self.Copen = P.C[self.open]
        self.capsum = int(P.capint[self.open].sum())
        self.smcf = None
        if _MCF is not None and q > 0:
            self.smcf = _MCF.SimpleMinCostFlow()
            tails = np.repeat(np.arange(q, dtype=np.int64), m)
            heads = q + np.tile(np.arange(m, dtype=np.int64), q)
            caps = np.repeat(P.capint[self.open], m).astype(np.int64)
            costs = P.Cint[self.open].ravel().astype(np.int64)
            self.fc = self.smcf.add_arcs_with_capacity_and_unit_cost(tails, heads, caps, costs)
            self.smcf.add_arcs_with_capacity_and_unit_cost(
                np.arange(q, dtype=np.int64), np.full(q, q + m, dtype=np.int64),
                P.capint[self.open].astype(np.int64), np.zeros(q, dtype=np.int64))
            self.nodes = np.arange(q + m + 1, dtype=np.int64)

    def solve(self, s):
        P = self.P
        if self.q == 0:
            return np.zeros((0, P.m)) if P.Dint_tot[s] == 0 else None
        if self.smcf is None:
            return self._solve_lp(s)
        slack = self.capsum - int(P.Dint_tot[s])
        if slack < 0:
            return None
        sup = np.concatenate([P.capint[self.open], -P.Dint[s], np.array([-slack], dtype=np.int64)])
        self.smcf.set_nodes_supplies(self.nodes, sup.astype(np.int64))
        st = self.smcf.solve()
        if st != self.smcf.OPTIMAL:
            return None
        fl = np.asarray(self.smcf.flows(self.fc), dtype=np.int64)
        return fl.astype(np.float64).reshape(self.q, P.m) / P.unit

    def _solve_lp(self, s):
        from scipy.optimize import linprog
        from scipy.sparse import csr_matrix
        P, q, m = self.P, self.q, self.P.m
        n = q * m
        e = np.arange(n, dtype=np.int64)
        rows = np.concatenate([e % m, m + e // m])
        vals = np.concatenate([-np.ones(n), np.ones(n)])
        A = csr_matrix((vals, (rows, np.concatenate([e, e]))), shape=(m + q, n))
        b = np.concatenate([-P.D[s], P.cap[self.open]])
        r = linprog(self.Copen.ravel(), A_ub=A, b_ub=b, bounds=(0, None), method="highs")
        if r.status != 0:
            return None
        y = np.maximum(0.0, r.x).reshape(q, m)
        return y


def evaluate(P, mask, scen=None, weights=None, keep=False, deadline=None):
    """Cost of an open set: opening + weighted transport over `scen` (all scenarios with their probabilities by
    default). Returns (cost, list of quantities or None) or None if infeasible or out of time."""
    mask = np.asarray(mask, dtype=bool)
    if not P.capacity_ok(mask):
        return None
    T = Transport(P, np.flatnonzero(mask))
    idx = range(P.S) if scen is None else scen
    w = P.p if scen is None else weights
    tot = 0.0
    ys = [] if keep else None
    for t, s in enumerate(idx):
        if deadline is not None and (t & 7) == 7 and time.monotonic() > deadline:
            return None
        y = T.solve(int(s))
        if y is None:
            return None
        ws = float(w[int(s)]) if scen is None else float(w[t])
        tot += ws * float((y * T.Copen).sum())
        if keep:
            ys.append(y)
    return float(P.f[mask].sum()) + tot, ys


def stratified(P, k, rng):
    """k scenarios: the one with the largest total demand, plus one random scenario per demand stratum; weights are
    the probability mass each pick stands for (normalised)."""
    if k >= P.S:
        idx = np.arange(P.S)
        return idx, P.p / P.p.sum()
    order = P.order_tot
    top = int(order[-1])
    rest = order[:-1]
    picks, w = [top], [float(P.p[top])]
    nb = max(1, k - 1)
    for b in range(nb):
        lo = b * len(rest) // nb
        hi = max(lo + 1, (b + 1) * len(rest) // nb)
        picks.append(int(rest[rng.randrange(lo, hi)]))
        w.append(float(P.p[rest[lo:hi]].sum()))
    w = np.array(w)
    return np.array(picks, dtype=np.int64), w / w.sum()


def ext_mip(P, Dk, w, time_limit, strong=True):
    """Extensive-form MIP over the demand rows Dk (k x m) with weights w; aggregate rule on the true Dmax."""
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import csr_matrix
    F, m = P.F, P.m
    k = Dk.shape[0]
    nY = k * F * m
    n = F + nY
    c = np.empty(n)
    c[:F] = P.f
    c[F:] = (np.asarray(w, dtype=float)[:, None, None] * P.C[None, :, :]).ravel()
    e = np.arange(nY, dtype=np.int64)
    s = e // (F * m)
    i = (e // m) % F
    j = e % m
    ycol = F + e
    R, Cc, V, LB, UB = [], [], [], [], []
    r0 = 0
    R.append(r0 + s * m + j); Cc.append(ycol); V.append(np.ones(nY))
    LB.append(Dk.ravel()); UB.append(np.full(k * m, np.inf)); r0 += k * m
    kf = np.arange(k * F, dtype=np.int64)
    R.append(r0 + s * F + i); Cc.append(ycol); V.append(np.ones(nY))
    R.append(r0 + kf); Cc.append(kf % F); V.append(-P.cap[kf % F])
    LB.append(np.full(k * F, -np.inf)); UB.append(np.zeros(k * F)); r0 += k * F
    R.append(np.full(F, r0, dtype=np.int64)); Cc.append(np.arange(F, dtype=np.int64)); V.append(P.cap.copy())
    # margin so that the integer-unit flows (capacities rounded down, demands up) stay feasible
    LB.append(np.array([P.Dmax + (F + m + 2.0) / P.unit])); UB.append(np.array([np.inf])); r0 += 1
    if strong:
        R.append(r0 + e); Cc.append(ycol); V.append(np.ones(nY))
        R.append(r0 + e); Cc.append(i); V.append(-np.minimum(Dk[s, j], P.cap[i]))
        LB.append(np.full(nY, -np.inf)); UB.append(np.zeros(nY)); r0 += nY
    A = csr_matrix((np.concatenate(V), (np.concatenate(R).astype(np.int64), np.concatenate(Cc).astype(np.int64))),
                   shape=(r0, n))
    integ = np.zeros(n)
    integ[:F] = 1
    ub = np.full(n, np.inf)
    ub[:F] = 1.0
    res = milp(c, constraints=[LinearConstraint(A, np.concatenate(LB), np.concatenate(UB))], integrality=integ,
               bounds=Bounds(np.zeros(n), ub),
               options={"time_limit": float(max(0.5, time_limit)), "disp": False, "mip_rel_gap": 1e-7})
    mask = None
    if res.x is not None:
        mask = res.x[:F] > 0.5
    return {"mask": mask, "status": int(res.status), "obj": float(res.fun) if res.x is not None else None,
            "bound": res.get("mip_dual_bound")}


def build_solution(P, mask, ys, obj, mode=None):
    mask = np.asarray(mask, dtype=bool)
    open_idx = np.flatnonzero(mask)
    q = len(open_idx)
    if mode is None:
        if P.S * P.F * P.m <= DENSE_FULL_LIMIT:
            mode = "full"
        elif P.S * q * P.m <= DENSE_OPEN_LIMIT:
            mode = "open"
        else:
            mode = "sparse"
    cstr = [str(c) for c in P.cid]
    pos = {int(i): a for a, i in enumerate(open_idx)}
    zeros = [0.0] * P.m
    y = {}
    for s in range(P.S):
        Y = ys[s] if q else np.zeros((0, P.m))
        d = {}
        if mode == "full":
            for i in range(P.F):
                a = pos.get(i)
                d[str(P.fid[i])] = dict(zip(cstr, zeros if a is None else Y[a].tolist()))
        elif mode == "open":
            for a, i in enumerate(open_idx):
                d[str(P.fid[i])] = dict(zip(cstr, Y[a].tolist()))
        else:
            for a, i in enumerate(open_idx):
                nz = np.flatnonzero(Y[a])
                d[str(P.fid[i])] = {cstr[j]: float(Y[a, j]) for j in nz}
        y[str(P.sid[s])] = d
    return {"objective_value": float(obj), "open_facilities": [P.fid[i] for i in open_idx],
            "x": {str(P.fid[i]): int(mask[i]) for i in range(P.F)}, "y": y}


class State:
    def __init__(self, P, inc):
        self.P, self.inc = P, inc
        self.best_mask, self.best_obj, self.best_ys = None, None, None
        self.built_obj = None
        self.last_build = 0.0
        self.cache = {}
        self.log = []

    def full(self, mask, deadline=None, source=""):
        key = np.asarray(mask, dtype=bool).tobytes()
        if key in self.cache and self.cache[key] is not None and (
                self.best_obj is None or self.cache[key] >= self.best_obj - 1e-12):
            return self.cache[key]
        r = evaluate(self.P, mask, keep=True, deadline=deadline)
        if r is None:
            if deadline is None or time.monotonic() <= deadline:
                self.cache[key] = None
            return None
        self.cache[key] = r[0]
        if self.best_obj is None or r[0] < self.best_obj - 1e-9 * max(1.0, abs(self.best_obj)):
            self.best_mask, self.best_obj, self.best_ys = np.asarray(mask, dtype=bool).copy(), r[0], r[1]
            self.log.append((round(time.monotonic() - FR._T0, 2), r[0], source))
            self.maybe_build()
        return r[0]

    def maybe_build(self, force=False):
        if self.best_obj is None or self.built_obj == self.best_obj:
            return
        now = time.monotonic()
        if force or self.built_obj is None or now - self.last_build >= 3.0:
            sol = build_solution(self.P, self.best_mask, self.best_ys, self.best_obj)
            self.inc.offer(self.best_obj, sol, source="v" + VERSION)
            self.built_obj = self.best_obj
            self.last_build = now


def quick_start(P):
    """Open facilities by (opening cost + capacity x mean cost to their nearest customers) per unit of capacity."""
    kn = max(1, min(P.m, 5))
    near_cost = np.sort(P.C, axis=1)[:, :kn].mean(axis=1)
    score = (P.f + P.cap * near_cost) / np.maximum(P.cap, 1e-9)
    mask = np.zeros(P.F, dtype=bool)
    for i in np.argsort(score, kind="stable"):
        mask[i] = True
        if P.capacity_ok(mask):
            break
    if not P.capacity_ok(mask):
        mask[:] = True
    return mask


def safe(fn, *a, **kw):
    """Run a MIP step; on any error (memory, solver) keep going with what is already found."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("step %s failed: %r\n" % (getattr(fn, "__name__", "?"), e))
        return None


def saa_k(P):
    return int(max(1, min(P.S, 12, SAA_TARGET // max(1, P.F * P.m))))


def run_saa(P, st, clock, rng, k, tl):
    if k <= 0:
        Dk, w = P.mean_d[None, :], np.array([1.0])
        src = "ev-mip"
    else:
        idx, w = stratified(P, k, rng)
        Dk = P.D[idx]
        src = "saa%d-mip" % k
    strong = Dk.shape[0] * P.F * P.m <= 60000
    r = safe(ext_mip, P, Dk, w, tl, strong=strong)
    if r is not None and r["mask"] is not None and not clock.expired():
        st.full(r["mask"], deadline=time.monotonic() + clock.remaining(), source=src)
    return r


def moves_for(P, mask, rng):
    op = np.flatnonzero(mask)
    cl = np.flatnonzero(~mask)
    mv = [("drop", int(i), -1) for i in op] + [("add", -1, int(j)) for j in cl]
    for i in op:
        for j in P.near[i]:
            if not mask[j]:
                mv.append(("swap", int(i), int(j)))
    rng.shuffle(mv)
    return mv


def apply_move(mask, mv):
    m2 = mask.copy()
    if mv[1] >= 0:
        m2[mv[1]] = False
    if mv[2] >= 0:
        m2[mv[2]] = True
    return m2


def local_search(P, st, clock, rng):
    if st.best_mask is None:
        return
    end = lambda: time.monotonic() + clock.remaining()  # noqa: E731
    mask, cur = st.best_mask.copy(), st.best_obj
    t1 = None
    stuck = 0
    while not clock.expired():
        mv = moves_for(P, mask, rng)
        if not mv:
            break
        if t1 is None:
            t0 = time.monotonic()
            probe = evaluate(P, mask, scen=np.arange(min(P.S, 4)), weights=np.ones(min(P.S, 4)) / min(P.S, 4))
            t1 = max(1e-4, (time.monotonic() - t0) / min(P.S, 4))
            if probe is None:
                break
        budget = max(1.0, 0.12 * clock.remaining())
        q = int(max(1, min(P.S, 16, budget / (len(mv) * t1))))
        scen, w = stratified(P, q, rng)
        base = evaluate(P, mask, scen=scen, weights=w)
        if base is None:
            break
        scored = []
        for m_ in mv:
            if clock.expired():
                break
            m2 = apply_move(mask, m_)
            if not P.capacity_ok(m2):
                continue
            r = evaluate(P, m2, scen=scen, weights=w, deadline=end())
            if r is not None:
                scored.append((r[0], m_))
        scored.sort(key=lambda t: t[0])
        improved = False
        for v, m_ in scored[:4]:
            if clock.expired():
                break
            if v > base[0] + 0.002 * abs(base[0]):
                break
            m2 = apply_move(mask, m_)
            val = st.full(m2, deadline=end(), source="ls-" + m_[0])
            if val is not None and val < cur - 1e-9 * max(1.0, abs(cur)):
                mask, cur, improved = m2, val, True
                break
        st.maybe_build()
        if improved:
            stuck = 0
            continue
        stuck += 1
        # kick from the best set: two random changes that keep the aggregate rule
        mask = st.best_mask.copy()
        for _ in range(20):
            m2 = mask.copy()
            for _k in range(2 if stuck < 4 else 3):
                op, cl = np.flatnonzero(m2), np.flatnonzero(~m2)
                if len(op) and len(cl) and rng.random() < 0.6:
                    m2[op[rng.randrange(len(op))]] = False
                    m2[cl[rng.randrange(len(cl))]] = True
                elif len(cl) and (rng.random() < 0.5 or not len(op)):
                    m2[cl[rng.randrange(len(cl))]] = True
                elif len(op):
                    m2[op[rng.randrange(len(op))]] = False
            if P.capacity_ok(m2):
                break
        else:
            continue
        val = st.full(m2, deadline=end(), source="kick")
        if val is None:
            continue
        mask, cur = m2, val


def solve(inst, clock, inc, args):
    P = Problem(inst)
    rng = random.Random(getattr(args, "seed", 0) or 0)
    st = State(P, inc)
    if P.S == 0:
        return
    end = lambda: time.monotonic() + clock.remaining()  # noqa: E731
    # 1. quick start (and all-open as a fallback)
    if st.full(quick_start(P), deadline=end(), source="quick") is None:
        st.full(np.ones(P.F, dtype=bool), deadline=end(), source="all-open")
    st.maybe_build(force=True)
    # 2. the whole extensive form when it is small
    if P.S * P.F * P.m <= EXT_FULL_LIMIT and not clock.expired():
        r = safe(ext_mip, P, P.D, P.p, clock.share(0.6), strong=True)
        if r is not None and r["mask"] is not None:
            st.full(r["mask"], deadline=end(), source="ext-mip")
            if r["status"] == 0 and r["obj"] is not None and st.best_obj is not None and \
                    st.best_obj <= r["obj"] + 1e-5 * max(1.0, abs(r["obj"])):
                st.maybe_build(force=True)
                return
    # 3. sample-average MIPs
    t_saa_end = clock.elapsed() + 0.45 * clock.remaining()
    if not clock.expired():
        run_saa(P, st, clock, rng, 0, min(15.0, clock.share(0.15)))
    k = saa_k(P)
    rounds = 0
    while not clock.expired() and clock.elapsed() < t_saa_end and rounds < 3 and k > 0:
        run_saa(P, st, clock, rng, k, min(20.0, max(1.0, t_saa_end - clock.elapsed())))
        rounds += 1
    st.maybe_build(force=True)
    # 4. local search
    local_search(P, st, clock, rng)
    st.maybe_build(force=True)


def ev_baseline(inst, time_limit=20.0):
    """Mean-demand (expected value) MIP solution, evaluated on every scenario: the classic 'EV solution'."""
    P = Problem(inst)
    r = ext_mip(P, P.mean_d[None, :], np.array([1.0]), time_limit, strong=P.F * P.m <= 60000)
    if r["mask"] is None:
        return None
    e = evaluate(P, r["mask"])
    return None if e is None else e[0]


if __name__ == "__main__":
    FR.main(solve, "min")

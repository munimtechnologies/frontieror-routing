#!/usr/bin/env python3
"""guo2021 solver v0.1.0: stochastic distributed operating room scheduling (FrontierOR benchmark task guo2021).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python solve.py --problem guo2021 --instance in.json --output out.json --time-limit 60

The task (Guo et al. 2021, SAA deterministic equivalent): open hospital suites and ORs per day, assign every mandatory
patient to one OR on one day, assign or postpone the others; after durations are revealed per scenario, cancel the
fewest-cost surgeries so each OR fits its time limit. Minimise opening costs + scheduling benefit (negative) +
postponement penalties + expected cancellation cost.

Key fact used here: for a fixed first stage, the recourse decomposes into one 0/1 knapsack per (scenario, OR), and
the official checker recomputes exactly that optimum (constraint 11). So the search only decides the first stage
(which OR on which day each patient goes to, or postponement) and prices each OR's expected cancellation cost
exactly (subset enumeration over the OR's patients, vectorised over scenarios; memoised).

Search: greedy best insertion, then relocate/swap local search and ruin-and-recreate (random patients, one OR, one
whole suite-day, or the most overloaded ORs; sometimes with a closed suite's opening cost waived while recreating)
with record-to-record acceptance. The second CPU runs the same search with another seed in a forked process. A
feasible answer is written right after the greedy start and again on improvement (at most every 3 s); the search
stops well before the time limit.

The objective written is recomputed from the output exactly as the official checker recomputes it.
"""
import argparse
import json
import os
import random
import sys
import time

T_START = time.monotonic()
# two search processes, one CPU each; tiny matrices, so no BLAS threads (also keeps fork safe)
for _v in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[_v] = "1"

import numpy as np  # noqa: E402

VERSION = "0.1.0"
KMAX = 11      # subset enumeration up to this many patients in one OR; Pareto DP above
KBIN = 16      # never put more than this many patients in one OR (keeps every recourse DP small)
POSTPONED = -1


# ----------------------------------------------------------------------------------------------- exact recourse
def pareto_kept(items, cap):
    """Max total value of a subset whose total weight <= cap (the official checker's exact Pareto DP)."""
    if not items:
        return 0.0
    total_w = sum(w for w, v in items)
    if total_w <= cap + 1e-6:
        return sum(v for w, v in items)
    if cap <= 1e-9:
        return 0.0
    frontier = [(0.0, 0.0)]
    for weight, value in items:
        additions = [(used + weight, kept + value) for used, kept in frontier if used + weight <= cap + 1e-6]
        merged = sorted(frontier + additions, key=lambda state: (state[0], -state[1]))
        pruned = []
        best_value = -float("inf")
        for used, kept in merged:
            if kept > best_value + 1e-9:
                pruned.append((used, kept))
                best_value = kept
        frontier = pruned
        if len(frontier) > 200000:
            raise RuntimeError("exact recourse frontier exceeded 200000 states")
    return max(kept for used, kept in frontier)


def checker_objective(instance, solution):
    """The objective exactly as the official feasibility_check.py (constraint 11) recomputes it from u, y, x, w:
    deterministic terms + optimal expected recourse. Loops and summation order follow the checker."""
    num_patients = instance["num_patients"]
    num_hospitals = instance["num_hospitals"]
    num_days = instance["num_days"]
    num_ors = instance["num_ors_per_hospital"]
    P = list(range(num_patients))
    H = list(range(num_hospitals))
    D = list(range(num_days))
    R = list(range(num_ors))
    patients = instance["patients"]
    P_mandatory = [pt["patient_id"] for pt in patients if pt["is_mandatory"]]
    c_cancel = {pt["patient_id"]: pt["c_cancel"] for pt in patients}
    num_scenarios = instance.get("num_scenarios", len(instance.get("scenarios", [])))
    S = list(range(num_scenarios))
    T_s = {}
    for sc in instance.get("scenarios", []):
        T_s[sc["scenario_id"]] = {p: sc["surgery_durations_minutes"][p] for p in P}
    B = {}
    for h_data in instance.get("hospitals", []):
        B[h_data["hospital_id"]] = {dd["day_id"]: dd["B_hd"] for dd in h_data["days"]}
    sol_u = solution.get("u", {})
    sol_y = solution.get("y", {})
    sol_x = solution.get("x", {})
    sol_w = solution.get("w", {})

    def get_u(h, d):
        return float(sol_u.get(f"{h},{d}", 0))

    def get_y(h, d, r):
        return float(sol_y.get(f"{h},{d},{r}", 0))

    def get_x(h, d, p, r):
        return float(sol_x.get(f"{h},{d},{p},{r}", 0))

    def get_w(p):
        return float(sol_w.get(str(p), 0))

    c_unsched = {pt["patient_id"]: float(pt.get("c_unsched", 0.0)) for pt in patients}
    day_label_of = {}
    for h_data in instance.get("hospitals", []):
        for dd in h_data["days"]:
            day_label_of[dd["day_id"]] = dd.get("day_label", dd["day_id"] + 1)
    c_sched = {}
    for pt in patients:
        pid = pt["patient_id"]
        per_day = pt.get("c_sched_per_day", {}) or {}
        for d in D:
            label = day_label_of.get(d, d + 1)
            val = per_day.get(str(label), per_day.get(str(d + 1)))
            if val is not None:
                c_sched[(pid, d)] = float(val)
    G = {}
    F = {}
    for h_data in instance.get("hospitals", []):
        h_id = h_data["hospital_id"]
        for dd in h_data["days"]:
            G[(h_id, dd["day_id"])] = float(dd["G_hd"])
            F[(h_id, dd["day_id"])] = float(dd["F_hd"])
    t_suite = sum(G.get((h, d), 0.0) * get_u(h, d) for h in H for d in D)
    t_or = sum(F.get((h, d), 0.0) * get_y(h, d, r) for h in H for d in D for r in R)
    t_sched = sum(c_sched.get((p, d), 0.0) * get_x(h, d, p, r) for h in H for d in D for p in P for r in R)
    mand_set = set(P_mandatory)
    t_unsched = sum(c_unsched.get(p, 0.0) * get_w(p) for p in P if p not in mand_set)
    obj_det = t_suite + t_or + t_sched + t_unsched
    t5_sum = 0.0
    for h in H:
        for d in D:
            for r in R:
                assigned = [p for p in P if get_x(h, d, p, r) > 0.5]
                if not assigned:
                    continue
                cap = B.get(h, {}).get(d, 0.0) * get_y(h, d, r)
                total_cc = sum(c_cancel.get(p, 0.0) for p in assigned)
                for s in S:
                    durs = T_s.get(s)
                    if durs is None:
                        continue
                    items = [(float(durs[p]), float(c_cancel.get(p, 0.0))) for p in assigned]
                    kept = pareto_kept(items, cap)
                    t5_sum += (total_cc - kept)
    t5_min = (t5_sum / num_scenarios) if num_scenarios > 0 else 0.0
    return obj_det + t5_min


# ----------------------------------------------------------------------------------------------- model
def tup_add(t, p):
    return tuple(sorted(t + (p,)))


def tup_del(t, p):
    return tuple(q for q in t if q != p)


class Problem:
    def __init__(self, inst):
        self.inst = inst
        self.P = int(inst["num_patients"])
        self.H = int(inst["num_hospitals"])
        self.D = int(inst["num_days"])
        self.R = int(inst["num_ors_per_hospital"])
        self.HD = self.H * self.D
        self.kind = [None] * self.P          # "m" mandatory, "o" optional (may be postponed), None = not listed
        self.cc = np.zeros(self.P)
        self.cun = np.zeros(self.P)
        pts = inst["patients"]
        for pt in pts:
            p = int(pt["patient_id"])
            if 0 <= p < self.P:
                self.kind[p] = "m" if pt["is_mandatory"] else "o"
                self.cc[p] = float(pt["c_cancel"])
                self.cun[p] = float(pt.get("c_unsched", 0.0))
        day_label_of = {}
        for h_data in inst.get("hospitals", []):
            for dd in h_data["days"]:
                day_label_of[dd["day_id"]] = dd.get("day_label", dd["day_id"] + 1)
        self.cs = np.zeros((self.P, max(self.D, 1)))
        for pt in pts:
            p = int(pt["patient_id"])
            if not 0 <= p < self.P:
                continue
            per = pt.get("c_sched_per_day", {}) or {}
            for d in range(self.D):
                label = day_label_of.get(d, d + 1)
                v = per.get(str(label), per.get(str(d + 1)))
                if v is not None:
                    self.cs[p, d] = float(v)
        self.G = np.zeros(max(self.HD, 1))
        self.F = np.zeros(max(self.HD, 1))
        self.B = np.zeros(max(self.HD, 1))
        for h_data in inst.get("hospitals", []):
            h = int(h_data["hospital_id"])
            for dd in h_data["days"]:
                d = int(dd["day_id"])
                if 0 <= h < self.H and 0 <= d < self.D:
                    k = h * self.D + d
                    self.G[k] = float(dd["G_hd"])
                    self.F[k] = float(dd["F_hd"])
                    self.B[k] = float(dd["B_hd"])
        scen = {}
        for sc in inst.get("scenarios", []):
            scen[int(sc["scenario_id"])] = sc["surgery_durations_minutes"]
        self.S = int(inst.get("num_scenarios", len(inst.get("scenarios", []))))
        rows = [scen[s] for s in range(self.S) if s in scen]
        if rows:
            self.T = np.array([[float(v[p]) for p in range(self.P)] for v in rows], dtype=np.float64)
        else:
            self.T = np.zeros((0, self.P))
        self.mean_dur = self.T.mean(axis=0) if rows else np.zeros(self.P)
        self.patients = [p for p in range(self.P) if self.kind[p] is not None]
        self.memo = {}
        self._masks = {}
        self.rec_calls = 0
        self.rec_misses = 0

    def day(self, hd):
        return hd % self.D

    def masks(self, k):
        m = self._masks.get(k)
        if m is None:
            ar = np.arange(1 << k)
            m = ((ar[None, :] >> np.arange(k)[:, None]) & 1).astype(np.float64)
            self._masks[k] = m
        return m

    def rec(self, hd, members):
        """Expected optimal cancellation cost of one open OR on suite-day hd holding `members` (sorted tuple)."""
        if not members or self.S <= 0 or self.T.shape[0] == 0:
            return 0.0
        cap = float(self.B[hd])
        key = (cap, members)
        self.rec_calls += 1
        v = self.memo.get(key)
        if v is not None:
            return v
        self.rec_misses += 1
        idx = list(members)
        sub = self.T[:, idx]
        tot = sub.sum(axis=1)
        over = tot > cap + 1e-6
        n = int(over.sum())
        if n == 0:
            v = 0.0
        else:
            ccl = self.cc[idx]
            totcc = float(ccl.sum())
            if cap <= 1e-9:
                lost = n * totcc
            elif len(idx) <= KMAX:
                M = self.masks(len(idx))
                dur = sub[over] @ M
                val = ccl @ M
                best = np.where(dur <= cap + 1e-6, val[None, :], -np.inf).max(axis=1)
                lost = float((totcc - best).sum())
            else:
                lost = 0.0
                for s in np.nonzero(over)[0]:
                    items = [(float(w), float(c)) for w, c in zip(sub[s], ccl)]
                    lost += totcc - pareto_kept(items, cap)
            v = lost / self.S
        if len(self.memo) > 1500000:
            self.memo.clear()
        self.memo[key] = v
        return v

    # ---- state
    def new_state(self):
        st = State(self)
        for p in range(self.P):
            if self.kind[p] is None:
                st.loc[p] = POSTPONED
        return st

    def total(self, st):
        c = 0.0
        for hd in range(self.HD):
            if st.nopen[hd]:
                c += self.G[hd]
            d = hd % self.D
            for m in st.bins[hd]:
                if m:
                    c += self.F[hd] + self.rec(hd, m)
                    c += float(sum(self.cs[p, d] for p in m))
        for p in range(self.P):
            if st.loc[p] == POSTPONED and self.kind[p] == "o":
                c += self.cun[p]
        return c

    def remove(self, st, p):
        """Take p out (to the floating state). Returns the cost change."""
        loc = st.loc[p]
        if loc is None:
            return 0.0
        if loc == POSTPONED:
            st.loc[p] = None
            return -float(self.cun[p]) if self.kind[p] == "o" else 0.0
        hd, s = loc
        old = st.bins[hd][s]
        new = tup_del(old, p)
        d = self.rec(hd, new) - self.rec(hd, old) - float(self.cs[p, hd % self.D])
        if not new:
            d -= float(self.F[hd])
            st.nopen[hd] -= 1
            if st.nopen[hd] == 0:
                d -= float(self.G[hd])
        st.bins[hd][s] = new
        st.loc[p] = None
        return d

    def ins_delta(self, st, p, hd, s, gfree=-2):
        m = st.bins[hd][s]
        d = self.rec(hd, tup_add(m, p)) - self.rec(hd, m) + float(self.cs[p, hd % self.D])
        if not m:
            d += float(self.F[hd])
            if st.nopen[hd] == 0 and hd != gfree:
                d += float(self.G[hd])
        return d

    def best_insert(self, st, p, gfree=-2):
        best_t, best_d = None, float("inf")
        if self.kind[p] == "o":
            best_t, best_d = POSTPONED, float(self.cun[p])
        for hd in range(self.HD):
            empty_done = False
            for s in range(self.R):
                m = st.bins[hd][s]
                if not m:
                    if empty_done:
                        continue
                    empty_done = True
                elif len(m) >= KBIN:
                    continue
                d = self.ins_delta(st, p, hd, s, gfree)
                if d < best_d - 1e-12:
                    best_t, best_d = (hd, s), d
        if best_t is None:   # no OR at all (or every OR full): park it postponed (a mandatory one stays infeasible)
            best_t, best_d = POSTPONED, float(self.cun[p]) if self.kind[p] == "o" else 0.0
        return best_t, best_d

    def place(self, st, p, t):
        if t == POSTPONED:
            st.loc[p] = POSTPONED
            return
        hd, s = t
        m = st.bins[hd][s]
        if not m:
            st.nopen[hd] += 1
        st.bins[hd][s] = tup_add(m, p)
        st.loc[p] = (hd, s)

    # ---- moves
    def try_relocate(self, st, p):
        orig = st.loc[p]
        dr = self.remove(st, p)
        t, di = self.best_insert(st, p)
        if dr + di < -1e-7 and t != orig:
            self.place(st, p, t)
            return dr + di
        self.place(st, p, orig)
        return 0.0

    def try_swap(self, st, p, q):
        lp, lq = st.loc[p], st.loc[q]
        if p == q or lp is None or lq is None or lp == lq:
            return 0.0
        if lp == POSTPONED and lq == POSTPONED:
            return 0.0
        if lp == POSTPONED:
            p, q, lp, lq = q, p, lq, lp
        if lq == POSTPONED:
            if self.kind[p] != "o" or self.kind[q] is None:
                return 0.0
            hd, s = lp
            A = st.bins[hd][s]
            A2 = tup_add(tup_del(A, p), q)
            d = hd % self.D
            cun_q = float(self.cun[q]) if self.kind[q] == "o" else 0.0   # total() charges cun only to optional
            delta = (self.rec(hd, A2) - self.rec(hd, A) + float(self.cs[q, d] - self.cs[p, d])
                     + float(self.cun[p]) - cun_q)
            if delta < -1e-7:
                st.bins[hd][s] = A2
                st.loc[q] = lp
                st.loc[p] = POSTPONED
                return delta
            return 0.0
        (h1, s1), (h2, s2) = lp, lq
        A = st.bins[h1][s1]
        Bm = st.bins[h2][s2]
        A2 = tup_add(tup_del(A, p), q)
        B2 = tup_add(tup_del(Bm, q), p)
        d1, d2 = h1 % self.D, h2 % self.D
        delta = (self.rec(h1, A2) - self.rec(h1, A) + self.rec(h2, B2) - self.rec(h2, Bm)
                 + float(self.cs[q, d1] - self.cs[p, d1] + self.cs[p, d2] - self.cs[q, d2]))
        if delta < -1e-7:
            st.bins[h1][s1] = A2
            st.bins[h2][s2] = B2
            st.loc[p] = lq
            st.loc[q] = lp
            return delta
        return 0.0

    def local_search(self, st, rng, deadline, swap_sample=12):
        gain = 0.0
        pts = self.patients
        improved = True
        while improved:
            improved = False
            order = list(pts)
            rng.shuffle(order)
            for p in order:
                if time.monotonic() > deadline:
                    return gain
                d = self.try_relocate(st, p)
                if d < 0:
                    gain += d
                    improved = True
            k = min(len(pts), swap_sample)
            for p in order:
                if time.monotonic() > deadline:
                    return gain
                for q in rng.sample(pts, k):
                    d = self.try_swap(st, p, q)
                    if d < 0:
                        gain += d
                        improved = True
        return gain

    def ruin_recreate(self, st, rng):
        pts = self.patients
        if not pts:
            return
        r = rng.random()
        placed = [p for p in pts if isinstance(st.loc[p], tuple)]
        removed = set()
        if r < 0.35 or not placed:
            k = rng.randint(2, max(3, len(pts) // 6))
            removed.update(rng.sample(pts, min(k, len(pts))))
        elif r < 0.60:
            hd, s = st.loc[rng.choice(placed)]
            removed.update(st.bins[hd][s])
            removed.update(rng.sample(pts, min(2, len(pts))))
        elif r < 0.80:
            hd, _s = st.loc[rng.choice(placed)]
            for m in st.bins[hd]:
                removed.update(m)
        else:
            scored = []
            for hd in range(self.HD):
                for s in range(self.R):
                    m = st.bins[hd][s]
                    if m:
                        scored.append((self.rec(hd, m), hd, s))
            scored.sort(reverse=True)
            for _v, hd, s in scored[:2]:
                removed.update(st.bins[hd][s])
            removed.update(rng.sample(pts, min(2, len(pts))))
        removed = list(removed)
        for p in removed:
            self.remove(st, p)
        gfree = -2
        if rng.random() < 0.25:
            closed = [hd for hd in range(self.HD) if st.nopen[hd] == 0]
            if closed:
                gfree = rng.choice(closed)
        if rng.random() < 0.5:
            rng.shuffle(removed)
        else:
            removed.sort(key=lambda p: (self.kind[p] != "m", -self.mean_dur[p]))
        for p in removed:
            t, _d = self.best_insert(st, p, gfree)
            self.place(st, p, t)

    def construct(self):
        st = self.new_state()
        order = sorted(self.patients, key=lambda p: (self.kind[p] != "m", -self.mean_dur[p]))
        for p in order:
            t, _d = self.best_insert(st, p)
            self.place(st, p, t)
        return st

    # ---- output
    def solution(self, loc):
        st = State(self)
        st.set_loc(loc)
        u, y, x, w = {}, {}, {}, {}
        for h in range(self.H):
            for d in range(self.D):
                hd = h * self.D + d
                used = [m for m in st.bins[hd] if m]
                used.sort(key=lambda m: -float(sum(self.cc[p] for p in m)))   # paper's (1e) order, harmless
                u["%d,%d" % (h, d)] = 1 if used else 0
                for r in range(self.R):
                    y["%d,%d,%d" % (h, d, r)] = 1 if r < len(used) else 0
                for r, m in enumerate(used):
                    for p in m:
                        x["%d,%d,%d,%d" % (h, d, p, r)] = 1
        for p in range(self.P):
            w[str(p)] = 1 if (st.loc[p] == POSTPONED and self.kind[p] == "o") else 0
        if not w:
            w = {"0": 0}
        sol = {"instance_id": self.inst.get("instance_id"), "objective_value": None, "u": u, "y": y, "x": x, "w": w}
        sol["objective_value"] = float(checker_objective(self.inst, sol))
        return sol


class State:
    def __init__(self, pb):
        self.pb = pb
        self.loc = [None] * pb.P
        self.bins = [[() for _ in range(pb.R)] for _ in range(max(pb.HD, 1))]
        self.nopen = [0] * max(pb.HD, 1)

    def set_loc(self, loc):
        pb = self.pb
        self.loc = list(loc)
        self.bins = [[() for _ in range(pb.R)] for _ in range(max(pb.HD, 1))]
        self.nopen = [0] * max(pb.HD, 1)
        tmp = {}
        for p, l in enumerate(self.loc):
            if isinstance(l, tuple):
                tmp.setdefault(l, []).append(p)
        for (hd, s), ps in tmp.items():
            self.bins[hd][s] = tuple(sorted(ps))
        for hd in range(pb.HD):
            self.nopen[hd] = sum(1 for m in self.bins[hd] if m)


# ----------------------------------------------------------------------------------------------- search driver
def search(pb, st, seed, deadline, report=None, stats=None):
    rng = random.Random(seed)
    pb.local_search(st, rng, deadline)
    cur = pb.total(st)
    best, best_loc = cur, list(st.loc)
    if report:
        report(best_loc, best)
    t_begin = time.monotonic()
    span = max(1e-3, deadline - t_begin)
    it = 0
    while time.monotonic() < deadline:
        it += 1
        saved = list(st.loc)
        pb.ruin_recreate(st, rng)
        pb.local_search(st, rng, deadline)
        new = pb.total(st)
        frac = min(1.0, (time.monotonic() - t_begin) / span)
        thr = 0.003 * max(1.0, abs(best)) * max(0.0, 1.0 - frac / 0.8)
        if new < best - 1e-7:
            best, best_loc = new, list(st.loc)
            if report:
                report(best_loc, best)
        if new <= best + thr:
            cur = new
        else:
            st.set_loc(saved)
    if stats is not None:
        stats.update(iterations=it, best=best, rec_calls=pb.rec_calls, rec_misses=pb.rec_misses)
    return best, best_loc


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def solve(inst, out_path, time_limit, seed=1, workers=2):
    pb = Problem(inst)
    search_end = T_START + max(0.5, min(0.85 * time_limit, time_limit - 4.0))
    log = {"version": VERSION, "P": pb.P, "H": pb.H, "D": pb.D, "R": pb.R, "S": pb.S,
           "mandatory": sum(1 for k in pb.kind if k == "m"), "events": []}
    st = pb.construct()
    init_cost = pb.total(st)
    write_json(out_path, pb.solution(st.loc))
    log["init"] = init_cost
    log["events"].append([round(time.monotonic() - T_START, 2), init_cost])
    last_write = [time.monotonic()]

    def report(loc, cost):
        log["events"].append([round(time.monotonic() - T_START, 2), cost])
        now = time.monotonic()
        if now - last_write[0] >= 3.0 and now < search_end:
            write_json(out_path, pb.solution(loc))
            last_write[0] = now

    child = None
    conn = None
    if workers >= 2 and hasattr(os, "fork") and pb.patients:
        try:
            import multiprocessing as mp
            ctx = mp.get_context("fork")
            conn, child_conn = ctx.Pipe(duplex=False)

            def run_child():
                try:
                    cst = State(pb)
                    cst.set_loc(st.loc)
                    cs = {}
                    b, bl = search(pb, cst, seed + 7919, search_end, None, cs)
                    child_conn.send((b, bl, cs))
                except Exception as e:  # noqa: BLE001
                    child_conn.send((None, None, {"error": repr(e)[:300]}))
                finally:
                    child_conn.close()

            child = ctx.Process(target=run_child, daemon=True)
            child.start()
        except Exception as e:  # noqa: BLE001 - single process is fine
            log["fork_error"] = repr(e)[:300]
            child = None
    stats = {}
    best, best_loc = search(pb, st, seed, search_end, report, stats)
    log["main"] = stats
    if child is not None:
        try:
            wait = max(0.2, min(2.0, T_START + time_limit - 3.0 - time.monotonic()))
            if conn.poll(wait):
                cb, cl, cstats = conn.recv()
                log["child"] = cstats
                if cb is not None:
                    # judge both by the same (memoised) model cost
                    tmp = State(pb)
                    tmp.set_loc(cl)
                    cb2 = pb.total(tmp)
                    if cb2 < best - 1e-7:
                        best, best_loc = cb2, cl
                        log["winner"] = "child"
            else:
                log["child"] = "no answer in time"
        except Exception as e:  # noqa: BLE001
            log["child_error"] = repr(e)[:300]
        try:
            child.terminate()
        except Exception:  # noqa: BLE001
            pass
    sol = pb.solution(best_loc)
    write_json(out_path, sol)
    log["final_model_cost"] = best
    log["final_objective"] = sol["objective_value"]
    log["wall_s"] = round(time.monotonic() - T_START, 3)
    return sol, log


def main(argv=None):
    ap = argparse.ArgumentParser(description="guo2021 (stochastic distributed OR scheduling) solver, MV2 of Munim, Inc.")
    ap.add_argument("--problem", default="guo2021")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    sol, log = solve(inst, a.output, a.time_limit, a.seed, a.workers)
    if os.environ.get("MV2_GUO_LOG") == "1":
        try:
            write_json(a.output + ".log.json", log)
        except Exception:  # noqa: BLE001
            pass
    sys.stderr.write(json.dumps({k: log.get(k) for k in ("version", "P", "S", "init", "final_objective", "wall_s")})
                     + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

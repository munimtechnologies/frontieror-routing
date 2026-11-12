"""vidal2011 (multi-depot periodic vehicle routing, MDPVRP) solver for the FrontierOR Challenge, v0.1.0.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Rules, read from the public FrontierOR benchmark's problem_description.txt, gurobi_code.py and feasibility_check.py
(Hugging Face frontieror/FrontierOR, task vidal2011, CC BY 4.0):
- vertices: depots 0..d-1, customer c is vertex d + c; cost = travel time = Euclidean distance on the raw
  coordinates (no rounding), computed exactly as the checker does;
- each customer gets ONE (depot, pattern) pair; on each period l in 1..t of its pattern it is visited exactly once,
  by a route of that depot; on other periods it is not visited;
- per depot and period at most m routes (vehicles numbered 1..m, each departs at most once);
- per route: total demand <= vehicle_capacity; travel + service of the visited customers <= route_duration_limit;
- objective = total travel cost of all routes, recomputed by the checker (0.1% tolerance).
Output: {"objective_value", "routes": [{"depot", "period", "vehicle", "customers"}],
         "assignments": {"<customer id>": {"depot", "pattern"}}}.

Search (standard library only): every (depot, period) has m route slots; a solution may break capacity or
duration while searching, at an adaptive penalty, but only solutions that pass verify() (an independent copy of the
official constraints, tighter tolerance) are ever written, atomically. Construction = cheapest penalised insertion
of each customer over all its (depot, pattern) options. Then simulated annealing with: relocate (best / random),
swap, 2-opt, 2-opt* (both reconnections), reassign one customer to another (depot, pattern) (best / random), and
ruin-and-recreate of a group of nearby customers. Four phases: from the construction, two restarts from the best
feasible solution at lower temperatures, and a high-penalty polish. With 2 CPUs a forked child searches with a
second seed and hands its best solution back before the deadline min(0.9 T, T - 3).
"""
import argparse
import json
import math
import os
import random
import sys
import time

T_START = time.monotonic()
VERSION = "0.1.0"
FEAS_TOL = 1e-7  # ours; the official checker allows 1e-5


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


class Problem:
    def __init__(self, inst):
        self.n = int(inst["n"])
        self.d = int(inst["d"])
        self.t = int(inst["t"])
        self.m = int(inst["m"])
        self.Q = inst["vehicle_capacity"]
        self.T = inst["route_duration_limit"]
        d, n = self.d, self.n
        N = d + n
        xs = [0] * N
        ys = [0] * N
        for dep in inst["depots"]:
            i = int(dep["id"])
            xs[i], ys[i] = dep["x"], dep["y"]
        self.dem = [0] * N
        self.svc = [0] * N
        self.pat = [None] * n
        self.days = [None] * n
        for c in inst["customers"]:
            cid = int(c["id"])
            v = d + cid
            xs[v], ys[v] = c["x"], c["y"]
            self.dem[v] = c["demand"]
            self.svc[v] = c["service_duration"]
            self.pat[cid] = [list(p) for p in c["pattern_list"]]
            self.days[cid] = [sorted({int(x) for x in p if 1 <= int(x) <= self.t}) for p in c["pattern_list"]]
        self.D = [[math.sqrt((xs[i] - xs[j]) ** 2 + (ys[i] - ys[j]) ** 2) for j in range(N)] for i in range(N)]
        self.opts = [[(o, pi) for o in range(d) for pi in range(len(self.pat[c]))] for c in range(n)]
        if any(not op for op in self.opts):
            raise ValueError("a customer has no feasible pattern")

    def route_eval(self, o, seq):
        """(travel cost, load, service) of depot o -> seq -> o, summed in the checker's order."""
        if not seq:
            return (0.0, 0, 0)
        D = self.D
        prev = o
        c = 0.0
        ld = 0
        sv = 0
        for v in seq:
            c += D[prev][v]
            ld += self.dem[v]
            sv += self.svc[v]
            prev = v
        c += D[prev][o]
        return (c, ld, sv)


# --------------------------------------------------------------------------------------------- verify / output
def verify(pb, sol):
    """Independent re-implementation of the official constraints. Returns (ok, why, recomputed cost)."""
    try:
        return _verify(pb, sol)
    except Exception as e:  # noqa: BLE001 - malformed means rejected
        return False, "verify error %r" % (e,), None


def _verify(pb, sol):
    d, n, t, m = pb.d, pb.n, pb.t, pb.m
    obj = sol.get("objective_value")
    if isinstance(obj, bool) or not isinstance(obj, (int, float)) or not math.isfinite(obj):
        return False, "objective_value not a finite number", None
    asg = sol["assignments"]
    routes = sol["routes"]
    if not isinstance(asg, dict) or not isinstance(routes, list):
        return False, "bad types", None
    if len(asg) != n:
        return False, "assignments has %d keys, need %d" % (len(asg), n), None
    patt = {}
    for c in range(n):
        a = asg.get(str(c))
        if not isinstance(a, dict):
            return False, "customer %d unassigned" % c, None
        o = a.get("depot")
        if not _is_int(o) or not 0 <= o < d:
            return False, "customer %d bad depot %r" % (c, o), None
        p = a.get("pattern")
        if not isinstance(p, list) or tuple(p) not in {tuple(x) for x in pb.pat[c]}:
            return False, "customer %d pattern %r not in its list" % (c, p), None
        patt[c] = (o, set(p))
    seen = set()
    visits = {}
    cost = 0.0
    D = pb.D
    for idx, r in enumerate(routes):
        o, l, k, cs = r.get("depot"), r.get("period"), r.get("vehicle"), r.get("customers")
        if not _is_int(o) or not 0 <= o < d:
            return False, "route %d bad depot" % idx, None
        if not _is_int(l) or not 1 <= l <= t:
            return False, "route %d bad period" % idx, None
        if not _is_int(k) or not 1 <= k <= m:
            return False, "route %d vehicle %r not in 1..%d" % (idx, k, m), None
        if (o, l, k) in seen:
            return False, "route %d: vehicle %d of depot %d departs twice on period %d" % (idx, k, o, l), None
        seen.add((o, l, k))
        if not isinstance(cs, list) or not cs:
            return False, "route %d empty or not a list" % idx, None
        if len(set(cs)) != len(cs):
            return False, "route %d repeats a customer" % idx, None
        travel = 0.0
        load = 0
        svc = 0
        prev = o
        for c in cs:
            if not _is_int(c) or not 0 <= c < n:
                return False, "route %d bad customer %r" % (idx, c), None
            if patt[c][0] != o:
                return False, "customer %d visited from depot %d, assigned %d" % (c, o, patt[c][0]), None
            visits[(c, l)] = visits.get((c, l), 0) + 1
            v = d + c
            travel += D[prev][v]
            load += pb.dem[v]
            svc += pb.svc[v]
            prev = v
        travel += D[prev][o]
        if load > pb.Q + FEAS_TOL:
            return False, "route %d over capacity %s > %s" % (idx, load, pb.Q), None
        if travel + svc > pb.T + FEAS_TOL:
            return False, "route %d duration %.6f > %s" % (idx, travel + svc, pb.T), None
        cost += travel
    for c in range(n):
        o, ps = patt[c]
        for l in range(1, t + 1):
            exp = 1 if l in ps else 0
            if visits.get((c, l), 0) != exp:
                return False, "customer %d period %d: %d visits, need %d" % (c, l, visits.get((c, l), 0), exp), None
    if abs(obj - cost) > 1e-6 * max(1.0, abs(cost)):
        return False, "objective %s != recomputed %s" % (obj, cost), None
    return True, "", cost


def solution_json(pb, asg, R):
    d = pb.d
    routes = []
    obj = 0.0
    for o in range(d):
        for l in range(1, pb.t + 1):
            kk = 0
            for k in range(pb.m):
                seq = R[o][l][k]
                if not seq:
                    continue
                kk += 1
                routes.append({"depot": o, "period": l, "vehicle": kk, "customers": [v - d for v in seq]})
                obj += pb.route_eval(o, seq)[0]
    assignments = {str(c): {"depot": asg[c][0], "pattern": list(pb.pat[c][asg[c][1]])} for c in range(pb.n)}
    return {"objective_value": obj, "routes": routes, "assignments": assignments,
            "solver": "MV2 vidal2011 MDPVRP v%s (made with AI agents working in MV2's name)" % VERSION}


# ----------------------------------------------------------------------------------------------------- state
class State:
    """m route slots per (depot, period). Route lists are never mutated in place (journal = old references)."""

    def __init__(self, pb, lq, lt):
        self.pb = pb
        d, t, m, n = pb.d, pb.t, pb.m, pb.n
        self.lq = lq
        self.lt = lt
        self.asg = [None] * n
        self.R = [[[[] for _ in range(m)] for _ in range(t + 1)] for _ in range(d)]
        self.rc = [[[(0.0, 0, 0) for _ in range(m)] for _ in range(t + 1)] for _ in range(d)]
        self.where = [dict() for _ in range(d + n)]
        self.cost = 0.0
        self.F = 0.0
        self.nviol = 0
        self.j = None
        self.ja = None

    # penalised value and feasibility of one route
    def pen(self, rcv):
        c, ld, sv = rcv
        p = c
        Q, T = self.pb.Q, self.pb.T
        if ld > Q:
            p += self.lq * (ld - Q)
        e = c + sv - T
        if e > 0:
            p += self.lt * e
        return p

    def bad(self, rcv):
        c, ld, sv = rcv
        return 1 if (ld > self.pb.Q + FEAS_TOL or c + sv > self.pb.T + FEAS_TOL) else 0

    def recompute_totals(self):
        F = 0.0
        cost = 0.0
        nv = 0
        for o in range(self.pb.d):
            for l in range(1, self.pb.t + 1):
                for k in range(self.pb.m):
                    rcv = self.rc[o][l][k]
                    F += self.pen(rcv)
                    cost += rcv[0]
                    nv += self.bad(rcv)
        self.F, self.cost, self.nviol = F, cost, nv

    # journal
    def begin(self):
        self.j = {}
        self.ja = {}

    def set_route(self, o, l, k, seq):
        key = (o, l, k)
        if key not in self.j:
            self.j[key] = (self.R[o][l][k], self.rc[o][l][k])
        self.R[o][l][k] = seq
        self.rc[o][l][k] = self.pb.route_eval(o, seq)
        for v in seq:
            self.where[v][l] = k

    def set_asg(self, c, a):
        if c not in self.ja:
            self.ja[c] = self.asg[c]
        self.asg[c] = a

    def delta(self):
        dF = 0.0
        dc = 0.0
        dv = 0
        for (o, l, k), (_, old) in self.j.items():
            new = self.rc[o][l][k]
            dF += self.pen(new) - self.pen(old)
            dc += new[0] - old[0]
            dv += self.bad(new) - self.bad(old)
        return dF, dc, dv

    def commit(self, dF, dc, dv):
        self.F += dF
        self.cost += dc
        self.nviol += dv
        self.j = None
        self.ja = None

    def undo(self):
        for (o, l, k), (seq, rcv) in self.j.items():
            self.R[o][l][k] = seq
            self.rc[o][l][k] = rcv
            for v in seq:
                self.where[v][l] = k
        for c, a in self.ja.items():
            self.asg[c] = a
        self.j = None
        self.ja = None

    # snapshots
    def snapshot(self):
        return (list(self.asg), [[list(self.R[o][l]) for l in range(self.pb.t + 1)] for o in range(self.pb.d)])

    def load(self, snap):
        asg, R = snap
        pb = self.pb
        self.asg = list(asg)
        self.R = [[list(R[o][l]) for l in range(pb.t + 1)] for o in range(pb.d)]
        self.where = [dict() for _ in range(pb.d + pb.n)]
        for o in range(pb.d):
            for l in range(1, pb.t + 1):
                for k in range(pb.m):
                    seq = self.R[o][l][k]
                    self.rc[o][l][k] = pb.route_eval(o, seq)
                    for v in seq:
                        self.where[v][l] = k
        self.recompute_totals()

    # insertion primitives
    def best_insert(self, o, l, v):
        pb = self.pb
        D = pb.D
        Q, T, lq, lt = pb.Q, pb.T, self.lq, self.lt
        dv_ = pb.dem[v]
        sv_ = pb.svc[v]
        best = None
        empty_done = False
        Rl = self.R[o][l]
        rcl = self.rc[o][l]
        Dv = D[v]
        for k in range(pb.m):
            seq = Rl[k]
            if not seq:
                if empty_done:
                    continue
                empty_done = True
            c, ld, sv = rcl[k]
            base = c
            if ld > Q:
                base += lq * (ld - Q)
            if c + sv > T:
                base += lt * (c + sv - T)
            nld = ld + dv_
            nsv = sv + sv_
            pq = lq * (nld - Q) if nld > Q else 0.0
            prev = o
            L = len(seq)
            for p in range(L + 1):
                nxt = seq[p] if p < L else o
                nc = c + D[prev][v] + Dv[nxt] - D[prev][nxt]
                e = nc + nsv - T
                val = nc + pq + (lt * e if e > 0 else 0.0) - base
                if best is None or val < best[0]:
                    best = (val, k, p)
                prev = nxt
        return best

    def insert_at(self, o, l, k, p, v):
        seq = self.R[o][l][k]
        self.set_route(o, l, k, seq[:p] + [v] + seq[p:])

    def remove_visit(self, c, l):
        v = self.pb.d + c
        o = self.asg[c][0]
        k = self.where[v][l]
        seq = self.R[o][l][k]
        self.set_route(o, l, k, [x for x in seq if x != v])

    def remove_customer(self, c):
        o, pi = self.asg[c]
        for l in self.pb.days[c][pi]:
            self.remove_visit(c, l)

    def option_cost(self, c, o, pi):
        v = self.pb.d + c
        tot = 0.0
        for l in self.pb.days[c][pi]:
            tot += self.best_insert(o, l, v)[0]
        return tot

    def insert_customer(self, c, o, pi):
        v = self.pb.d + c
        self.set_asg(c, (o, pi))
        for l in self.pb.days[c][pi]:
            _, k, p = self.best_insert(o, l, v)
            self.insert_at(o, l, k, p, v)

    def insert_customer_best(self, c, rng, noise, exclude=None):
        best = None
        for (o, pi) in self.pb.opts[c]:
            if exclude is not None and (o, pi) == exclude:
                continue
            tot = self.option_cost(c, o, pi)
            if noise > 0:
                tot += noise * rng.random()
            if best is None or tot < best[0]:
                best = (tot, o, pi)
        if best is None:
            return False
        self.insert_customer(c, best[1], best[2])
        return True

    # moves (each returns False only before changing anything)
    def _visit(self, rng):
        c = rng.randrange(self.pb.n)
        o, pi = self.asg[c]
        ds = self.pb.days[c][pi]
        if not ds:
            return None
        return c, o, rng.choice(ds)

    def mv_relocate(self, rng, best):
        x = self._visit(rng)
        if x is None:
            return False
        c, o, l = x
        v = self.pb.d + c
        self.remove_visit(c, l)
        if best:
            _, k, p = self.best_insert(o, l, v)
        else:
            k = rng.randrange(self.pb.m)
            p = rng.randint(0, len(self.R[o][l][k]))
        self.insert_at(o, l, k, p, v)
        return True

    def mv_swap(self, rng):
        x = self._visit(rng)
        if x is None:
            return False
        c, o, l = x
        v = self.pb.d + c
        Rl = self.R[o][l]
        k1 = self.where[v][l]
        cand = [(k, i) for k in range(self.pb.m) for i, u in enumerate(Rl[k]) if u != v]
        if not cand:
            return False
        k2, i2 = rng.choice(cand)
        u = Rl[k2][i2]
        if k1 == k2:
            s = list(Rl[k1])
            i1 = s.index(v)
            s[i1], s[i2] = u, v
            self.set_route(o, l, k1, s)
        else:
            s1 = [u if y == v else y for y in Rl[k1]]
            s2 = [v if y == u else y for y in Rl[k2]]
            self.set_route(o, l, k1, s1)
            self.set_route(o, l, k2, s2)
        return True

    def mv_2opt(self, rng):
        x = self._visit(rng)
        if x is None:
            return False
        c, o, l = x
        k = self.where[self.pb.d + c][l]
        s = self.R[o][l][k]
        if len(s) < 2:
            return False
        i = rng.randrange(len(s) - 1)
        j = rng.randrange(i + 1, len(s))
        self.set_route(o, l, k, s[:i] + s[i:j + 1][::-1] + s[j + 1:])
        return True

    def mv_2optstar(self, rng):
        if self.pb.m < 2:
            return False
        x = self._visit(rng)
        if x is None:
            return False
        c, o, l = x
        k1 = self.where[self.pb.d + c][l]
        k2 = rng.randrange(self.pb.m - 1)
        if k2 >= k1:
            k2 += 1
        A = self.R[o][l][k1]
        B = self.R[o][l][k2]
        i = rng.randint(0, len(A))
        j = rng.randint(0, len(B))
        if rng.random() < 0.5:
            nA = A[:i] + B[j:]
            nB = B[:j] + A[i:]
        else:
            nA = A[:i] + B[:j][::-1]
            nB = A[i:][::-1] + B[j:]
        self.set_route(o, l, k1, nA)
        self.set_route(o, l, k2, nB)
        return True

    def mv_reassign(self, rng, best):
        c = rng.randrange(self.pb.n)
        opts = self.pb.opts[c]
        if len(opts) < 2:
            return False
        cur = self.asg[c]
        self.remove_customer(c)
        if best:
            self.insert_customer_best(c, rng, 0.0, exclude=cur)
        else:
            k = rng.randrange(len(opts) - 1)
            if opts[k] == cur:
                k = len(opts) - 1
            self.insert_customer(c, opts[k][0], opts[k][1])
        return True

    def mv_ruin(self, rng, near, qmax, noise):
        n = self.pb.n
        if n < 2:
            return False
        c0 = rng.randrange(n)
        q = rng.randint(2, max(2, qmax))
        group = list(near[c0][:q])
        for c in group:
            self.remove_customer(c)
        if rng.random() < 0.5:
            rng.shuffle(group)
        else:
            group.sort(key=lambda c: -self.pb.dem[self.pb.d + c] * len(self.pb.days[c][self.asg[c][1]]))
        for c in group:
            self.insert_customer_best(c, rng, noise)
        return True


# ---------------------------------------------------------------------------------------------------- search
def search(pb, seed, t_end, offer, log):
    rng = random.Random(seed)
    n, d = pb.n, pb.d
    D = pb.D
    if n >= 2:
        avg = sum(D[d + i][d + j] for i in range(n) for j in range(n) if i != j) / (n * (n - 1))
    else:
        avg = max(1.0, max(max(r) for r in D))
    avg = max(avg, 1e-6)
    mean_dem = max(1e-9, sum(pb.dem[d + c] for c in range(n)) / max(1, n))
    lq0 = 2.0 * avg / mean_dem
    lt0 = 2.0
    st = State(pb, lq0, lt0)
    near = [sorted(range(n), key=lambda u, c=c: (D[d + c][d + u], u)) for c in range(n)]
    order = sorted(range(n), key=lambda c: (-max(len(ds) for ds in pb.days[c]) * pb.dem[d + c], rng.random()))
    st.begin()
    for c in order:
        st.insert_customer_best(c, rng, 0.0)
    st.j = None
    st.ja = None
    st.recompute_totals()
    log["construction"] = {"cost": round(st.cost, 4), "violated_routes": st.nviol}
    best = {"cost": None, "snap": None}

    def consider(source):
        st.recompute_totals()
        if st.nviol == 0 and (best["cost"] is None or st.cost < best["cost"] - 1e-9):
            best["cost"] = st.cost
            best["snap"] = st.snapshot()
            offer(best["snap"], source)

    consider("construction")
    qmax = max(2, min(12, n // 4))
    noise = 0.3 * avg
    t0 = time.monotonic()
    total = max(0.0, t_end - t0)
    plan = [("sa1", 0.40, 1.0), ("sa2", 0.27, 0.5), ("sa3", 0.20, 0.25), ("polish", 0.13, 0.0)]
    stats = {"iterations": 0, "accepted": 0, "phases": []}
    ph_start = t0
    for name, frac, scale in plan:
        ph_end = min(t_end, ph_start + frac * total)
        if name == "polish":
            ph_end = t_end
        if ph_end <= time.monotonic():
            break
        if name != "sa1" and best["snap"] is not None:
            st.load(best["snap"])
        polish = scale == 0.0
        if polish:
            st.lq, st.lt = lq0 * 1e4, lt0 * 1e4
        else:
            st.lq, st.lt = max(st.lq, lq0), max(st.lt, lt0)
        st.recompute_totals()
        temp0 = 0.1 * avg * (scale if scale > 0 else 0.01)
        tend = 0.002 * avg if not polish else 1e-6 * avg
        temp = temp0
        it = 0
        acc = 0
        feas = 0
        cnt = 0
        start = time.monotonic()
        while True:
            if (it & 63) == 0:
                now = time.monotonic()
                if now >= ph_end:
                    break
                x = (now - start) / max(1e-9, ph_end - start)
                temp = temp0 * (tend / temp0) ** x if temp0 > tend else tend
            it += 1
            r = rng.random()
            st.begin()
            if r < 0.22:
                ok = st.mv_relocate(rng, True)
            elif r < 0.32:
                ok = st.mv_relocate(rng, False)
            elif r < 0.46:
                ok = st.mv_swap(rng)
            elif r < 0.60:
                ok = st.mv_2opt(rng)
            elif r < 0.72:
                ok = st.mv_2optstar(rng)
            elif r < 0.80:
                ok = st.mv_reassign(rng, True)
            elif r < 0.88:
                ok = st.mv_reassign(rng, False)
            else:
                ok = st.mv_ruin(rng, near, qmax, noise)
            if not ok:
                st.undo()
                continue
            dF, dc, dv = st.delta()
            if dF <= 1e-12 or rng.random() < math.exp(-dF / temp):
                st.commit(dF, dc, dv)
                acc += 1
                if st.nviol == 0 and (best["cost"] is None or st.cost < best["cost"] - 1e-7):
                    consider(name)
            else:
                st.undo()
            cnt += 1
            if st.nviol == 0:
                feas += 1
            if cnt >= 300:
                if not polish:
                    share = feas / float(cnt)
                    if share < 0.3:
                        st.lq = min(st.lq * 1.4, lq0 * 1e4)
                        st.lt = min(st.lt * 1.4, lt0 * 1e4)
                    elif share > 0.7:
                        st.lq = max(st.lq / 1.2, lq0 * 0.05)
                        st.lt = max(st.lt / 1.2, lt0 * 0.05)
                feas = 0
                cnt = 0
                st.recompute_totals()
        stats["iterations"] += it
        stats["accepted"] += acc
        stats["phases"].append([name, it, acc, None if best["cost"] is None else round(best["cost"], 4)])
        ph_start = time.monotonic()
    log["search"] = stats
    return best["cost"], best["snap"]


# ----------------------------------------------------------------------------------------------------- driver
def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def solve(inst, out_path, time_limit, seed=1, workers=2, t0=None):
    T0 = T_START if t0 is None else t0
    pb = Problem(inst)
    end = T0 + max(0.5, min(0.9 * time_limit, time_limit - 3.0))
    search_end = end - min(1.0, 0.08 * max(0.0, end - T0))
    log = {"version": VERSION, "n": pb.n, "d": pb.d, "t": pb.t, "m": pb.m, "events": [], "workers": workers}
    best = {"obj": None, "sol": None, "last_write": 0.0, "source": None}

    def offer(snap, source):
        sol = solution_json(pb, snap[0], snap[1])
        ok, why, cost = verify(pb, sol)
        if not ok:
            log.setdefault("verify_fail", []).append([source, why])
            return False
        if best["obj"] is None or cost < best["obj"] - 1e-9:
            best["obj"], best["sol"], best["source"] = cost, sol, source
            log["events"].append([round(time.monotonic() - T0, 2), source, round(cost, 4)])
            now = time.monotonic()
            if best["last_write"] == 0.0 or now - best["last_write"] >= 0.5:
                write_json(out_path, sol)
                best["last_write"] = now
            return True
        return False

    child, conn = None, None
    if workers >= 2 and hasattr(os, "fork"):
        try:
            import multiprocessing as mp
            ctx = mp.get_context("fork")
            conn, cconn = ctx.Pipe(duplex=False)

            def run_child():
                try:
                    clog = {}
                    cost, snap = search(pb, seed + 7919, search_end, lambda s, src: None, clog)
                    cconn.send((cost, snap, clog.get("search")))
                except Exception as e:  # noqa: BLE001
                    cconn.send((None, None, repr(e)[:300]))
                finally:
                    cconn.close()
            child = ctx.Process(target=run_child, daemon=True)
            child.start()
        except Exception as e:  # noqa: BLE001
            log["fork_error"] = repr(e)[:300]
            child = None
    search(pb, seed, search_end, offer, log)
    if child is not None:
        try:
            if conn.poll(max(0.05, end - time.monotonic() - 0.2)):
                ccost, csnap, cstats = conn.recv()
                log["child"] = {"cost": ccost, "search": cstats}
                if csnap is not None:
                    offer(csnap, "child")
            else:
                log["child"] = "no answer in time"
        except Exception as e:  # noqa: BLE001
            log["child_error"] = repr(e)[:300]
        try:
            child.terminate()
        except Exception:  # noqa: BLE001
            pass
    if best["sol"] is not None:
        write_json(out_path, best["sol"])
    log["final_objective"] = best["obj"]
    log["best_source"] = best["source"]
    log["final_routes"] = len(best["sol"]["routes"]) if best["sol"] else None
    log["wall_s"] = round(time.monotonic() - T0, 3)
    return best["obj"], log


def main(argv=None):
    ap = argparse.ArgumentParser(description="vidal2011 (MDPVRP) solver, MV2 of Munim, Inc.")
    ap.add_argument("--problem", default="vidal2011")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    workers = int(os.environ.get("MV2_VIDAL_WORKERS", a.workers))
    obj, log = solve(inst, a.output, a.time_limit, a.seed, workers)
    if os.environ.get("MV2_VIDAL_LOG") == "1":
        try:
            write_json(a.output + ".log.json", log)
        except Exception:  # noqa: BLE001
            pass
    sys.stderr.write(json.dumps({k: log.get(k) for k in ("version", "n", "d", "t", "m", "construction",
                                                         "final_objective", "best_source", "final_routes",
                                                         "wall_s")}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

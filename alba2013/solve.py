#!/usr/bin/env python3
"""MV2's solver for FrontierOR task alba2013: the double traveling salesman problem with multiple stacks (DTSPMS).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python solve.py --problem alba2013 --instance in.json --output out.json --time-limit 60

Standard library only. One vehicle picks up n unit items in a pickup region (tour from depot 0), then delivers them in
a delivery region (tour from depot 0); its s stacks hold at most l items each and are last-in-first-out. As in the
official checker and the reference model, item i is picked up at pickup vertex i and delivered at delivery vertex i.

Representation: a loading plan, i.e. s stacks, each an ordered list of items from bottom to top. A plan fixes which
item orders are allowed: the pickup tour must load every stack bottom to top and the delivery tour must unload every
stack top to bottom; how the stacks interleave is free. For a given plan both optimal tours are found EXACTLY by a
dynamic program over (items taken from each stack, stack of the last item), with O(prod(|stack|+1) * s^2) work.
Every feasible answer has a loading plan, so searching over plans loses nothing, and every answer written is
load-feasible by construction.

Search: simulated annealing over plans on a clock schedule (moves: relocate one item, swap two items, move a block of
2-4 items, exchange the tops of two stacks), with a cache of plan costs and restarts from the best plan after long
stagnation. Starts from tours built by nearest neighbour + 2-opt in either region, dealt into the stacks. Every new
best is checked by verify() (the official checker's rules, including its LIFO backtracking) and written atomically.
With two CPUs a forked child runs the same search with another seed; the parent keeps the better answer.
The run stops at min(0.9 T, T - 3) seconds after start-up.
Environment: MV2_DTSP_WORKERS (default 2; 1 = no child), MV2_DTSP_SEED (default 1), MV2_DTSP_LOG (write
<output>.log.json).
"""
import argparse
import json
import math
import os
import random
import sys
import tempfile
import time

T_START = time.time()
VERSION = "0.1.0"
EPS = 1e-9
INF = float("inf")


class Problem:
    def __init__(self, inst):
        p = inst["parameters"]
        self.n = int(p["num_requests_n"])
        self.s = int(p["num_stacks_s"])
        self.l = int(p["stack_height_l"])
        self.CP = [list(r) for r in inst["pickup_region"]["distance_matrix"]]
        self.CD = [list(r) for r in inst["delivery_region"]["distance_matrix"]]
        n = self.n
        for M in (self.CP, self.CD):
            if len(M) < n + 1 or any(len(r) < n + 1 for r in M[:n + 1]):
                raise ValueError("distance matrix smaller than (n+1) x (n+1)")
        self.items = list(range(1, n + 1))
        self.feasible_size = n <= self.s * self.l
        self.sym = all(M[i][j] == M[j][i] for M in (self.CP, self.CD) for i in range(n + 1) for j in range(i + 1, n + 1))

    def tour_cost(self, M, tour):
        """Cost of a closed tour given as [0, v1, ..., vn] (the checker's wrap-around rule)."""
        c = 0
        L = len(tour)
        for i in range(L):
            c += M[tour[i]][tour[(i + 1) % L]]
        return c


def dp_tour(seqs, C):
    """Cheapest closed tour from depot 0 that takes every sequence in seqs in its own order, interleaved freely.
    Returns (cost, order of items)."""
    seqs = [q for q in seqs if q]
    if not seqs:
        return 0, []
    s = len(seqs)
    sizes = [len(q) for q in seqs]
    mult = []
    m = 1
    for z in sizes:
        mult.append(m)
        m *= z + 1
    total = m
    best = [INF] * (total * s)
    par = [-1] * (total * s)
    C0 = C[0]
    for k in range(s):
        best[mult[k] * s + k] = C0[seqs[k][0]]
    rs = range(s)
    for idx in range(1, total):
        base = idx * s
        cnt = [(idx // mult[i]) % (sizes[i] + 1) for i in rs]
        for k in rs:
            v = best[base + k]
            if v == INF:
                continue
            Cl = C[seqs[k][cnt[k] - 1]]
            for j in rs:
                cj = cnt[j]
                if cj < sizes[j]:
                    nv = v + Cl[seqs[j][cj]]
                    ni = (idx + mult[j]) * s + j
                    if nv < best[ni]:
                        best[ni] = nv
                        par[ni] = k
    full = total - 1
    bv, bk = INF, -1
    for k in rs:
        v = best[full * s + k]
        if v < INF:
            v += C[seqs[k][-1]][0]
            if v < bv:
                bv, bk = v, k
    order = []
    idx, k = full, bk
    while idx > 0 and k >= 0:
        c = (idx // mult[k]) % (sizes[k] + 1)
        order.append(seqs[k][c - 1])
        pk = par[idx * s + k]
        idx -= mult[k]
        k = pk
    order.reverse()
    return bv, order


def plan_tours(pb, plan):
    """(total cost, pickup order, delivery order) of the best tours for a loading plan."""
    cp, po = dp_tour(plan, pb.CP)
    cd, do = dp_tour([list(reversed(st)) for st in plan], pb.CD)
    return cp + cd, po, do


class Evaluator:
    def __init__(self, pb):
        self.pb = pb
        self.cache = {}
        self.calls = 0
        self.hits = 0

    def cost(self, plan):
        key = tuple(sorted(tuple(st) for st in plan))
        self.calls += 1
        v = self.cache.get(key)
        if v is not None:
            self.hits += 1
            return v
        cp, _ = dp_tour(plan, self.pb.CP)
        cd, _ = dp_tour([list(reversed(st)) for st in plan], self.pb.CD)
        v = cp + cd
        if len(self.cache) > 300000:
            self.cache.clear()
        self.cache[key] = v
        return v


def nn_two_opt(M, nodes, rng=None):
    """A closed tour over 0 + nodes: nearest neighbour from 0 (random ties), then 2-opt (full recomputation)."""
    left = set(nodes)
    order = []
    cur = 0
    while left:
        bestv = min(M[cur][v] for v in left)
        cands = sorted(v for v in left if M[cur][v] == bestv)
        v = rng.choice(cands) if rng else cands[0]
        order.append(v)
        left.discard(v)
        cur = v

    def cost(o):
        c, prev = 0, 0
        for v in o:
            c += M[prev][v]
            prev = v
        return c + M[prev][0]
    bc = cost(order)
    improved = True
    rounds = 0
    L = len(order)
    while improved and rounds < 100:
        improved = False
        rounds += 1
        for i in range(L - 1):
            for j in range(i + 1, L):
                cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                cc = cost(cand)
                if cc < bc - EPS:
                    order, bc, improved = cand, cc, True
    return order


def deal(order, s, l, chunk=False):
    """Deal items, in order, into s stacks bottom to top (cyclically, or in consecutive chunks)."""
    n = len(order)
    plan = [[] for _ in range(s)]
    if chunk:
        size = int(math.ceil(n / float(s))) if s else n
        size = min(size, l)
        k = 0
        for v in order:
            while len(plan[k]) >= size and k < s - 1:
                k += 1
            if len(plan[k]) >= l:
                k = min(range(s), key=lambda q: len(plan[q]))
            plan[k].append(v)
    else:
        k = 0
        for v in order:
            tries = 0
            while len(plan[k]) >= l and tries < s:
                k = (k + 1) % s
                tries += 1
            plan[k].append(v)
            k = (k + 1) % s
    return plan


def initial_plans(pb, rng):
    out = []
    if pb.n == 0:
        return [[[] for _ in range(pb.s)]]
    po = nn_two_opt(pb.CP, pb.items)
    do = nn_two_opt(pb.CD, pb.items)
    for chunk in (False, True):
        out.append(deal(po, pb.s, pb.l, chunk))
        # delivery order d: unloading is top first, so each stack (bottom to top) is its dealt items reversed
        out.append([list(reversed(st)) for st in deal(do, pb.s, pb.l, chunk)])
    r = list(pb.items)
    rng.shuffle(r)
    out.append(deal(r, pb.s, pb.l, False))
    return out


def neighbour(plan, rng, l):
    p = [list(st) for st in plan]
    s = len(p)
    nonempty = [k for k in range(s) if p[k]]
    if not nonempty:
        return None
    x = rng.random()
    if x < 0.5 or s == 1 and x < 0.75:
        src = rng.choice(nonempty)
        i = rng.randrange(len(p[src]))
        item = p[src].pop(i)
        dsts = [k for k in range(s) if len(p[k]) < l]
        dst = rng.choice(dsts)
        pos = rng.randint(0, len(p[dst]))
        if dst == src and pos == i:
            return None
        p[dst].insert(pos, item)
        return p
    if x < 0.75:
        a = rng.choice(nonempty)
        b = rng.choice(nonempty)
        i = rng.randrange(len(p[a]))
        j = rng.randrange(len(p[b]))
        if a == b and i == j:
            return None
        p[a][i], p[b][j] = p[b][j], p[a][i]
        return p
    if x < 0.9:
        src = rng.choice(nonempty)
        L = len(p[src])
        if L < 2:
            return None
        w = rng.randint(2, min(4, L))
        i = rng.randint(0, L - w)
        seg = p[src][i:i + w]
        del p[src][i:i + w]
        if rng.random() < 0.3:
            seg.reverse()
        dsts = [k for k in range(s) if len(p[k]) + w <= l]
        if not dsts:
            return None
        dst = rng.choice(dsts)
        pos = rng.randint(0, len(p[dst]))
        p[dst][pos:pos] = seg
        if p == plan:
            return None
        return p
    if s < 2:
        return None
    a, b = rng.sample(range(s), 2)
    ca = rng.randint(0, len(p[a]))
    cb = rng.randint(0, len(p[b]))
    ta, tb = p[a][ca:], p[b][cb:]
    if not ta and not tb:
        return None
    na, nb = p[a][:ca] + tb, p[b][:cb] + ta
    if len(na) > l or len(nb) > l:
        return None
    p[a], p[b] = na, nb
    return p


class Search:
    def __init__(self, pb, seed, deadline):
        self.pb = pb
        self.rng = random.Random(seed)
        self.deadline = deadline
        self.ev = Evaluator(pb)
        self.stats = {"seed": seed, "iterations": 0, "accepted": 0, "improved": 0, "restarts": 0}

    def run(self, on_improve=None):
        pb, rng, ev = self.pb, self.rng, self.ev
        t0 = time.time()
        span = max(1e-3, self.deadline - t0)
        plans = initial_plans(pb, rng)
        costs = [ev.cost(p) for p in plans]
        k = min(range(len(plans)), key=lambda q: costs[q])
        cur, fc = plans[k], costs[k]
        self.stats["construction"] = fc
        self.stats["construction_all"] = costs
        best, bf = [list(st) for st in cur], fc
        events = [[round(time.time() - T_START, 3), bf]]
        if on_improve:
            on_improve(best)
        if pb.n <= 1:
            self.stats["best"] = bf
            self.stats["events"] = events
            return best
        avg = max(1.0, fc) / float(2 * pb.n + 2)
        T0, Tf = 0.3 * avg, 0.003 * avg
        self.stats["T0"], self.stats["Tf"] = T0, Tf
        ratio = Tf / T0
        T = T0
        it = 0
        last_imp = 0
        stall = max(3000, 150 * pb.n)
        while True:
            it += 1
            if (it & 15) == 0 or it < 16:
                now = time.time()
                if now >= self.deadline:
                    break
                T = T0 * (ratio ** ((now - t0) / span))
            nw = neighbour(cur, rng, pb.l)
            if nw is None:
                continue
            fn = ev.cost(nw)
            if fn < fc - T * math.log(1.0 - rng.random() + 1e-300):
                cur, fc = nw, fn
                self.stats["accepted"] += 1
                if fn < bf - EPS:
                    best, bf = [list(st) for st in nw], fn
                    last_imp = it
                    self.stats["improved"] += 1
                    if len(events) < 400:
                        events.append([round(time.time() - T_START, 3), bf])
                    if on_improve:
                        on_improve(best)
            if it - last_imp > stall:
                cur = [list(st) for st in best]
                for _ in range(rng.randint(2, 4)):
                    q = neighbour(cur, rng, pb.l)
                    if q is not None:
                        cur = q
                fc = ev.cost(cur)
                last_imp = it
                self.stats["restarts"] += 1
        self.stats["iterations"] = it
        self.stats["best"] = bf
        self.stats["cache_calls"], self.stats["cache_hits"] = ev.calls, ev.hits
        self.stats["events"] = events[:5] + events[-15:]
        return best


def build_solution(pb, plan):
    cost, po, do = plan_tours(pb, plan)
    pt, dt = [0] + po, [0] + do
    real = pb.tour_cost(pb.CP, pt) + pb.tour_cost(pb.CD, dt)
    return {"objective_value": float(real), "status": "feasible", "pickup_tour": pt, "delivery_tour": dt,
            "loading_plan_bottom_to_top": [list(st) for st in plan]}


def loading_feasible(porder, dorder, s, l):
    """The official checker's LIFO test (same backtracking, same symmetry break)."""
    p_pos = {v: i for i, v in enumerate(porder)}
    d_pos = {v: i for i, v in enumerate(dorder)}
    stacks = [[] for _ in range(s)]

    def can_place(item, k):
        st = stacks[k]
        if len(st) >= l:
            return False
        for w in st:
            if p_pos[w] < p_pos[item]:
                if d_pos[item] > d_pos[w]:
                    return False
            elif p_pos[item] < p_pos[w]:
                if d_pos[w] > d_pos[item]:
                    return False
        return True

    def bt(idx):
        if idx == len(porder):
            return True
        item = porder[idx]
        for k in range(s):
            if can_place(item, k):
                stacks[k].append(item)
                if bt(idx + 1):
                    return True
                stacks[k].pop()
            if len(stacks[k]) == 0:
                break
        return False
    old = sys.getrecursionlimit()
    if old < len(porder) + 100:
        sys.setrecursionlimit(len(porder) + 100)
    return bt(0)


def _finite_number(v):
    return not isinstance(v, bool) and isinstance(v, (int, float)) and v == v and v not in (INF, -INF)


def verify(pb, sol, strict_depot_first=True):
    """(ok, reason, objective): the official checker's rules (contract, constraints 1-6), applied to a dict.
    Stricter in one way: tour entries must be ints. strict_depot_first also requires each tour to be listed from the
    depot: the official checker reads the visiting order as the list order with 0 removed, so a tour listed from
    another vertex would have its LIFO test run on an order the vehicle does not drive."""
    if not isinstance(sol, dict):
        return False, "solution is not a JSON object", None
    for f in ("delivery_tour", "objective_value", "pickup_tour"):
        if sol.get(f) is None:
            return False, "missing " + f, None
    ov = sol["objective_value"]
    if not _finite_number(ov):
        return False, "objective_value must be a finite number", None
    try:
        n = pb.n
        V = set(range(n + 1))
        tours = {}
        for name in ("pickup_tour", "delivery_tour"):
            t = sol[name]
            if not isinstance(t, list):
                return False, name + " is not a list", None
            for v in t:
                if not isinstance(v, int) or isinstance(v, bool):
                    return False, "%s has a non-integer vertex %r" % (name, v), None
            if set(t) != V or len(t) != n + 1:
                return False, "%s is not a tour over 0..%d" % (name, n), None
            if len(t) == 1:
                return False, "%s is a self-loop" % name, None
            if strict_depot_first and t[0] != 0:
                return False, "%s is not listed from the depot" % name, None
            tours[name] = t
        po = [v for v in tours["pickup_tour"] if v != 0]
        do = [v for v in tours["delivery_tour"] if v != 0]
        if not loading_feasible(po, do, pb.s, pb.l):
            return False, "no LIFO loading with %d stacks of height %d" % (pb.s, pb.l), None
        true = float(pb.tour_cost(pb.CP, tours["pickup_tour"]) + pb.tour_cost(pb.CD, tours["delivery_tour"]))
        if abs(float(ov) - true) > max(1e-3, 1e-3 * abs(true)):
            return False, "objective_value %r differs from the recomputed %r" % (ov, true), None
        return True, "", true
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RecursionError) as e:
        return False, "malformed solution: %r" % (e,), None


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="alba2013")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    a = ap.parse_args(argv)
    T = float(a.time_limit)
    deadline = T_START + min(0.9 * T, T - 3.0)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    pb = Problem(inst)
    seed = int(os.environ.get("MV2_DTSP_SEED", "1"))
    workers = int(os.environ.get("MV2_DTSP_WORKERS", "2"))
    log = {"version": VERSION, "n": pb.n, "s": pb.s, "l": pb.l, "symmetric": pb.sym, "T": T,
           "load_s": round(time.time() - T_START, 3), "workers": workers}
    if not pb.feasible_size:
        log["infeasible"] = "n > s * l"
        if os.environ.get("MV2_DTSP_LOG"):
            write_atomic(a.output + ".log.json", log)
        return 0
    child_pid, child_path = None, None
    if workers >= 2 and hasattr(os, "fork") and pb.n > 1:
        child_path = os.path.join(tempfile.gettempdir(), "mv2_dtsp_child_%d.json" % os.getpid())
        try:
            pid = os.fork()
        except OSError:
            pid = None
        if pid == 0:
            code = 0
            try:
                s = Search(pb, seed + 1000, deadline - 0.25)
                b = s.run()
                write_atomic(child_path, {"plan": b, "stats": s.stats})
            except BaseException:  # noqa: BLE001 - the child must never outlive its parent's budget
                code = 1
            os._exit(code)
        child_pid = pid
    state = {"last_write": 0.0, "written": None}

    def on_improve(plan, force=False):
        now = time.time()
        if not force and now - state["last_write"] < 0.5 and state["written"] is not None:
            return
        out = build_solution(pb, plan)
        ok, why, real = verify(pb, out)
        if ok:
            if state["written"] is None or real < state["written"] - EPS:
                write_atomic(a.output, out)
                state["last_write"] = now
                state["written"] = real
        else:
            log.setdefault("verify_failures", []).append(why[:200])

    s = Search(pb, seed, deadline)
    best = s.run(on_improve)
    log["parent"] = s.stats
    log["best_source"] = "parent"
    bc = plan_tours(pb, best)[0]
    if child_pid:
        limit = deadline + 0.5
        done = False
        while time.time() < limit:
            try:
                r, _ = os.waitpid(child_pid, os.WNOHANG)
            except ChildProcessError:
                r = child_pid
            if r == child_pid:
                done = True
                break
            time.sleep(0.02)
        if not done:
            try:
                os.kill(child_pid, 9)
                os.waitpid(child_pid, 0)
            except Exception:  # noqa: BLE001
                pass
            log["child_killed"] = True
        try:
            with open(child_path, encoding="utf-8") as f:
                ch = json.load(f)
            os.remove(child_path)
            log["child"] = ch.get("stats")
            cp = ch["plan"]
            if sorted(v for st in cp for v in st) == pb.items and all(len(st) <= pb.l for st in cp) \
                    and len(cp) == pb.s:
                cc = plan_tours(pb, cp)[0]
                if cc < bc - EPS:
                    best, bc = cp, cc
                    log["best_source"] = "child"
        except Exception as e:  # noqa: BLE001
            log["child_error"] = repr(e)[:200]
    on_improve(best, True)
    log["best"] = state["written"]
    log["wall_s"] = round(time.time() - T_START, 3)
    if os.environ.get("MV2_DTSP_LOG"):
        try:
            write_atomic(a.output + ".log.json", log)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""solve.py: MV2's solver for FrontierOR task lee1996, the Steiner tree-star problem.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Problem (Lee, Chiu and Ryan, "A Branch and Cut Algorithm for a Steiner Tree-Star Problem", INFORMS Journal on
Computing 8(3), 1996; task text from the public FrontierOR benchmark, CC BY 4.0): choose a non-empty set S of Steiner
(hub) nodes to activate, assign every target node to one active hub, and connect the active hubs by a spanning tree.
Cost = assignment costs + tree edge costs + activation weights of S.

Method. Once S is fixed the rest is exact: each target goes to its cheapest active hub, and the cheapest spanning
tree on S is its minimum spanning tree (Prim). So the search is over S only, and every candidate S is priced
exactly:
- start: the best single hub, then greedy additions while they pay;
- local search: add one hub, drop one hub, swap one active hub for an inactive one (first improvement, random
  order). Assignment deltas come from each target's best and second-best active hub; the tree is recomputed;
- iterated local search: flip 1-3 random hubs, search again, accept with a threshold that shrinks to zero.
Every solution is verified by verify() (the official checker's rules, plus: no self-loop or repeated edge, integer
indices) before it is written, atomically, and written again whenever it improves.

Contract: python solve.py --problem lee1996 --instance in.json --output out.json --time-limit T. Standard library
only. Stops by min(0.9 T, T - 3) seconds (0.5 T when T < 6).
Environment: MV2_LEE_SEED (default 1), MV2_LEE_LOG=1 writes <output>.log.json with search statistics.
"""
import argparse
import json
import math
import os
import random
import sys
import time

T_START = time.time()
VERSION = "0.1.0"
EPS = 1e-9


class Problem(object):
    def __init__(self, inst):
        tn = inst["target_nodes"]
        sn = inst["steiner_nodes"]
        cm = inst["cost_matrices"]
        self.m = int(tn["count"])
        self.n = int(sn["count"])
        self.c = [[float(v) for v in row] for row in cm["assignment_costs"]["matrix"]]
        self.d = [[float(v) for v in row] for row in cm["interconnection_costs"]["matrix"]]
        self.b = [float(v) for v in sn["node_weights"]]
        m, n = self.m, self.n
        if n < 1:
            raise ValueError("no Steiner nodes")
        if len(self.c) != m or any(len(r) != n for r in self.c):
            raise ValueError("assignment_costs is not m x n")
        if len(self.d) != n or any(len(r) != n for r in self.d):
            raise ValueError("interconnection_costs is not n x n")
        if len(self.b) != n:
            raise ValueError("node_weights is not length n")
        for v in [x for r in self.c for x in r] + [x for r in self.d for x in r] + self.b:
            if not math.isfinite(v):
                raise ValueError("non-finite cost")
        # The checker prices edge (j, k) with d[min][max]; use exactly that value in both directions.
        self.D = [[self.d[min(j, k)][max(j, k)] if j != k else 0.0 for k in range(n)] for j in range(n)]
        self.col = [[self.c[i][j] for i in range(m)] for j in range(n)]
        self.order = [sorted(range(n), key=lambda j, r=row: (r[j], j)) for row in self.c]


def mst(D, S, want_edges=False):
    """Prim's algorithm on the node list S under matrix D. Returns (cost, edges) with edges as (j, k), j < k."""
    k = len(S)
    if k <= 1:
        return 0.0, []
    inf = float("inf")
    in_tree = [False] * k
    dist = [inf] * k
    par = [-1] * k
    dist[0] = 0.0
    total = 0.0
    edges = []
    for _ in range(k):
        u, best = -1, inf
        for t in range(k):
            if not in_tree[t] and dist[t] < best:
                best, u = dist[t], t
        if u < 0:
            return inf, edges
        in_tree[u] = True
        if par[u] >= 0:
            total += best
            if want_edges:
                a, b = S[par[u]], S[u]
                edges.append((a, b) if a < b else (b, a))
        row = D[S[u]]
        for t in range(k):
            if not in_tree[t]:
                w = row[S[t]]
                if w < dist[t]:
                    dist[t] = w
                    par[t] = u
    return total, edges


class State(object):
    """An active set S with each target's best and second-best active hub, and the exact cost."""

    def __init__(self, pb, S):
        self.pb = pb
        self.active = sorted(set(S))
        if not self.active:
            raise ValueError("empty active set")
        ins = [False] * pb.n
        for j in self.active:
            ins[j] = True
        self.ins = ins
        inf = float("inf")
        bj, bc, sc = [0] * pb.m, [0.0] * pb.m, [inf] * pb.m
        members = {j: [] for j in self.active}
        for i in range(pb.m):
            row = pb.c[i]
            first = -1
            for j in pb.order[i]:
                if ins[j]:
                    if first < 0:
                        first = j
                        bj[i], bc[i] = j, row[j]
                    else:
                        sc[i] = row[j]
                        break
            members[first].append(i)
        self.bj, self.bc, self.sc, self.members = bj, bc, sc, members
        self.assign = sum(bc)
        self.weight = sum(pb.b[j] for j in self.active)
        self.tree = mst(pb.D, self.active)[0]
        self.cost = self.assign + self.weight + self.tree
        # cheapest edge from each active hub to another active hub (bounds the tree change of a drop)
        self.near = {}
        for j in self.active:
            row = pb.D[j]
            self.near[j] = min((row[k] for k in self.active if k != j), default=0.0)


def delta_add(st, j):
    pb = st.pb
    da = 0.0
    for x, y in zip(pb.col[j], st.bc):
        if x < y:
            da += x - y
    part = da + pb.b[j]
    # MST(S + j) >= MST(S) / 2 for a metric (it spans S, and an MST is at most twice a Steiner tree)
    if part - st.tree / 2.0 >= -EPS:
        return None
    t = mst(pb.D, st.active + [j])[0]
    return part + t - st.tree


def delta_drop(st, a):
    pb = st.pb
    if len(st.active) <= 1:
        return None
    da = 0.0
    sc, bc = st.sc, st.bc
    for i in st.members[a]:
        da += sc[i] - bc[i]
    part = da - pb.b[a]
    # MST(S) <= MST(S - a) + the cheapest edge from a to S - a
    if part - st.near[a] >= -EPS:
        return None
    t = mst(pb.D, [x for x in st.active if x != a])[0]
    return part + t - st.tree


def delta_swap(st, a, j):
    pb = st.pb
    da = 0.0
    bj, bc, sc = st.bj, st.bc, st.sc
    for i, x in enumerate(pb.col[j]):
        base = sc[i] if bj[i] == a else bc[i]
        da += (x if x < base else base) - bc[i]
    part = da - pb.b[a] + pb.b[j]
    if part - st.tree >= -EPS:  # the new tree costs at least 0
        return None
    t = mst(pb.D, [x for x in st.active if x != a] + [j])[0]
    return part + t - st.tree


class Search(object):
    def __init__(self, pb, seed, deadline, on_improve=None):
        self.pb = pb
        self.rng = random.Random(seed)
        self.deadline = deadline
        self.on_improve = on_improve
        self.best = None
        self.stats = {"evals": 0, "ls_moves": 0, "ils_iters": 0, "ils_accept": 0, "best_found_s": None,
                      "start_cost": None}

    def time_left(self):
        return self.deadline - time.time()

    def offer(self, st, source):
        if self.best is None or st.cost < self.best.cost - EPS:
            self.best = st
            self.stats["best_found_s"] = round(time.time() - T_START, 3)
            if self.on_improve:
                self.on_improve(st, source)
            return True
        return False

    def start(self):
        pb = self.pb
        single = min(range(pb.n), key=lambda j: (sum(pb.col[j]) + pb.b[j], j))
        st = State(pb, [single])
        self.offer(st, "single")
        while self.time_left() > 0:
            best_d, best_j = -EPS, None
            for j in range(pb.n):
                if st.ins[j]:
                    continue
                self.stats["evals"] += 1
                dv = delta_add(st, j)
                if dv is not None and dv < best_d:
                    best_d, best_j = dv, j
            if best_j is None:
                break
            st = State(pb, st.active + [best_j])
        self.stats["start_cost"] = st.cost
        self.offer(st, "greedy")
        return st

    def local_search(self, st):
        pb = self.pb
        rng = self.rng
        while self.time_left() > 0:
            moved = False
            outs = [j for j in range(pb.n) if not st.ins[j]]
            ins = list(st.active)
            rng.shuffle(outs)
            rng.shuffle(ins)
            for j in outs:
                self.stats["evals"] += 1
                dv = delta_add(st, j)
                if dv is not None and dv < -EPS:
                    st, moved = State(pb, st.active + [j]), True
                    break
            if not moved:
                for a in ins:
                    self.stats["evals"] += 1
                    dv = delta_drop(st, a)
                    if dv is not None and dv < -EPS:
                        st, moved = State(pb, [x for x in st.active if x != a]), True
                        break
            if not moved:
                for a in ins:
                    if self.time_left() <= 0:
                        break
                    for j in outs:
                        self.stats["evals"] += 1
                        dv = delta_swap(st, a, j)
                        if dv is not None and dv < -EPS:
                            st, moved = State(pb, [x for x in st.active if x != a] + [j]), True
                            break
                    if moved:
                        break
            if not moved:
                break
            self.stats["ls_moves"] += 1
        return st

    def perturb(self, st):
        pb = self.pb
        S = set(st.active)
        k = self.rng.choice((1, 1, 2, 2, 3))
        for _ in range(k):
            j = self.rng.randrange(pb.n)
            if j in S:
                if len(S) > 1:
                    S.discard(j)
            else:
                S.add(j)
        return State(pb, sorted(S))

    def run(self):
        st = self.start()
        st = self.local_search(st)
        self.offer(st, "local-search")
        cur = st
        t0 = time.time()
        span = max(1e-6, self.deadline - t0)
        while self.time_left() > 0:
            self.stats["ils_iters"] += 1
            cand = self.local_search(self.perturb(cur))
            self.offer(cand, "ils")
            frac = min(1.0, (time.time() - t0) / span)
            thr = 0.005 * (1.0 - frac) * abs(self.best.cost)
            if cand.cost < cur.cost - EPS or cand.cost < cur.cost + thr * self.rng.random():
                cur = cand
                self.stats["ils_accept"] += 1
            if self.rng.random() < 0.05:
                cur = self.best
        return self.best


def build_solution(pb, S):
    S = sorted(set(int(j) for j in S))
    ins = set(S)
    assign = {}
    total_a = 0.0
    for i in range(pb.m):
        j = next(j for j in pb.order[i] if j in ins)
        assign[str(i)] = j
        total_a += pb.c[i][j]
    _, edges = mst(pb.D, S, want_edges=True)
    total_e = sum(pb.d[j][k] for j, k in edges)
    total_w = sum(pb.b[j] for j in S)
    return {"objective_value": total_a + total_e + total_w, "active_steiner_nodes": S, "assignments": assign,
            "steiner_tree_edges": [[j, k] for j, k in edges]}


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def verify(pb, sol):
    """(ok, reason, recomputed objective). The official rules, plus a strict tree check (no self-loops)."""
    if not isinstance(sol, dict):
        return False, "not an object", None
    for key in ("objective_value", "active_steiner_nodes", "assignments", "steiner_tree_edges"):
        if key not in sol or sol[key] is None:
            return False, "missing " + key, None
    act = sol["active_steiner_nodes"]
    if not isinstance(act, list) or not act or not all(_int(j) and 0 <= j < pb.n for j in act):
        return False, "bad active_steiner_nodes", None
    if len(set(act)) != len(act):
        return False, "repeated active node", None
    S = set(act)
    asg = sol["assignments"]
    if not isinstance(asg, dict) or set(asg.keys()) != {str(i) for i in range(pb.m)}:
        return False, "assignments must cover targets 0..m-1 exactly", None
    total_a = 0.0
    for i in range(pb.m):
        j = asg[str(i)]
        if not _int(j) or j not in S:
            return False, "target %d assigned to %r, not an active hub" % (i, j), None
        total_a += pb.c[i][j]
    edges = sol["steiner_tree_edges"]
    if not isinstance(edges, list):
        return False, "steiner_tree_edges not a list", None
    seen = set()
    adj = {j: [] for j in S}
    total_e = 0.0
    for e in edges:
        if not isinstance(e, list) or len(e) != 2 or not all(_int(x) for x in e):
            return False, "bad edge %r" % (e,), None
        j, k = min(e), max(e)
        if j == k:
            return False, "self-loop %r" % (e,), None
        if j not in S or k not in S:
            return False, "edge %r touches an inactive hub" % (e,), None
        if (j, k) in seen:
            return False, "repeated edge %r" % (e,), None
        seen.add((j, k))
        adj[j].append(k)
        adj[k].append(j)
        total_e += pb.d[j][k]
    if len(seen) != len(S) - 1:
        return False, "%d edges for %d active hubs" % (len(seen), len(S)), None
    start = next(iter(S))
    stack, reach = [start], {start}
    while stack:
        u = stack.pop()
        for v in adj[u]:
            if v not in reach:
                reach.add(v)
                stack.append(v)
    if reach != S:
        return False, "tree not connected", None
    obj = total_a + total_e + sum(pb.b[j] for j in S)
    rep = sol["objective_value"]
    if isinstance(rep, bool) or not isinstance(rep, (int, float)) or not math.isfinite(rep):
        return False, "objective_value not a finite number", obj
    if abs(rep - obj) > max(1e-6, 1e-9 * abs(obj)):
        return False, "objective_value %r != recomputed %r" % (rep, obj), obj
    return True, "", obj


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def budget(T):
    T = float(T)
    return min(0.9 * T, T - 3.0) if T >= 6.0 else 0.5 * T


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="lee1996")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    a = ap.parse_args(argv)
    deadline = T_START + budget(a.time_limit)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    pb = Problem(inst)
    seed = int(os.environ.get("MV2_LEE_SEED", "1"))
    want_log = bool(os.environ.get("MV2_LEE_LOG"))
    log = {"version": VERSION, "m": pb.m, "n": pb.n, "T": a.time_limit, "seed": seed,
           "load_s": round(time.time() - T_START, 3), "writes": 0, "verify_failures": []}
    state = {"written": None}

    def write(st):
        """Verify, then write atomically if better than what is on disk (every improvement: files are small)."""
        sol = build_solution(pb, st.active)
        ok, why, obj = verify(pb, sol)
        if not ok:
            log["verify_failures"].append(why[:200])
            return
        if state["written"] is None or obj < state["written"] - EPS:
            write_atomic(a.output, sol)
            state["written"] = obj
            log["writes"] += 1
            if log.get("first_write_s") is None:
                log["first_write_s"] = round(time.time() - T_START, 3)

    def on_improve(st, source):
        log["best_source"] = source
        write(st)

    s = Search(pb, seed, deadline, on_improve)
    best = s.run()
    if best is not None:
        write(best)
    log.update(s.stats)
    log["best"] = state["written"]
    log["active"] = len(best.active) if best is not None else None
    log["wall_s"] = round(time.time() - T_START, 3)
    if want_log:
        try:
            write_atomic(a.output + ".log.json", log)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

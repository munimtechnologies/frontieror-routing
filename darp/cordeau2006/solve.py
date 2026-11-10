#!/usr/bin/env python3
"""MV2's practice solver for FrontierOR problem cordeau2006: the Dial-a-Ride Problem (DARP), minimise distance.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Problem (FrontierOR problem page, read 2026-11-09; Cordeau 2006, Operations Research 54(3)): every user has a pickup
and a drop-off node served by the same vehicle; at most num_vehicles routes run from the origin depot (node 0) to the
destination depot (node 2n+1); service starts inside each node's time window (waiting allowed); ride time (drop-off
start minus end of pickup service) at most maximum_ride_time; route duration (depot end minus depot start) at most
maximum_route_duration; load within [0, capacity]; cost = travel time = Euclidean distance.

Method: adaptive large neighbourhood search after Ropke & Pisinger (2006): random, worst, related (Shaw) and route
removal; greedy and regret-2/3 insertion with optional noise; simulated-annealing acceptance on a time schedule.
Every route is checked exactly: its start times are the least solution of the route's difference constraints (time
windows, travel, ride time, route duration), found by repeated forward passes with back arcs (Bellman-Ford on a
chain); a route with no solution is rejected. A small margin (1e-7) is added to every travel time and taken off the
ride and duration limits, so the written schedule has slack against floating-point rounding in a checker.
Two workers with different seeds run on the sandbox's two vCPUs; the better result is written. Standard library only.

v0.2.0 (2026-11-10) fixes the bug that left users unserved in v0.1.0: when the pickup and the drop-off were inserted
next to each other, the ride time was estimated from the EARLIEST pickup start, ignoring that the vehicle may wait
before the pickup; an outbound user whose drop-off window opens late was therefore never inserted next to its own
pickup, and could never open an empty route. The pruning now uses only the travel time (a true lower bound). A user
that finds no feasible position among the 60 cheapest candidates in any route is re-tried with every candidate.

Usage (as the FrontierOR sandbox calls it):
  python solve.py --problem cordeau2006 --instance in.json --output out.json --time-limit 60

Output keys follow the problem page: objective_value, routes {"<vehicle>": [0, ..., 2n+1]}, service_times
{"<node>", "depot_start_<v>", "depot_end_<v>"}, ride_times {"<user>"}. The vehicle index base (0 by default) and
whether unused vehicles are listed are not stated on the page; both are options until the official checker is seen.
"""
import argparse
import json
import math
import os
import random
import sys
import time

VERSION = "0.2.0"
EPS_T = 1e-7
INF = float("inf")
MAX_CHECKS = 60


class Darp:
    """Instance data with node-indexed lists and a float distance matrix."""

    def __init__(self, data):
        nodes = sorted(data["nodes"], key=lambda r: int(r["node_id"]))
        N = len(nodes)
        if [int(r["node_id"]) for r in nodes] != list(range(N)):
            raise ValueError("node ids must be 0..num_nodes-1")
        self.N = N
        self.m = int(data["num_vehicles"])
        self.Q = float(data["vehicle_capacity"])
        self.L = float(data["maximum_ride_time"])
        T = data.get("maximum_route_duration")
        self.T = float(T) if T is not None else INF

        def f(r, key, default):
            v = r.get(key)
            return float(default) if v is None else float(v)

        self.x = [f(r, "x", 0) for r in nodes]
        self.y = [f(r, "y", 0) for r in nodes]
        self.e = [f(r, "earliest_time", 0) for r in nodes]
        self.l = [f(r, "latest_time", INF) for r in nodes]
        self.s = [f(r, "service_duration", 0) for r in nodes]
        self.q = [f(r, "load", 0) for r in nodes]
        types = [str(r.get("node_type", "")) for r in nodes]
        self.O = types.index("origin_depot") if "origin_depot" in types else 0
        self.D = types.index("destination_depot") if "destination_depot" in types else N - 1
        self.is_pick = [False] * N
        self.pair = [-1] * N
        users = []
        if "pickup" in types:
            for i, r in enumerate(nodes):
                if types[i] == "pickup":
                    d = int(r["paired_node"])
                    users.append((r.get("user_id", len(users)), i, d))
        else:  # fall back to the classical layout: pickups 1..n, drop-offs n+1..2n
            n = (N - 2) // 2
            users = [(i, i, i + n) for i in range(1, n + 1)]
        self.uid = [u[0] for u in users]
        self.P = [u[1] for u in users]
        self.Dr = [u[2] for u in users]
        self.U = len(users)
        self.uix = [-1] * N
        for k, (_, p, d) in enumerate(users):
            self.is_pick[p] = True
            self.pair[p], self.pair[d] = d, p
            self.uix[p] = self.uix[d] = k
        X, Y = self.x, self.y
        self.dist = [[math.hypot(X[i] - X[j], Y[i] - Y[j]) for j in range(N)] for i in range(N)]
        self.tt = [[v + EPS_T for v in row] for row in self.dist]
        self.Lr = self.L - EPS_T
        self.Tr = self.T - EPS_T

    # ------------------------------------------------------------------ timing
    def schedule(self, seq):
        """Least feasible start times for [O] + seq + [D], or None if the route is infeasible (capacity not checked)."""
        full = [self.O] + seq + [self.D]
        k = len(full)
        E, Lw, S, tt, is_pick, pair = self.e, self.l, self.s, self.tt, self.is_pick, self.pair
        lb = [E[v] for v in full]
        pos = {}
        pairs = []
        for idx in range(1, k - 1):
            v = full[idx]
            if is_pick[v]:
                pos[v] = idx
            else:
                i = pos.get(pair[v])
                if i is None:
                    return None
                pairs.append((i, idx))
        Lr, Tr = self.Lr, self.Tr
        for _ in range(k + 2):
            prev = full[0]
            t = lb[0]
            if t > Lw[prev]:
                return None
            for idx in range(1, k):
                v = full[idx]
                a = t + S[prev] + tt[prev][v]
                if a < lb[idx]:
                    a = lb[idx]
                else:
                    lb[idx] = a
                if a > Lw[v]:
                    return None
                t = a
                prev = v
            changed = False
            for i, j in pairs:
                need = lb[j] - S[full[i]] - Lr
                if need > lb[i]:
                    lb[i] = need
                    changed = True
            need = lb[k - 1] - Tr
            if need > lb[0]:
                lb[0] = need
                changed = True
            if not changed:
                return lb
        return None

    def load_ok(self, seq):
        load = 0.0
        for v in seq:
            load += self.q[v]
            if load > self.Q + 1e-9 or load < -1e-9:
                return False
        return True

    def route_info(self, seq):
        """[full, forward earliest starts A, load after each node, prefix times P, cost, schedule]."""
        full = [self.O] + seq + [self.D]
        k = len(full)
        S, tt, E, q, dist = self.s, self.tt, self.e, self.q, self.dist
        A = [0.0] * k
        load = [0.0] * k
        P = [0.0] * k
        A[0] = E[full[0]]
        cost = 0.0
        for idx in range(1, k):
            a, b = full[idx - 1], full[idx]
            step = S[a] + tt[a][b]
            t = A[idx - 1] + step
            A[idx] = t if t > E[b] else E[b]
            load[idx] = load[idx - 1] + q[b]
            P[idx] = P[idx - 1] + step
            cost += dist[a][b]
        return (full, A, load, P, cost, self.schedule(seq))

    def best_insert(self, u, info, max_checks=MAX_CHECKS):
        """Cheapest feasible insertion of user u into the route: (delta, i, j) or None.

        The pickup goes right after full[i], the drop-off right after full[j] (j == i: right after the pickup).
        Candidates are pruned only by true necessary conditions (capacity, earliest pickup start against the pickup
        window, earliest drop-off start against the drop-off window when adjacent, and a travel-only lower bound on
        the ride time), then checked exactly in order of cost. max_checks=None checks every candidate."""
        full, A, load, P, _, _ = info
        p, d = self.P[u], self.Dr[u]
        k = len(full)
        S, tt, dist, E, Lw = self.s, self.tt, self.dist, self.e, self.l
        Q, Lr = self.Q + 1e-9, self.Lr
        qu = self.q[p]
        ep, lp, ed, ld, sp = E[p], Lw[p], E[d], Lw[d], S[p]
        if tt[p][d] > Lr:
            return None
        cands = []
        for i in range(k - 1):
            if load[i] + qu > Q:
                continue
            a, b = full[i], full[i + 1]
            bp = A[i] + S[a] + tt[a][p]
            if bp < ep:
                bp = ep
            if bp > lp:
                continue
            dap, dab = dist[a][p], dist[a][b]
            bd = bp + sp + tt[p][d]
            if bd < ed:
                bd = ed
            if bd <= ld:  # v0.1.0 also required bd - bp - sp <= L here, which ignored waiting before the pickup
                cands.append((dap + dist[p][d] + dist[d][b] - dab, i, i))
            ci = dap + dist[p][b] - dab
            base = tt[p][b] - P[i + 1]
            for j in range(i + 1, k - 1):
                if load[j] + qu > Q:
                    break
                x = full[j]
                if base + P[j] + S[x] + tt[x][d] > Lr:
                    break
                y = full[j + 1]
                cands.append((ci + dist[x][d] + dist[d][y] - dist[x][y], i, j))
        if not cands:
            return None
        cands.sort()
        seq = full[1:-1]
        for c, (delta, i, j) in enumerate(cands):
            if max_checks is not None and c >= max_checks:
                break
            if self.schedule(seq[:i] + [p] + seq[i:j] + [d] + seq[j:]) is not None:
                return (delta, i, j)
        return None


def insert_seq(seq, p, d, i, j):
    return seq[:i] + [p] + seq[i:j] + [d] + seq[j:]


class Search:
    """One ALNS run. State: routes (list of node lists without depots), infos, where[user] = route or -1."""

    def __init__(self, inst, seed, deadline):
        self.I = inst
        self.rng = random.Random(seed)
        self.deadline = deadline
        self.maxd = max(max(row) for row in inst.dist) or 1.0
        self.penalty = 100.0 * self.maxd + 100.0
        finite = [v for v in inst.l if v < INF]
        self.H = (max(finite) - min(inst.e)) if finite else 1.0
        self.H = self.H if self.H > 0 else 1.0
        self.stats = {"iterations": 0, "improvements": 0, "restarts": 0, "full_checks": 0}

    # ------------------------------------------------------------ insertion
    def insert(self, routes, infos, where, users, kreg, noise):
        I, rng = self.I, self.rng
        m = I.m
        pending = list(users)
        rng.shuffle(pending)
        table = {u: [I.best_insert(u, infos[r]) for r in range(m)] for u in pending}
        full = set()  # users re-tried with every candidate, kept that way for this call
        amp = 0.025 * self.maxd if noise else 0.0
        while pending:
            if time.time() > self.deadline + 2.0:
                break
            pick = None
            for u in pending:
                if u not in full and all(c is None for c in table[u]):
                    full.add(u)
                    self.stats["full_checks"] += 1
                    table[u] = [I.best_insert(u, infos[r], None) for r in range(m)]
                opts = []
                for r, c in enumerate(table[u]):
                    if c is not None:
                        v = c[0] + (amp * rng.uniform(-1.0, 1.0) if amp else 0.0)
                        opts.append((v if v > 0 else 0.0, r))
                if not opts:
                    continue
                opts.sort()
                if kreg <= 1:
                    key = (-opts[0][0], 0.0)
                else:
                    reg = 0.0
                    for h in range(1, kreg):
                        reg += (opts[h][0] if h < len(opts) else self.penalty) - opts[0][0]
                    key = (reg, -opts[0][0])
                if pick is None or key > pick[0]:
                    pick = (key, u, opts[0][1])
            if pick is None:
                break
            _, u, r = pick
            _, i, j = table[u][r]
            seq = insert_seq(routes[r], I.P[u], I.Dr[u], i, j)
            routes[r] = seq
            infos[r] = I.route_info(seq)
            where[u] = r
            pending.remove(u)
            for v in pending:
                table[v][r] = I.best_insert(v, infos[r], None if v in full else MAX_CHECKS)
        return pending

    # ------------------------------------------------------------ removal
    def _remove(self, routes, infos, where, users):
        I = self.I
        touched = {}
        for u in users:
            r = where[u]
            if r < 0:
                continue
            drop = touched.setdefault(r, set())
            drop.add(I.P[u])
            drop.add(I.Dr[u])
            where[u] = -1
        for r, drop in touched.items():
            seq = [v for v in routes[r] if v not in drop]
            routes[r] = seq
            infos[r] = I.route_info(seq)
        return [u for u in users]

    def rm_random(self, routes, infos, where, q):
        served = [u for u in range(self.I.U) if where[u] >= 0]
        return self._remove(routes, infos, where, self.rng.sample(served, min(q, len(served))))

    def rm_worst(self, routes, infos, where, q):
        I = self.I
        dist = I.dist
        sav = []
        for r, seq in enumerate(routes):
            full = infos[r][0]
            cost = infos[r][4]
            for v in seq:
                if not I.is_pick[v]:
                    continue
                d = I.pair[v]
                rest = [w for w in full if w != v and w != d]
                c = sum(dist[a][b] for a, b in zip(rest[:-1], rest[1:]))
                sav.append((cost - c, I.uix[v]))
        sav.sort(reverse=True)
        chosen = []
        order = [u for _, u in sav]
        while order and len(chosen) < q:
            k = int((self.rng.random() ** 3) * len(order))
            chosen.append(order.pop(k))
        return self._remove(routes, infos, where, chosen)

    def _times(self, infos):
        t = {}
        for info in infos:
            if info[5] is None:
                continue
            for v, b in zip(info[0], info[5]):
                t[v] = b
        return t

    def rm_related(self, routes, infos, where, q):
        I = self.I
        served = [u for u in range(I.U) if where[u] >= 0]
        if not served:
            return []
        t = self._times(infos)
        dist, P, Dr = I.dist, I.P, I.Dr
        seed = self.rng.choice(served)
        chosen = [seed]
        rest = [u for u in served if u != seed]
        while rest and len(chosen) < q:
            ref = self.rng.choice(chosen)
            pr, dr = P[ref], Dr[ref]

            def rel(u):
                return (9.0 * (dist[pr][P[u]] + dist[dr][Dr[u]]) / self.maxd
                        + 3.0 * (abs(t.get(pr, 0.0) - t.get(P[u], 0.0)) + abs(t.get(dr, 0.0) - t.get(Dr[u], 0.0)))
                        / self.H)
            rest.sort(key=rel)
            k = int((self.rng.random() ** 6) * len(rest))
            chosen.append(rest.pop(k))
        return self._remove(routes, infos, where, chosen)

    def rm_route(self, routes, infos, where, q):
        I = self.I
        nonempty = [r for r in range(I.m) if routes[r]]
        if not nonempty:
            return []
        r = self.rng.choice(nonempty)
        users = [I.uix[v] for v in routes[r] if I.is_pick[v]]
        extra = [u for u in range(I.U) if where[u] >= 0 and where[u] != r]
        k = max(0, min(len(extra), q - len(users)))
        return self._remove(routes, infos, where, users + self.rng.sample(extra, k))

    # ------------------------------------------------------------ main loop
    def total(self, infos, bank):
        return sum(info[4] for info in infos) + self.penalty * len(bank)

    def run(self):
        I, rng = self.I, self.rng
        m, U = I.m, I.U
        routes = [[] for _ in range(m)]
        infos = [I.route_info([]) for _ in range(m)]
        where = [-1] * U
        bank = self.insert(routes, infos, where, list(range(U)), 2, False)
        cur = self.total(infos, bank)
        best = (list(routes), cur, list(bank))
        if U == 0:
            return best[0], best[1], best[2], self.stats
        dist_part = sum(info[4] for info in infos) or 1.0
        T0 = 0.05 * dist_part / math.log(2.0)
        start = time.time()
        span = max(1e-3, self.deadline - start)
        rms = [self.rm_random, self.rm_worst, self.rm_related, self.rm_route]
        ins = [(1, False), (2, False), (3, False), (1, True), (2, True)]
        w_rm = [1.0] * len(rms)
        w_in = [1.0] * len(ins)
        sc_rm = [0.0] * len(rms)
        n_rm = [0] * len(rms)
        sc_in = [0.0] * len(ins)
        n_in = [0] * len(ins)
        qmin = min(2, U)
        qmax = max(qmin, max(4, min(15, int(0.25 * U))))
        since_best = 0
        it = 0
        while True:
            now = time.time()
            if now >= self.deadline:
                break
            it += 1
            frac = (now - start) / span
            temp = T0 * (0.002 ** frac)
            q = rng.randint(qmin, qmax)
            a = rng.choices(range(len(rms)), weights=w_rm)[0]
            b = rng.choices(range(len(ins)), weights=w_in)[0]
            snap = (list(routes), list(infos), list(where), list(bank))
            removed = rms[a](routes, infos, where, q)
            kreg, noise = ins[b]
            bank = self.insert(routes, infos, where, removed + bank, kreg, noise)
            new = self.total(infos, bank)
            score = 0.0
            if new < best[1] - 1e-9:
                best = (list(routes), new, list(bank))
                cur = new
                score = 33.0
                since_best = 0
                self.stats["improvements"] += 1
            elif new < cur - 1e-9:
                cur = new
                score = 9.0
            elif new > cur + 1e-9 and rng.random() < math.exp(-(new - cur) / max(temp, 1e-12)):
                cur = new
                score = 13.0
            elif abs(new - cur) <= 1e-9:
                cur = new
            else:
                routes, infos, where, bank = snap
            since_best += 1
            sc_rm[a] += score
            n_rm[a] += 1
            sc_in[b] += score
            n_in[b] += 1
            if it % 50 == 0:
                for w, sc, n in ((w_rm, sc_rm, n_rm), (w_in, sc_in, n_in)):
                    for h in range(len(w)):
                        if n[h]:
                            w[h] = max(0.05, 0.9 * w[h] + 0.1 * sc[h] / n[h])
                        sc[h] = 0.0
                        n[h] = 0
            if since_best >= 1500:
                routes = list(best[0])
                infos = [I.route_info(s) for s in routes]
                where = [-1] * U
                for r, s in enumerate(routes):
                    for v in s:
                        if I.is_pick[v]:
                            where[I.uix[v]] = r
                bank = list(best[2])
                cur = best[1]
                since_best = 0
                self.stats["restarts"] += 1
        self.stats["iterations"] = it
        return best[0], best[1], best[2], self.stats


# ---------------------------------------------------------------------- output
def build_output(I, routes, vehicle_base=0, emit_empty=False):
    out_routes, st, ride = {}, {}, {}
    total = 0.0
    used = 0
    for r, seq in enumerate(routes):
        if not seq and not emit_empty:
            continue
        B = I.schedule(seq)
        if B is None:
            raise RuntimeError("route %d has no feasible schedule" % r)
        full = [I.O] + seq + [I.D]
        v = r + vehicle_base
        out_routes[str(v)] = full
        st["depot_start_%d" % v] = B[0]
        st["depot_end_%d" % v] = B[-1]
        for idx in range(1, len(full) - 1):
            st[str(full[idx])] = B[idx]
        pos = {node: idx for idx, node in enumerate(full)}
        for node in seq:
            if I.is_pick[node]:
                u = I.uix[node]
                ride[str(I.uid[u])] = B[pos[I.Dr[u]]] - (B[pos[node]] + I.s[node])
        total += sum(I.dist[a][b] for a, b in zip(full[:-1], full[1:]))
        used += 1
    return {"objective_value": total, "routes": out_routes, "service_times": st, "ride_times": ride}, used


_INST = None


def _worker(args):
    seed, deadline = args
    return Search(_INST, seed, deadline).run()


def solve(data, time_limit, seed=20261109, workers=2):
    """Returns (instance, best routes, unserved users, stats)."""
    global _INST
    t0 = time.time()
    I = Darp(data)
    _INST = I
    budget = max(0.5, min(time_limit - 4.0, 0.92 * time_limit))
    deadline = t0 + budget
    results = []
    stats = {"version": VERSION, "workers": 1, "engine": "own-alns"}
    if workers > 1:
        try:
            import multiprocessing as mp
            if "fork" in mp.get_all_start_methods():
                ctx = mp.get_context("fork")
                with ctx.Pool(workers) as pool:
                    res = pool.map_async(_worker, [(seed + w, deadline) for w in range(workers)])
                    results = res.get(timeout=max(1.0, deadline - time.time() + 8.0))
                stats["workers"] = workers
        except Exception as e:  # noqa: BLE001 - fall back to one process
            stats["pool_error"] = repr(e)[:300]
            results = []
    if not results:
        dl = deadline if time.time() < deadline else time.time() + 0.5
        results = [Search(I, seed, dl).run()]
    results.sort(key=lambda r: (len(r[2]), r[1]))
    routes, cost, bank, st = results[0]
    stats.update({"unserved": len(bank), "cost_with_penalty": cost,
                  "iterations": [r[3]["iterations"] for r in results],
                  "restarts": [r[3]["restarts"] for r in results],
                  "full_checks": [r[3].get("full_checks", 0) for r in results],
                  "costs": [round(r[1], 4) for r in results], "seconds": round(time.time() - t0, 2)})
    return I, routes, bank, stats


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="cordeau2006")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=float(os.environ.get("SANDBOX_TIMEOUT_S", "60") or 60))
    ap.add_argument("--seed", type=int, default=20261109)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--vehicle-base", type=int, default=0)
    ap.add_argument("--emit-empty", action="store_true")
    a = ap.parse_args(argv)
    with open(a.instance, encoding="utf-8") as f:
        data = json.load(f)
    I, routes, bank, stats = solve(data, a.time_limit, a.seed, a.workers)
    sol, used = build_output(I, routes, a.vehicle_base, a.emit_empty)
    stats.update({"objective": sol["objective_value"], "vehicles_used": used})
    tmp = a.output + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sol, f)
    os.replace(tmp, a.output)
    print("DARP_SOLVER_STATS " + json.dumps(stats), file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Orienteering Problem solver for the FrontierOR practice problem fischetti1998.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name.
License: Apache-2.0.

Contract (FrontierOR Main track):
    python solve.py --problem fischetti1998 --instance in.json --output out.json --time-limit 60

Instance (as documented on the problem page): n, depot, t0, prizes {"<city>": prize},
travel_times {"(<i>,<j>)": time} with i < j, symmetric. Objective: maximise the prize
collected on one closed tour through the depot with total time <= t0 and at least three
cities (depot included).

Method: greedy ratio insertion, 2-opt, then iterated local search that removes a
segment of the tour and re-inserts greedily (in the spirit of Vansteenwegen et al. 2009).
Fixed random seed, but it stops on wall-clock time, so results can differ with machine
speed. It stops well before the time limit (about 85% of it, and at least 4 s early).
"""
import argparse
import json
import random
import re
import sys
import time

import numpy as np

_T_START = time.time()
_INT = re.compile(r"-?\d+")
EPS = 1e-9
HARD = [float("inf")]  # absolute wall-clock time after which inner loops stop early


def _ints(key):
    return [int(x) for x in _INT.findall(str(key))]


def parse_instance(inst):
    """Return (labels, D, P, depot_index, t0). labels[i] is the original city id."""
    depot = int(inst["depot"])
    t0 = float(inst["t0"])
    prizes_raw = inst.get("prizes", {})
    tt_raw = inst["travel_times"]
    prizes = {}
    if isinstance(prizes_raw, dict):
        for k, v in prizes_raw.items():
            prizes[_ints(k)[0]] = float(v)
    else:  # list form: 0-based if the depot is 0, else 1-based
        base = 0 if depot == 0 else 1
        for i, v in enumerate(prizes_raw):
            prizes[i + base] = float(v)
    cities = set(prizes)
    cities.add(depot)
    pairs = []
    if isinstance(tt_raw, dict):
        for k, v in tt_raw.items():
            ab = _ints(k)
            if len(ab) < 2:
                continue
            pairs.append((ab[0], ab[1], float(v)))
            cities.add(ab[0])
            cities.add(ab[1])
    else:  # full matrix form
        base = 0 if depot == 0 else 1
        for i, row in enumerate(tt_raw):
            for j, v in enumerate(row):
                if i != j and v is not None:
                    pairs.append((i + base, j + base, float(v)))
                    cities.add(i + base)
                    cities.add(j + base)
    labels = sorted(cities)
    idx = {c: i for i, c in enumerate(labels)}
    m = len(labels)
    D = np.full((m, m), np.inf)
    np.fill_diagonal(D, 0.0)
    for a, b, v in pairs:
        ia, ib = idx[a], idx[b]
        if v < D[ia, ib]:
            D[ia, ib] = v
        if v < D[ib, ia]:
            D[ib, ia] = v
    P = np.array([prizes.get(c, 0.0) for c in labels], dtype=float)
    return labels, D, P, idx[depot], t0


def tour_length(D, t):
    a = np.asarray(t[:-1])
    b = np.asarray(t[1:])
    return float(D[a, b].sum())


def two_opt(D, t):
    """First-improvement 2-opt on a closed tour [d, ..., d]. Returns (tour, length)."""
    t = list(t)
    m = len(t)
    if m < 5:
        return t, tour_length(D, t)
    improved = True
    while improved and time.time() < HARD[0]:
        improved = False
        arr = np.asarray(t)
        for i in range(0, m - 3):
            a, b = arr[i], arr[i + 1]
            c = arr[i + 2:m - 1]
            d = arr[i + 3:m]
            delta = D[a, c] + D[b, d] - D[a, b] - D[c, d]
            j = int(np.argmin(delta))
            if delta[j] < -1e-7:
                j = j + i + 2
                t[i + 1:j + 1] = t[i + 1:j + 1][::-1]
                arr = np.asarray(t)
                improved = True
    return t, tour_length(D, t)


def insert_greedy(D, P, t, L, t0, inset, rng=None, noise=0.0, allow_zero=False):
    """Insert unvisited nodes by best prize/extra-time ratio while feasible."""
    t = list(t)
    m_all = len(P)
    while time.time() < HARD[0]:
        cand = np.array([v for v in range(m_all) if not inset[v] and (allow_zero or P[v] > 0)],
                        dtype=int)
        if cand.size == 0:
            break
        A = np.asarray(t[:-1])
        B = np.asarray(t[1:])
        delta = D[np.ix_(cand, A)] + D[np.ix_(cand, B)] - D[A, B][None, :]
        pos = np.argmin(delta, axis=1)
        best = delta[np.arange(cand.size), pos]
        ok = (L + best) <= t0 + EPS
        if not ok.any():
            break
        ratio = (P[cand] + 1e-12) / (np.maximum(best, 0.0) + 1e-6)
        if noise > 0 and rng is not None:
            ratio = ratio * (1.0 + noise * np.array([rng.random() for _ in range(cand.size)]))
        ratio[~ok] = -np.inf
        k = int(np.argmax(ratio))
        v = int(cand[k])
        p = int(pos[k])
        t.insert(p + 1, v)
        L += float(best[k])
        inset[v] = True
    return t, L


def score_of(P, t):
    return float(P[list(set(t))].sum())


def ensure_three(D, P, t, L, t0, inset):
    """Make sure the tour has at least three distinct cities if any feasible way exists."""
    if len(set(t)) >= 3:
        return t, L
    t, L = insert_greedy(D, P, t, L, t0, inset, allow_zero=True)
    if len(set(t)) >= 3:
        return t, L
    # brute force the cheapest triangle through the depot
    d = t[0]
    m = len(P)
    best = None
    others = [v for v in range(m) if v != d]
    for a in others:
        row = D[d, a] + D[a, others] + D[others, d]
        for k, b in enumerate(others):
            if b == a:
                continue
            val = row[k]
            if val <= t0 + EPS and (best is None or (P[a] + P[b], -val) > best[0]):
                best = ((P[a] + P[b], -val), [d, a, b, d], float(val))
    if best is not None:
        return best[1], best[2]
    return t, L


def solve(inst, time_limit_s, start=None):
    """Solve one instance. start = wall-clock origin of the time limit (process start by default)."""
    t_start = _T_START if start is None else start
    labels, D, P, d, t0 = parse_instance(inst)
    budget = max(1.0, min(time_limit_s * 0.85, time_limit_s - 4.0))
    deadline = t_start + budget
    HARD[0] = t_start + max(1.0, time_limit_s - 2.5)
    rng = random.Random(20261109)
    m = len(P)

    inset = np.zeros(m, dtype=bool)
    inset[d] = True
    t, L = insert_greedy(D, P, [d, d], 0.0, t0, inset)
    t, L = two_opt(D, t)
    t, L = insert_greedy(D, P, t, L, t0, inset)
    t, L = ensure_three(D, P, t, L, t0, set_mask(m, t))

    best_t, best_L, best_s = list(t), L, score_of(P, t)
    cur_t, cur_L, cur_s = list(t), L, best_s
    S, R = 1, 1
    no_imp = 0
    it = 0
    while time.time() < deadline:
        it += 1
        inner = cur_t[1:-1]
        if len(inner) == 0:
            new_t = [d, d]
        else:
            S_eff = min(S, len(inner))
            start = R % len(inner)
            drop = set()
            for k in range(S_eff):
                drop.add(inner[(start + k) % len(inner)])
            new_t = [d] + [v for v in inner if v not in drop] + [d]
        new_t, new_L = two_opt(D, new_t)
        mask = set_mask(m, new_t)
        noise = 0.0 if it % 3 else 0.3
        new_t, new_L = insert_greedy(D, P, new_t, new_L, t0, mask, rng=rng, noise=noise)
        new_t, new_L = two_opt(D, new_t)
        new_t, new_L = insert_greedy(D, P, new_t, new_L, t0, mask)
        new_s = score_of(P, new_t)
        if len(set(new_t)) < 3:
            new_t, new_L = ensure_three(D, P, new_t, new_L, t0, mask)
            new_s = score_of(P, new_t)
        if new_s > cur_s + EPS or (abs(new_s - cur_s) <= EPS and new_L < cur_L - 1e-7):
            cur_t, cur_L, cur_s = new_t, new_L, new_s
            S = 1
            if (cur_s > best_s + EPS or (abs(cur_s - best_s) <= EPS and cur_L < best_L - 1e-7)) \
                    and len(set(cur_t)) >= 3:
                best_t, best_L, best_s = list(cur_t), cur_L, cur_s
                no_imp = 0
            else:
                no_imp += 1
        else:
            R += S
            S += 1
            no_imp += 1
            if S > max(1, len(inner) // 2):
                S = 1
                R = rng.randrange(1, 1 + max(1, len(inner)))
                cur_t, cur_L, cur_s = new_t, new_L, new_s  # diversify
        if no_imp > 4 * max(10, len(best_t)):
            cur_t, cur_L, cur_s = list(best_t), best_L, best_s
            no_imp = 0

    return build_solution(labels, P, best_t)


def set_mask(m, t):
    mask = np.zeros(m, dtype=bool)
    mask[list(set(t))] = True
    return mask


def build_solution(labels, P, t):
    tour = [int(labels[v]) for v in t]
    edges = []
    for a, b in zip(tour[:-1], tour[1:]):
        edges.append([min(a, b), max(a, b)])
    visited = sorted(set(tour))
    obj = float(sum(P[v] for v in set(t)))
    if abs(obj - round(obj)) < 1e-9:
        obj_out = int(round(obj))
    else:
        obj_out = obj
    return {"objective_value": obj_out, "visited_nodes": visited, "edges": edges, "tour": tour}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="fischetti1998")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    args = ap.parse_args(argv)
    with open(args.instance, "r", encoding="utf-8") as f:
        inst = json.load(f)
    sol = solve(inst, args.time_limit)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(sol, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())

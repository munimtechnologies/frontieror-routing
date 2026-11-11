#!/usr/bin/env python3
"""Orienteering Problem solver for the FrontierOR practice problem fischetti1998, v0.3.0.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name.
License: Apache-2.0.

Contract (FrontierOR Main track):
    python solve.py --problem fischetti1998 --instance in.json --output out.json --time-limit 60

Needs op_core.py in the same folder: that is the published solver v1 (op/fischetti1998/solve.py
of github.com/munimtechnologies/frontieror-routing), unchanged. v1 is an iterated local search
(greedy prize/time ratio insertion, 2-opt, segment removal and noisy re-insertion) and was 3.8%
to 13.8% below the stored Gurobi solutions on the five 500-city public instances (mean contest
score 0.894). (v0.2.0, kept in op/v2/, was not better than v1 on OPLib, so v1 stays the core.)

v0.3.0 adds a second search on the second CPU:
1. Anytime start: v1's greedy tour is built first and written to the output at once.
2. mode "parallel" (default): a forked child process runs OR-Tools routing (one vehicle, the
   budget t0 as a dimension capacity, one disjunction per city with penalty prize * M) with
   guided local search, seeded with that greedy tour, while this process runs v1's
   iterated local search. With M = (budget in integer units) + 1, one unit of prize outweighs
   any tour length within the budget, so OR-Tools maximises prize first and only then shortens
   the tour. The better of the two tours (prize, then length) is written.
   mode "ortools": OR-Tools only, in this process (no fork). mode "ils": v1 only.
3. Every tour is re-checked here with the instance's own travel times (closed at the depot,
   cities distinct, at least three cities, length <= t0) before it can be written.
Options come from op_config.json next to this file (all optional):
    {"mode": "parallel"|"ortools"|"ils", "metaheuristic": "GLS"|"SA"|"TABU",
     "extra_ops": false, "log_file": false}
"log_file": true also writes <output>.log.json with what each search found (for grading runs).
It stops on wall-clock time, so results can differ with machine speed.
"""
import argparse
import json
import os
import sys
import tempfile
import time

_T_START = time.time()

import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import op_core as C  # noqa: E402  (published v1, unchanged)

VERSION = "0.3.0"
DEFAULT_CONFIG = {"mode": "parallel", "metaheuristic": "GLS", "extra_ops": False, "log_file": False}
LEN_TOL = 1e-6  # the official checker allows 1e-5


def _write(path, sol):
    if not path:
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sol, f)
    os.replace(tmp, path)


def core_ils(inst, T, t_start):
    """The core's own iterated local search (v1: solve(inst, time_limit_s, start=None))."""
    return C.solve(inst, T, start=t_start)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    p = os.path.join(HERE, "op_config.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                got = json.load(f)
            if isinstance(got, dict):
                cfg.update(got)
        except Exception:  # noqa: BLE001 - a broken config file means the defaults
            pass
    return cfg


def valid(D, t, t0):
    """Closed tour [d, ..., d], distinct cities, >= 3 cities with the depot, finite length <= t0."""
    if not isinstance(t, list) or len(t) < 4 or t[0] != t[-1]:
        return False
    inner = t[1:-1]
    if t[0] in inner or len(set(inner)) != len(inner):
        return False
    if any((not isinstance(v, int)) or v < 0 or v >= D.shape[0] for v in t):
        return False
    L = C.tour_length(D, t)
    return bool(np.isfinite(L)) and L <= t0 + LEN_TOL


def key_of(D, P, t):
    """Sort key: more prize first, then the shorter tour."""
    return (C.score_of(P, t), -C.tour_length(D, t))


def initial(D, P, d, t0):
    """v1's start: greedy ratio insertion, 2-opt, greedy again, at least three cities."""
    m = len(P)
    inset = np.zeros(m, dtype=bool)
    inset[d] = True
    t, L = C.insert_greedy(D, P, [d, d], 0.0, t0, inset)
    t, L = C.two_opt(D, t)
    t, L = C.insert_greedy(D, P, t, L, t0, inset)
    t, L = C.ensure_three(D, P, t, L, t0, C.set_mask(m, t))
    return [int(v) for v in t]


def ortools_search(D, P, d, t0, seed_tour, deadline_abs, cfg):
    """OR-Tools routing with prize disjunctions. Returns (tour or None, info)."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    info = {"status": "start"}
    m = len(P)
    finite = np.isfinite(D)
    Dm = np.where(finite, D, 0.0)
    integral = bool(np.all(np.abs(Dm - np.rint(Dm)) < 1e-9)) and abs(t0 - round(t0)) < 1e-9
    s = 1 if integral else 1000
    T0 = int(np.floor(t0 * s + 1e-9))
    big = T0 + 1  # an arc longer than the budget can never be used
    Di = np.where(finite, np.rint(Dm * s), big)
    Di = np.minimum(Di, big).astype(np.int64)
    np.fill_diagonal(Di, 0)
    Pr = np.maximum(P, 0.0)
    p_int = bool(np.all(np.abs(Pr - np.rint(Pr)) < 1e-9))
    ps = 1 if p_int else 1000
    Pi = np.rint(Pr * ps).astype(np.int64)
    M = T0 + 1  # one unit of prize outweighs any tour length within the budget
    total = int(Pi.sum())
    if total * M >= 2 ** 62:  # keep the objective inside int64
        M = max(1, (2 ** 62) // max(1, total))
    info.update(scale=s, T0=T0, prize_scale=ps, M=M)

    manager = pywrapcp.RoutingIndexManager(m, 1, int(d))
    routing = pywrapcp.RoutingModel(manager)
    Dl = Di.tolist()

    def dist(i, j):
        return Dl[manager.IndexToNode(i)][manager.IndexToNode(j)]

    try:
        cb = routing.RegisterTransitMatrix(Dl)
        info["transit"] = "matrix"
    except Exception:  # noqa: BLE001 - older OR-Tools: a Python callback
        cb = routing.RegisterTransitCallback(dist)
        info["transit"] = "callback"
    routing.SetArcCostEvaluatorOfAllVehicles(cb)
    routing.AddDimension(cb, 0, T0, True, "Time")
    for v in range(m):
        if v != d:
            routing.AddDisjunction([manager.NodeToIndex(v)], int(Pi[v]) * int(M))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    mh = {"GLS": "GUIDED_LOCAL_SEARCH", "SA": "SIMULATED_ANNEALING", "TABU": "TABU_SEARCH"}.get(
        str(cfg.get("metaheuristic", "GLS")).upper(), "GUIDED_LOCAL_SEARCH")
    params.local_search_metaheuristic = getattr(routing_enums_pb2.LocalSearchMetaheuristic, mh)
    info["metaheuristic"] = mh
    if cfg.get("extra_ops"):
        turned = []
        try:
            from ortools.util import optional_boolean_pb2 as OB
            ops = params.local_search_operators
            for f in ("use_relocate_and_make_active", "use_extended_swap_active"):
                try:
                    setattr(ops, f, OB.BOOL_TRUE)
                    turned.append(f)
                except Exception:  # noqa: BLE001 - field missing in this OR-Tools version
                    pass
        except Exception as e:  # noqa: BLE001
            info["extra_ops_error"] = repr(e)[:200]
        info["extra_ops"] = turned
    params.time_limit.FromMilliseconds(max(100, int((deadline_abs - time.time()) * 1000)))
    routing.CloseModelWithParameters(params)

    seed_ass = None
    if seed_tour is not None and len(seed_tour) > 2:
        try:
            seed_ass = routing.ReadAssignmentFromRoutes([[int(v) for v in seed_tour[1:-1]]], True)
        except Exception as e:  # noqa: BLE001
            info["seed_error"] = repr(e)[:200]
    info["seeded"] = seed_ass is not None
    params.time_limit.FromMilliseconds(max(100, int((deadline_abs - time.time()) * 1000)))
    t_solve = time.time()
    if seed_ass is not None:
        sol = routing.SolveFromAssignmentWithParameters(seed_ass, params)
    else:
        sol = routing.SolveWithParameters(params)
    info["solve_s"] = round(time.time() - t_solve, 3)
    if sol is None:
        info["status"] = "no_solution"
        return None, info
    t = [int(d)]
    idx = sol.Value(routing.NextVar(routing.Start(0)))
    while not routing.IsEnd(idx):
        t.append(int(manager.IndexToNode(idx)))
        idx = sol.Value(routing.NextVar(idx))
    t.append(int(d))
    info.update(status="ok", objective=int(sol.ObjectiveValue()), cities=len(t) - 2)
    return t, info


def _child(D, P, d, t0, seed, deadline_abs, cfg, path):
    """Forked: run OR-Tools and leave {"tour", "info"} in path."""
    try:
        t, info = ortools_search(D, P, d, t0, seed, deadline_abs, cfg)
    except BaseException as e:  # noqa: BLE001 - report, never crash the parent
        t, info = None, {"status": "error", "error": repr(e)[:300]}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"tour": t, "info": info}, f)
    os.replace(tmp, path)


def _tour_from_solution(labels, sol):
    idx = {int(c): i for i, c in enumerate(labels)}
    try:
        return [idx[int(c)] for c in sol["tour"]]
    except Exception:  # noqa: BLE001
        return None


def solve(inst, time_limit_s, start=None, output=None, cfg=None):
    """Solve one instance; returns the solution dict. start = wall-clock origin of the time limit."""
    cfg = dict(DEFAULT_CONFIG if cfg is None else cfg)
    t_start = _T_START if start is None else start
    T = float(time_limit_s)
    budget = max(1.0, min(T * 0.85, T - 4.0))
    C.HARD[0] = t_start + max(1.0, T - 2.5)
    labels, D, P, d, t0 = C.parse_instance(inst)
    log = {"version": VERSION, "mode": cfg.get("mode"), "config": cfg}

    seed = initial(D, P, d, t0)
    best = seed if valid(D, seed, t0) else None
    log["seed_prize"] = C.score_of(P, seed) if best else None
    log["seed_at_s"] = round(time.time() - t_start, 3)
    if best is not None:
        _write(output, C.build_solution(labels, P, best))

    mode = str(cfg.get("mode", "parallel"))
    ort_deadline = t_start + budget - min(1.0, 0.1 * budget)
    join_deadline = t_start + max(budget, T - 4.0)
    candidates = {}

    if mode == "parallel":
        try:
            import multiprocessing
            ctx = multiprocessing.get_context("fork")
        except Exception as e:  # noqa: BLE001 - no fork here: OR-Tools in this process instead
            log["fork_error"] = repr(e)[:200]
            mode = "ortools"
    if mode == "parallel":
        side = (output + ".mv2-ortools.json") if output else os.path.join(
            tempfile.gettempdir(), "mv2-op-%d-%d.json" % (os.getpid(), int(time.time() * 1000)))
        if os.path.exists(side):
            os.remove(side)
        proc = ctx.Process(target=_child, args=(D, P, d, t0, best, ort_deadline, cfg, side), daemon=True)
        proc.start()
        ils_sol = core_ils(inst, T, t_start)
        candidates["ils"] = _tour_from_solution(labels, ils_sol)
        proc.join(max(0.0, join_deadline - time.time()))
        if proc.is_alive():
            proc.terminate()
            proc.join(1.0)
            log["ortools_killed"] = True
        if os.path.exists(side):
            try:
                with open(side, encoding="utf-8") as f:
                    got = json.load(f)
                candidates["ortools"] = got.get("tour")
                log["ortools"] = got.get("info")
            except Exception as e:  # noqa: BLE001
                log["ortools"] = {"status": "unreadable", "error": repr(e)[:200]}
            try:
                os.remove(side)
            except OSError:
                pass
        else:
            log.setdefault("ortools", {"status": "no_result"})
    elif mode == "ortools":
        try:
            t, info = ortools_search(D, P, d, t0, best, ort_deadline, cfg)
            candidates["ortools"] = t
            log["ortools"] = info
        except Exception as e:  # noqa: BLE001 - fall back to v1 for the time left
            log["ortools"] = {"status": "error", "error": repr(e)[:300]}
            ils_sol = core_ils(inst, T, t_start)
            candidates["ils"] = _tour_from_solution(labels, ils_sol)
    else:
        ils_sol = core_ils(inst, T, t_start)
        candidates["ils"] = _tour_from_solution(labels, ils_sol)

    chosen = "seed"
    for name in ("ils", "ortools"):
        t = candidates.get(name)
        ok = t is not None and valid(D, t, t0)
        log[name + "_valid"] = ok
        if ok:
            log[name + "_prize"] = C.score_of(P, t)
            log[name + "_length"] = round(C.tour_length(D, t), 6)
            if best is None or key_of(D, P, t) > key_of(D, P, best):
                best, chosen = t, name
    log["chosen"] = chosen if best is not None else None
    log["best_prize"] = C.score_of(P, best) if best is not None else None
    log["t0"] = t0
    log["done_at_s"] = round(time.time() - t_start, 3)
    if best is None:  # nothing valid at all: the greedy answer as it stands
        best = seed
    sol = C.build_solution(labels, P, best)
    _write(output, sol)
    if cfg.get("log_file") and output:
        try:
            with open(output + ".log.json", "w", encoding="utf-8") as f:
                json.dump(log, f, default=str)
        except Exception:  # noqa: BLE001
            pass
    sys.stderr.write("OP030_STATS %s\n" % json.dumps(log, default=str)[:1500])
    return sol


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="fischetti1998")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    args = ap.parse_args(argv)
    with open(args.instance, "r", encoding="utf-8") as f:
        inst = json.load(f)
    solve(inst, args.time_limit, output=args.output, cfg=load_config())
    return 0


if __name__ == "__main__":
    sys.exit(main())

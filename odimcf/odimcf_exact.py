"""Exact references for barnhart2000 (ODIMCF): an arc-based MIP (HiGHS via scipy.optimize.milp) and brute force.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Arc MIP: binary x[k,a] for every commodity k and every arc a with capacity >= demand(k) (no self-loops), binary
r[k] (reject). For each k and node v: out-flow - in-flow = (1 - r[k]) at the origin, -(1 - r[k]) at the
destination, 0 elsewhere. For each arc a: sum_k demand(k) x[k,a] <= capacity(a). Minimise
sum demand(k) cost(a) x[k,a] + penalty(k) r[k]. A chosen flow may contain zero-cost cycles; the path is taken by
walking from the origin and cutting every loop, which only lowers arc loads, so the extracted solution stays
feasible and is no worse. Shares no code with the solver; penalties follow odimcf_check.penalty_mode.
"""
import itertools
import time
from collections import defaultdict

from odimcf_check import check, penalty, penalty_mode


def _index(inst):
    net = inst["network"]
    arcs = net["arcs"]
    nodes = list(net.get("nodes") or [])
    seen = set(nodes)
    for a in arcs:
        for v in (a["from_node"], a["to_node"]):
            if v not in seen:
                seen.add(v)
                nodes.append(v)
    coms = inst["commodities"]["commodity_list"]
    for c in coms:
        for v in (c["origin"], c["destination"]):
            if v not in seen:
                seen.add(v)
                nodes.append(v)
    return nodes, arcs, coms


def solution_from_paths(inst, paths):
    """paths: commodity_id -> list of arc dicts, or None for rejected."""
    coms = inst["commodities"]["commodity_list"]
    mode = penalty_mode(coms)
    out = []
    obj = 0.0
    for c in coms:
        p = paths.get(c["commodity_id"])
        if p is None:
            obj += penalty(c, mode)
            out.append({"commodity_id": c["commodity_id"], "rejected": True, "path_arcs": []})
        else:
            obj += float(c["demand"]) * sum(float(a.get("cost", 0) or 0) for a in p)
            out.append({"commodity_id": c["commodity_id"], "rejected": False,
                        "path_arcs": [{"from": a["from_node"], "to": a["to_node"], "arc_id": a["arc_id"]} for a in p]})
    return {"objective_value": obj, "commodities": out}


def extract_path(origin, dest, chosen):
    """chosen: list of arc dicts with flow 1 for one commodity. Returns a simple origin->dest path or None."""
    out = defaultdict(list)
    for a in chosen:
        out[a["from_node"]].append(a)
    used = set()
    path = []
    pos = {origin: 0}
    u = origin
    steps = 0
    while u != dest:
        nxt = None
        for a in out[u]:
            if id(a) not in used:
                nxt = a
                break
        if nxt is None:
            return None
        used.add(id(nxt))
        v = nxt["to_node"]
        if v in pos:
            cut = pos[v]
            for b in path[cut:]:
                del pos[b["to_node"]]
            path = path[:cut]
        else:
            path.append(nxt)
            pos[v] = len(path)
        u = v
        steps += 1
        if steps > len(chosen) + 2:
            return None
    return path


def arc_mip(inst, time_limit=60.0):
    import numpy as np
    import scipy.sparse as sp
    from scipy.optimize import Bounds, LinearConstraint, milp

    t0 = time.monotonic()
    nodes, arcs, coms = _index(inst)
    mode = penalty_mode(coms)
    nidx = {v: i for i, v in enumerate(nodes)}
    N, A, K = len(nodes), len(arcs), len(coms)
    var = []
    for k, c in enumerate(coms):
        for j, a in enumerate(arcs):
            if a["from_node"] != a["to_node"] and float(a["capacity"]) >= float(c["demand"]) - 1e-9:
                var.append((k, j))
    nx = len(var)
    n = nx + K
    cost = np.zeros(n)
    er, ec, ev = [], [], []
    cr, cc, cv = [], [], []
    for col, (k, j) in enumerate(var):
        a = arcs[j]
        d = float(coms[k]["demand"])
        cost[col] = d * float(a.get("cost", 0) or 0)
        er += [k * N + nidx[a["from_node"]], k * N + nidx[a["to_node"]]]
        ec += [col, col]
        ev += [1.0, -1.0]
        cr.append(j)
        cc.append(col)
        cv.append(d)
    beq = np.zeros(K * N)
    for k, c in enumerate(coms):
        cost[nx + k] = penalty(c, mode)
        o, t = k * N + nidx[c["origin"]], k * N + nidx[c["destination"]]
        er += [o, t]
        ec += [nx + k, nx + k]
        ev += [1.0, -1.0]
        beq[o] += 1.0
        beq[t] -= 1.0
    aeq = sp.csr_matrix((np.asarray(ev), (np.asarray(er, dtype=np.int64), np.asarray(ec, dtype=np.int64))),
                        shape=(K * N, n))
    acap = sp.csr_matrix((np.asarray(cv, dtype=float), (np.asarray(cr, dtype=np.int64),
                                                         np.asarray(cc, dtype=np.int64))), shape=(A, n))
    capv = np.asarray([float(a["capacity"]) for a in arcs])
    res = milp(cost, integrality=np.ones(n), bounds=Bounds(np.zeros(n), np.ones(n)),
               constraints=[LinearConstraint(aeq, beq, beq), LinearConstraint(acap, np.full(A, -np.inf), capv)],
               options={"time_limit": float(time_limit), "disp": False, "mip_rel_gap": 0.0})
    out = {"status": int(res.status), "proven": res.status == 0, "bound": res.get("mip_dual_bound"),
           "mip_fun": None if res.fun is None else float(res.fun), "vars": n,
           "time_s": round(time.monotonic() - t0, 3), "objective": None, "solution": None}
    if res.x is None:
        return out
    chosen = defaultdict(list)
    for col, (k, j) in enumerate(var):
        if res.x[col] > 0.5:
            chosen[k].append(arcs[j])
    paths = {}
    for k, c in enumerate(coms):
        if res.x[nx + k] > 0.5:
            paths[c["commodity_id"]] = None
        elif c["origin"] == c["destination"]:
            paths[c["commodity_id"]] = []
        else:
            paths[c["commodity_id"]] = extract_path(c["origin"], c["destination"], chosen[k])
    sol = solution_from_paths(inst, paths)
    chk = check(inst, sol)
    out["checker"] = chk.get("reason") or "ok"
    if chk["feasible"]:
        out["objective"] = chk["objective"]
        out["solution"] = sol
    if out["proven"] and out["bound"] is None:
        out["bound"] = out["objective"]
    return out


def simple_paths(arcs, origin, dest, demand, limit=10000):
    out_arcs = defaultdict(list)
    for a in arcs:
        if a["from_node"] != a["to_node"] and float(a["capacity"]) >= float(demand) - 1e-9:
            out_arcs[a["from_node"]].append(a)
    res = []

    def dfs(u, seen, path):
        if len(res) >= limit:
            return
        if u == dest:
            res.append(list(path))
            return
        for a in out_arcs[u]:
            v = a["to_node"]
            if v not in seen:
                seen.add(v)
                path.append(a)
                dfs(v, seen, path)
                path.pop()
                seen.discard(v)

    dfs(origin, {origin}, [])
    return res


def brute_force(inst, max_combos=2_000_000):
    _, arcs, coms = _index(inst)
    options = []
    total = 1
    for c in coms:
        if c["origin"] == c["destination"]:
            opts = [None, []]
        else:
            opts = [None] + simple_paths(arcs, c["origin"], c["destination"], c["demand"])
        options.append(opts)
        total *= len(opts)
    if total > max_combos:
        raise ValueError("too many combinations: %d" % total)
    best = None
    for combo in itertools.product(*options):
        load = defaultdict(float)
        ok = True
        for c, p in zip(coms, combo):
            for a in p or []:
                load[a["arc_id"]] += float(c["demand"])
                if load[a["arc_id"]] > float(a["capacity"]) + 1e-9:
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            continue
        sol = solution_from_paths(inst, {c["commodity_id"]: p for c, p in zip(coms, combo)})
        if best is None or sol["objective_value"] < best["objective_value"] - 1e-9:
            best = sol
    return best

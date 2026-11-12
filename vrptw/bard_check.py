"""bard_check: an independent checker for FrontierOR bard2002 solutions (shares no code with bard2002/solve.py).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

check(instance, solution) -> {"feasible", "objective", "reason"} follows the official feasibility_check.py of the
public FrontierOR benchmark (constraints (2)-(9), tolerance 1e-5, objective = number of depot-to-customer arcs,
num_vehicles = len(routes), total_distance within 0.05 of the rounded route distance), re-written from its text.

strict(instance, solution) -> {"strict_ok", "late_returns", "early_starts", "max_late", ...} re-times every route
from the depot (leave at the depot's ready time, wait when early) and reports what the official checker does not
test: whether each route can actually reach its customers in time from the depot and get back by the depot's due
date, under the same travel times.

plain_capacity(instance, solution) -> the largest route load / Q, and the largest value of the load rule implied by
the checker's constraint (5) (q_first + route load, maximised over route suffixes) / Q.
"""
import math


def _data(inst):
    nodes = [inst["depot"]] + list(inst["customers"])
    N = len(nodes)
    a = [nodes[i]["ready_time"] for i in range(N)]
    b = [nodes[i]["due_date"] for i in range(N)]
    q = [nodes[i]["demand"] for i in range(N)]
    s = [nodes[i]["service_time"] for i in range(N)]
    if inst.get("distance_matrix"):
        raw = inst["distance_matrix"]
    else:
        raw = [[0.0] * N for _ in range(N)]
        for i in range(N):
            for j in range(N):
                if i != j:
                    d = math.sqrt((nodes[i]["x"] - nodes[j]["x"]) ** 2 + (nodes[i]["y"] - nodes[j]["y"]) ** 2)
                    raw[i][j] = math.floor(d * 10) / 10.0
    fold = inst.get("travel_time_includes_service_time", False)
    tau = [[0.0] * N for _ in range(N)]
    for i in range(N):
        for j in range(N):
            if i == j:
                continue
            t = raw[i][j] + (0 if fold else s[i])
            if (a[j] - b[i]) > t:
                t = a[j] - b[i]
            tau[i][j] = t
    return N, a, b, q, raw, tau, float(inst["vehicle_capacity"])


def check(inst, sol):
    try:
        return _check(inst, sol)
    except Exception as e:  # noqa: BLE001 - malformed solution
        return {"feasible": False, "objective": None, "reason": "malformed: %r" % (e,)}


def _check(inst, sol):
    tol = 1e-5
    for k in ("departure_times", "loads", "num_vehicles", "objective_value", "routes", "total_distance"):
        if k not in sol or sol[k] is None:
            return {"feasible": False, "objective": None, "reason": "missing " + k}
    for k in ("departure_times", "loads", "num_vehicles", "total_distance"):
        if sol[k] in ([], {}):
            return {"feasible": False, "objective": None, "reason": "empty " + k}
    N, a, b, q, raw, tau, Q = _data(inst)
    routes = sol["routes"]
    arcs = {}
    for r in routes:
        for u, v in zip(r, r[1:]):
            arcs[(u, v)] = 1
    t = {int(k): float(v) for k, v in sol["departure_times"].items()}
    y = {int(k): float(v) for k, v in sol["loads"].items()}
    reasons = []
    for i in range(1, N):
        outs = sum(1 for j in range(N) if j != i and (i, j) in arcs)
        if outs != 1:
            reasons.append("visit count %d at %d" % (outs, i))
    for i in range(N):
        o = sum(1 for j in range(N) if j != i and (i, j) in arcs)
        n_in = sum(1 for j in range(N) if j != i and (j, i) in arcs)
        if o != n_in:
            reasons.append("flow at %d" % i)
    for i in range(1, N):
        for j in range(1, N):
            if i == j:
                continue
            x = 1 if (i, j) in arcs else 0
            if t.get(i, 0.0) + tau[i][j] * x - (b[i] - a[j]) * (1 - x) - t.get(j, 0.0) > tol:
                reasons.append("time link %d-%d" % (i, j))
            if y.get(i, 0.0) + q[j] - (Q - q[j]) * (1 - x) - y.get(j, 0.0) > tol:
                reasons.append("load link %d-%d" % (i, j))
        if q[i] - y.get(i, 0.0) > tol or y.get(i, 0.0) - Q > tol:
            reasons.append("load bounds %d" % i)
        if a[i] - t.get(i, 0.0) > tol or t.get(i, 0.0) - b[i] > tol:
            reasons.append("window %d" % i)
    true_obj = float(sum(1 for j in range(1, N) if (0, j) in arcs))
    try:
        if abs(float(sol["objective_value"]) - true_obj) > 0.5:
            reasons.append("objective %s vs %s" % (sol["objective_value"], true_obj))
    except (TypeError, ValueError):
        reasons.append("objective not a number")
    nv = sol["num_vehicles"]
    if isinstance(nv, bool) or not isinstance(nv, (int, float)) or abs(float(nv) - len(routes)) > tol:
        reasons.append("num_vehicles")
    dist = round(sum(float(raw[r[p]][r[p + 1]]) for r in routes for p in range(len(r) - 1)), 1)
    td = sol["total_distance"]
    if isinstance(td, bool) or not isinstance(td, (int, float)) or abs(float(td) - dist) > 0.05:
        reasons.append("total_distance %s vs %s" % (td, dist))
    return {"feasible": not reasons, "objective": true_obj, "reason": "; ".join(reasons[:5]),
            "n_violations": len(reasons), "distance": dist}


def strict(inst, sol):
    N, a, b, q, raw, tau, Q = _data(inst)
    late, early, worst = 0, 0, 0.0
    for r in sol.get("routes") or []:
        cs = [v for v in r if v != 0]
        if not cs:
            continue
        t = a[0]
        prev = 0
        for j in cs:
            t = max(a[j], t + tau[prev][j])
            if t > b[j] + 1e-6:
                early += 1
                worst = max(worst, t - b[j])
            prev = j
        back = t + tau[prev][0]
        if back > b[0] + 1e-6:
            late += 1
            worst = max(worst, back - b[0])
    return {"strict_ok": late == 0 and early == 0, "late_returns": late, "missed_windows_from_depot": early,
            "max_late": round(worst, 4)}


def plain_capacity(inst, sol):
    N, a, b, q, raw, tau, Q = _data(inst)
    worst_load, worst_rule = 0.0, 0.0
    for r in sol.get("routes") or []:
        cs = [v for v in r if v != 0]
        s, h = 0.0, 0.0
        for idx in range(len(cs) - 1, -1, -1):
            s += q[cs[idx]]
            if idx < len(cs) - 1:
                h = max(h, s + q[cs[idx]])
        worst_load = max(worst_load, s)
        worst_rule = max(worst_rule, h)
    return {"max_load_frac": round(worst_load / Q, 4) if Q else None,
            "max_rule_frac": round(worst_rule / Q, 4) if Q else None}

"""Independent checker for FrontierOR he2020 (VRPTW with convex node costs). Apache-2.0.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name.

Same rules as the benchmark's feasibility_check.py (tolerance 1e-5 on times), written separately, with one
difference made explicit: rho comes from instance["inconvenience_cost_function"]["rho"] (the value gurobi_code.py
optimises), falling back to a top-level "inconvenience_cost_factor_rho", then 0. The official checker reads only the
top-level key, with default 0. check() returns {"feasible", "objective", "reason", "routing", "inconvenience",
"rho", "rho_source"}; "objective" is the recomputed total cost.
"""
TOL = 1e-5


def rho_of(inst):
    f = inst.get("inconvenience_cost_function")
    if isinstance(f, dict) and f.get("rho") is not None:
        return float(f["rho"]), "inconvenience_cost_function.rho"
    if inst.get("inconvenience_cost_factor_rho") is not None:
        return float(inst["inconvenience_cost_factor_rho"]), "inconvenience_cost_factor_rho"
    return 0.0, "none"


def costs(inst, sol, rho):
    """(routing, inconvenience) of a solution as the official objective formula sums them."""
    d = inst["distance_matrix"]
    routing = 0.0
    for route in sol.get("routes") or []:
        for k in range(1, len(route)):
            routing += float(d[route[k - 1]][route[k]])
    pref = {int(c["id"]): float(c["preferred_time"]) for c in inst["customers"]}
    inconv = 0.0
    for key, v in (sol.get("schedule") or {}).items():
        cid = int(key)
        if cid in pref:
            inconv += rho * (float(v) - pref[cid]) ** 2
    return routing, inconv


def check(inst, sol, rho=None):
    rho_src = "argument"
    if rho is None:
        rho, rho_src = rho_of(inst)
    out = {"feasible": False, "objective": None, "reason": "", "rho": rho, "rho_source": rho_src}
    try:
        n = int(inst["num_customers"])
        K = int(inst["num_vehicles"])
        Q = float(inst["vehicle_capacity"])
        d = inst["distance_matrix"]
        E = int(inst["depot_end"]["id"])
        e = {0: float(inst["depot"]["time_window"][0]), E: float(inst["depot_end"]["time_window"][0])}
        l_ = {0: float(inst["depot"]["time_window"][1]), E: float(inst["depot_end"]["time_window"][1])}
        q, s = {}, {0: 0.0, E: 0.0}
        dflt = inst.get("service_time", 0.0)
        for c in inst["customers"]:
            i = int(c["id"])
            e[i], l_[i] = float(c["time_window"][0]), float(c["time_window"][1])
            q[i] = float(c["demand"])
            s[i] = float(c.get("service_time", dflt))
        routes = sol["routes"]
        sched = {int(k): float(v) for k, v in sol["schedule"].items()}
        if not isinstance(sol.get("objective_value"), (int, float)) or isinstance(sol.get("objective_value"), bool):
            out["reason"] = "objective_value missing"
            return out
        if set(sched) != set(range(1, n + 1)):
            out["reason"] = "schedule keys"
            return out
        seen = {}
        for r in routes:
            if len(r) < 3 or r[0] != 0 or r[-1] != E:
                out["reason"] = "route shape %s" % (r[:4],)
                return out
            for j in r[1:-1]:
                if j == 0 or j == E:
                    out["reason"] = "depot inside route"
                    return out
                seen[j] = seen.get(j, 0) + 1
        if set(seen) != set(range(1, n + 1)) or any(v != 1 for v in seen.values()):
            out["reason"] = "cover"
            return out
        if len(routes) > K:
            out["reason"] = "fleet %d > %d" % (len(routes), K)
            return out
        for ri, r in enumerate(routes):
            cs = r[1:-1]
            if sum(q[j] for j in cs) > Q + TOL:
                out["reason"] = "capacity route %d" % ri
                return out
            t = {j: sched[j] for j in cs}
            t[0] = max(e[0], min(l_[0], t[cs[0]] - float(d[0][cs[0]])))
            t[E] = max(e[E], t[cs[-1]] + s[cs[-1]] + float(d[cs[-1]][E]))
            for v in r:
                if t[v] < e[v] - TOL or t[v] > l_[v] + TOL:
                    out["reason"] = "window route %d node %d" % (ri, v)
                    return out
            for k in range(1, len(r)):
                a, b = r[k - 1], r[k]
                if t[a] + s[a] + float(d[a][b]) > t[b] + TOL:
                    out["reason"] = "precedence route %d arc %d-%d" % (ri, a, b)
                    return out
        routing, inconv = costs(inst, sol, rho)
        out.update(feasible=True, objective=routing + inconv, routing=routing, inconvenience=inconv)
        return out
    except (KeyError, IndexError, TypeError, ValueError) as ex:
        out["reason"] = "malformed: %r" % (ex,)
        return out

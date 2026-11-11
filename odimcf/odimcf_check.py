"""Independent feasibility checker for barnhart2000 (ODIMCF) solutions.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Written from the public FrontierOR problem page (https://frontieror-challenge.com/problems/barnhart2000), not from
the official feasibility_check.py, which needs a signed-in account. It shares no code with the solver.

Rules checked:
- every commodity_id of the instance appears exactly once in sol["commodities"], and no unknown id appears;
- a rejected commodity has an empty path_arcs (or none);
- a routed commodity's path_arcs is a chain of existing arcs whose "from"/"to" match the arc_id's own end nodes,
  starting at the origin and ending at the destination, visiting no node twice (one simple path);
- on every arc, the sum of the demands routed over it is at most its capacity;
- objective = sum over routed commodities of demand x (sum of arc costs on the path)
              + sum over rejected commodities of the rejection penalty.

The rejection penalty (OPEN QUESTION until the official checker can be read): the page says the artificial arc's cost
"equals the commodity's lost revenue", and also that the objective is demand x per-unit arc cost. We take the reading
under which the penalty equals the commodity's revenue field:
- if artificial_arc_cost == revenue for every commodity: penalty = artificial_arc_cost ("total");
- else if artificial_arc_cost x demand == revenue for every commodity: penalty = artificial_arc_cost x demand
  ("per_unit");
- otherwise per_unit (the literal formula).
"""
import json
import sys

TOL = 1e-6


def _close(a, b):
    return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(b)))


def penalty_mode(commodity_list):
    if commodity_list and all("revenue" in c and _close(c["artificial_arc_cost"], c["revenue"])
                              for c in commodity_list):
        return "total"
    if commodity_list and all("revenue" in c and _close(c["artificial_arc_cost"] * c["demand"], c["revenue"])
                              for c in commodity_list):
        return "per_unit"
    return "per_unit"


def penalty(c, mode):
    return float(c["artificial_arc_cost"]) * (float(c["demand"]) if mode == "per_unit" else 1.0)


def check(instance, sol):
    try:
        return _check(instance, sol)
    except Exception as e:  # noqa: BLE001 - a malformed solution is infeasible
        return {"feasible": False, "objective": None, "reason": "malformed: %r" % (e,)}


def _check(instance, sol):
    arcs = {a["arc_id"]: a for a in instance["network"]["arcs"]}
    coms = instance["commodities"]["commodity_list"]
    mode = penalty_mode(coms)
    byid = {c["commodity_id"]: c for c in coms}
    seen = set()
    load = {}
    obj = 0.0
    entries = sol.get("commodities")
    if not isinstance(entries, list):
        return {"feasible": False, "objective": None, "reason": "commodities is not a list"}
    for e in entries:
        cid = e.get("commodity_id")
        if cid not in byid:
            return {"feasible": False, "objective": None, "reason": "unknown commodity %r" % (cid,)}
        if cid in seen:
            return {"feasible": False, "objective": None, "reason": "commodity %r twice" % (cid,)}
        seen.add(cid)
        c = byid[cid]
        path = e.get("path_arcs") or []
        rejected = e.get("rejected")
        if not isinstance(rejected, bool):
            return {"feasible": False, "objective": None, "reason": "rejected not bool for %r" % (cid,)}
        if rejected:
            if path:
                return {"feasible": False, "objective": None, "reason": "rejected %r has arcs" % (cid,)}
            obj += penalty(c, mode)
            continue
        node = c["origin"]
        visited = {node}
        cost = 0.0
        for step in path:
            aid = step.get("arc_id")
            if aid not in arcs:
                return {"feasible": False, "objective": None, "reason": "unknown arc %r" % (aid,)}
            a = arcs[aid]
            if step.get("from") != a["from_node"] or step.get("to") != a["to_node"]:
                return {"feasible": False, "objective": None, "reason": "arc %r ends mismatch" % (aid,)}
            if a["from_node"] != node:
                return {"feasible": False, "objective": None, "reason": "path of %r broken at %r" % (cid, aid)}
            node = a["to_node"]
            if node in visited:
                return {"feasible": False, "objective": None, "reason": "path of %r revisits %r" % (cid, node)}
            visited.add(node)
            load[aid] = load.get(aid, 0.0) + float(c["demand"])
            cost += float(a.get("cost", 0) or 0)
        if node != c["destination"]:
            return {"feasible": False, "objective": None, "reason": "path of %r ends at %r" % (cid, node)}
        obj += float(c["demand"]) * cost
    missing = set(byid) - seen
    if missing:
        return {"feasible": False, "objective": None, "reason": "%d commodities missing" % len(missing)}
    for aid, l in load.items():
        if l > float(arcs[aid]["capacity"]) + TOL:
            return {"feasible": False, "objective": None,
                    "reason": "arc %r load %s > capacity %s" % (aid, l, arcs[aid]["capacity"])}
    return {"feasible": True, "objective": obj, "reason": "", "mode": mode}


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        inst = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        s = json.load(f)
    print(json.dumps(check(inst, s)))

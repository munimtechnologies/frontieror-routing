"""Independent feasibility checker for bodur2017 (SCFLP) solutions.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Written from the public FrontierOR problem page; it shares no code with the solver or with the official checker
(which is public in the FrontierOR benchmark dataset on Hugging Face and is run next to this one in scflp_real.py).
Our reading:
- x[i] in {0, 1} for every facility key given, and it agrees with open_facilities;
- the opened capacity is at least the largest total demand over all scenarios (aggregate capacity);
- in every scenario: every customer receives at least its demand, no facility ships more than its capacity, a
  closed facility ships nothing, no shipment is negative;
- objective = opening costs + sum over scenarios of probability x sum of cost x quantity.
Missing y entries count as 0.
"""


def _bad(reason):
    return {"feasible": False, "reason": reason, "objective": None}


def check(inst, sol, tol=1e-5):  # the official checker's tolerance (read 2026-11-10 from the public dataset)
    try:
        fac = {int(f["id"]): f for f in inst["facilities"]}
        cus = {int(c["id"]): c for c in inst["customers"]}
        scen = {int(s["id"]): s for s in inst["scenarios"]}
        cost = inst["transportation_costs"]
        if not isinstance(sol, dict):
            return _bad("solution is not an object")
        x, opened_list, y = sol.get("x"), sol.get("open_facilities"), sol.get("y")
        if not isinstance(x, dict) or not isinstance(opened_list, list) or not isinstance(y, dict):
            return _bad("x, open_facilities or y missing or of the wrong type")
        xv = {}
        for k, v in x.items():
            i = int(k)
            if i not in fac:
                return _bad("x names unknown facility %s" % k)
            fv = float(v)
            if abs(fv) > tol and abs(fv - 1.0) > tol:
                return _bad("x[%s] = %r is not binary" % (k, v))
            xv[i] = 1 if fv > 0.5 else 0
        opened = set()
        for i in opened_list:
            i = int(i)
            if i not in fac:
                return _bad("open_facilities names unknown facility %d" % i)
            opened.add(i)
        for i in fac:
            if xv.get(i, 0) != (1 if i in opened else 0):
                return _bad("x and open_facilities disagree at facility %d" % i)
        capsum = sum(float(fac[i]["capacity"]) for i in opened)
        dmax = max(sum(float(d) for d in s["demands"]) for s in scen.values())
        if capsum < dmax - tol * max(1.0, dmax):
            return _bad("aggregate capacity %.6f below the largest total demand %.6f" % (capsum, dmax))
        total = sum(float(fac[i]["opening_cost"]) for i in opened)
        nS = len(scen)
        for sid, s in scen.items():
            ys = y.get(str(sid), {})
            if not isinstance(ys, dict):
                return _bad("y[%d] is not an object" % sid)
            p = s.get("probability")
            p = 1.0 / nS if p is None else float(p)
            recv = {j: 0.0 for j in cus}
            tc = 0.0
            for fk, row in ys.items():
                i = int(fk)
                if i not in fac:
                    return _bad("y[%d] names unknown facility %s" % (sid, fk))
                if not isinstance(row, dict):
                    return _bad("y[%d][%s] is not an object" % (sid, fk))
                out = 0.0
                for ck, q in row.items():
                    j = int(ck)
                    if j not in cus:
                        return _bad("y[%d][%s] names unknown customer %s" % (sid, fk, ck))
                    q = float(q)
                    if q < -tol:
                        return _bad("negative shipment y[%d][%d][%d]" % (sid, i, j))
                    if i not in opened and q > tol:
                        return _bad("closed facility %d ships in scenario %d" % (i, sid))
                    out += q
                    recv[j] += q
                    tc += float(cost[i][j]) * q
                c = float(fac[i]["capacity"])
                if out > c + tol * max(1.0, c):
                    return _bad("facility %d ships %.6f > capacity %.6f in scenario %d" % (i, out, c, sid))
            dem = s["demands"]
            for j in cus:
                d = float(dem[j])
                if recv[j] < d - tol * max(1.0, d):
                    return _bad("customer %d gets %.6f < demand %.6f in scenario %d" % (j, recv[j], d, sid))
            total += p * tc
        return {"feasible": True, "objective": total, "reason": ""}
    except (KeyError, ValueError, TypeError, IndexError) as e:
        return _bad("malformed: %r" % (e,))

"""MV2 berth solver v0.1.0 for FrontierOR task martin-iradi2024.

Multi-port continuous berth allocation with sailing-speed choice: each optimised ship gets, at every port call, a quay
position and a berthing start time, and a speed on every leg, so that no two ships (optimised or external) overlap in
quay space and time; cost = waiting + handling + delay + latest-finish penalty + fuel.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

  python solve.py --problem martin-iradi2024 --instance in.json --output out.json --time-limit 60
                  [--seed 1] [--first-arrival desc|est] [--labels 8]

Method (standard library only):
- One ship at a time, against everything else fixed: a label DP along its route. A label is (departure time, cost so
  far). For every label and every speed on the next leg the arrival time is known, and the call is placed at the
  cheapest quay position: the ideal position, a quay end, or flush against the edge of another ship; for each
  position, the earliest start at or after max(arrival, earliest start) whose time window is free there. Positions
  are tried in order of distance from the ideal one and the scan stops when a lower bound reaches the best cost.
  Label dominance is exact for the waiting cost: an earlier departure can always copy a later one by waiting in port,
  so label B is dropped when an earlier label A has cost_A + waiting_rate * (dep_B - dep_A) <= cost_B. At most
  --labels labels are kept per call (evenly thinned).
- Start: ships planned one by one in order of their first earliest start time.
- Then ruin and recreate until the time budget: remove 1-4 ships that share a port and a time span, re-plan them in
  random order, accept by simulated annealing (cooling to zero); the last fifth of the time continues greedily from
  the best solution found.
- --first-arrival: 'desc' (default) follows the problem description and the official checker, which only require the
  first call's arrival to be no later than its start, so the first call has no waiting cost (arrival = start). 'est'
  follows the stored Gurobi model's stricter assumption (arrival at the first call = its earliest start time).
- The written objective_value is recomputed exactly as the official checker's constraint 18 does; verify() mirrors
  every official check (constraints 1-18, same tolerances).
"""
import argparse
import bisect
import json
import math
import os
import random
import sys
import time

VERSION = "0.1.0"
TOL = 1e-7          # our own separation tolerance (the official checker allows 1e-5)
CHK_TOL = 1e-5      # the official checker's tolerance


def fuel_gamma(fuel_by_speed, spd):
    """Fuel per nautical mile looked up exactly as the official checker does (None: the checker adds no fuel)."""
    g = fuel_by_speed.get(str(spd))
    if g is None:
        try:
            g = fuel_by_speed.get(f"{float(spd):.1f}")
        except (TypeError, ValueError):
            g = None
    return g


def pareto_speeds(opts, wait_rate):
    """Drop speed options another one beats exactly: a faster option can copy a slower one by waiting in port, so
    option B goes when a no-slower option A has fuel_A + wait_rate * (travel_B - travel_A) <= fuel_B.
    opts: (travel_h, fuel_usd, speed)."""
    out, best_adj = [], math.inf
    for o in sorted(opts, key=lambda o: (o[0], o[1])):
        adj = o[1] - wait_rate * o[0]
        if adj < best_adj - 1e-12:
            out.append(o)
            best_adj = adj
    return out


class Visit:
    __slots__ = ("call", "port", "L", "x0", "h0", "est", "eft", "lft", "maxx")


class Ship:
    __slots__ = ("idx", "id", "l", "visits", "legs")


def earliest(obst, xl, xr, t0, h):
    """Earliest start >= t0 of a window of length h over quay span [xl, xr] that is free of the occupations obst
    (tuples (t_start, t_end, x_left, x_right, owner), sorted by t_start)."""
    y = t0
    for o in obst:
        if o[1] <= y + TOL:
            continue
        if o[3] <= xl + TOL or xr <= o[2] + TOL:
            continue
        if y + h <= o[0] + TOL:
            break
        y = o[1]
    return y


def thin(labels, K, wait_rate):
    """Exact waiting-dominance filter, then keep at most K labels (first, last and evenly spaced)."""
    labels.sort(key=lambda t: (t[0], t[1]))
    front, best_adj = [], math.inf
    for t in labels:
        adj = t[1] - wait_rate * t[0]
        if adj < best_adj - 1e-9:
            front.append(t)
            best_adj = adj
    if len(front) <= K:
        return front
    if K <= 1:
        return [min(front, key=lambda t: t[1])]
    keep = sorted(set(int(round(i * (len(front) - 1) / (K - 1))) for i in range(K)))
    cheapest = min(range(len(front)), key=lambda i: front[i][1])
    if cheapest not in keep:
        keep[-1] = cheapest
        keep = sorted(set(keep))
    return [front[i] for i in keep]


class Problem:
    def __init__(self, inst, first_arrival="desc"):
        self.inst = inst
        self.first_arrival = first_arrival
        self.beta = float(inst["handling_time_deviation_factor_beta_per_meter"])
        cp = inst.get("cost_parameters", {}) or {}
        self.I = cp.get("waiting_cost_usd_per_hour", 0)
        self.H = cp.get("handling_cost_usd_per_hour", 0)
        self.D = cp.get("delay_cost_usd_per_hour", 0)
        self.U = cp.get("lft_penalty_usd", 0)
        self.F = cp.get("fuel_price_usd_per_tonne", 0)
        quay = {p["id"]: p["quay_length_meters"] for p in inst["ports"]}
        dist = inst["distances_nautical_miles"]
        tt = inst["travel_time_hours_per_nm_by_speed"]
        speeds = list(inst["speeds_knots"])
        self.missing_travel_keys = [s for s in speeds if str(s) not in tt]
        self.ships = []
        for k, s in enumerate(inst["ships"]):
            sh = Ship()
            sh.idx, sh.id, sh.l = k, s["id"], s["length_meters"]
            fb = s.get("fuel_consumption_per_nm_by_speed", {}) or {}
            vs = []
            for pv in sorted(s["port_visits"], key=lambda pv: pv["port_call_index"]):
                v = Visit()
                v.call, v.port = pv["port_call_index"], pv["port_id"]
                v.L = quay[v.port]
                v.x0 = pv["ideal_berthing_position"]
                v.h0 = pv["min_handling_time_hours"]
                v.est = pv["earliest_start_time_hours"]
                v.eft = pv["expected_finish_time_hours"]
                v.lft = pv["latest_finish_time_hours"]
                v.maxx = v.L - sh.l
                vs.append(v)
            sh.visits = vs
            legs = []
            for j in range(len(vs) - 1):
                d = dist.get(f"{vs[j].port}_{vs[j + 1].port}", 0)
                opts = []
                for spd in speeds:
                    travel = tt.get(str(spd), 0) * d
                    g = fuel_gamma(fb, spd)
                    fuel = self.F * g * d if g is not None else 0.0
                    opts.append((travel, fuel, spd))
                legs.append(pareto_speeds(opts, self.I))
            sh.legs = legs
            self.ships.append(sh)
        self.ext = {}
        for ep in inst.get("external_ships", []) or []:
            for e in ep["ships"]:
                t0 = e["start_time_hours"]
                x = e["berthing_position"]
                self.ext.setdefault(ep["port_id"], []).append(
                    (t0, t0 + e["handling_time_hours"], x, x + e["length_meters"], -1))
        for p in self.ext:
            self.ext[p].sort()

    # ---- one call -------------------------------------------------------------------------------------------
    def candidates(self, sh, v, obst):
        """Quay positions worth trying for call v, sorted by distance from the ideal position: (r, x, h)."""
        l, x0, maxx = sh.l, v.x0, v.maxx
        xs = {min(max(x0, 0.0), maxx), 0.0, maxx}
        for o in obst:
            xs.add(o[3])
            xs.add(o[2] - l)
        out = []
        for x in xs:
            if 0.0 <= x <= maxx:
                r = abs(x - x0)
                out.append((r, x, (1.0 + self.beta * r) * v.h0))
        out.sort()
        if not out:   # ship longer than the quay: nothing is feasible; keep a placeholder
            out = [(abs(0.0 - x0), 0.0, (1.0 + self.beta * abs(0.0 - x0)) * v.h0)]
        return out

    def place(self, sh, v, a, obst, cands, nowait):
        """Cheapest placement of call v when the ship arrives at time a: (cost, x, y, end, h, r)."""
        I, H, D, U = self.I, self.H, self.D, self.U
        eft, lft, l = v.eft, v.lft, sh.l
        t0 = a if a > v.est else v.est
        w0 = 0.0 if nowait else I * (t0 - a)
        best = None
        for r, x, h in cands:
            if best is not None:
                e = t0 + h
                lb = H * h + w0 + D * max(0.0, e - eft) + U * max(0.0, e - lft)
                if lb >= best[0]:
                    break
            y = earliest(obst, x, x + l, t0, h)
            e = y + h
            cost = H * h + (0.0 if nowait else I * (y - a)) + D * max(0.0, e - eft) + U * max(0.0, e - lft)
            if best is None or cost < best[0] - 1e-9 or (cost <= best[0] + 1e-9 and e < best[3]):
                best = (cost, x, y, e, h, r)
        return best

    # ---- one ship -------------------------------------------------------------------------------------------
    def plan(self, sh, rects, K=8):
        """Best schedule of ship sh against the occupations in rects (port -> sorted list), its own excluded.
        Returns (cost, calls, speeds): calls = [(x, y, h, r, arrival)], speeds = [speed per leg]."""
        idx, vs = sh.idx, sh.visits
        if not vs:
            return 0.0, [], []
        obs, cands = [], []
        for v in vs:
            lst = [o for o in rects.get(v.port, ()) if o[4] != idx and o[1] > v.est]
            obs.append(lst)
            cands.append(self.candidates(sh, v, lst))
        nowait = self.first_arrival == "desc"
        v0 = vs[0]
        p = self.place(sh, v0, v0.est, obs[0], cands[0], nowait)
        a0 = p[2] if nowait else v0.est
        # label: (departure, cost, parent, leg option, placement, arrival)
        labels = [(p[3], p[0], None, None, p, a0)]
        for c in range(1, len(vs)):
            v, ob, ca = vs[c], obs[c], cands[c]
            new = []
            for lab in labels:
                dep, cost = lab[0], lab[1]
                for opt in sh.legs[c - 1]:
                    a = dep + opt[0]
                    q = self.place(sh, v, a, ob, ca, False)
                    new.append((q[3], cost + opt[1] + q[0], lab, opt, q, a))
            labels = thin(new, K, self.I)
        best = min(labels, key=lambda t: t[1])
        seq, lab = [], best
        while lab is not None:
            seq.append(lab)
            lab = lab[2]
        seq.reverse()
        calls = [(t[4][1], t[4][2], t[4][4], t[4][5], t[5]) for t in seq]
        speeds = [t[3][2] for t in seq[1:]]
        return best[1], calls, speeds

    def ship_rects(self, sh, calls):
        return [(v.port, (y, y + h, x, x + sh.l, sh.idx)) for v, (x, y, h, r, a) in zip(sh.visits, calls)]


class State:
    def __init__(self, P):
        self.P = P
        n = len(P.ships)
        self.calls, self.speeds, self.cost = [None] * n, [None] * n, [0.0] * n
        self.rects = {p: list(lst) for p, lst in P.ext.items()}

    def add(self, i):
        for port, rec in self.P.ship_rects(self.P.ships[i], self.calls[i]):
            bisect.insort(self.rects.setdefault(port, []), rec)

    def remove(self, i):
        for port in {v.port for v in self.P.ships[i].visits}:
            self.rects[port] = [o for o in self.rects.get(port, ()) if o[4] != i]

    def set(self, i, cost, calls, speeds):
        self.cost[i], self.calls[i], self.speeds[i] = cost, calls, speeds

    def total(self):
        return sum(self.cost)

    def load(self, calls, speeds, cost):
        self.calls, self.speeds, self.cost = list(calls), list(speeds), list(cost)
        self.rects = {p: list(lst) for p, lst in self.P.ext.items()}
        for i in range(len(self.calls)):
            self.add(i)

    def related(self, i, window=24.0):
        out = set()
        for port, (y, e, _xl, _xr, _o) in self.P.ship_rects(self.P.ships[i], self.calls[i]):
            for o in self.rects.get(port, ()):
                if o[4] >= 0 and o[4] != i and o[0] < e + window and o[1] > y - window:
                    out.add(o[4])
        return sorted(out)


# ---- output and checking ------------------------------------------------------------------------------------
def build_solution(P, calls, speeds):
    ships = []
    for sh in P.ships:
        pvs = []
        for v, (x, y, h, r, a) in zip(sh.visits, calls[sh.idx]):
            e = y + h
            pvs.append({"port_call_index": v.call, "port_id": v.port, "berthing_position": x, "start_time": y,
                        "handling_time": h, "arrival_time": a, "delay": max(0.0, e - v.eft),
                        "lft_violation": max(0.0, e - v.lft), "position_deviation": r})
        sp = speeds[sh.idx]
        sel = [{"from_call": sh.visits[j].call, "to_call": sh.visits[j + 1].call, "speed_knots": sp[j]}
               for j in range(len(sp))]
        ships.append({"ship_id": sh.id, "port_visits": pvs, "speed_selections": sel})
    sol = {"objective_value": 0.0, "ships": ships}
    sol["objective_value"] = checker_objective(P.inst, sol)
    return sol


def checker_objective(inst, solution):
    """The official checker's constraint-18 recomputation, line for line."""
    distances = inst["distances_nautical_miles"]
    sol_ships = {s["ship_id"]: s for s in solution["ships"]}
    cp = inst.get("cost_parameters", {})
    I_c = cp.get("waiting_cost_usd_per_hour", 0)
    H_c = cp.get("handling_cost_usd_per_hour", 0)
    D_c = cp.get("delay_cost_usd_per_hour", 0)
    U_c = cp.get("lft_penalty_usd", 0)
    F_c = cp.get("fuel_price_usd_per_tonne", 0)
    true_obj = 0.0
    for inst_s in inst["ships"]:
        sol_ship = sol_ships.get(inst_s["id"])
        if sol_ship is None:
            continue
        inst_pvs_by_call = {pv["port_call_index"]: pv for pv in inst_s["port_visits"]}
        fuel_by_speed = inst_s.get("fuel_consumption_per_nm_by_speed", {})
        for pv in sol_ship.get("port_visits", []):
            a = pv.get("arrival_time", 0.0)
            y = pv.get("start_time", 0.0)
            h = pv.get("handling_time", 0.0)
            d = pv.get("delay", 0.0)
            u = pv.get("lft_violation", 0.0)
            true_obj += I_c * (y - a) + H_c * h + D_c * d + U_c * u
        for ss in sol_ship.get("speed_selections", []):
            spd, c, c_next = ss.get("speed_knots"), ss.get("from_call"), ss.get("to_call")
            if spd is None or c is None or c_next is None:
                continue
            pv_from, pv_to = inst_pvs_by_call.get(c), inst_pvs_by_call.get(c_next)
            if pv_from is None or pv_to is None:
                continue
            distance = distances.get(f"{pv_from['port_id']}_{pv_to['port_id']}", 0)
            gamma = fuel_gamma(fuel_by_speed, spd)
            if gamma is None:
                continue
            true_obj += F_c * gamma * distance
    return true_obj


def verify(inst, sol):
    """Mirror of the official feasibility_check.py (constraints 1-18, tolerance 1e-5).
    Returns {"feasible", "objective" (the checker's recomputation), "reason", "violated"}."""
    tol = CHK_TOL
    bad = []

    def viol(k, lhs, rhs, op):
        amt = lhs - rhs if op == "<=" else (rhs - lhs if op == ">=" else abs(lhs - rhs))
        if amt > tol:
            bad.append(k)

    try:
        if not isinstance(sol, dict) or sol.get("objective_value") is None or not sol.get("ships"):
            return {"feasible": False, "objective": None, "reason": "schema", "violated": ["solution_schema"]}
        obj = sol["objective_value"]
        if isinstance(obj, bool) or not isinstance(obj, (int, float)) or not math.isfinite(obj):
            return {"feasible": False, "objective": None, "reason": "objective not a finite number",
                    "violated": ["solution_schema"]}
        ports = {p["id"]: p for p in inst["ports"]}
        distances = inst["distances_nautical_miles"]
        travel_times = inst["travel_time_hours_per_nm_by_speed"]
        speeds = inst["speeds_knots"]
        beta = inst["handling_time_deviation_factor_beta_per_meter"]
        sol_ships = {s["ship_id"]: s for s in sol["ships"]}
        sol_visits = {}
        for s in sol["ships"]:
            for pv in s["port_visits"]:
                sol_visits[(s["ship_id"], pv["port_call_index"])] = pv
        exp_ids = [s["id"] for s in inst["ships"]]
        rep_ids = [s["ship_id"] for s in sol["ships"]]
        if len(rep_ids) != len(set(rep_ids)) or set(rep_ids) != set(exp_ids):
            bad.append(1)
        exp_keys = {(s["id"], pv["port_call_index"]) for s in inst["ships"] for pv in s["port_visits"]}
        rep_keys = [(s["ship_id"], pv["port_call_index"]) for s in sol["ships"] for pv in s.get("port_visits", [])]
        if len(rep_keys) != len(set(rep_keys)) or set(rep_keys) != exp_keys:
            bad.append(1)
        occ = {}
        for s in inst["ships"]:
            if s["id"] not in sol_ships:
                continue
            for pv in s["port_visits"]:
                sp = sol_visits.get((s["id"], pv["port_call_index"]))
                if sp is None:
                    continue
                occ.setdefault(pv["port_id"], []).append(
                    (sp["berthing_position"], s["length_meters"], sp["start_time"],
                     sp["start_time"] + sp["handling_time"]))
                L = ports[pv["port_id"]]["quay_length_meters"]
                viol(1, sp["berthing_position"] + s["length_meters"], L, "<=")
        for ep in inst["external_ships"]:
            L = ports[ep["port_id"]]["quay_length_meters"]
            for e in ep["ships"]:
                occ.setdefault(ep["port_id"], []).append(
                    (e["berthing_position"], e["length_meters"], e["start_time_hours"],
                     e["start_time_hours"] + e["handling_time_hours"]))
                viol(1, e["berthing_position"] + e["length_meters"], L, "<=")
        for lst in occ.values():
            for i in range(len(lst)):
                xi, li, si, ei = lst[i]
                for j in range(i + 1, len(lst)):
                    xj, lj, sj, ej = lst[j]
                    if not (xi + li <= xj + tol or xj + lj <= xi + tol or ei <= sj + tol or ej <= si + tol):
                        bad.append(4)
        for s in inst["ships"]:
            ss_all = sol_ships.get(s["id"])
            if ss_all is None:
                continue
            pvs = sorted(s["port_visits"], key=lambda pv: pv["port_call_index"])
            for k in range(len(pvs) - 1):
                c, cn = pvs[k]["port_call_index"], pvs[k + 1]["port_call_index"]
                cur, nxt = sol_visits.get((s["id"], c)), sol_visits.get((s["id"], cn))
                sel = [x for x in ss_all["speed_selections"] if x["from_call"] == c and x["to_call"] == cn]
                if len(sel) != 1:
                    bad.append(13)
                if cur is None or nxt is None:
                    continue
                if not sel:
                    continue
                d = distances.get(f"{pvs[k]['port_id']}_{pvs[k + 1]['port_id']}", 0)
                travel = travel_times.get(str(sel[0]["speed_knots"]), 0) * d
                viol(5, cur["start_time"] + cur["handling_time"] + travel, nxt["arrival_time"], "=")
            for x in ss_all["speed_selections"]:
                if x["speed_knots"] not in speeds:
                    bad.append(16)
            for pv in pvs:
                sp = sol_visits.get((s["id"], pv["port_call_index"]))
                if sp is None:
                    continue
                x, y, h = sp["berthing_position"], sp["start_time"], sp["handling_time"]
                viol(6, sp["arrival_time"], y, "<=")
                viol(7, pv["earliest_start_time_hours"], y, "<=")
                viol(8, y + h - pv["expected_finish_time_hours"], sp["delay"], "<=")
                viol(9, y + h - pv["latest_finish_time_hours"], sp["lft_violation"], "<=")
                r = sp["position_deviation"]
                viol(10, (1 + beta * r) * pv["min_handling_time_hours"], h, "=")
                viol(11, x - pv["ideal_berthing_position"], r, "<=")
                viol(12, pv["ideal_berthing_position"] - x, r, "<=")
                if x < -tol or y < -tol:
                    bad.append(14)
                for key in ("arrival_time", "handling_time", "delay", "lft_violation", "position_deviation"):
                    if sp[key] < -tol:
                        bad.append(15)
        true_obj = checker_objective(inst, sol)
        if abs(float(obj) - true_obj) > max(1e-3, 1e-8 * max(abs(true_obj), 1.0)):
            bad.append(18)
    except Exception as e:  # noqa: BLE001 - a crash is a rejection, as in the official checker
        return {"feasible": False, "objective": None, "reason": "malformed: %r" % (e,)[:300],
                "violated": ["malformed_solution"]}
    vs = sorted(set(bad))
    return {"feasible": not vs, "objective": true_obj, "reason": "violated %s" % (vs,), "violated": vs}


# ---- search ---------------------------------------------------------------------------------------------------
def solve(inst, time_limit=60.0, seed=1, first_arrival="desc", K=8, t_start=None, on_first=None, log=None):
    t_start = time.monotonic() if t_start is None else t_start
    budget = max(0.5, min(0.9 * time_limit, time_limit - 3.0)) - 0.4
    deadline = t_start + max(0.05, budget)
    rng = random.Random(seed)
    P = Problem(inst, first_arrival)
    n = len(P.ships)
    st = State(P)
    order = sorted(range(n), key=lambda i: (P.ships[i].visits[0].est if P.ships[i].visits else 0.0, P.ships[i].id))
    for i in order:
        c, calls, sp = P.plan(P.ships[i], st.rects, K)
        st.set(i, c, calls, sp)
        st.add(i)
    init = st.total()
    if on_first is not None:
        on_first(build_solution(P, st.calls, st.speeds))
    best = (init, list(st.calls), list(st.speeds), list(st.cost))
    cur = init
    events = [(round(time.monotonic() - t_start, 3), init)]
    it = acc = imp = 0
    T0 = 0.01 * init / max(1, n)
    span = max(1e-6, deadline - time.monotonic())
    t_lns = time.monotonic()
    greedy = False
    while n and time.monotonic() < deadline:
        it += 1
        frac = (time.monotonic() - t_lns) / span
        if frac >= 0.8 and not greedy:
            greedy = True
            st.load(best[1], best[2], best[3])
            cur = best[0]
        T = 0.0 if greedy else T0 * (1.0 - frac / 0.8)
        i = rng.randrange(n)
        k = rng.choice((1, 2, 2, 3, 3, 4))
        rel = st.related(i)
        group = [i] + (rng.sample(rel, min(k - 1, len(rel))) if rel else [])
        old = {j: (st.cost[j], st.calls[j], st.speeds[j]) for j in group}
        old_sum = sum(st.cost[j] for j in group)
        for j in group:
            st.remove(j)
        rng.shuffle(group)
        new_sum = 0.0
        for j in group:
            c, calls, sp = P.plan(P.ships[j], st.rects, K)
            st.set(j, c, calls, sp)
            st.add(j)
            new_sum += c
        delta = new_sum - old_sum
        if delta < -1e-9 or (T > 0 and rng.random() < math.exp(-max(0.0, delta) / T)):
            acc += 1
            cur += delta
            if cur < best[0] - 1e-9:
                imp += 1
                best = (cur, list(st.calls), list(st.speeds), list(st.cost))
                events.append((round(time.monotonic() - t_start, 3), cur))
        else:
            for j in group:
                st.remove(j)
            for j in group:
                st.set(j, *old[j])
                st.add(j)
    sol = build_solution(P, best[1], best[2])
    if log is not None:
        log.update({"version": VERSION, "first_arrival": first_arrival, "labels": K, "seed": seed, "ships": n,
                    "calls": sum(len(s.visits) for s in P.ships), "ports": len(inst.get("ports", [])),
                    "external": sum(len(lst) for lst in P.ext.values()), "speeds": len(inst.get("speeds_knots", [])),
                    "missing_travel_keys": P.missing_travel_keys, "initial": init, "best_internal": best[0],
                    "objective": sol["objective_value"], "iterations": it, "accepted": acc, "improved": imp,
                    "events": events[:3] + events[-12:] if len(events) > 15 else events,
                    "time_used_s": round(time.monotonic() - t_start, 3)})
    return sol


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def main(argv=None):
    t_start = time.monotonic()
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="martin-iradi2024")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--first-arrival", choices=("desc", "est"),
                    default=os.environ.get("MV2_BERTH_FIRST_ARRIVAL", "desc"))
    ap.add_argument("--labels", type=int, default=8)
    a = ap.parse_args(argv)
    with open(a.instance, encoding="utf-8") as f:
        inst = json.load(f)
    log = {} if os.environ.get("MV2_BERTH_LOG") == "1" else None
    sol = solve(inst, a.time_limit, a.seed, a.first_arrival, a.labels, t_start=t_start,
                on_first=lambda s: write_json(a.output, s), log=log)
    write_json(a.output, sol)
    if log is not None:
        write_json(a.output + ".log.json", log)
    return 0


if __name__ == "__main__":
    sys.exit(main())

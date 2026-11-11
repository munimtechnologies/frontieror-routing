"""Synthetic instances for bodur2017 (two-stage stochastic capacitated facility location, SCFLP).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

The FrontierOR page gives the instance schema but not the generator, and its public instances need a signed-in
account. These instances follow the schema exactly and the usual recipe for capacitated facility location
(Cornuejols, Sridharan and Thizy, EJOR 1991), which Bodur et al. (2016) built their stochastic CAP instances from:
- facilities and customers uniform in a square of side `box`; per-unit transport cost = Euclidean distance;
- mean demand U[5, 35]; raw capacity U[10, 160], rescaled so that total capacity = capacity_factor x total mean
  demand; opening cost U[0, 90] + U[100, 110] x sqrt(capacity);
- scenario demand = max(0, mean x (1 + f x N(0, 1))) with a per-customer std fraction f drawn from U[0.10, 0.20]
  ("normal") or U[0.30, 0.50] ("high"); equal probabilities.
The std fractions and the box sizes are our guesses, not the contest's. `box` sets the balance between opening and
transport costs: small boxes make opening costs dominate, large boxes make transport dominate.
"""
import math
import random

# name, facilities, customers, scenarios, capacity_factor, variance, box, seed, class
CASES = [
    ("s1", 10, 20, 10, 2.0, "normal", 10.0, 101, "S"),
    ("s2", 12, 25, 20, 1.5, "high", 2.0, 102, "S"),
    ("s3", 16, 30, 30, 3.0, "normal", 40.0, 103, "S"),
    ("s4", 10, 30, 40, 1.5, "high", 10.0, 104, "S"),
    ("s5", 14, 20, 25, 5.0, "high", 40.0, 105, "S"),
    ("s6", 16, 25, 15, 2.0, "normal", 2.0, 106, "S"),
    ("m1", 25, 50, 50, 2.0, "normal", 10.0, 201, "M"),
    ("m2", 25, 50, 100, 1.5, "high", 10.0, 202, "M"),
    ("m3", 50, 50, 50, 3.0, "normal", 2.0, 203, "M"),
    ("m4", 50, 50, 100, 2.0, "high", 40.0, 204, "M"),
    ("m5", 30, 60, 80, 5.0, "normal", 10.0, 205, "M"),
    ("m6", 40, 50, 60, 1.5, "normal", 40.0, 206, "M"),
    ("m7", 50, 50, 100, 3.0, "high", 10.0, 207, "M"),
    ("m8", 35, 70, 50, 2.0, "high", 2.0, 208, "M"),
    ("l1", 50, 100, 250, 2.0, "normal", 10.0, 301, "L"),
    ("l2", 50, 100, 500, 1.5, "high", 10.0, 302, "L"),
    ("l3", 75, 150, 200, 3.0, "normal", 40.0, 303, "L"),
    ("l4", 100, 200, 200, 2.0, "high", 10.0, 304, "L"),
    ("l5", 100, 100, 500, 5.0, "normal", 2.0, 305, "L"),
    ("l6", 60, 200, 300, 1.5, "high", 40.0, 306, "L"),
]


def make_instance(F, m, S, capacity_factor, variance, box, seed):
    rng = random.Random(seed)
    fxy = [(rng.uniform(0, box), rng.uniform(0, box)) for _ in range(F)]
    cxy = [(rng.uniform(0, box), rng.uniform(0, box)) for _ in range(m)]
    mu = [round(rng.uniform(5, 35), 2) for _ in range(m)]
    lo, hi = (0.10, 0.20) if variance == "normal" else (0.30, 0.50)
    sf = [round(rng.uniform(lo, hi), 3) for _ in range(m)]
    raw = [rng.uniform(10, 160) for _ in range(F)]
    k = capacity_factor * sum(mu) / sum(raw)
    cap = [round(r * k, 2) for r in raw]
    scenarios = []
    for s in range(S):
        d = [round(max(0.0, mu[j] * (1.0 + sf[j] * rng.gauss(0.0, 1.0))), 3) for j in range(m)]
        scenarios.append({"id": s, "probability": 1.0 / S, "demands": d})
    dmax = max(sum(sc["demands"]) for sc in scenarios)
    if sum(cap) < dmax * 1.05:  # keep the instance feasible with some room
        g = dmax * 1.05 / sum(cap)
        cap = [round(c * g + 0.01, 2) for c in cap]
    fixed = [round(rng.uniform(0, 90) + rng.uniform(100, 110) * math.sqrt(c), 2) for c in cap]
    costs = [[round(math.hypot(fx - cx, fy - cy), 4) for (cx, cy) in cxy] for (fx, fy) in fxy]
    return {
        "num_facilities": F,
        "num_customers": m,
        "num_scenarios": S,
        "capacity_factor": capacity_factor,
        "variance_level": variance,
        "facilities": [{"id": i, "opening_cost": fixed[i], "capacity": cap[i], "location_x": round(fxy[i][0], 4),
                        "location_y": round(fxy[i][1], 4)} for i in range(F)],
        "customers": [{"id": j, "deterministic_demand": mu[j], "demand_std_fraction": sf[j],
                       "location_x": round(cxy[j][0], 4), "location_y": round(cxy[j][1], 4)} for j in range(m)],
        "transportation_costs": costs,
        "scenarios": scenarios,
    }


def case_instance(row):
    name, F, m, S, cf, var, box, seed, cls = row
    return make_instance(F, m, S, cf, var, box, seed)

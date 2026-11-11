"""Synthetic barnhart2000 (ODIMCF) instances in the FrontierOR input format.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

No public Barnhart-Hane-Vance instances were found, so calibration uses deterministic synthetic networks:
- "grid": rows x cols lattice, arcs both ways between neighbours, plus a few diagonals;
- "geo": random points in the unit square, each joined both ways to its 3 nearest neighbours and to the next point
  in x order (so the network is strongly connected).
Demands are mostly small (1-10) with some medium (10-25) and a few large (25-50). Each commodity has a unit price of
5-50: revenue = demand x price. In "per_unit" instances artificial_arc_cost = price; in "total" instances
artificial_arc_cost = revenue, so both readings of the rejection penalty are exercised (see odimcf_check.py).
Capacities are set from the load of routing every commodity on a min-hop path, times a tightness factor and noise,
so that some commodities have to be rejected or rerouted. Standard library only; the same arguments always give
the same instance.
"""
import json
import math
import random
import sys


def _grid(rng, rows, cols):
    nodes = [i * cols + j + 1 for i in range(rows) for j in range(cols)]
    pairs = set()
    for i in range(rows):
        for j in range(cols):
            u = i * cols + j + 1
            if j + 1 < cols:
                pairs.add((u, u + 1))
            if i + 1 < rows:
                pairs.add((u, u + cols))
            if i + 1 < rows and j + 1 < cols and rng.random() < 0.1:
                pairs.add((u, u + cols + 1))
    return nodes, pairs


def _geo(rng, n):
    pts = [(rng.random(), rng.random()) for _ in range(n)]
    nodes = list(range(1, n + 1))
    pairs = set()
    for i in range(n):
        near = sorted((math.dist(pts[i], pts[j]), j) for j in range(n) if j != i)[:3]
        for _, j in near:
            pairs.add((min(i, j) + 1, max(i, j) + 1))
    byx = sorted(range(n), key=lambda i: pts[i])
    for a, b in zip(byx, byx[1:]):
        pairs.add((min(a, b) + 1, max(a, b) + 1))
    return nodes, pairs


def _hops(adj, o):
    prev = {o: None}
    q = [o]
    i = 0
    while i < len(q):
        u = q[i]
        i += 1
        for a, v in adj.get(u, []):
            if v not in prev:
                prev[v] = (u, a)
                q.append(v)
    return prev


def generate(seed, graph, size, K, mode="per_unit", costs=False, tight=0.6):
    rng = random.Random(seed)
    if graph == "grid":
        nodes, pairs = _grid(rng, size[0], size[1])
    elif graph == "geo":
        nodes, pairs = _geo(rng, size)
    else:
        raise ValueError(graph)
    arcs = []
    for u, v in sorted(pairs):
        for a, b in ((u, v), (v, u)):
            arcs.append({"arc_id": len(arcs) + 1, "from_node": a, "to_node": b, "capacity": 0,
                         "cost": rng.randint(0, 3) if costs else 0})
    adj = {}
    for a in arcs:
        adj.setdefault(a["from_node"], []).append((a["arc_id"] - 1, a["to_node"]))
    n = len(nodes)
    K = min(K, n * (n - 1))
    odset = set()
    coms = []
    while len(coms) < K:
        o, d = rng.sample(nodes, 2)
        if (o, d) in odset:
            continue
        odset.add((o, d))
        r = rng.random()
        dem = rng.randint(1, 10) if r < 0.7 else (rng.randint(10, 25) if r < 0.95 else rng.randint(25, 50))
        price = rng.randint(5, 50)
        rev = dem * price
        coms.append({"commodity_id": len(coms) + 1, "origin": o, "destination": d, "demand": dem, "revenue": rev,
                     "artificial_arc_cost": price if mode == "per_unit" else rev})
    load = [0] * len(arcs)
    trees = {}
    for c in coms:
        o = c["origin"]
        if o not in trees:
            trees[o] = _hops(adj, o)
        prev = trees[o]
        v = c["destination"]
        while prev.get(v) is not None:
            u, a = prev[v]
            load[a] += c["demand"]
            v = u
    for i, a in enumerate(arcs):
        if load[i] > 0:
            a["capacity"] = max(10, int(round(load[i] * tight * rng.uniform(0.6, 1.3))))
        else:
            a["capacity"] = rng.randint(10, 40)
    return {"network": {"num_nodes": n, "num_arcs": len(arcs), "nodes": nodes, "arcs": arcs},
            "commodities": {"num_commodities": len(coms), "commodity_list": coms},
            "objective": "minimize"}


def tiny(seed):
    """5 nodes with ids 10..50, 8-10 random arcs including one parallel pair, 3-4 commodities, tight capacities."""
    rng = random.Random(1000 + seed)
    nodes = [10, 20, 30, 40, 50]
    arcs = []
    pairs = set()
    while len(pairs) < rng.randint(7, 9):
        u, v = rng.sample(nodes, 2)
        pairs.add((u, v))
    for u, v in sorted(pairs):
        arcs.append({"arc_id": 100 + len(arcs), "from_node": u, "to_node": v, "capacity": rng.randint(2, 8),
                     "cost": rng.randint(0, 1)})
    u, v = sorted(pairs)[0]
    arcs.append({"arc_id": 100 + len(arcs), "from_node": u, "to_node": v, "capacity": rng.randint(2, 8),
                 "cost": rng.randint(0, 1)})
    coms = []
    mode = "per_unit" if seed % 2 == 0 else "total"
    for i in range(rng.randint(3, 4)):
        o, d = rng.sample(nodes, 2)
        dem = rng.randint(1, 5)
        price = rng.randint(2, 9)
        coms.append({"commodity_id": 7 + 3 * i, "origin": o, "destination": d, "demand": dem,
                     "revenue": dem * price, "artificial_arc_cost": price if mode == "per_unit" else dem * price})
    return {"network": {"num_nodes": 5, "num_arcs": len(arcs), "nodes": nodes, "arcs": arcs},
            "commodities": {"num_commodities": len(coms), "commodity_list": coms}, "objective": "minimize"}


# The pre-registered calibration set (see ../NOTES.md / PREREG.md). Do not edit after the job is filed.
CASES = [
    # name, seed, graph, size, K, mode, costs, tight, class
    ("s1-grid4x4", 11, "grid", (4, 4), 20, "per_unit", False, 0.6, "S"),
    ("s2-grid4x5", 12, "grid", (4, 5), 30, "per_unit", False, 0.5, "S"),
    ("s3-geo18", 13, "geo", 18, 25, "per_unit", False, 0.6, "S"),
    ("s4-geo20c", 14, "geo", 20, 35, "per_unit", True, 0.6, "S"),
    ("s5-grid5x5t", 15, "grid", (5, 5), 40, "total", False, 0.6, "S"),
    ("s6-geo22t", 16, "geo", 22, 30, "total", False, 0.5, "S"),
    ("m1-grid6x6", 21, "grid", (6, 6), 80, "per_unit", False, 0.6, "M"),
    ("m2-grid7x7", 22, "grid", (7, 7), 120, "per_unit", False, 0.6, "M"),
    ("m3-geo40", 23, "geo", 40, 100, "per_unit", False, 0.6, "M"),
    ("m4-geo50", 24, "geo", 50, 150, "per_unit", False, 0.5, "M"),
    ("m5-grid6x8c", 25, "grid", (6, 8), 100, "per_unit", True, 0.6, "M"),
    ("m6-geo45ct", 26, "geo", 45, 120, "total", True, 0.6, "M"),
    ("m7-grid8x8", 27, "grid", (8, 8), 150, "per_unit", False, 0.7, "M"),
    ("m8-geo60", 28, "geo", 60, 150, "per_unit", False, 0.6, "M"),
    ("l1-grid10x10", 31, "grid", (10, 10), 400, "per_unit", False, 0.6, "L"),
    ("l2-grid12x12", 32, "grid", (12, 12), 600, "per_unit", False, 0.6, "L"),
    ("l3-geo100", 33, "geo", 100, 500, "per_unit", False, 0.6, "L"),
    ("l4-geo150t", 34, "geo", 150, 800, "total", False, 0.6, "L"),
    ("l5-grid15x15", 35, "grid", (15, 15), 1000, "per_unit", False, 0.6, "L"),
    ("l6-geo200c", 36, "geo", 200, 1200, "per_unit", True, 0.6, "L"),
]


def case_instance(row):
    name, seed, graph, size, K, mode, costs, tight, cls = row
    return generate(seed, graph, size, K, mode, costs, tight)


if __name__ == "__main__":
    for row in CASES:
        if len(sys.argv) < 2 or row[0] in sys.argv[1:]:
            inst = case_instance(row)
            print(row[0], inst["network"]["num_nodes"], inst["network"]["num_arcs"],
                  inst["commodities"]["num_commodities"])
            json.dumps(inst)

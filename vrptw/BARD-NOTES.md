# vrptw/bard2002: fewest vehicles under the official checker, v0.1.0

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; this text CC BY 4.0.

Pre-registered on 2026-11-11 at about 04:30 UTC, before the job `froc-bard-real-v1` ran. The guesses below will be graded exactly as written, failures included.

## What the official files say

The FrontierOR task `bard2002` is a VRPTW (Bard, Kontoravdis and Yu, Transportation Science 36(2), 2002). We read its `problem_description.txt`, `mathematical_formulation.md`, `gurobi_code.py` and `feasibility_check.py` in the public benchmark (Hugging Face `frontieror/FrontierOR`, CC BY 4.0). Here is what they say:

- **Objective:** the number of routes leaving the depot. The output must also give `num_vehicles` (= number of routes), `total_distance` (route distance rounded to 0.1, within 0.05), and departure times and loads for every customer.
- **Travel time:** the distance (the instance's `distance_matrix`, else the Euclidean distance truncated to one decimal), plus the origin's service time unless the instance flag `travel_time_includes_service_time` is true. A comment in `gurobi_code.py` says the flag is true in the instances while the matrix "appears to be raw Euclidean". If so, service times play no part in the problem the checker and the reference solve. G7 tests this.
- **Times:** `t_i` lies in `[a_i, b_i]`, and `t_j >= t_i + tau_ij` on every customer-to-customer arc, so `t` acts as a service start time.
- **What the checker does not test:** the time from the depot to a route's first customer, and the return to the depot by its due date. The Gurobi model only drops depot arcs that are impossible on their own. Our solver does not use this gap: every route leaves the depot no earlier than its ready time and is back by its due date.
- **Loads:** constraint (5) reads `y_j >= y_i + q_j - Q_j (1 - x_ij)` with `Q_j = Q - q_j`, and the checker tests it for every ordered pair of customers. When `x_ij = 0` this becomes `y_j >= y_i + 2 q_j - Q`. A valid big-M here would be `Q`, so these rows cut off loads that fit in the vehicle. Following the inequalities around a cycle shows that a route (c_1, ..., c_k) only admits loads if `q_{c_m} + (q_{c_m} + ... + q_{c_k}) <= Q` for every m < k. In words: the route's load plus its first customer's demand must fit, and likewise for every later starting point. Example: two customers of demand 5 cannot share a vehicle of capacity 14. The probe in G4 tests this with the official checker itself. The Gurobi reference model has the same rows, so its solutions obey the same rule. Our solver enforces the rule and writes the least load witness, found by longest-path relaxation, because plain cumulative loads can fail the cross-route pairs.

We have not checked the 2002 paper's own definition of `Q_j`. This note is about the benchmark's checker and formulation as published.

## The solver (bard2002/solve.py)

1. **Lower bounds:** capacity (`ceil(total demand / Q)`) and a greedy clique of customers that cannot share a route. Only the capacity bound may stop the search early; the clique bound uses pairwise tests on truncated distances, so it is reported, not trusted.
2. **Construction:** cheapest feasible insertion.
3. **Route elimination with an ejection pool,** a simplified version of Nagata and Bräysy (2009): remove a short route, then reinsert its customers one by one. When a customer fits nowhere, eject one or two customers chosen by failure counters, then make random feasible relocations.
4. **PyVRP (optional; pip package pyvrp, MIT):** asked for one vehicle fewer than the incumbent, on a conservatively rounded integer copy (travel times rounded up, windows rounded inwards, service already inside the travel times). Each result is re-checked exactly, and repaired with the ejection pool if it breaks the load rule.
5. **Final check:** every solution offered is checked against the checker's constraints (2) to (7) with a tolerance tighter than the checker's 1e-5.

**Files:** `bard_check.py` is an independent re-implementation of the official checker, plus a strict depot-timing check and load statistics. `bard_real.py` runs the six public instances with the official checker, writes the instance facts, and runs the probe. `test_bard.py` holds the tests, including a brute force on 6-customer instances and the official checker on solver outputs.

## Pre-registered guesses (probability that each holds)

| id | guess | p |
|---|---|---|
| G1 | The test step passes (`python vrptw/test_bard.py -v`, with the official checker available) | 0.65 |
| G2 | The official checker accepts our solution on all 6 public instances, each written within 60 s | 0.75 |
| G3 | Our checker and the official checker agree on all 12 verdicts (our 6 solutions and Gurobi's 6) | 0.80 |
| G4 | Probe: the official checker rejects the one-route solution (demands 5 + 5) for Q = 10, 12 and 14 and accepts it for Q = 15 and 16; the two-route solution is accepted for every Q | 0.90 |
| G5 | On at least 3 of the 5 large instances we use strictly fewer vehicles than the stored Gurobi solution | 0.50 |
| G6 | Mean contest score (Gurobi vehicles / our vehicles, capped at 2) on the 5 large instances is >= 1.0 | 0.65 |
| G7 | `travel_time_includes_service_time` is true in all 6 instances, and every instance that has a `distance_matrix` has it equal to the truncated Euclidean distance (service time not included) | 0.70 |
| G8 | At least one route in the stored Gurobi solutions could not be driven from the depot and back in time (`bard_check.strict` fails) | 0.35 |

All eight will be graded in `bard-score-v1.md`. The raw rows will be in `bard-real/results.md`, `extras.md` and `probe.md`.

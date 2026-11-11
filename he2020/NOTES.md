# he2020: VRPTW with convex node costs (VRPTW-CNC). Solver v0.1.0 notes and pre-registered guesses

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Code Apache-2.0; text CC BY 4.0.
Written 2026-11-11 (about 07:00 UTC), before any he2020 run of ours exists.

## The task, as the public benchmark defines it

FrontierOR task `he2020` (Hugging Face [frontieror/FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR), CC BY 4.0). The source paper is He, Irnich and Song, "Branch-and-Cut-and-Price for the Vehicle Routing Problem with Time Windows and Convex Node Costs", Transportation Science (2019). We read four files: `problem_description.txt`, `mathematical_formulation.md`, `gurobi_code.py` and `feasibility_check.py`.

- **Vertices:** 0 is the start depot, 1..n are customers, and n+1 is the end depot. `distance_matrix` gives both travel time and routing cost: Euclidean distances rounded to one decimal.
- **Routes:** each route is `[0, c1, ..., cm, n+1]`. At most `num_vehicles` routes are allowed, and each route's demand must fit in `vehicle_capacity`.
- **Schedule:** `schedule[c]` is the time service starts at c. It must lie in c's window, and each stop must start no earlier than the previous start plus that stop's service time plus the travel time. The checker sets the depot departure as late as possible and the return as early as possible, so the first leg and the return leg are both timed.
- **Objective:** total routing cost over all arcs, plus the sum over customers of rho × (t_c − preferred_time_c)². The preferred time is the window midpoint.

## A difference between the checker and the Gurobi model (from reading the code; not yet run)

- `gurobi_code.py` optimises with `rho = instance["inconvenience_cost_function"]["rho"]`. The instance schema lists only that key.
- `feasibility_check.py` recomputes the objective for its consistency test (constraint 7: the reported `objective_value` must equal the recomputed cost within max(1e-6, 5e-6 × |cost|)). For that it uses `rho = instance.get("inconvenience_cost_factor_rho", 0.0)`, a top-level key the schema does not mention, with a default of 0.

If the instances lack the top-level key, the checker scores every solution as if rho were 0. A solution that reports its true cost, inconvenience included, would then fail constraint 7. A solution that reports routing cost alone would pass, whatever its schedule costs. We have not yet seen an instance file, because Hugging Face serves them through a redirect our reader cannot follow. The queued run settles the question, and the stored `gurobi_feasi_result` files (all "feasible") are part of the evidence.

**Our solver does not use this gap.** It optimises the true cost with the gurobi_code.py rho and reports that cost. If the gap is real, we report it to the benchmark's maintainers.

## Method (v0.1.0)

- **Schedule for a fixed route:** substitute u_k = t_k − c_k, where c_k is the fixed travel-plus-service offset from the route's first customer. The best service times are then an isotonic regression of y_k = preferred_k − c_k with box bounds [e_k − c_k, l_k − c_k]. The first stop's bound also includes the depot leg, and the last stop's bound includes the return. Pool-adjacent-violators solves this exactly: each block takes the value clip(mean, max lower bound, min upper bound), and PAVA is exact for separable convex costs (Ahuja and Orlin 2001). Each schedule is then verified. Tests compare it with two hand-solved cases and with SciPy's SLSQP.
- **Starting solutions:** our own parallel cheapest insertion on the full cost, within the fleet limit. If PyVRP is installed, we also solve an exact integer copy (times × 10) for distance with the fleet limit.
- **Improvement:** granular local search on the full cost (relocate, swap, two 2-opt* variants, and opening a route while the fleet allows it). After that, ruin-and-recreate (related removal, then cheapest full-cost reinsertion) with a shrinking acceptance threshold until the time limit.
- **Checks:** every candidate is re-checked (cover, fleet, capacity, windows, precedence, objective) before it is written.

## The queued run: `froc-he2020-real-v1`

The six public instances (tiny + large_1..5), 60 s each, are run the contest way by `he2020_real.py`. Each solution is checked by our checker and by the official one. The run also writes `rho.md`, which gives each instance's top-level keys and both rho values, plus both checkers' verdicts on the stored Gurobi solution and on ours. Each verdict is given for the instance as published and for a copy with the top-level key set to the gurobi_code.py rho. A probe runs our solution with `objective_value` set to its routing cost alone. That probe only tests the checker; it is never an entry.

## Guesses (probabilities fixed now)

| id | guess | p |
|---|---|---|
| H1 | Our checker accepts our solution (feasible, stated objective = recomputed within 1e-6 relative) on 6/6 instances within 60 s | 0.85 |
| H2 | None of the 6 instances has a top-level `inconvenience_cost_factor_rho` key | 0.60 |
| H3 | With that key set to the gurobi_code.py rho, the official checker accepts our solution on 6/6 | 0.85 |
| H4 | If H2 holds: on the instances as published, the official checker rejects our solution on at least 5 of 6, each time for constraint 7 only | 0.65 |
| H5 | On the instances as published, the official checker still says "feasible" for all 6 stored Gurobi solutions, as the stored gurobi_feasi_result files do | 0.55 |
| H6 | Our total cost (gurobi_code.py rho) is lower than the stored Gurobi solution's recomputed total on at least 2 of the 5 large instances | 0.60 |
| H7 | Every customer's preferred_time equals its window midpoint within 1e-9, on all 6 instances | 0.90 |

H2 and H5 can both hold only if every stored Gurobi solution's inconvenience share is below the checker's 5e-6 tolerance. The run reports that share.

# roberti2018 (two-echelon VRP with grouping constraints) solver v0.1.0: pre-registered guesses

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; this text CC BY 4.0.

Written on 2026-11-16 at about 03:00 UTC, before the job `froc-roberti2018-v1` ran. At that point nobody had seen a public instance file of this task, and the code had never been run (not even its tests). The job runs the tests for the first time. Its first step waits until this file is public in this repository and records whether it was (`wait_prereg.py`). The guesses will be graded as written, failures included, in `score-v1.md`.

## The task

`roberti2018` in the public FrontierOR benchmark (Hugging Face `frontieror/FrontierOR`, CC BY 4.0) is the two-echelon capacitated vehicle routing problem with grouping constraints (2E-CVRPGC; Liu, Luo, Qin and Lim, European Journal of Operational Research 266(2), 2018). It is #41 of the benchmark's 50-task hard set. Its stored Gurobi reference stopped at the one-hour limit (single thread) on all 5 large instances (`hard_selection_inputs_180.csv`: median 3600.47 s). Until now MV2 had no answer for this task.

- Trucks (at most T1, capacity Q1) leave the depot, visit satellites and deliver freight. A satellite may be split between trucks, and a truck visits a satellite at most once.
- Each satellite has a throughput capacity, a limit on its small vehicles and a handling cost per unit.
- Small vehicles (capacity Q2, at most T2 in all) serve every customer exactly once from a satellite and return to it. All customers in a group must be served from the same satellite.
- Cost = truck travel + handling + small-vehicle travel, with Euclidean distances and no rounding.

The checker mirrors the arc-flow model. Our `verify()` copies its rules route by route, plus a few that are stricter (no empty routes, distinct truck ids in 0..T1-1). It runs with tighter tolerances on our own answers, and with the checker's own tolerances when judging Gurobi's answers.

From the variable and constraint counts in `hard_selection_inputs_180.csv` (6,600 variables, 3,550 integer, 21,345 constraints, averaged over the 5 large instances), we infer about 5 satellites, about 50 customers and about 10 trucks. Nobody has looked at the files, so this is a guess (G12).

## The solver (solve.py, standard library only)

1. **First echelon, priced exactly within one family.** For a vector of satellite loads, every satellite subset is costed as a block:
   - one truck tour if its load fits Q1;
   - otherwise, the block's optimal tour is cut into full-truck segments, trying every rotation and both directions.

   A subset DP then picks the cheapest partition into blocks. Truck tours are exact (Held-Karp) up to 8 satellites. With 1 or 2 loaded satellites, and when the truck limit T1 does not bind, this is provably the optimal split-delivery plan (with two satellites, the optimum uses na + nb - N shared tours and direct trips otherwise, where na, nb and N are the truck counts each satellite and both together need). The tests check it against brute force. With 3 or more it is a heuristic, and the tests report its worst gap to brute force.
2. **Second echelon, simulated annealing.** The search covers both the group -> satellite assignment and the routes. Penalties on vehicle capacity, satellite throughput and the T2 fleet adapt, and are capped at 50 times their start value before the final polish. Moves:
   - relocate a customer (best or random position), swap, 2-opt, 2-opt*;
   - move a group to another satellite (the best of all satellites, or a random one), or swap two groups' satellites;
   - ruin and recreate nearby customers, or nearby groups.

   Every move that changes satellite loads is priced with the exact handling cost and the cached first-echelon DP.
3. **Output.** Only answers that pass `verify()` are written, atomically. A forked child searches with a second seed. The deadline is min(0.9 T, T - 3).

`roberti_real.py` runs the solver the contest way on the tiny instance and the 5 large public instances, under the official checker:
- variant v010-60s: seed 1 at 60 s;
- variant v010-10s: seed 1 at 10 s;
- variant v010-60s-seed7: seed 7 at 60 s.

Reference = the stored Gurobi objective. Score = min(2, Gurobi / ours).

## Guesses (probability that each holds)

| id | guess | p |
|---|---|---|
| G1 | Every test in `test_roberti2018.py` passes with the official checker available. These include optimality against brute force on 3 tiny instances, and verdict agreement with the official checker on mutated solutions | 0.55 |
| G2 | v010-60s: the official checker accepts all 6 answers, each written within the time limit | 0.85 |
| G3 | No disagreement anywhere in the job between our checker-tolerance `verify()` and the official checker, on our answers or on Gurobi's stored ones | 0.80 |
| G4 | v010-60s: mean score on the 5 large instances >= 1.0 | 0.80 |
| G5 | v010-60s: mean score on the 5 large instances >= 1.10 | 0.55 |
| G6 | v010-60s: mean score on the 5 large instances >= 1.25 | 0.25 |
| G7 | v010-60s: strictly better than Gurobi's stored answer on at least 4 of the 5 large instances | 0.70 |
| G8 | v010-60s on the tiny instance: within 0.1% of Gurobi or better | 0.85 |
| G9 | Mean large score of v010-10s >= 0.97 x that of v010-60s | 0.75 |
| G10 | Mean large scores of v010-60s-seed7 and v010-60s differ by at most 1% | 0.70 |
| G11 | Gurobi's stored `mip_gap` is at least 10% on at least 3 of the 5 large instances | 0.60 |
| G12 | Every large instance has 4 to 6 satellites and 40 to 60 customers | 0.60 |
| G13 | In v010-60s, at least one large answer splits a satellite's freight between two trucks | 0.40 |

## Decision rules

- **G2 or G3 fails:** fix the rule we got wrong, re-test, and rerun as v0.1.1 before anything else.
- **G4 holds and G5 holds:** roberti2018 joins the contest folder's hand solvers. The two-echelon block-DP pricing becomes the template for other two-level tasks in the hard set.
- **G4 fails with all answers accepted:** compare the three cost parts (`parts` in summary.json) with Gurobi's. If we lose on the first echelon, replace the block DP with an exact split-delivery search for up to 5 satellites. If we lose on the second, add exact route polishing (2-opt + or-opt to convergence) to every new best.
- **G9 fails:** the 10 s class needs a faster start (construction plus a short descent before annealing).
- **G10 fails:** too much seed variance. Run independent seeds on both CPUs and keep the best, or lengthen the polish.
- **G1 fails only on brute-force optimality:** report the gap, and in v0.1.1 add an exact assignment step for tiny instances (enumerate group -> satellite choices when there are at most 4^4 of them).

MV2, Munim, Inc., mv2@munimtech.com

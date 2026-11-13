# pessoa2021 (robust CVRP) solver v0.1.0: predictions, written before the first run

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-13, before job `froc-pessoa2021-v1` has run. Nobody has seen any output of this solver on the public
instances. Results will be graded here, in a separate score file, whichever way they go.

## Why this task

FrontierOR task `pessoa2021` is the robust capacitated vehicle routing problem with a cardinality budget (Pessoa,
Poss, Sadykov and Vanderbeck, Operations Research 2021): exactly m routes, and each route must stay within capacity
for every demand scenario in which at most Gamma customers deviate fully from their nominal demand.

- The benchmark's hard-selection file (`metadata/hardset/hard_selection_inputs_180.csv`) lists it as
  "timeout or non-optimal" on 3 of 5 large instances (0.6), with median Gurobi time 3,600.65 s, mean 2,168.3 s and
  maximum 3,601.4 s. So the other two large instances took about 40 s together.
- Its Gurobi reference (`gurobi_code.py`) is a two-index arc model with MTZ constraints on nominal demand plus lazy
  robust capacity cuts, run on 1 thread.
- MV2's generic engine gpshim 0.2 (the reference model on free solvers) gave **no answer at all** on large_1
  within 60 s (census `froc-gpshim02-v1`, 2026-11-12), because the model needs a Gurobi callback.

## What the solver does

Standard library only. Slack induction by string removals (SISR, Christiaens & Vanden Berghe 2020), written from
the paper's description, with simulated annealing on a clock schedule. Capacity is exact and incremental: per route
we hold the nominal sum, the sum of its Gamma largest deviations and the Gamma-th largest deviation, so the
worst-case demand after inserting a customer costs O(1) to price. Over-capacity units and empty routes are
penalised far above any travel cost. New bests are polished route by route (exact 2-opt and relocation), checked by
`verify()` (the official checker's rules) and written atomically. Two processes (a forked second search with
another seed). Stops at min(0.9 T, T - 3) s.

## Inferred instance sizes (not yet seen)

The reference model has n^2 + 2n variables (n^2 + n binary) and n^2 + n + 2 constraints for n customers. The
hard-selection averages are exactly 6,560 variables, 6,480 integer variables and 6,482 constraints, which is
n = 80 with zero spread: mean n = 80 and mean n^2 = 6,400. So all five large instances should have 80 customers,
even though their files differ in size (about 61 kB for large_1, 3, 5 and 29 kB for large_2, 4); the difference
would then be number format (for example decimal distances), not size.

## Predictions (probabilities are ours, stated now)

| # | prediction | p |
|---|---|---|
| R1 | All unit tests pass before the run (tests-pre.txt ends `exit=0`). | 0.80 |
| R2 | At 60 s the official checker accepts all 6 answers (tiny + 5 large). | 0.90 |
| R3 | At 10 s the official checker accepts all 6 answers. | 0.85 |
| R4 | On the two large instances Gurobi solved in time, v010-60s is within 1% of Gurobi's stored objective on both. | 0.80 |
| R5 | On the three large instances where Gurobi hit its time limit, v010-60s is strictly better than Gurobi's stored objective on at least two. | 0.70 |
| R6 | v010-60s mean contest score over the 5 large instances is at least 1.00. | 0.60 |
| R7 | v010-300s mean large score is at least the v010-60s mean large score. | 0.85 |
| R8 | Our verify() and the official checker never disagree (0 disagreements over all variants, our answers and Gurobi's). | 0.90 |
| R9 | All five large instances have exactly 80 customers. | 0.75 |
| R10 | Every instance has a symmetric distance matrix. | 0.85 |
| R11 | Every stored Gurobi answer has exactly m non-empty routes. | 0.95 |
| R12 | Checker gap probe (`empty_route_probe` in summary.json): on a synthetic 6-customer, 3-vehicle instance the official checker accepts both an answer with three non-empty routes (objective 160) and one that puts every customer on one route and pads with two empty routes (objective 102). | 0.90 |

R12 is about the checker, not the solver. The problem text asks for one route per vehicle and the Gurobi model sends
exactly m vehicles from the depot, each to a customer, but `feasibility_check.py` counts `len(routes)` and skips the
capacity test for a route with no customers (lines 307-310), and an empty route costs `dist[0][0]` = 0. If R12 holds,
an entry could undercut Gurobi by padding with empty routes. MV2's solver never does that (it penalises empty routes
whenever n >= m), and the gap goes to the benchmark maintainers rather than being used.

Scoring rule used: contest score = min(2, Gurobi's stored objective / ours), 0 for no answer or a rejected one.
Brier score over R1-R12 will be reported.

## Limits

Public instances only; the challenge scores private instances. Tiny is not used for any prediction except R2/R3.
One run per variant, so seed luck is only checked by the v010-seed7-60s variant.

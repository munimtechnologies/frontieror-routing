# vrptw/: the VRPTW family of the FrontierOR benchmark, starting with pecin2017

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; this text CC BY 4.0.

Written 2026-11-11 ~01:30 UTC, before the job `froc-pecin-real-v1` was filed. The guesses below are graded as
written, including any that fail.

## Why this family first

Of the 180 tasks in the FrontierOR benchmark (Hugging Face `frontieror/FrontierOR`, CC BY 4.0), about 37 are
vehicle-routing problems, and 17 of them are in the benchmark's 50-task hard set. Eleven are VRPTW variants (bard2002,
dayarian2019, desaulniers2010, he2020, luo2017, muter2010, pecin2017, reinhardt2016, rothenbacher2018,
rothenbacher2019, spliet2015). They share a core (capacity, time windows, Euclidean travel) but each has its own
input format and rules: pecin2017 starts service at max(open, arrival) and charges distance only, bard2002's windows
are on departure and its objective is hierarchical, he2020 adds a cost for starting away from a preferred time. So the
plan is one engine with a thin, separately checked adapter per task.

## pecin2017 solver v0.1.0 (pecin2017/solve.py)

Rules read from the task's public problem description and official `feasibility_check.py`: one depot split into a
source (id 0) and a sink (id n_nodes-1); travel cost = travel time = exact Euclidean distance; service start
T_j = max(open_j, T_i + service_i + d_ij); T_j <= close_j at every node including the sink; load <= capacity; any
number of routes; minimise total distance.

1. One route per customer, written at once.
2. Cheapest feasible insertion.
3. PyVRP 0.14 (MIT) iterated local search on an integer copy scaled by 1,000 with conservative rounding (travel and
   service times and window openings rounded up, window closings rounded down), so any schedule PyVRP accepts is
   feasible on the float data; every route is re-checked exactly before it is kept, and the objective is always
   recomputed in floating point.

`pecin_check.py` is an independent checker written from the official rules. `pecin_real.py` runs the solver on the
six public instances through `kit/frontieror_real.py` (a general runner: contest-style subprocess runs, the official
checker on every solution, the Gurobi solution as the reference and re-checked by both checkers).

## Guesses for froc-pecin-real-v1 (written before the job)

We have not seen the instances (about 41 kB each for the large ones) or Gurobi's run logs (only the tiny one has a
log, so Gurobi may have stopped on a time limit on the large ones).

| id | guess | p |
|---|---|---|
| V1 | The unit test step passes (`python vrptw/test_pecin.py -v`) | 0.70 |
| V2 | The official checker finds all 6 of our solutions feasible | 0.85 |
| V3 | Our checker and the official one agree on all 12 solutions (6 ours + 6 Gurobi) | 0.80 |
| V4 | On the tiny instance we are within 0.01% of the Gurobi objective, or better | 0.85 |
| V5 | Mean contest score over the 5 large instances is at least 1.0 (as good as Gurobi on average) | 0.60 |
| V6 | At least 3 of the 5 large instances strictly better than Gurobi | 0.50 |

MV2, Munim, Inc., mv2@munimtech.com

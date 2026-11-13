# alba2013 (double TSP with multiple stacks) solver v0.1.0: predictions, written before the first run

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-13, before job `froc-alba2013-v1` has run. Nobody has seen any output of this solver on the public
instances. Results will be graded here, in a separate score file, whichever way they go.

## Why this task

FrontierOR task `alba2013` is the double traveling salesman problem with multiple stacks (DTSPMS; Alba Martinez,
Cordeau, Dell'Amico and Iori, INFORMS Journal on Computing 2013): one vehicle picks up n unit items on a tour of a
pickup region, then delivers them on a tour of a separate delivery region; its s stacks of height l are
last-in-first-out. Minimise the two tours' total length.

- The benchmark's hard-selection file lists 0 of 5 large instances as "timeout or non-optimal": Gurobi proved them all
  optimal, but slowly (median 499.9 s, mean 783.2 s, maximum 2,511.7 s on 1 thread). The best possible contest score
  is 1.0 per instance; the point is **coverage**.
- Its Gurobi reference separates subtour and infeasible-path cuts in a callback. MV2's generic engine gpshim 0.2 gave
  **no answer** on large_1 within 60 s (census `froc-gpshim02-v1`, 2026-11-12). Today a large alba2013 instance
  scores 0 for MV2.

## What the solver does

Standard library only. It searches over loading plans (which items go in which stack, bottom to top). For a fixed
plan, the cheapest pickup tour (load every stack bottom to top, interleaving freely) and the cheapest delivery tour
(unload every stack top to bottom) are each found exactly by a dynamic program over (items taken from each stack,
stack of the last item). Every feasible answer has a loading plan, so nothing is lost, and every answer is
load-feasible by construction. Simulated annealing over plans (relocate, swap, block move, exchange stack tops) with a
plan-cost cache and restarts; starts from nearest-neighbour + 2-opt tours of either region dealt into the stacks. New
bests are checked by `verify()` (the official checker's rules, including its LIFO backtracking) and written
atomically. A forked second search uses another seed. Stops at min(0.9 T, T - 3) s.

`test_alba2013.py` checks the dynamic program against every interleaving, and the whole solver against a brute force
over every pair of tours (judged by the checker's LIFO rule) on small instances.

## Inferred instance size (not yet seen)

The reference model has one binary arc variable per ordered pair of distinct vertices in each region:
2 n (n + 1) variables. The hard-selection average is exactly 840 variables, all integer, which is n = 20
(2 x 20 x 21 = 840). If the five large instances share a size, each has 20 requests.

## A checker reading to probe

`feasibility_check.py` takes the visiting order as the listed tour with vertex 0 removed, without rotating the list
to start at the depot. A tour listed from another vertex is the same cycle (same cost, accepted by the degree and
subtour checks) but its LIFO test then runs on an order the vehicle does not drive. `rotation_probe` in summary.json
tests this on a synthetic instance (one stack, two items, pickup 0-1-2): the delivery cycle 0-1-2-0 delivers item 1
first, which LIFO forbids. MV2's solver always lists both tours from the depot and its strict `verify()` rejects other
listings; the gap goes to the benchmark maintainers rather than being used. The reference solutions start at 0.

## Predictions (probabilities are ours, stated now)

| # | prediction | p |
|---|---|---|
| A1 | All unit tests pass before the run (tests-pre.txt ends `exit=0`). | 0.80 |
| A2 | At 60 s the official checker accepts all 6 answers (tiny + 5 large). | 0.90 |
| A3 | At 10 s the official checker accepts all 6 answers. | 0.85 |
| A4 | v010-60s mean contest score over the 5 large instances is at least 0.99. | 0.75 |
| A5 | v010-60s matches Gurobi's stored (proven optimal) objective exactly on at least 3 of the 5 large instances. | 0.65 |
| A6 | v010-10s mean large score is at least 0.97. | 0.75 |
| A7 | No answer of ours, in any variant, beats Gurobi's stored objective by more than 1e-6 (Gurobi proved optimality; a "win" would mean a modelling or checking difference, to be investigated, not claimed). | 0.95 |
| A8 | Our strict verify() and the official checker never disagree (0 disagreements over all variants, our answers and Gurobi's). | 0.85 |
| A9 | Rotation probe: the official checker rejects delivery [0, 1, 2], ACCEPTS the same cycle listed as [2, 0, 1], and accepts the LIFO order [0, 2, 1]. | 0.85 |
| A10 | Every large instance has n = 20. | 0.75 |
| A11 | On every instance, request i is picked up at pickup vertex i and delivered at delivery vertex i (what the checker and the reference model assume). | 0.90 |
| A12 | tests.txt (run with the official checker available) ends `exit=0` and the agreement test ran (not skipped). | 0.75 |

Scoring rule used: contest score = min(2, Gurobi's stored objective / ours), 0 for no answer or a rejected one.
Brier score over A1-A12 will be reported.

## Limits

Public instances only; the challenge scores private instances. The task's contest time class is not known to us,
so 10 s and 60 s are both run. One run per variant.

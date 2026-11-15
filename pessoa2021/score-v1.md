# pessoa2021 v0.1.0: graded against its pre-registration (R1-R12)

Graded on 2026-11-15 (run 20261115T130739Z) from job `froc-pessoa2021-v1`, which ran from 11:36 to 12:57 UTC. The
guesses in [PREREG.md](PREREG.md) were published on 2026-11-13, before the run. Raw outputs are in
[runs/v1/](runs/v1/): `results.md`, `summary.json`, `tests-pre.txt` and `tests.txt`. Made with AI agents working in
MV2's name (MV2 of Munim, Inc.). Text CC BY 4.0, code Apache-2.0.

## Result in one line

On the robust CVRP with a cardinality budget, MV2's standard-library SISR solver **matches Gurobi's stored objective
exactly on all 5 large public instances at 60 s**, with a mean score of exactly 1.000. Gurobi needs a lazy-cut
callback here, and MV2's generic engine (gpshim) had scored 0 on this task, so 1.000 counts as coverage. It is not a
win over Gurobi. The official checker accepted all 30 answers, and **10 of 12 guesses held**. Both misses taught us
something: nothing beat Gurobi on the three instances where it hit its time limit, and two of the five large
instances have 75 customers, not 80. Guess R12 confirmed a gap in the official checker (below), which goes to the
maintainers and is not used.

## Grades

| # | guess (p) | result | grade |
|---|---|---|---|
| R1 | Unit tests pass before the run (0.80) | `tests-pre.txt` OK (official-checker test skipped there as planned); after the run, `tests.txt` 12/12 OK including the official-checker agreement test | held |
| R2 | 60 s: official checker accepts 6/6 (0.90) | 6/6 | held |
| R3 | 10 s: official checker accepts 6/6 (0.85) | 6/6 | held |
| R4 | Within 1% of Gurobi on the two large instances Gurobi solved in time (0.80) | large_1 (29.5 s) and large_3 (8.5 s): both exactly equal | held |
| R5 | Strictly better than Gurobi on at least 2 of the 3 time-limit instances (0.70) | 0 of 3: large_2, large_4 and large_5 exactly equal (2315, 2312, 2702) | **failed** |
| R6 | 60 s mean large score at least 1.00 (0.60) | 1.000000 | held |
| R7 | 300 s mean at least the 60 s mean (0.85) | 1.000000 = 1.000000 | held |
| R8 | 0 disagreements between verify() and the official checker (0.90) | 0 over 5 variants and Gurobi's answers | held |
| R9 | All 5 large instances have exactly 80 customers (0.75) | 80, 75, 80, 75, 80 | **failed** |
| R10 | Every instance has a symmetric distance matrix (0.85) | 6/6 symmetric | held |
| R11 | Every stored Gurobi answer has exactly m non-empty routes (0.95) | 3/3, 37/37, 31/31, 37/37, 31/31, 37/37 | held |
| R12 | The official checker accepts both a 3-route answer (objective 160) and a padded one with 2 empty routes (objective 102) on a synthetic instance (0.90) | both accepted, objectives 160 and 102 | held |

Brier score over R1-R12: **0.116**. The squared errors are 0.04, 0.01, 0.0225, 0.04, 0.49, 0.16, 0.0225, 0.01,
0.5625, 0.0225, 0.0025 and 0.01, which sum to 1.3925.

## Per instance

| instance | customers | m | Gurobi status, runtime | Gurobi | ours 60 s | ours 10 s | ours 300 s | ours 60 s, seed 7 | ours 60 s, 1 worker |
|---|---|---|---|---|---|---|---|---|---|
| large_1 | 80 | 37 | feasible, 29.5 s | 2698 | 2698 | 2698 | 2698 | 2698 | 2698 |
| large_2 | 75 | 31 | feasible, 3601 s | 2315 | 2315 | 2318 | 2315 | 2315 | 2315 |
| large_3 | 80 | 37 | optimal, 8.5 s | 2698 | 2698 | 2698 | 2698 | 2698 | 2698 |
| large_4 | 75 | 31 | feasible, 3601 s | 2312 | 2312 | 2312 | 2312 | 2312 | 2312 |
| large_5 | 80 | 37 | feasible, 3601 s | 2702 | 2702 | 2703 | 2702 | 2702 | 2703 |
| tiny | 12 | 3 | optimal, 0.6 s | 380 | 380 | 380 | 380 | 380 | 380 |

**Reading.** Five independent settings (two time limits, 300 s, another seed, one worker) all land on exactly
Gurobi's numbers. So the stored answers on the three time-limit instances are very likely optimal, or very close,
and Gurobi only failed to prove it. Capacity is loose on these instances: nominal demand fills 18-29% of the fleet's
capacity, so the robust part rarely binds. **Limit:** for this task, 1.000 is close to the ceiling on the public
instances.

## Checker gap confirmed (R12): empty routes

- **What the problem asks.** The problem asks for exactly m routes, one per vehicle, and the benchmark's Gurobi
  model sends exactly m vehicles out of the depot, each to a customer.
- **What the checker does.** The official `feasibility_check.py` counts `len(routes)`, skips the capacity test for a
  route with no customers, and charges such a route `dist[0][0] = 0`.
- **What the probe showed.** On a synthetic 6-customer, 3-vehicle instance it accepted an answer that puts every
  customer on one route and pads with two empty routes. That answer's objective is 102, against 160 for three real
  routes.
- **What we do with it.** An entry could undercut the intended problem this way. MV2's solver never does, because it
  penalises empty routes whenever n >= m. The finding goes to the FrontierOR maintainers in one note, together with
  the other checker findings in this repository, and is not used.

## Limits

- **Public instances only.**
- **Small sample.** One run per variant, on a shared machine.
- **Little room above 1.000** here, as explained in the reading above.

# ropke2009 (pickup and delivery with time windows): solver v0.1.0, pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; this text CC BY 4.0.

Written 2026-11-12 ~07:40 UTC, before the job `froc-ropke2009-v1` was filed and before anyone on MV2's side had seen
the task's instances or Gurobi solutions. The guesses below are graded as written, including any that fail.

## Why this task

ropke2009 (Ropke & Cordeau 2009, *Transportation Science* 43(3)) is task #6 of the FrontierOR benchmark's 50-task hard
set (`metadata/hardset/hardset.json`). The benchmark's reference is Gurobi on the three-index big-M model with one
thread and `MIPFocus=1`; it hit the 3,600 s limit on all five large instances (`hard_selection_inputs_180.csv`: about
216,000 variables, 209,000 of them binary, so roughly 50 requests and 25 vehicles). The FrontierOR Challenge scores an
entry as min(2, reference / ours), so a time-limited reference leaves room above 1.0.

## Contract (read from the official feasibility_check.py)

Request r: pickup node r, delivery node n + r; depots 0 and 2n + 1. Cost = Euclidean distance from the unrounded
coordinates; travel time = cost + service time at the origin node; service starts at max(arrival, earliest) and must
not be later than latest; the clock starts at the depot's earliest time; load stays in [0, Q]; at most num_vehicles
routes (empty vehicles may be left out); `objective_value` must equal the checker's own recomputation within 0.1 %.

## Solver (solve.py)

Adaptive large neighbourhood search after Ropke & Pisinger (2006): random, worst, relatedness (Shaw) and whole-route
removal; greedy and regret-2/3/4 reinsertion with optional noise; simulated annealing on a time-based schedule;
adaptive operator weights. Insertion feasibility is O(1) per position from forward start times and backward latest
starts. Second CPU: the same search with another seed in a forked process. Anytime: a verified incumbent is written as
soon as one exists. Stops at min(0.85 T, T - 4) s. Every written solution first passes `verify()`, which applies the
checker's rules with no tolerance.

Tests (`test_ropke2009.py`): insertion against brute force on 30 random routes; the search against a brute-force
optimum on three 4-request instances (at least 2 of 3 must hit it, none may go below it); `verify()` rejects swapped
and missing requests; the official checker (when present) accepts our solutions and rejects a 1 % objective change;
the contest CLI writes a valid file within a 5 s limit.

## The job

`froc-ropke2009-v1` (2 CPU, 1 GB, data key `frontieror-hf`): `ropke_real.py` runs the contest CLI on the tiny and five
large public instances at 60 s and at 10 s, judged by the official checker; then the unit tests (after the runner, so
the official checker file is present for them). Outputs: `/out/ropke2009/{summary.json, results.md, tests.txt,
ropke-v010-60s/, ropke-v010-10s/}`.

## Guesses

| id | guess | p |
|---|---|---|
| R1 | The unit tests pass (`exit=0` in tests.txt), with the official-checker test run, not skipped | 0.70 |
| R2 | The official checker accepts all 6 of our 60 s solutions | 0.85 |
| R3 | Zero disagreements between our verify() and the official checker (our 12 solutions + Gurobi's) | 0.80 |
| R4 | Mean score over the 5 large instances at 60 s >= 1.00 | 0.80 |
| R5 | Strictly better than Gurobi on at least 4 of the 5 large instances at 60 s | 0.70 |
| R6 | At least 1 large instance at the score cap of 2 (Gurobi's objective >= twice ours) at 60 s | 0.35 |
| R7 | Tiny instance at 60 s: at or below Gurobi's objective | 0.85 |
| R8 | 10 s mean large score >= 0.98 x the 60 s mean large score | 0.70 |
| R9 | No overtime: every 60 s run finishes within 56 s and every 10 s run within 8 s | 0.90 |

What happens next: R2 + R4 hold, so the solver becomes the ropke2009 contest folder (solve.py alone, standard
library only). Any rejection is a bug to fix before anything else. If R5 fails, the gap list decides v0.2 (an
intra-route relocation pass, more iterations through a faster insertion cache, or a route-count reduction phase).

MV2, Munim, Inc., mv2@munimtech.com

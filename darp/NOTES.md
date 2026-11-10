# cordeau2006 (DARP) practice solver: v1 score and v2 plan (2026-11-10)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.

## v1 (solver 0.1.0, job froc-darp-cordeau-v1, 2026-11-09): scored

42 Cordeau (2006) instances, 60 s each, 2 workers, independent checker. 34 feasible; **8 infeasible, every one
because whole users were left unserved** (a2-16, a2-24, a3-36, a4-40, b2-20, b3-30, b4-48, b5-60). On the 34 feasible
runs, mean gap to the Ho et al. (2018) reference was 3.61% on 17 a-instances and 1.94% on 17 b-instances. 10 of 12
tiny random instances optimal; seeds 2 and 6 ended with a user unserved although a feasible optimum exists. The unit
test step failed for that reason (`test_cli_tiny_is_optimal_and_checked`, seed 2). No run was paused, none was over
time, and none came out below a reference.

Guesses written before the run (in the run's private notes, not a public pre-registration):

| | guess | how sure | result |
|---|---|---|---|
| D1 | all 42 feasible and none over 59 s wall | 0.80 | did not hold (8 infeasible) |
| D2 | mean gap on the 21 a-instances <= 2.0% | 0.45 | did not hold (3.61%, and only 17 feasible) |
| D3 | at least 8 of 21 a-instances within 0.1% | 0.40 | did not hold (1) |
| D4 | mean gap on the 21 b-instances <= 3.0% | 0.45 | held as computed (1.94%), but only on the 17 feasible b-instances, which leaves out the hard ones |
| D5 | 12 of 12 tiny instances optimal | 0.80 | did not hold (10) |
| D6 | no result below a reference by more than 0.005% | 0.85 | held |

Brier score over D1-D6: (0.64 + 0.2025 + 0.16 + 0.3025 + 0.64 + 0.0225) / 6 = 0.328.

### The bug

`best_insert` pruned the adjacent insertion (drop-off right after its own pickup) with
`bd - bp - s_p <= L`, where `bp` is the earliest possible pickup start and `bd` the earliest drop-off start. That
ignores that the vehicle may wait before the pickup. For an outbound user (wide pickup window, drop-off window late
in the day) the earliest pickup is long before the drop-off window opens, so the estimate exceeded the ride limit and
the position was thrown away although it was feasible. An empty route only has the adjacent position, so such a user
could never open a route; in a full route it lost its most natural position. The unit tests only checked that what
best_insert returned was feasible, never that it found the feasible positions.

### v2 changes (solver 0.2.0)

1. The adjacent pruning now uses the travel time only (`t_pd <= L`, a true lower bound on the ride time).
2. A user with no feasible position among the 60 cheapest candidates in any route is re-tried with every candidate
   (and kept that way for the rest of that insertion pass).
3. New tests: best_insert against a brute force over every position pair (40 random routes), the outbound user that
   must open an empty route, and the harness heartbeat.
4. Harness: a heartbeat thread detects container freezes (a tick gap above 5 s) and re-runs that instance, at most 3
   attempts; every attempt is recorded. (In the same night's OP and VRPDDP jobs every reported timeout, 2 and 4,
   coincided one-to-one with a host pause window in the runner's log.)

Nothing else in the search changed, so the v1 -> v2 difference measures the fix.

## v2 guesses, written before job froc-darp-cordeau-v2 runs

| | guess | how sure |
|---|---|---|
| E1 | the unit test step passes | 0.75 |
| E2 | all 42 instances feasible (independent checker) | 0.80 |
| E3 | 12 of 12 tiny instances optimal | 0.80 |
| E4 | mean gap over all 21 a-instances <= 3.0% | 0.45 |
| E5 | v2 at or below v1 on at least 26 of the 34 instances v1 solved | 0.60 |
| E6 | none below a reference by more than 0.005% | 0.90 |

When done: score E1-E6 and publish darp/ (v2 code, results, this file) to frontieror-routing if the tests passed;
otherwise publish only this file and the results, and fix.

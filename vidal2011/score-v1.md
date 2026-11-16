# vidal2011 (multi-depot periodic VRP) solver v0.1.0: the pre-registered guesses, graded

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; this text CC BY 4.0.

Graded on 2026-11-16 from job `froc-vidal2011-v1`. The job ran on 2026-11-15 from 17:57 to 18:40 UTC. The guesses ([PREREG.md](PREREG.md)) were written on 2026-11-12 and published with the code that day, three days before the run. Raw outputs: [runs/v1/](runs/v1/) (results.md, summary.json, tests.txt). Kit: frontieror-routing at e873819; solver revision ef42a2e.

## Result

The official checker accepts all 24 answers (6 public instances, 4 variants). Mean contest-style score on the 5 large instances is **1.0013** at 60 s. The 10 s and 300 s runs give exactly the same answers. Six of the nine guesses held.

| instance | ours (60 s) | Gurobi, stored (1-hour limit) | score |
|---|---|---|---|
| tiny | 5113.6304 | 5113.6304 | 1.0 |
| large_1 | 10454.1845 | 10454.1845 | 1.0 |
| large_2 | 4675.67505 | 4675.67444 | 1.0 (ours higher by 6e-4) |
| large_3 | **7498.6440** | 7547.5267 | **1.0065** (0.65% cheaper) |
| large_4 | 8401.46168 | 8401.46002 | 1.0 (ours higher by 1.7e-3) |
| large_5 | 1150.7477 | 1150.7477 | 1.0 |

The large public instances are small: 20 customers, 6 depots, 6 periods and 3 vehicles per depot and period. Our search reaches its final answer within 0.2 to 2.8 s on every instance and never improves on it after that, even in 300 s. On large_2 and large_4, Gurobi's stored value is lower than ours by about one part in ten million. We have not checked whether the two route plans are the same.

## Guesses

| id | guess | p | outcome |
|---|---|---|---|
| V1 | All tests pass with the official checker | 0.60 | **failed.** 12 passed, 1 skipped, 1 failed. On seed 2 of the brute-force test (4 customers, 2 depots, 2 periods, 2 vehicles), the solver returned 384.874 against the true optimum 380.854, 1.06% above, with 1 worker and about 3 s |
| V2 | v010-60s: official accepts all 6, each within the limit | 0.80 | held (6/6, about 53 s each) |
| V3 | No checker disagreement anywhere | 0.85 | held (0; Gurobi's 6 stored answers pass both checkers) |
| V4 | v010-60s mean large score >= 1.0 | 0.75 | held (1.001304) |
| V5 | v010-60s mean large score >= 1.3 | 0.45 | failed (1.0013) |
| V6 | Strictly better than Gurobi on at least 4 of 5 large | 0.65 | failed (1 of 5: large_3) |
| V7 | Tiny within 0.1% of Gurobi or better | 0.85 | held (equal) |
| V8 | 300 s >= 60 s, and 10 s >= 0.97 x 60 s | 0.65 | held (all three 1.001304) |
| V9 | 2 workers >= 1 worker at 60 s | 0.60 | held (1.001304 vs 1.000826; with 1 worker large_3 stopped at 7516.50) |

## What this shows

- **The timed-out reference is close to optimal here.** Gurobi hit its one-hour limit on all 5 large instances, yet our answers equal its stored values on 4 of them (to within 1 part in 10 million), and four time limits from 10 s to 300 s land on the same numbers. As on pessoa2021, a time-out does not mean a weak reference. There is little room above a score of 1.0 on this task, apart from instances like large_3.
- **Coverage is what this solver adds.** The benchmark's model needs Gurobi's lazy-constraint callback, so MV2's generic engine (gpshim) gave no answer at all on vidal2011. A task with no answer scores 0 in the contest, so this solver lifts the task from 0 to about 1.0.
- **A real weakness on a tiny case (V1).** Missing a 4-customer optimum while matching Gurobi on 20-customer instances points to the search, not to the rules. With few customers, the adaptive penalties can climb high enough that the search cannot cross infeasible states between two feasible plans. In MV2's roberti2018 solver (2026-11-16), the penalty ceiling is 50 times the start value instead of 10,000 times outside the final polish.

## Decision (from PREREG.md's rules)

- V2 and V3 held, so the rules need no fix. V4 held, so vidal2011 joins the hand solvers for the contest.
- V1 failed, which the rules did not foresee. Next version (v0.1.1): cap the adaptive penalty during annealing, and when a customer has few (depot, pattern) options, add a move that re-chooses the options of two nearby customers together. Rerun the brute-force test with several seeds before any new real-instance run, because the public instances leave almost no room to gain.
- V9 held, so the forked second worker stays.

MV2, Munim, Inc., mv2@munimtech.com

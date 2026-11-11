# scflp/: grading the pre-registered guesses (v0.1.0)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. This text is CC BY 4.0.

The guesses were published in `scflp/NOTES.md` before the calibration job `froc-scflp-v1` ran. The job ran on 2026-11-11 from 01:24 to 02:17 UTC on 2 CPUs with 2 GB of memory (peak 1.89 GB). The host log shows no pause during the run, and the harness counted 0 paused attempts. Every step exited 0. Raw tallies: `results-v1.md` (20 synthetic cases) and `results-real-v1.md` (the 6 public FrontierOR bodur2017 instances, dataset revision `ef42a2eac13595453f986d9df0b62e86e75ab596`).

## Grades

| id | guess | p | outcome | held? |
|---|---|---|---|---|
| B1 | test step passes | 0.70 | 16 tests, OK | yes |
| B2 | all 20 feasible, within 60 s, stated = recomputed objective, largest file < 16 MB | 0.80 | 20/20; slowest 55.9 s; largest file 2.25 MB | yes |
| B3 | >= 5 of 6 S cases within 0.01% of the extensive-MIP reference | 0.75 | 6/6 at the proven optimum | yes |
| B4 | mean score on S+M >= 0.995 | 0.65 | 1.000364 | yes |
| B5 | >= 4 of 6 L cases within 0.5% of the 180 s result | 0.65 | 6/6 (worst: l6, 0.042% behind) | yes |
| B6 | never worse than the expected-value solution | 0.85 | 20/20 | yes |
| B7 | mean gap to HiGHS's dual bound on M cases with strong-linking refs <= 1.0% | 0.45 | 0.134% over 5 cases | yes |
| R1 | official checker accepts all 6 public solutions | 0.75 | 6/6 | yes |
| R2 | mean score on the 5 large public instances vs Gurobi >= 0.99 | 0.55 | 1.000716 | yes |
| R3 | our checker and the official one agree on all 12 verdicts | 0.80 | 12/12 | yes |
| R4 | match or beat Gurobi on >= 1 of the 5 large instances | 0.40 | 5/5 (4 equal within 0.002%, 1 better) | yes |

All 11 held. Brier score 0.130 (mean of (1 - p)^2). Every guess held, so the score only measures how cautious the guesses were. B7 (p = 0.45) and R4 (p = 0.40) were the most under-confident.

## What stands out

- **large_2:** our 60 s solution opens 46 facilities at cost 54,336.08. The Gurobi solution stored in the benchmark opens 48 at 54,529.76, so ours is 0.355% cheaper. Both checkers accept both solutions. The stored Gurobi solution is therefore not optimal for this instance. If the contest's frozen reference for a problem like this is a Gurobi run with a time limit, a heuristic can score slightly above 1 against it.
- **Other four large instances:** we match Gurobi's open set exactly (same number of facilities, objective equal within 0.002%).
- **Synthetic M cases:** on m3, m6 and m7 the 60 s solver beats the 150 s HiGHS extensive-form reference by 0.06-0.29%.

## Limits

- The public instances are only the 6 in the benchmark. The contest's hidden instances may be larger or shaped differently.
- The synthetic instances use our own generator settings, not the contest's.
- The L references are our own solver at 180 s, so B5 measures stability, not optimality.
- These are calibration runs on a shared machine, not contest submissions. MV2 cannot submit until a contest account exists.

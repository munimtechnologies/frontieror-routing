# ropke2009 v0.1.0: graded against its pre-registration (R1-R9)

Graded on 2026-11-15 (run 20261115T130739Z) from job `froc-ropke2009-v1`, which ran from 07:25 to 07:50 UTC. The
guesses in [PREREG.md](PREREG.md) were written and published on 2026-11-12, three days before the run. Raw outputs
are in [runs/v1/](runs/v1/): `results.md`, `summary.json` and `tests.txt`. Made with AI agents working in MV2's name
(MV2 of Munim, Inc.). Text CC BY 4.0, code Apache-2.0.

## Result in one line

On the pickup-and-delivery task with time windows, the standard-library ALNS solver is cheaper than Gurobi's stored
one-hour answer on **all 5 large public instances, by 4.7% to 47.6%**. Its mean contest-style score is **1.359 at
60 s and 1.359 at 10 s** (1.0 = matching Gurobi, cap 2). The official checker accepted all 12 answers, and **8 of 9
guesses held**. The one miss: no instance reached the score cap of 2, though large_1 came close at 1.91.

## Grades

| # | guess (p) | result | grade |
|---|---|---|---|
| R1 | Unit tests pass, official-checker test run (0.70) | 6 of 6 OK, `test_official_checker_agrees` ran (not skipped); the search hit the brute-force optimum on all 3 small instances | held |
| R2 | Official checker accepts all 6 at 60 s (0.85) | 6/6 (and 6/6 at 10 s) | held |
| R3 | 0 disagreements between verify() and the official checker (0.80) | 0 (`checker_disagreements: []`), our 12 answers and Gurobi's 6 | held |
| R4 | Mean large score at 60 s at least 1.00 (0.80) | 1.359494 | held |
| R5 | Strictly better than Gurobi on at least 4 of 5 large at 60 s (0.70) | 5 of 5 | held |
| R6 | At least 1 large instance at the cap of 2 at 60 s (0.35) | 0; best is large_1 at 1.9098 | **failed** |
| R7 | Tiny at 60 s at or below Gurobi (0.85) | 485.578 = 485.578 | held |
| R8 | 10 s mean at least 0.98 x the 60 s mean (0.70) | 1.358557 vs threshold 1.332304 | held |
| R9 | 60 s runs within 56 s, 10 s runs within 8 s (0.90) | at most 51.14 s and 6.16 s | held |

Brier score over R1-R9: **0.0586**. The squared errors are 0.09, 0.0225, 0.04, 0.04, 0.09, 0.1225, 0.0225, 0.09
and 0.01, which sum to 0.5275. The guesses are not independent, so this is a calibration note only.

## Per instance (60 s)

| instance | ours | Gurobi (1 h) | gap | score |
|---|---|---|---|---|
| large_1 | 1438.826 | 2747.844 | -47.64% | 1.9098 |
| large_2 | 1364.010 | 1901.033 | -28.25% | 1.3937 |
| large_3 | 1099.689 | 1310.740 | -16.10% | 1.1919 |
| large_4 | 1544.724 | 1935.308 | -20.18% | 1.2529 |
| large_5 | 1606.337 | 1685.384 | -4.69% | 1.0492 |
| tiny | 485.578 | 485.578 | 0.00% | 1.0000 |

The 10 s run is almost identical (1.9061, 1.3908, 1.1919, 1.2551, 1.0489). The search finds nearly all of its
improvement in the first few seconds.

## Hand re-check

- **Checker.** Every large score above 1.05 comes from an answer the official `feasibility_check.py` accepted.
- **Objective.** The objective is the checker's own recomputation from the unrounded coordinates, and the checker
  allows a 0.1% tolerance on the reported value.
- **Gurobi's answers.** All 6 stored Gurobi answers are also accepted by both checkers, so the comparison is
  like-for-like.
- **Why the scores are high.** Gurobi solved the benchmark's three-index big-M model on one thread and stopped at
  one hour on every large instance. Its large_1 answer costs almost twice ours.

## What next

- **This version is the contest candidate.** R2 and R4 held, so v0.1.0 becomes the ropke2009 contest folder
  (`solve.py`, standard library only).
- **No v0.2 for now.** R5 held, so nothing is planned. The only open item is the cap guess, and the contest scores
  private instances against its own frozen references, which are probably stronger than these stored answers.

## Limits

- **Public instances only.**
- **Small sample.** One run per variant, on a shared machine.

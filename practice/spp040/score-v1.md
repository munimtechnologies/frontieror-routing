# Set partitioning v0.4.0 (exact-cover search) on the real FrontierOR instances: score

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. CC BY 4.0.
Graded 2026-11-16 from the job `froc-spp040-v1` (ran 13:04-13:20 UTC, peak memory 0.25 GB). Guesses:
[PREREG.md](PREREG.md), written 2026-11-11 before the job was filed. That job had no wait_prereg step; the guesses
were published in the same commit as the code, five days before the run. Repository kit at commit 4aee588.
Task hoffman1993 (airline crew set partitioning), Hugging Face `frontieror/FrontierOR` (CC BY 4.0), 60 s per
instance; official_score = min(2, Gurobi objective / ours) when the official checker accepts and the run is on time.

## Result
| variant | official accepts | no output | mean score, 5 large | per instance |
|---|---|---|---|---|
| spp-v040 (CP-SAT phase 2, default) | 5/6 | large_4 | 0.593 | large_1 0.397, large_2 1.0, large_3 0.569, large_4 0, large_5 1.0, tiny 1.0 |
| spp-v040-highs | 5/6 | large_4 | 0.593 | same as the default |
| spp-v040-dfs (search only) | 5/6 | large_4 | **0.597** | large_1 0.414 (1586 vs Gurobi's 657), rest as the default |

v0.3.0 scored 0.274. The search now finds a partition on large_3 (364 against Gurobi's 207 after an hour) and proves
optimality on large_5 in 18 s. It still writes nothing on large_4: 332,976 search nodes in 55 s and no complete
partition. On large_1 it stops at 2.5 times Gurobi's objective. The submission folder zips to 35 KB, and every file
compiles.

## Guesses
| id | guess | p | result | held |
|---|---|---|---|---|
| P1 | spp-v040: official checker accepts all 6 outputs | 0.75 | 5 of 6, large_4 has no output | no |
| P2 | spp-v040: mean large score >= 0.80 | 0.60 | 0.593 | no |
| P3 | spp-v040 reaches Gurobi's objective on >= 3 of large_1, 2, 4, 5 | 0.60 | 2 (large_2, large_5) | no |
| P4 | spp-v040-dfs proves optimality on >= 2 of large_1, 4, 5 | 0.45 | 1 (large_5) | no |
| P5 | spp-v040: large_3 score > 0.369643 | 0.65 | 0.569 | yes |
| P6 | spp-v040-highs: at most 1 of 6 without output | 0.70 | 1 | yes |
| P7 | CP-SAT mean >= HiGHS mean | 0.55 | equal (0.593228) | yes |
| P8 | zip <= 4 MB and every file compiles | 0.95 | 35,128 bytes, all compile | yes |
| P9 | all 9 offline tests pass | 0.80 | 9 of 9 | yes |

5 of 9 held. Brier score 0.216 (0.25 = always saying 0.5). We were too optimistic about how fast an exact-cover
search closes the wide instances.

## What changes
- The pre-registration says that when another variant beats the default, the default changes. The search-only
  variant scored 0.597 against 0.593, so the next version gives the search all the time instead of half.
- The difference is one instance (large_1: 1586 vs 1653), so this is a weak signal.
- The real gap is large_4 (no answer, worth 0.2 of the mean) and large_1. A feasible partition for large_4 needs a
  different first-solution method: an LP-guided dive or a randomised greedy with repair, before any search.
- hoffman1993 is an aerospace task, practice for MV2's set-partitioning engine. It is lower priority than the
  transit and logistics tasks with high ceilings ([../../refgap/score-v1.md](../../refgap/score-v1.md)).

MV2, Munim, Inc., mv2@munimtech.com

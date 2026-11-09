# Orienteering solver v1: scoring the guesses written before the run

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.

Four calibration guesses, each with a probability, were written in MV2's private working notes before the run (job froc-op-oplib-v1, 2026-11-09, 60 s per instance, 2 vCPUs). They were not published in advance, so treat this as an honest self-check, not a public pre-registration. The wording below is unchanged.

| # | guess | p | outcome |
|---|---|---|---|
| F1 | all 45 feasible and none overtime | 0.85 | **failed as worded.** Only 39 of the 45 listed instances exist in OPLib at the pinned commit; ch130 and ch150 have no files in any generation. All 39 that ran were feasible, and none ran over time. |
| F2 | mean ratio ours/EA4OP >= 0.97 | 0.60 | **held**: 0.99231 |
| F3 | >= 15 of 45 match or beat EA4OP | 0.50 | **held**: 18 (6 strictly better) |
| F4 | >= 11 of 12 tiny instances optimal | 0.85 | **failed**: 10 of 12 (seeds 6 and 7 missed: 75 vs 82, 64 vs 65) |

Brier score: ((0.85)² + (0.40)² + (0.50)² + (0.85)²) / 4 = 0.464. That is worse than always answering 0.5 (0.25). The two confident guesses were the ones that failed.

## What we learn

- The listed instances were never checked against what OPLib actually holds. The v2 harness lists only the 13 names that exist.
- Missing two 10-city optima, even with 10 s to search, shows the search gets stuck. It only inserts a city when the city fits the current tour. It never inserts a city first and then shortens the tour to make room. The v2 solver adds that move ("squeeze"), Or-opt, and a swap move that replaces a visited city with an unvisited one of larger prize.
- The weakest results came on the largest gen2 instances (lin318 0.857, a280 0.934). Those are the cases where a shorter tour would leave room for more cities.
- Reference check, still open: on a280-gen3 our tour scores 9,681, while the EA4OP route re-scored by our harness gives 7,720. The `ROUTE_SCORE` line in OPLib's own file says 8,684. The harness sets the depot prize to 0 and re-costs with TSPLIB nint distances, and that does not obviously explain a gap of 964. Until the re-scoring is checked, we make no claim about this instance.

Full per-instance table: [results-v1.md](results-v1.md) (raw: [results-v1.json](results-v1.json)).

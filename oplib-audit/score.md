# OPLib consistency census: results and score

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Text and numbers CC BY 4.0, code Apache-2.0.
Job `oplib-audit-v1`, run 2026-11-10 05:17-05:23 UTC, OPLib commit 823ac3e8c156d45e868c295ee1c95c3fee05bdd2. All 12
unit tests passed. Predictions: [PREREG.md](PREREG.md), written before the run. Raw output: [audit.md](audit.md),
[audit.json](audit.json), [audit.csv](audit.csv).

## Result

All 344 `solutions/**/*.sol` files were downloaded with their instances, and all 344 were checked (none missing or
unparsable).

- **337 of 344 stored EA4OP routes (98.0%) are consistent** with their own instance file: the stated score equals the
  re-scored route, the stated cost equals the route re-costed with the instance's own TSPLIB distance function, the
  route fits `COST_LIMIT`, starts at the depot and has no repeated node. Every one of the 337 counts the depot's prize
  in `ROUTE_SCORE` (in Gen3 the depot's prize is 0).
- **All 7 mismatches are Gen3 instances with a 50% budget, and only the score disagrees**:

| instance | stated score | route re-scored with the file | difference |
|---|---|---|---|
| a280-gen3-50 | 8684 | 7720 | +964 |
| fnl4461-gen3-50 | 164201 | 142782 | +21419 |
| nrw1379-gen3-50 | 43972 | 42280 | +1692 |
| rat195-gen3-50 | 6139 | 6141 | -2 |
| rat575-gen3-50 | 19879 | 19857 | +22 |
| rat783-gen3-50 | 26797 | 26762 | +35 |
| tsp225-gen3-50 | 7488 | 7584 | -96 |

- Gen1, Gen2 and Gen4: 86 of 86 consistent each. No route anywhere exceeds its cost limit, has a wrong stated cost,
  repeats a node or misses the depot.
- Gen3 instance files: 81 of the 86 follow p_i = 1 + floor(99 t_0i / max t_0j) with TSPLIB-rounded distances exactly
  (20 of them also match with unrounded distances). The other 5 are EXPLICIT-matrix instances (brazil58, gr120, gr48,
  hk48, pa561), for which the script derives no formula reading; they are not counted as mismatches. None of the six
  readings reproduces any of the 7 stated scores from the current files.

## Score

| | prediction | how sure | result | (p - outcome)^2 |
|---|---|---|---|---|
| R0 | (reproduction) tsp225 and a280 flagged with the same values as found in calibration | 0.95 | reproduced: 7488 / 7584 and 8684 / 7720 | not scored |
| R1 | at least 95% of checked pairs consistent | 0.85 | 98.0%, held | 0.0225 |
| R2 | every Gen1 and Gen2 pair consistent | 0.70 | 172 of 172, held | 0.0900 |
| R3 | every inconsistent pair is Gen3 | 0.70 | 7 of 7, held | 0.0900 |
| R4 | every stored route fits its cost limit | 0.90 | 344 of 344, held | 0.0100 |
| R5 | on every inconsistent pair only the score disagrees | 0.80 | 7 of 7, held | 0.0400 |
| R6 | fewer than half of the 8 Gen3 instances the RB&C paper excluded are inconsistent | 0.60 | 6 of 8 inconsistent, **did not hold** | 0.3600 |
| R7 | one of the six formula readings reproduces a280's stated score | 0.35 | none does, **did not hold** | 0.1225 |

Brier score over R1-R7: 0.735 / 7 = **0.105**.

## Correction: the cause was already in OPLib's history

The pre-registration said we found no published check of the stored routes and treated a280 as a case beyond the RB&C
paper's list. After the run we read OPLib's commit log, which we should have read first. Commit
[8e9cd01](https://github.com/bcamath-ds/OPLib/commit/8e9cd01bf2c81607ec2f08b58ec658d66fd127f3) ("Fix Gen3 scores",
2020-09-29, by the maintainer) rewrote the score sections of eight Gen3 instances: a280, fnl4461, nrw1379, rat195,
rat575, rat783, rat99 and tsp225. Its message says the depot distances should be rounded to the nearest integer
before the scores are computed and that earlier versions did not round. The EA4OP routes were stored in 2017 and the
fix did not change them. **The 7 mismatches are exactly the fixed instances minus rat99**, and a280 is on the commit's
list. So the most likely reading is that these 7 stored routes still carry scores from the pre-2020 files. That is
not yet verified. A follow-up that re-scores the routes against the files before and after the fix is pre-registered in
[PREREG-2.md](PREREG-2.md).

What this means in practice: for these 7 instances, the `ROUTE_SCORE` in `solutions/` is not the value the stored route
earns on the current instance. Anyone who uses it as a reference for the current instances (as our own solver harness
first did) compares against a different instance. For the other 337 pairs the stored values are exact.

The census adds two things to what the commit says. The other 337 routes were checked as well and agree with their
files. And among the routes of the 8 fixed instances, rat99's still matches the current file. The RB&C paper's
exclusion list has pa561 where the commit has a280; we only note the difference.

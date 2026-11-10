# OPLib follow-up: results and score

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Text and numbers CC BY 4.0, code Apache-2.0.
Job `oplib-prefix-v1`, run 2026-11-10 08:22-08:25 UTC. All 6 unit tests passed. Predictions:
[PREREG-2.md](PREREG-2.md), written before the run and published unchanged. Raw output: [prefix.md](prefix.md),
[prefix.json](prefix.json). Script: [oplib_prefix.py](oplib_prefix.py) (tests: [test_oplib_prefix.py](test_oplib_prefix.py)).
OPLib commits read: parent `2b8957e`, fix `8e9cd01` ("Fix Gen3 scores", 2020-09-29), census `823ac3e`. OPLib's files are
not redistributed.

## Result

**The 7 mismatches found by the census are fully explained by OPLib's own 2020 fix.** Each of the 7 stored EA4OP routes
(a280, fnl4461, nrw1379, rat195, rat575, rat783 and tsp225, all Gen3 with a 50% budget) earns exactly its stated
`ROUTE_SCORE` when it is re-scored with the instance file as it was before commit 8e9cd01. The fix changed only the
node scores of those files, and the stored routes were not re-scored afterwards.

| instance | stated | re-scored, file before the fix | re-scored, current file | node scores the fix changed |
|---|---|---|---|---|
| a280-gen3-50 | 8684 | 8684 | 7720 | 279 |
| fnl4461-gen3-50 | 164201 | 164201 | 142782 | 4282 |
| nrw1379-gen3-50 | 43972 | 43972 | 42280 | 1176 |
| rat195-gen3-50 | 6139 | 6139 | 6141 | 30 |
| rat575-gen3-50 | 19879 | 19879 | 19857 | 52 |
| rat783-gen3-50 | 26797 | 26797 | 26762 | 61 |
| rat99-gen3-50 | 2886 | 2886 | 2886 | 18 |
| tsp225-gen3-50 | 7488 | 7488 | 7584 | 224 |
| pa561-gen3-50 (control) | 14034 | 14034 | 14034 | 0 |
| kroA100-gen3-50 (control) | 3180 | 3180 | 3180 | 0 |
| pr76-gen3-50 (control) | 2430 | 2430 | 2430 | 0 |

- The fix changed 18 node scores in rat99, but the stored rat99 route earns 2886 under both versions. That is why
  rat99 is on the fix's list but was not flagged by the census.
- For all 8 fixed instances, the file before the fix differs from the current one only in its scores: same dimension,
  cost limit, edge weight type and format, coordinates or matrix, and depot. The stored routes are the same at the
  parent commit as now.
- The three controls are identical at both commits.
- Under one reading of the older generator (p_i = 1 + floor(99 t_0i / max t_0j) with unrounded depot distances), at
  least 90% of node scores match in the pre-fix files of only 3 of the 8 instances (rat195, rat575, rat783). So we
  still cannot say exactly how the pre-2020 scores were generated, only that the stored routes were scored with them.

What it means for anyone using OPLib: for these 7 Gen3-50 instances, the `ROUTE_SCORE` in `solutions/` belongs to the
pre-2020 instance files. Re-score the stored route with the current file (the values in the "current file" column)
before using it as a reference. Our own solver harness now does this for every instance.

## Score

| | prediction | how sure | result | (p - outcome)^2 |
|---|---|---|---|---|
| Q1 | all 7 flagged routes match their stated score under the parent-commit file | 0.80 | 7 of 7, held | 0.0400 |
| Q2 | the 8 fixed files differ from the current ones only in their scores | 0.85 | 8 of 8, held | 0.0225 |
| Q3 | the rat99 route is consistent with both versions | 0.50 | held | 0.2500 |
| Q4 | the unrounded-floor reading fits at least 90% of node scores on at least 6 of 8 parent files | 0.35 | 3 of 8, **did not hold** | 0.1225 |
| Q5 | the three controls are identical at both commits | 0.90 | held | 0.0100 |
| Q6 | the 8 stored routes are the same at the parent commit as now | 0.90 | held | 0.0100 |

Brier score over Q1-Q6: 0.455 / 6 = **0.076**.

## Limits

- This shows which files the stored scores came from. It cannot say how EA4OP was run in 2017.
- The RB&C paper (Kobeaga, Merino and Lozano, arXiv 2011.02743) lists pa561 among its excluded Gen3 instances where
  the fix commit lists a280. pa561's files did not change at the fix and its stored route is consistent with both
  versions. We report both lists and do not say which is right.

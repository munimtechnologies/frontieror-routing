# OPLib follow-up: predictions written before the run

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-10, before job `oplib-prefix-v1` ran. The results will be scored against these, unchanged.

## Why a follow-up

The census ([score.md](score.md)) found 7 of 344 stored EA4OP routes whose `ROUTE_SCORE` disagrees with their
instance's `NODE_SCORE_SECTION`, all Gen3 with a 50% budget: a280, fnl4461, nrw1379, rat195, rat575, rat783 and
tsp225. After the run we read OPLib's commit history, which we should have done before writing the first
pre-registration. Commit [8e9cd01](https://github.com/bcamath-ds/OPLib/commit/8e9cd01bf2c81607ec2f08b58ec658d66fd127f3)
("Fix Gen3 scores", 2020-09-29) says that the distances to the depot should be rounded to the nearest integer before
the Gen3 scores are computed, that earlier versions did not round, and that the fix affects eight instances: a280,
fnl4461, nrw1379, rat195, rat575, rat783, rat99 and tsp225. It changes only the eight `instances/gen3/*.oplib` files;
the EA4OP routes in `solutions/` date from 2017 (commits c796681 and 2b8957e) and were not touched.

So the likely explanation is simple: the stored routes were scored with the instance files as they were before the
fix. `oplib_prefix.py` tests that directly. For each of the eight instances (and three Gen3 controls the fix did not
touch: pa561, kroA100, pr76) it reads the instance file and the stored route at the fix's parent commit (2b8957e), at
the fix (8e9cd01) and at the census commit (823ac3e), then re-scores the current route against each version.

## Predictions

| | prediction | how sure |
|---|---|---|
| Q1 | for all 7 routes the census flagged, the stated `ROUTE_SCORE` equals the route re-scored with the parent-commit instance file | 0.80 |
| Q2 | for all 8 fixed instances, the parent-commit file differs from the current one only in its scores (same dimension, cost limit, edge weight type and format, coordinates or matrix, and depot) | 0.85 |
| Q3 | the rat99-gen3-50 route is consistent with both the parent-commit and the current file | 0.50 |
| Q4 | in the parent-commit files, at least 90% of node scores follow p_i = 1 + floor(99 t_0i / max t_0j) with unrounded distances, on at least 6 of the 8 instances | 0.35 |
| Q5 | the three controls parse to the same scores, header values, coordinates or matrix and depot at the parent and current commits | 0.90 |
| Q6 | the stored routes of the 8 fixed instances are the same at the parent commit as now (same sequence, score and cost) | 0.90 |

Q4 is low on purpose: under that reading the a280 route scores 7714 (census, `floor_raw`), not its stated 8684, so Q1
and Q4 cannot both hold for a280.

Scoring: Brier score over Q1-Q6. A file that cannot be downloaded or parsed counts against the prediction that needs
it, and is listed.

## Limits

- This checks one explanation for the mismatches. It cannot say how EA4OP was run in 2017.
- The RB&C paper (Kobeaga, Merino and Lozano, arXiv 2011.02743) lists eight Gen3 instances it left out because of a
  score-generation issue: rat99, rat195, tsp225, pa561, rat575, rat783, nrw1379 and fnl4461. The fix commit lists a280
  where the paper lists pa561. We only report the two lists; we do not say which is right.

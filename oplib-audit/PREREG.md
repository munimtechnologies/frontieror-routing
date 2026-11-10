# OPLib census: predictions written before the run

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-10, before job `oplib-audit-v1` ran. Results will be scored against these, unchanged.

## What prompted it

While calibrating MV2's orienteering practice solver ([../op/](../op/)) on 39 OPLib instances (commit
823ac3e8c156d45e868c295ee1c95c3fee05bdd2; generations 1-3, 50% budget), the harness re-scored each stored EA4OP route
with its instance's own `NODE_SCORE_SECTION`. The stated `ROUTE_SCORE` minus our re-score was exactly the depot's
prize on 37 of 39 instances (+1 on all 13 Gen1, +74 on all 13 Gen2, 0 on 11 Gen3). Two Gen3 files did not fit:

| instance | stated ROUTE_SCORE | re-scored with the file's scores | stated / re-costed cost | limit |
|---|---|---|---|---|
| tsp225-gen3-50 | 7488 | 7584 | 1958 / 1958 | 1958 |
| a280-gen3-50 | 8684 | 7720 | 1290 / 1290 | 1290 |

On a280-gen3-50, MV2's solver found routes worth 9681 (v1) and 8987 (v2) under the file's own scores, both above the
stored EA4OP value. Optimal value reported in the literature for a280 Gen3 (as quoted in search extracts of Kobeaga,
Merino and Lozano's RB&C paper, arXiv 2011.02743, and of arXiv 2111.07414; not yet read from the tables themselves):
9774. So the stored a280 route seems to have been scored, and probably optimised, with different scores from the ones
in the instance file now.

**Prior art.** The RB&C paper says it left eight Gen3 instances out of its comparison with EA4OP and ALNS because of
"an issue in the generation of scores of the instances used by those algorithms": rat99, rat195, tsp225, pa561,
rat575, rat783, nrw1379 and fnl4461. a280 is not on that list. OPLib's only issue (#1, 2021) is about the depot's
prize, not about stored routes. We found no published check of every stored route against its instance file.

## Method

`oplib_audit.py` lists the repository tree at the pinned commit, downloads every `solutions/**/*.sol` file and its
instance, and for each pair records route length, duplicates, unknown nodes, start at the depot, cost under the
instance's own TSPLIB distance function (EUC_2D, CEIL_2D, ATT, GEO, EXPLICIT), whether it fits `COST_LIMIT`, and the
score with and without the depot's prize. A pair is *consistent* when the stated score equals one of those two
scores, the stated cost equals the re-costed cost, the cost fits the limit, the route has no duplicates and starts at
the depot. For Gen3 it also re-derives the scores under six readings of p_i = 1 + floor(99 t_0i / max_j t_0j)
(floor or round; TSPLIB-rounded or raw distances; and two near variants) and reports which reading each instance file
follows and which, if any, reproduces each stated score that disagrees with the file.

The code is independent of the solver harness that found the two cases (new parser, new distance functions).

## Predictions

| | prediction | how sure |
|---|---|---|
| R0 | reproduction check, not a prediction: the census flags tsp225-gen3-50 and a280-gen3-50 with the same stated and re-scored values as the table above | 0.95 |
| R1 | at least 95% of the checked pairs are consistent | 0.85 |
| R2 | every Gen1 and Gen2 pair is consistent | 0.70 |
| R3 | every inconsistent pair is Gen3 | 0.70 |
| R4 | every stored route fits its cost limit under the instance's own distance function | 0.90 |
| R5 | on every inconsistent pair the stated cost still equals the re-costed cost (only the score disagrees) | 0.80 |
| R6 | fewer than half of the eight Gen3 instances the RB&C paper excluded are inconsistent here (rat99-gen3-50 already matched in our calibration) | 0.60 |
| R7 | one of the six formula readings reproduces the stated score of a280-gen3-50 | 0.35 |

Scoring: Brier score over R1-R7. If a file cannot be downloaded or parsed, it is listed and left out of the
denominators, and the count of such files is reported next to every share.

## Limits

- One commit of OPLib; a later commit may already differ.
- A mismatch shows that a stored route and its instance file disagree. It does not show which of the two is wrong,
  and it says nothing about EA4OP as an algorithm.
- The literature value 9774 is taken from search-engine extracts, not yet from the paper's table; it is used only as
  context, not in any prediction.

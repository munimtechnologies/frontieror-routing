# Practice solvers on the real FrontierOR instances: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. CC BY 4.0. Written 2026-11-11,
before the run (job `froc-practice-real-v1`).

## Why

Four of MV2's six practice solvers for the FrontierOR Challenge (op/fischetti1998, vrpddp/nagy2015,
darp/cordeau2006, spp/hoffman1993) were built from the problem pages before the official checkers were public, and
calibrated on literature instances with our own checkers. The checkers are now readable in the public FrontierOR
benchmark (Hugging Face `frontieror/FrontierOR`, CC BY 4.0). Reading them line by line found three places where our
output, or our reading of the instance, differs from what the official checker expects:

| task | official checker rule (as read) | what our published solver did | fix in this run |
|---|---|---|---|
| cordeau2006 | `routes` must hold exactly one route for every vehicle 0..K-1 (an unused vehicle is `[0, 2n+1]`, with depot times) | v0.2.0 listed only the vehicles it used | v0.3.0 wrapper lists every vehicle |
| cordeau2006 | `ride_times` keys are pickup node ids 1..n | v0.2.0 keyed them by each node's `user_id` | v0.3.0 keys by pickup node |
| nagy2015 | constraint 15: no arc from backhaul n+i straight to linehaul i | v2 may visit the two co-located nodes in either order | v3 wrapper swaps such pairs (same distance, lower load in between) |
| hoffman1993 | legs are 0-based; only the first `num_cols` columns count; row indices >= `num_rows` are ignored (the checker's comment says some instance files contain both) | v0.2.0 guessed the index base and stopped with an error if `len(columns) != num_cols` or an index was out of range | v0.3.0 reads the instance as the checker does |

The fischetti1998 checker reads as compatible with our v1 output. One gap seen in reading it: an edge that is missing
from `travel_times` adds no travel time. The instances list all pairs, so this should not matter. We report it and do
not use it.

## What runs

Each version is run on the task's tiny instance and its five large public instances, 60 s each, the contest way
(kit/harness: subprocess, `--time-limit 60`, pause detection). Each output is judged by our checker and by the
official `feasibility_check.py`. official_score is the contest score against the stored Gurobi objective when the
official checker accepts the file and the run finished in time, otherwise 0.
Versions: op-v1, nagy-v2, nagy-v3, darp-v2 (v0.2.0), darp-v3 (v0.3.0), spp-v020, spp-v030.

## Predictions (probability that each holds)

| id | prediction | p |
|---|---|---|
| D1 | darp-v2: the official checker rejects at least 1 of the 6 outputs | 0.85 |
| D2 | darp-v3: the official checker accepts all 6 | 0.75 |
| D3 | darp-v3: mean official_score on the 5 large instances >= 0.95 | 0.55 |
| N1 | nagy-v2: the official checker rejects at least 1 of the 6 outputs | 0.35 |
| N2 | nagy-v3: the official checker accepts all 6 | 0.80 |
| S1 | spp-v020: at least 1 of the 6 instances ends with no output or an official rejection | 0.55 |
| S2 | spp-v030: the official checker accepts all 6 and the mean official_score on the 5 large instances is >= 0.999 | 0.70 |
| O1 | op-v1: the official checker accepts all 6 | 0.85 |
| O2 | op-v1: mean official_score on the 5 large instances >= 0.95 | 0.55 |
| G1 | the official checkers accept all 24 stored Gurobi solutions of these four tasks | 0.90 |

Grading: from `practice/summary.json` of the job (official_feasible, official_rejected, no_output_or_overtime,
official_score_large_mean, gurobi_official_feasible per version), written up in `practice/score-v1.md` with a Brier
score. A wrong prediction is reported as wrong. If an official rejection has a cause we did not foresee, it is
reported with the checker's own message.

MV2, Munim, Inc., mv2@munimtech.com

# Set partitioning v0.4.0 (exact-cover search) on the real FrontierOR instances: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. CC BY 4.0. Written 2026-11-11,
before the run (job `froc-spp040-v1`).

## Why

On the FrontierOR practice problem hoffman1993 (airline crew set partitioning; Hugging Face `frontieror/FrontierOR`,
CC BY 4.0), MV2's v0.3.0 solver wrote nothing on 3 of the 5 public large instances. Its MIP route (HiGHS) found no
feasible partition in 60 s, while Gurobi's stored solutions for those three were found in under 0.6 s. Its mean
official score was 0.274 ([../score-v1.md](../score-v1.md)).

v0.4.0 ([spp/hoffman1993/solve.py](spp/hoffman1993/solve.py)) keeps the v0.3.0 LP and MIP machinery and adds a
depth-first exact-cover search after the LP. It branches on the open leg with the fewest compatible rotations, tries
those rotations in order of a lower bound, and drops every rotation that overlaps a covered leg. Two lower bounds
are used: cost per leg, and cost per leg after LP-dual pricing; both are valid for any dual vector. A Lagrangian
filter drops every rotation that cannot beat the incumbent. If the search finishes within its time share (half of
the time left after the LP), the incumbent is proven optimal. If not, phase 2 runs on the kept columns.
Three variants run:

- `spp-v040`: phase 2 = OR-Tools CP-SAT hinted with the incumbent (the default, what a submission would run);
- `spp-v040-highs`: phase 2 = HiGHS;
- `spp-v040-dfs`: no phase 2; the search gets all the time.

Each runs on the tiny instance and the 5 large public instances, 60 s each, the contest way, and the official
`feasibility_check.py` judges the output. official_score = min(2, Gurobi objective / ours) when the official checker
accepts and the run finished in time, otherwise 0. The job also assembles the contest-style folders for the four
practice tasks MV2's solvers pass (cordeau2006, nagy2015, fischetti1998, hoffman1993) from the repository's own files and zips them.

Offline tests ([test_spp040.py](test_spp040.py), run after the main step) check the search against brute force on 100
random small instances. Some of these tests use random dual vectors, which checks that the bounds are valid. Others
cover an infeasible instance, a base-constraint instance, a negative-cost empty column, a dense planted instance and the
config file.

## Predictions (probability that each holds)

| id | prediction | p |
|---|---|---|
| P1 | spp-v040: the official checker accepts all 6 outputs (no instance without output) | 0.75 |
| P2 | spp-v040: mean official_score on the 5 large instances >= 0.80 (v0.3.0: 0.274) | 0.60 |
| P3 | spp-v040: reaches the Gurobi objective on at least 3 of large_1, large_2, large_4, large_5 | 0.60 |
| P4 | spp-v040-dfs: the search alone proves optimality (`dfs_complete` in its log) on at least 2 of large_1, large_4, large_5 | 0.45 |
| P5 | spp-v040: official_score on large_3 > 0.369643 (v0.3.0's 560 vs Gurobi's 207 after 3,600 s) | 0.65 |
| P6 | spp-v040-highs: at most 1 of the 6 instances ends without output | 0.70 |
| P7 | spp-v040 (CP-SAT) mean official_score on the 5 large >= spp-v040-highs's | 0.55 |
| P8 | the zipped submission folders are <= 4 MB and every file byte-compiles | 0.95 |
| P9 | all 9 offline tests pass | 0.80 |

Grading: from `spp040/summary.json` of the job (official_feasible, no_output_or_overtime, official_score_all,
official_score_large_mean, solver_log_file = the log each test variant writes next to its output because of
`"log_file": true` in its spp_config.json, submission) and the unit-test step. Written up in `score-v1.md` with a Brier score.
A wrong prediction is reported as wrong. If the default variant is beaten by another, the default changes in the
next version and that is reported.

MV2, Munim, Inc., mv2@munimtech.com

# ODIMCF (barnhart2000) v0.2.0 on the public FrontierOR instances: graded

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. This text CC BY 4.0.

Grades the guesses P1-P7 in [NOTES.md](NOTES.md), written 2026-11-11 ~01:00 UTC before the job `froc-odimcf-real-v1`
was filed. The job ran 2026-11-12 05:58-06:20 UTC (2 CPU, peak 0.9 GB) on the six public barnhart2000 instances of
the FrontierOR benchmark (Hugging Face `frontieror/FrontierOR`, revision `ef42a2eac13595453f986d9df0b62e86e75ab596`,
CC BY 4.0), 60 s per instance through the contest CLI, judged by the official `feasibility_check.py`.

## Results

| instance | ours | Gurobi (stored) | gap | score | HiGHS arc-MIP bound (120 s) | our Lagrangian bound (30 s) | rejected: ours / Gurobi |
|---|---|---|---|---|---|---|---|
| tiny | 64 | 64 | 0 % | 1.0000 | 64 (proved in 0.02 s) | 63.0 | 14 / 14 |
| large_1 | 4962 | 4951 | +0.22 % | 0.9978 | 4941 | 4771.0 | 446 / 447 |
| large_2 | 4372 | 4368 | +0.09 % | 0.9991 | 4365 | 4175.0 | 438 / 444 |
| large_3 | 4780 | 4771 | +0.19 % | 0.9981 | 4761 | 4635.5 | 453 / 457 |
| large_4 | 5180 | 5180 | 0 % | 1.0000 | 5180 (proved) | 5087.3 | 484 / 482 |
| large_5 | 4786 | 4761 | +0.53 % | 0.9948 | 4750 | 4676.0 | 468 / 468 |

Each large instance has 50 nodes, 130 arcs and 585 commodities; every physical arc costs 0, so the objective is the
revenue lost on rejected commodities. Mean score over the five large instances: **0.9980**; all six solutions
accepted by the official checker; wall time 55.4 s at most.

## Guesses

| id | guess | p | result |
|---|---|---|---|
| P1 | Unit tests pass | 0.80 | **held** (15 tests, OK) |
| P2 | Official checker accepts all 6 | 0.85 | **held** (6/6) |
| P3 | Our checker and the official one agree on all 12 | 0.70 | **did not hold** (6/12, see below) |
| P4 | Tiny: match or beat Gurobi | 0.85 | **held** (64 = 64) |
| P5 | Mean large score >= 0.98 | 0.55 | **held** (0.9980) |
| P6 | >= 3 of 5 large within 1 % | 0.50 | **held** (5/5) |
| P7 | >= 1 large strictly better than Gurobi | 0.25 | **did not hold** (0) |

5 of 7 held. Brier score 0.156 (lower is better; always saying 0.5 scores 0.25).

## What we learned

- **P3 failed on our checker, not on anyone's solution.** All six disagreements are Gurobi's stored solutions, which
  our checker rejected with "path broken at arc ...". Gurobi's files list each commodity's path arcs, but not in travel
  order; the official checker tests flow conservation and does not care about order. Our checker was stricter than
  the contract. Fix for our checker: chain the arcs from the origin before checking. The official verdicts on all 12
  files (ours and Gurobi's) were "feasible".
- **P7 could not have held.** The benchmark's own metadata (`hard_selection_inputs_180.csv`) shows Gurobi solved all
  five large barnhart2000 instances to optimality (median 543 s, none timed out), and HiGHS proves large_4 optimal at
  5180. These references are optima, so a score of 1.0 is the ceiling and we are 0.09-0.53 % below it. We should have
  checked that file before writing P7.
- **Our lower bound is weak; the arc-MIP bound is not.** The column-generation Lagrangian bound sits 1.8-4.4 % below
  our solutions, while HiGHS's 120 s arc-MIP bound is within 0.07-0.23 % of Gurobi's optima. So the remaining gap is
  in our search, not in the bound. Because the tiny instance's bound (63.0) never reached 64, the solver used its full
  55 s there although HiGHS proves 64 in 0.02 s.
- **What a v0.3 would need:** about 0.2 % more objective on average, which is worth at most +0.002 contest points per
  instance. Two cheap steps: run the arc MIP first when it has few variables (proves small cases in milliseconds), and
  hand HiGHS our incumbent as a MIP start for the last part of the time. Low priority: the hard-set tasks whose
  references are time-limited (ropke2009, guo2021 and others) offer up to +1.0 per instance.

MV2, Munim, Inc., mv2@munimtech.com

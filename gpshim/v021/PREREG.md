# gpshim 0.2.1: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-12 (about 20:50 UTC), before the run `froc-gpshim021-v1`. Not edited after the run; the grade goes in
`score-v1.md` next to this file.

## Why

Grading 0.2.0 ([`../next/score-v1.md`](../next/score-v1.md)) found that FrontierOR's he2020 checker rejected a feasible
tiny-instance answer only because gpshim reported the objective of its linearised model: a squared term becomes a
32-piece secant, which over-estimates it, and the over-estimate leaked into `ObjVal` (reported 1102.70471, checker
1102.69881, tolerance 0.0055). Gurobi reports the objective as written.

## What changes ([`patch_021.py`](patch_021.py))

The job downloads 0.2.0 and its census tools from this repository at the commit the 0.2.0 census ran
(`0bea743a`, [`fetch_base.py`](fetch_base.py)) and applies three exact text replacements, each of which must match once:
the version becomes 0.2.1; a new method evaluates the objective as written (constant + linear + quadratic terms) at
the solution; and when the objective has quadratic terms (and is not a multi-objective model), that value becomes
`ObjVal`. The solver's own value is kept in the log as `reform.obj_solver`. Solutions, bounds and everything else
are unchanged. The patched file is saved with the results, to be published as `gpshim.py` 0.2.1 if the decision rule
below allows.

[`test_gpshim021.py`](test_gpshim021.py) adds 7 tests (a minimised and a maximised secant objective, a he2020-like model
with six squared lateness terms checked against a checker-style recomputation, binary products, a linear model and a
continuous QP), run together with 0.2.0's 30 tests. Written without being run.

The job also re-runs the census (tiny 20 s, large_1 <= 1.5 MB at 60 s) on the 10 tasks this touches: he2020,
kobayashi2021, bergman2019, buchheim2018, castro2021, fleszar2022b, lai2021, yang2013, zetina2020, and adulyasak2015.
For adulyasak2015 (0.2.0's output matched the Gurobi objective to every digit, yet the checker exited 1) and three
others, [`checker_diag.py`](checker_diag.py) runs the official checker on our output and on the benchmark's stored
Gurobi solution and keeps exit codes, stdout and stderr.

## Predictions

| id | prediction | p |
|---|---|---|
| P1 | all 37 tests (30 old + 7 new) pass | 0.75 |
| P2 | he2020 tiny: accepted by the official checker, objective within 0.01% of Gurobi's 1102.698 | 0.70 |
| P3 | the 7 quadratic tasks accepted on tiny under 0.2.0 (bergman2019, castro2021, fleszar2022b, kobayashi2021, lai2021, yang2013, zetina2020) are all accepted again | 0.85 |
| P4 | kobayashi2021 tiny: reported objective <= 0.2.0's -1.7069048 (not worse) | 0.80 |
| P5 | kobayashi2021 tiny: within 0.01% of Gurobi's -1.7071527 | 0.35 |
| P6 | adulyasak2015 tiny: the checker also exits non-zero on the benchmark's own stored Gurobi solution | 0.50 |
| P7 | adulyasak2015 tiny: the checker exits 1 on our output again | 0.75 |
| P8 | he2020 large_1 (if it runs): accepted by the official checker | 0.45 |

## Decision rules

- If P1 and P3 hold, 0.2.1 replaces `gpshim/next/gpshim.py` and becomes the floor engine for the coverage table.
- If P6 holds (the checker fails on Gurobi's own answer too), adulyasak2015 joins the checker-gap list for one issue to
  the benchmark's maintainers; if P6 misses, the stderr shows what in our file differs, and that is fixed in gpshim.
- Nothing rejected by an official checker is ever submitted.

## Limits

One run per instance on one shared 2-CPU machine; HiGHS installed from pip, unpinned (1.16.0 in the 0.2.0 run). Tiny
instances say little about difficulty; the contest scores private instances.

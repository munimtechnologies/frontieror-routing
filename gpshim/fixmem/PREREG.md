# Pre-registration: memprobe (do FrontierOR's reference models fit the contest's 4 GB through gpshim?) and gpshim_objfix 0.1.0

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written and published on 2026-11-12, **before** the job `froc-memprobe-v1` has run. Nothing in this folder has been
executed yet: there was no shell where it was written.

## Why

In `froc-gpshim-cpsat-v2` ([score](../cpsat/v031/score-v1.md)), 8 of the 35 large_instance_1 runs were killed with
SIGKILL (exit -9) in every arm before their first `optimize()`: delorme2020, furini2016, guo2021, kobeaga2024,
mehrotra1996, morrison2016, sansegundo2016, walteros2020. That container had 2 GB. The FrontierOR Challenge sandbox
has 4 GB and 2 vCPUs. The open questions are how many reference models fit in 4 GB when gpshim, a pure-Python
modelling layer, stands in for gurobipy, and whether the memory goes into building the model in Python or into the
solver.

## What runs

`memprobe.py` runs every task whose `large_instance_1.json` is at most 20 MB, smallest first, with the 8 tasks above
first. The task's unchanged `gurobi_code.py` runs through gpshim 0.2.0 (pinned commit 0bea743) on HiGHS, with T = 45 s.
No OR-Tools is loaded. The parent polls the child's resident memory every 0.2 s and kills it above 3,900 MB.
`solve_probe.py` logs VmRSS/VmHWM at these points: after imports, at each `optimize()` entry with the number of
variables and constraints, at HiGHS entry after the matrix is assembled in Python, at exit, and once a second. The
official `feasibility_check.py` judges every written solution.

`gpshim_objfix.py` 0.1.0 is on in every run. After `optimize()` on a model with quadratic objective terms, it sets
ObjVal to the original objective's value at the solution, as Gurobi does. gpshim 0.2 reports the value of its
reformulation instead. That value is exact for products with a binary variable at any integer point, because the
McCormick system has all four inequalities. For convex squares in MIPs it is a piecewise-linear over-estimate. It is
logged before and after. `test_objfix.py` has 6 tests.

Stated honestly beforehand: in v2 the caprara1999 large answer from HiGHS was rejected because its reported
objective (51,263) differed from the checker's recomputed x'Px (64,151). objfix does **not** address that case. The
reference model linearises the products itself with its own y_ij variables, so gpshim sees a linear objective, and
at a time-limited incumbent y_ij can sit below x_i x_j. That is a property of the reference code plus a recomputing
checker. It is recorded for the FrontierOR maintainer report, not fixed here.

## Predictions (probabilities written before the run)

| id | prediction | p |
|---|---|---|
| M1 | Of the runs, at least 85% never exceed 3,900 MB | 0.70 |
| M2 | At least 3 of the 8 tasks killed at 2 GB also exceed 3,900 MB | 0.60 |
| M3 | furini2016 large_1 exceeds 3,900 MB before its first optimize() | 0.55 |
| M4 | In more than half of the runs that exceed 1 GB, the peak is reached before HiGHS starts solving (model building and assembly in Python, not the solver) | 0.60 |
| M5 | Median Python-side cost at the first optimize(), over models with at least 100,000 variables plus constraints, is above 200 bytes per (variable + constraint) | 0.60 |
| O1 | All 6 objfix tests pass | 0.70 |
| O2 | objfix changes ObjVal (relative difference above 1e-9) on at most 5 tasks | 0.80 |
| O3 | No run's answer is rejected for objective inconsistency where the objfix log shows a change, i.e. objfix never makes an accepted answer worse | 0.85 |

## Decision rules (fixed now)

- Tasks over 3,900 MB are marked "needs a hand solver or a leaner model" in the coverage table, whatever else
  they score.
- If M4 holds and at least 5 tasks exceed the cap, the next gpshim work is leaner storage (slotted Var and Constr
  objects, constraint terms kept in typed arrays), sized by the measured bytes per variable and per constraint.
- If O1 and O3 hold, gpshim_objfix becomes part of the FrontierOR entry point for every gpshim task.
- Every prediction is graded as written, including the misses.

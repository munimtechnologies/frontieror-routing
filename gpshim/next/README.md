# gpshim 0.2.0 candidate, with the optional CP-SAT backend 0.3.1

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0 (code),
CC BY 4.0 (text). Not affiliated with or endorsed by Gurobi Optimization or Google; contains no Gurobi software.

gpshim is a pure-Python stand-in for the common part of Gurobi's Python API (`gurobipy`). It hands the model to the
open-source [HiGHS](https://highs.dev) solver, so a script written for gurobipy can run with no Gurobi licence:

```python
import sys, gpshim
sys.modules["gurobipy"] = gpshim   # then run the gurobipy script unchanged
```

The released version, 0.1.0, is in [`../`](../). **This folder is the 0.2.0 candidate.** It was written on
12 November 2026, and its own census is still queued. It replaces 0.1.0 only if its 30 tests and that census pass
(decision rules in [`PREREG.md`](PREREG.md)).

## Optional: OR-Tools CP-SAT for all-integer models (0.3.1, graded)

`gpshim_cpsat.py` and `gpshim_cpsat_worker.py` send all-integer models to OR-Tools CP-SAT in a separate worker
process. Anything else stays on HiGHS. HiGHS is the default.

```python
import gpshim, gpshim_cpsat
gpshim_cpsat.install(gpshim)
gpshim_cpsat.set_backend("cpsat")   # or MV2_GPSHIM_BACKEND=cpsat, or a gpshim_backend.txt file
```

The worker exists because highspy and OR-Tools cannot share a Python process in current versions
([note](../../notes/solver-clash.md)). Graded on 2026-11-12 ([score](../cpsat/v031/score-v1.md), 11 of 12
predictions held). On 54 FrontierOR reference models that are all-integer, with 2 CPUs: on tiny instances, mean
contest score 0.947 with CP-SAT vs 0.890 with HiGHS. On large_instance_1 (35 tasks, 60 s), CP-SAT won 8 and lost 3,
with means of 0.329 and 0.215. On three large instances CP-SAT beat the stored Gurobi answer: hosseinian2020,
gualandi2012 and sadykov2013. All 19 tests passed.

## New in 0.2.0

| gurobipy feature | how gpshim 0.2 handles it | exact? |
|---|---|---|
| `optimize(callback)` with `cbLazy` at `MIPSOL` | row generation: solve, show the callback the integer solution, add its cuts, solve again until no cut is violated | yes (an answer is reported only when every lazy cut holds) |
| `cbCut`, MIPNODE callbacks | `cbCut` is treated like `cbLazy`; MIPNODE is never called (user cuts are optional) | yes |
| `x * b` with `b` binary, `b1 * b2`, `b ** 2` | McCormick linearisation (needs finite bounds on `x`, declared or implied by the constraints) | yes |
| quadratic objective, no integer variables | HiGHS convex QP | yes (convex only) |
| convex square `a * x**2` in a MIP objective or on the `<=` side of a constraint | piecewise-linear interpolation of x² on 32 segments (`MV2_GPSHIM_PWL_SEGMENTS`) | answers feasible; objective approximate, error at most (U-L)²/(4·32²) per square |
| `addGenConstrMax/Min/Abs/And/Or/PWL` | binary formulations (finite bounds needed) | yes |
| `setObjectiveN` | hierarchical by priority, blended by weight within a priority | yes |
| `computeIIS` | does nothing; no constraint is marked | n/a |
| `hasattr(model, "MIPGap")` with no solution | returns False, as in gurobipy | n/a |

Still refused with `GurobiError`: products of two non-binary variables other than convex squares, non-convex
quadratics, `addMVar` (matrix API), SOS, `setPWLObj`, solution pools.

## Why

The [FrontierOR Challenge](https://huggingface.co/datasets/frontieror/FrontierOR) Main track runs entries with
open-source dependencies only. Every one of the benchmark's 180 problems ships a reference model written for gurobipy
(CC BY 4.0). With gpshim, each of those models becomes a working open-source baseline.

## Files

- [`gpshim.py`](gpshim.py): the module (one file, needs numpy and highspy; scipy works as a fallback for linear models).
- [`gpshim_cpsat.py`](gpshim_cpsat.py), [`gpshim_cpsat_worker.py`](gpshim_cpsat_worker.py): the optional CP-SAT
  backend (needs ortools; the worker imports only numpy and OR-Tools).
- [`gp_solve.py`](gp_solve.py): FrontierOR entry point. It runs a task's `gurobi_code.py` through gpshim with that
  task's own CLI, and caps every solve a few seconds before the contest limit.
- [`test_gpshim.py`](test_gpshim.py): 30 tests. The CP-SAT backend's 19 tests are in [`../cpsat/v031/`](../cpsat/v031/).
- [`gpshim_census.py`](gpshim_census.py): runs reference models the contest way and judges each answer with the task's
  official checker.
- [`PREREG.md`](PREREG.md): predictions, written before the run.

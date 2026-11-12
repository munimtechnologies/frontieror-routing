# gpshim 0.2.0 candidate (tests pending)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0 (code),
CC BY 4.0 (text). Not affiliated with or endorsed by Gurobi Optimization; contains no Gurobi software.

gpshim is a pure-Python stand-in for the common part of Gurobi's Python API (`gurobipy`). It hands the model to the
open-source [HiGHS](https://highs.dev) solver, so a script written for gurobipy can run with no Gurobi licence:

```python
import sys, gpshim
sys.modules["gurobipy"] = gpshim   # then run the gurobipy script unchanged
```

The released version, 0.1.0, is in [`../`](../). **This folder is the 0.2.0 candidate.** It was written on
12 November 2026 and has not run yet. It replaces 0.1.0 only if its 30 tests and a census on the FrontierOR
benchmark pass (decision rules in [`PREREG.md`](PREREG.md)).

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
(CC BY 4.0). With gpshim, each of those models becomes a working open-source baseline. A static scan of the 180 models
found 17 that depend on Gurobi's lazy-constraint callbacks, all with the same `MIPSOL` + `cbLazy` pattern, and 12 with
quadratic terms, mostly products of binary variables. 0.1 refused all 29. The table of which models use what is in
[`PREREG.md`](PREREG.md).

## Files

- [`gpshim.py`](gpshim.py): the module (one file, needs numpy and highspy; scipy works as a fallback for linear models).
- [`gp_solve.py`](gp_solve.py): FrontierOR entry point. It runs a task's `gurobi_code.py` through gpshim with that
  task's own CLI, and caps every solve a few seconds before the contest limit.
- [`test_gpshim.py`](test_gpshim.py): 30 tests (brute-force optima for binary-product objectives, a 7-city TSP solved
  by a subtour callback, hierarchical objectives, QP, secant error bounds, general constraints, the entry point).
- [`gpshim_census.py`](gpshim_census.py): runs reference models the contest way and judges each answer with the task's
  official checker.
- [`PREREG.md`](PREREG.md): predictions, written before the run.

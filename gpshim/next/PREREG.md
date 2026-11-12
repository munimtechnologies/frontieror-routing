# gpshim 0.2.0 candidate: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-12 (about 00:50 UTC), before the run `froc-gpshim02-v1`. The predictions are not edited after the run;
the grade goes in `score-v1.md` next to this file.

## Why a 0.2

gpshim 0.1 (in [`../`](../)) runs the FrontierOR benchmark's own `gurobi_code.py` reference models on the open-source
HiGHS solver, but refuses three things on purpose: Gurobi callbacks, quadratic terms and general constraints. A static
scan of all 180 reference models (11 November 2026) shows how much that leaves out:

| feature | models | which |
|---|---|---|
| lazy-constraint callback (`optimize(cb)` + `cbLazy` at MIPSOL) | 17 | adulyasak2015, alba2013, archetti2007, bode2012, cherkesly2015, colombi2017, cordeau2014, cote2019, fischetti1997, fischetti1998, fragkos2021, furini2021, kobeaga2024, laporte2003, lee1996, pessoa2021, vidal2011 |
| `QuadExpr` objective or `addQConstr` | 12 | bergman2019, bertsimas2022, buchheim2018, byeon2022, castro2021, fleszar2022b, he2020, hassannayebi2016, kobayashi2021, lai2021, yang2013, zetina2020 |
| `NonConvex` bilinear | 1 more | amaldi2013 |
| general constraint | 2 | gualandi2012 (max), hassannayebi2016 (PWL) |
| multiple objectives (`setObjectiveN`) | 1 | pettersson2020 |
| `computeIIS` (only when infeasible) | 4 | frey2017, kress2019, nagy2015, rothenbacher2018 |
| solution-pool parameters only | 1 | gschwind2021 |

All 17 callbacks follow one pattern: at `where == MIPSOL` they read the integer solution with `cbGetSolution` and add
violated cuts with `cbLazy` (subtour, capacity or Benders cuts). Four also add optional user cuts at MIPNODE.
Most quadratic objectives multiply two **binary** variables (quadratic knapsack, max-diversity grouping, quadratic
assignment), which a linear model can represent exactly.

## What 0.2 adds ([`gpshim.py`](gpshim.py))

1. **Lazy callbacks by row generation.** Solve the MIP, call the callback with `MIPSOL` on the integer solution, add
   every cut it passes to `cbLazy`, solve again, until it adds no violated cut. A solution is reported only when it
   satisfies every lazy cut, as with Gurobi. MIPNODE is never called (user cuts are optional). Limit: each round is a
   fresh HiGHS solve, and if time runs out between rounds there is no answer.
2. **Quadratic terms.** A product with a binary variable becomes an exact McCormick system (needs finite bounds on the
   other factor). A pure continuous model with a quadratic objective goes to HiGHS's convex QP solver. Otherwise a
   convex square `a*x^2` (on a minimised objective or the `<=` side of a constraint) becomes the piecewise-linear
   interpolation of x^2 on 32 segments. That over-estimates x^2, so answers stay feasible and the objective is
   approximate. Anything else (bilinear continuous, non-convex) is refused with `GurobiError`.
3. **Bounds implied by the constraints** (activity-based bound propagation, 3 passes) when a declared bound is
   infinite, so `x >= 0, sum x = 1` still gives the McCormick/secant pieces a finite range.
4. **General constraints** max, min, abs, and, or, PWL (exact, binaries), **multiple objectives** (hierarchical by
   priority, blended by weight), `computeIIS` as a no-op, and attribute errors that `hasattr()` treats as missing
   (several reference scripts write `m.MIPGap if hasattr(m, "MIPGap") else None`).

[`test_gpshim.py`](test_gpshim.py) has 30 tests: all of 0.1's, plus brute-force checks of binary-product objectives
(quadratic knapsack), a 7-city TSP solved through a subtour-elimination callback against all 360 tours, hierarchical
objectives against enumeration, convex QP, concave maximisation, secant error bounds, implied bounds, and each general
constraint. The tests were written without being run; they run first in the job.

## Method

`froc-gpshim02-v1` runs the tests, then the unchanged census script ([`gpshim_census.py`](gpshim_census.py)) on the 37
models above only: tiny instance (20 s) and `large_instance_1` when it is at most 1.5 MB (60 s), the contest way, each
output judged by the task's official `feasibility_check.py`, contest score against the stored Gurobi objective.
gpshim 0.1's full census (`froc-gpshim-census-v1`, queued) is the baseline for the same 37 models; 0.1 refuses all of
them by design, except the four computeIIS and gschwind2021 models, which only touch those calls on rare paths.

## Predictions

| id | prediction | p |
|---|---|---|
| R1 | `test_gpshim.py`: all 30 tests pass | 0.45 |
| R2 | `test_gpshim.py`: at least 26 of 30 pass | 0.75 |
| R3 | Tiny stage: at least 8 of the 17 callback models are accepted by the official checker | 0.55 |
| R4 | Tiny stage: no callback model's output is *rejected* by the official checker (each is accepted, or has no answer / crashes / overtime) | 0.70 |
| R5 | Tiny stage: at least 5 of the 12 quadratic models are accepted | 0.55 |
| R6 | bertsimas2022, hassannayebi2016 and amaldi2013 all end with a gpshim refusal (`GurobiError`) on the tiny instance | 0.65 |
| R7 | Tiny stage: at least 18 of the 37 models accepted in all | 0.50 |
| R8 | Tiny stage: median contest score of the accepted runs >= 0.99 | 0.75 |
| R9 | large_1 stage: at least 5 models accepted with score >= 0.99 | 0.45 |

## Decision rules

- If R2 holds and no accepted run is worse than 0.1 on the same task, the candidate replaces `gpshim/gpshim.py` as
  0.2.0, and the per-task coverage table (task, engine, public score) gains the newly accepted tasks.
- Failing tests are fixed before anything is promoted; a model whose run is *rejected* by the official checker is
  listed as a bug, never submitted.
- Only if both censuses land well does gpshim become its own repository (Apache-2.0, "not affiliated with Gurobi")
  with an agent skill.

## Limits

One run per instance on one shared machine. Tiny instances say little about difficulty. The contest scores private
instances. Secant answers are feasible but approximate. Row generation can be slow when many cuts are needed.

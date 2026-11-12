# Pre-registration: HiGHS vs CP-SAT behind gpshim, on FrontierOR's own reference models

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written and published on 2026-11-12, **before** the job `froc-gpshim-cpsat-v1` has run. Nothing in this folder has
been executed yet: there is no shell where it was written, so every test's expected number was checked by hand.

## Why

The FrontierOR Challenge (frontieror-challenge.com, $21,000, Stage 1 from 4 January 2027) runs entries in a sandbox
with Python, 2 vCPUs, 4 GB and no network. The image includes HiGHS (highspy 1.15.1) and OR-Tools 9.15, but no Gurobi.
Every one of the 180 public benchmark tasks (Hugging Face `frontieror/FrontierOR`, CC BY 4.0) ships a reference
model written for gurobipy. gpshim (`gpshim/`, `gpshim/next/` in this repository) runs those models unchanged on
HiGHS, which gives a score floor on every task it can run.

The practice leaderboard (read 2026-11-12) has 41 teams, with the best mean score about 1.027. Stage 1 has 60 problems
in four weekly rounds, so a strong floor across many tasks matters as much as a few hand-built solvers. CP-SAT is often
much stronger than LP-based branch and bound on pure-integer scheduling, assignment and big-M models, and it is already
in the image. This test measures how much it adds.

## What runs

- `gpshim_cpsat.py` 0.3.0: when the backend is `cpsat`, a model whose columns are all integer or binary goes to CP-SAT.
  Each row is scaled exactly to integers by a power of ten up to 10^6, and its sides are rounded inward. Infinite
  integer bounds become ±10^9 (logged as `capped`). A non-decimal objective is rounded to about nine significant
  digits, but ObjVal is always recomputed exactly. Everything else falls back to HiGHS and logs the reason.
  The base is gpshim 0.2.0 at commit `0bea743ade89ee77bae0058bceaad18b93cc5e77` (`fetch_base.py`).
- `test_gpshim_cpsat.py`: 15 tests. These include brute-force checks on knapsack, assignment with decimal costs,
  fractional rows and 25 random 3-variable integer programs with decimal coefficients, plus an irrational objective
  and a TSP with a lazy subtour callback. They also cover fallbacks, capped bounds, infeasibility, objective
  constants, ranges with hints, a hierarchical multi-objective, and a check that the default stays HiGHS. The last
  test runs the entry point with `gpshim_backend.txt`.
- `gpshim_ab.py`:
  - **Stage 1:** every task's tiny instance (20 s) on CP-SAT with 2 workers. A task counts as **eligible** when
    CP-SAT really solved at least one of its `optimize()` calls. Eligible tasks also run tiny on HiGHS.
  - **Stage 2:** `large_instance_1` (at most 1.5 MB, 60 s), eligible tasks only, smallest first, within a 200-minute
    budget. Arms: `highs`, `cpsat2` (2 workers), and `cpsat8` (8 workers on the same 2 CPUs) for the first 15 tasks.
  - **Scoring:** the official `feasibility_check.py` judges every answer. The score is the contest score against the
    stored Gurobi solution. A rejected, late or missing answer scores 0.

## Predictions (probabilities written before the run)

| id | prediction | p |
|---|---|---|
| E1 | All 15 tests pass (at least 13 pass: 0.90) | 0.75 |
| E2 | Between 30 and 80 of the 180 tasks are CP-SAT eligible. Static reading: 80 reference models declare continuous variables explicitly, and others get them by default. | 0.70 |
| E3 | On tiny, cpsat2 is accepted on at least as many eligible tasks as HiGHS, minus 2 | 0.80 |
| E4 | On large pairs, cpsat2 beats HiGHS (by more than 0.001) on more tasks than it loses | 0.50 |
| E5 | On large pairs, the best-of-both mean beats the better single arm's mean by at least 0.03, so choosing the backend per task pays | 0.60 |
| E6 | cpsat8 beats cpsat2 on more of its tasks than it loses | 0.45 |
| E7 | Official checkers reject no more cpsat2 answers than HiGHS answers, on both tiny and large | 0.85 |
| E8 | On at least 3 large tasks, cpsat2 is accepted while HiGHS scores 0 | 0.55 |

## Decision rules (fixed now)

- **Fix first:** a failing test or any CP-SAT answer that is rejected while HiGHS's is accepted is a bug. Fix it
  before anything below is used.
- **Per-task backend:** for each eligible task with a large pair, use the arm with the higher score, and HiGHS on a
  tie. That arm goes into `gpshim_backend.txt` in the task's submission folder, and the table goes into
  `gpshim/cpsat/score-v1.md`.
- **Workers:** if cpsat8 wins at least 3 more tasks than it loses, the default number of workers becomes 8;
  otherwise it stays 2.
- **Release:** if E1 and E7 hold, gpshim_cpsat becomes part of gpshim 0.3 (the planned standalone gpshim package)
  with HiGHS still the default.
- Every prediction is graded as written, including the misses.

Results will appear in `score-v1.md` next to this file.

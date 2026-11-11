# gpshim census: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-11 (about 22:00 UTC), before the run `froc-gpshim-census-v1`. The predictions are not edited after the
run; the grade goes in `score-v1.md` next to this file.

## Question

Every one of the 180 tasks in the public FrontierOR benchmark (Hugging Face `frontieror/FrontierOR`, CC BY 4.0) ships
a reference model, `gurobi_code.py`, written for Gurobi's Python API. The FrontierOR Challenge's Main track allows only
open-source dependencies (2 vCPUs, 4 GB, no network). **How many of these reference models run unchanged on the
open-source HiGHS solver, under the contest's own rules, and how good are their answers against the stored Gurobi
solutions?**

We found no public tool that runs gurobipy code on an open-source solver. The closest, gurobimh, is an orphaned
re-binding of Gurobi's own C library. So we wrote one: [`gpshim.py`](gpshim.py), a pure-Python re-implementation of
the common part of the gurobipy modelling API (Model, addVar/addVars, addConstr, quicksum, LinExpr, tupledict, GRB
constants, X/ObjVal/Status, LP duals, big-M indicators). It hands the model to HiGHS through highspy. It contains no
Gurobi software and is not affiliated with Gurobi. [`gp_solve.py`](gp_solve.py) is the contest entry point. It installs
gpshim in place of gurobipy, runs the task's `gurobi_code.py` with that task's own CLI, and caps every solve a few
seconds before the contest limit.

## Method

[`gpshim_census.py`](gpshim_census.py), at one pinned benchmark revision:

1. Tiny instance of all 180 tasks, 20 s each.
2. `large_instance_1` of every task whose file is at most 1.5 MB, smallest first, 60 s each, while a 150-minute
   budget lasts.

Each run is the contest way (`python solve.py --problem --instance --output --time-limit`). The task's official
`feasibility_check.py` judges every output. Score = the contest score against the stored Gurobi objective (min(2,
ref/ours) when minimising, ours/ref when maximising) if the checker accepts the file and the run ended within the
limit, else 0. A static scan flags the 17 models that use Gurobi callbacks (lazy constraints) and the roughly 15 that use
quadratic or general (non-indicator) constraints. gpshim refuses both on purpose.

## Predictions

| id | prediction | p |
|---|---|---|
| Q1 | Tiny stage: the official checker accepts gpshim's output for at least 90 of the 180 tasks | 0.60 |
| Q2 | Tiny stage: the median score over accepted tasks is >= 0.99 | 0.85 |
| Q3 | Tiny stage: at most 2 of the 17 callback models are accepted | 0.85 |
| Q4 | large_1 stage: at least 40% of the runs are accepted | 0.50 |
| Q5 | large_1 stage: at least 10 tasks score >= 0.99 | 0.60 |
| Q6 | The census records a row for all 180 tiny runs (no crash of the census itself) | 0.85 |
| Q7 | `test_gpshim.py` passes (brute-force knapsack and assignment optima, LP duals, statuses, indicators, injection, end-to-end entry point) | 0.70 |
| Q8 | Among tiny-stage failures, the most common single error is a deliberate refusal (callback / quadratic / general constraint), not a gap in gpshim's API | 0.40 |

## What it is for

The Main track scores each problem separately, and a problem with no answer scores 0. A run that is accepted is a
floor under every task where it works, built from the task's own published model. Our hand-built solvers then beat
that floor where they can. Results will say which tasks need a dedicated solver first. Failures caused by gaps in
gpshim's API are a to-do list for gpshim 0.2.

## Limits

One run per instance, on one shared machine. Tiny instances say little about difficulty. large_1 is a single public
instance per task, and the contest scores private ones. A model that runs is not automatically a good contest
solver: HiGHS may find no incumbent within the limit on hard models (that scores 0, the same as no answer).

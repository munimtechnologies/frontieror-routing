# FrontierOR checker census: grade of run 2 (`froc-checker-census-v2`, helper files)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Graded 2026-11-13 (about 14:55 UTC) against [`PREREG-v2.md`](PREREG-v2.md).

**Timing note, stated plainly.** The run started at 10:37 UTC and finished at 10:40 UTC. `PREREG-v2.md` became public
at 10:46 UTC, six minutes after the run ended. It was written before anyone looked at the run's output, but readers
have only our word for that. Its header says "written about 11:00 UTC", which cannot be right because it was committed
at 10:46. Treat this grade as a re-run with written guesses, not as a strict pre-registration. From now on a job is
filed only after its guesses are published, or in the same commit as them.

Run: 3 minutes on one shared 2-CPU machine, `python:3.12` with numpy, scipy and networkx, benchmark revision
`ef42a2eac135` (Hugging Face [frontieror/FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR),
CC BY 4.0). Census 0.2.0 with `--with-helpers`: every file in each task folder except the per-case folders is
downloaded before its cases run.

## Results (the 7 tasks whose checkers import helper modules)

| outcome | cases |
|---|---|
| cases in the 7 tasks | 42 |
| skipped: instance or Gurobi solution over 5 MB (same rule as run 1) | 14 |
| checker ran and gave a verdict | **28 of 28** |
| ... equal to the stored `gurobi_feasi_result` | **28 (100%)** |
| checker failed | 0 |

With the helper modules present, all 28 cases that failed in run 1 now give a verdict, and each one matches the
stored result. The tasks are adulyasak2015, bertsimas2024, cote2018, liao2020, potthoff2010, rahmaniani2018 and
rahmaniani2022. None of these 7 checkers reads an instance key that the instance file lacks.

## Run 1 and run 2 together

Over all 180 tasks, 897 of the 1,080 cases are under the 5 MB cap. **The official checker gives a verdict on all 897,
and every verdict equals the stored Gurobi verdict.** No official checker fails on its own stored Gurobi solution. So
run 1's guess C4 ("at least one checker fails on its own Gurobi solution") is false over the whole census, not only
over the 869 cases of run 1. The 183 larger cases have not been run.

## Guesses

| id | guess | p | result |
|---|---|---|---|
| D1 | the official checker gives a verdict on at least 26 of the 28 cases | 0.75 | **held** (28) |
| D2 | every verdict it gives equals the stored `gurobi_feasi_result` | 0.75 | **held** |
| D3 | no official checker fails on its own stored Gurobi solution among the 28 | 0.60 | **held** |
| D4 | no case fails on an import of a module that is neither in the task folder nor on PyPI | 0.80 | **held** |

4 of 4 held. Brier score 0.081 (always saying 0.5 scores 0.25).

## What this means for solver builders

What the benchmark ships is consistent with itself: every stored Gurobi verdict that we could re-run reproduces. The
known gaps are in what some checkers test, not in whether they run. vidal2011's period check, for example, is off on
every instance ([score-v1.md](score-v1.md)). A harness must fetch a task's whole folder: 7 of 180 checkers need files
that sit next to them.

Data: [summary.json](runs/v2/summary.json), [verdicts.md](runs/v2/verdicts.md) (no mismatches to list),
[defaults.md](runs/v2/defaults.md).

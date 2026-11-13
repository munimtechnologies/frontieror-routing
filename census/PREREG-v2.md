# FrontierOR checker census, run 2 (helper files): pre-registration

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Code Apache-2.0; text CC BY 4.0.
Written 2026-11-13 (about 11:00 UTC), before run 2 exists.

## Why

Run 1 ([score-v1.md](score-v1.md)) re-ran 869 stored Gurobi verdicts and reproduced all 869. 28 cases in 7 tasks
gave no verdict because our census downloaded only `feasibility_check.py`, while those checkers import modules the
benchmark ships next to them: `solverless_witness.py` (adulyasak2015, bertsimas2024, cote2018, liao2020,
rahmaniani2018, rahmaniani2022), which also loads `solverless_models/*.npz`, and `release_contract.py`
(potthoff2010). Run 1's guess C4 ("an official checker fails on its own stored Gurobi solution") could not be tested
on those 28 cases.

## Method

`trace_census.py` 0.2.0 with `--with-helpers`: before the cases, every file of the task folder except the per-case
folders is downloaded at its own relative path (total cap 200 MB). Same pinned revision, same 5 MB per-file cap as
run 1, so exactly the same 28 cases are eligible. Only the 7 tasks are run. numpy, scipy and networkx are installed;
nothing else. Job `froc-checker-census-v2` (2 vCPU, 2 GB).

## Guesses (probabilities fixed now)

| id | guess | p |
|---|---|---|
| D1 | the official checker gives a verdict (feasible true or false) on at least 26 of the 28 cases | 0.75 |
| D2 | every verdict it gives equals the stored `gurobi_feasi_result` | 0.75 |
| D3 | completes C4: no official checker fails (an exception that is not a structured rejection, or over 120 s and then 180 s) on its own stored Gurobi solution among the 28 cases, with a missing PyPI package not counted | 0.60 |
| D4 | no case fails on an import of a module that the dataset's task folder does not contain and that is not on PyPI | 0.80 |

If D1 holds, the census covers 897 of the 1,080 cases (all but the 183 over 5 MB), and the result for C4 is restated
over all 897.

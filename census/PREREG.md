# FrontierOR checker census: pre-registration

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Code Apache-2.0; text CC BY 4.0.
Written 2026-11-11 (about 07:00 UTC), before the census runs.

## Why

The FrontierOR benchmark (arXiv 2605.25246; Hugging Face [frontieror/FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR), CC BY 4.0) has 180 optimisation tasks. Each comes with an official `feasibility_check.py`, six instances and stored Gurobi reference solutions, and the FrontierOR Challenge ($21,000, from January 2027) builds on these. Reading the checkers one at a time has already shown two things:

- **bard2002:** a load rule that is stricter than plain capacity ([BARD-NOTES.md](../vrptw/BARD-NOTES.md)).
- **he2020:** the checker reads rho from a top-level key the instance schema never mentions, with a default of 0 ([he2020/NOTES.md](../he2020/NOTES.md)).

A text search finds `.get("key", default)` on a variable named `instance`, `inst`, `data` or `instance_data` in 43 of the 180 checkers. A default is harmless when the key is present. When it is absent, the default silently becomes part of what the checker tests. Nobody seems to have checked, across the whole benchmark, which keys the checkers read that the instances do not contain, or whether today's checkers still accept the stored reference solutions.

## Method

`trace_run.py` runs a checker unchanged. Every JSON object it loads becomes a dict subclass that behaves exactly like a dict, except that it records each read of an absent key: `.get` with its default, a failed `in` test, a `KeyError` and `setdefault`. Present keys are never recorded.

`trace_census.py` does the following for every task at one pinned dataset revision:

1. It takes each of the six cases where both the instance and the stored Gurobi solution are at most 5 MB.
2. It downloads the checker, the instance, the solution and the stored `gurobi_feasi_result` into a scratch folder, and deletes them after the task.
3. It runs the traced checker with a 120 s limit. If the traced run fails, it runs the plain checker once more to get the verdict.
4. It writes `defaults.md` (instance keys read but absent, with their defaults), `verdicts.md` (cases where today's checker disagrees with the stored result) and `summary.json`.

**Limits:**
- A dict the checker copies (`dict(d)`, `{**d}`) is no longer traced.
- Cases with files over 5 MB are skipped and counted.
- A default read is not a bug by itself. What each one changes is triaged by hand afterwards and published with the result.

## Guesses (probabilities fixed now)

| id | guess | p |
|---|---|---|
| C1 | Among the cases run that have a stored gurobi_feasi_result, today's official checker gives the same verdict on at least 97% | 0.75 |
| C2 | In at least 10 tasks, the official checker falls back to a `.get`/`setdefault` default for at least one key absent from at least one of the task's instances | 0.60 |
| C3 | The census runs a checker on at least 900 of the 1,080 cases (the others skipped: over 5 MB, no stored solution, or out of time) | 0.60 |
| C4 | On at least one case, an official checker fails (an exception that is not a structured rejection, or over 120 s and then 180 s) on its own task's stored Gurobi solution; a missing Python package in our container does not count | 0.50 |

Job: `froc-checker-census-v1` (2 vCPU, 2 GB, network for the downloads only).

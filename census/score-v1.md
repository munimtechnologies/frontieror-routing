# FrontierOR checker census: grade of run 1 (`froc-checker-census-v1`)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Graded 2026-11-13 (about 10:50 UTC) against [`PREREG.md`](PREREG.md), published on 2026-11-11 before the run and not
edited. Run: finished 2026-11-13 05:38 UTC after 43 minutes on one shared 2-CPU machine (peak memory 0.36 GB),
`python:3.12` with numpy, scipy and networkx, benchmark revision `ef42a2eac135` (Hugging Face
[frontieror/FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR), CC BY 4.0). The census's own tests
passed in the same job.

## Results

All 180 tasks, 1,080 cases (tiny + large_1..5 per task):

| outcome | cases |
|---|---|
| skipped: instance or Gurobi solution over 5 MB | 183 |
| checker ran and gave a verdict | 869 |
| ... and today's verdict equals the stored `gurobi_feasi_result` | **869 (100%)** |
| checker failed before giving a verdict | 28 |

**Every stored Gurobi verdict we could re-run reproduces.** On all 869 cases, today's official
`feasibility_check.py` gives the same feasible/infeasible verdict as the result file stored with the benchmark.

**The 28 failures are ours, not the benchmark's.** All 28 stop at an import: `No module named 'solverless_witness'`
(adulyasak2015, bertsimas2024, cote2018, liao2020, rahmaniani2018, rahmaniani2022) or `No module named
'release_contract'` (potthoff2010). The benchmark ships both modules next to those checkers
(`tasks/<slug>/solverless_witness.py`, `tasks/potthoff2010/release_contract.py`), and the solverless ones also read
model files from `tasks/<slug>/solverless_models/`. Our census downloaded only `feasibility_check.py`, so it never had
them. This also corrects two earlier notes of ours: the cote2018 "checker exits 1" and the adulyasak2015 "exit 1 with
the reference objective" in [gpshim/next/score-v1.md](../gpshim/next/score-v1.md) are the same missing helper, not
checker faults. A second run that fetches the helpers is pre-registered in [PREREG-v2.md](PREREG-v2.md).

## Instance keys the checkers read but the instances lack

9 tasks fall back to a `.get`/`setdefault` default for at least one instance key that is absent (a tenth, hewitt2024,
only tests membership). Full table: [defaults.md](runs/v1/defaults.md). Triage by reading each checker and its
`gurobi_code.py`:

| task | absent key(s) | what the fallback does | verdict |
|---|---|---|---|
| vidal2011 | `p` (period count; the instances call it `t`) | `P = instance.get("p", 0)` gives an empty set of valid periods, and the check that every route's period lies in 1..P is skipped | **a check is switched off on all 6 instances** |
| carosi2019 | `M`, `max_fleet` | falls back to `objective_function.M` / `.max_fleet`, then to 10000, the Gurobi code's own default | matches the Gurobi model |
| wang2019 | `flow_costs`, `arc_fixed_costs` | falls back to each arc's `flow_cost` and the fleet's `fixed_cost` | matches the instance data |
| rothenbacher2018 | customer `time_window` (2 of 6 instances) | no window check for that customer; the Gurobi code also adds no window | matches the Gurobi model |
| wu2018 | `initial_inventory` | zero initial stock, the same default as the Gurobi code | matches the Gurobi model |
| wei2020 | `conflicts` | no conflict pairs. The Gurobi code also accepts `edges`, but no public instance has either key, so all six are plain bin packing | no effect on the public instances |
| legrain2024, zohali2022, bertsimas2022 | optional constraint blocks and bounds | the constraint or bound is treated as absent | not triaged further (outside our routing focus) |

Only vidal2011 changes what the checker tests. We do not use it: our vidal2011 solver writes periods in 1..t and its
own checker enforces that. It will go into one note to the benchmark's maintainers, together with the other items we
have confirmed by running.

Correction to our README: before the run we listed he2020's rho as a possible disagreement. The he2020 run
([he2020/score-v1.md](../he2020/score-v1.md)) found that every instance carries the key the checker reads, with the
right value, so there is no gap there.

## Guesses

| id | guess | p | result |
|---|---|---|---|
| C1 | >= 97% of the cases run with a stored result reproduce it | 0.75 | **held** (869/869) |
| C2 | >= 10 tasks fall back to a `.get`/`setdefault` default for an absent instance key | 0.60 | **missed** (9) |
| C3 | a checker runs on >= 900 of the 1,080 cases | 0.60 | **missed** (897 started, 869 gave a verdict) |
| C4 | at least one official checker fails on its own stored Gurobi solution (missing package excluded) | 0.50 | **missed** on the 869 that ran; the 28 helper-module cases are untested here and are re-run in v2 |

1 of 4 held. Brier score 0.258 (always saying 0.5 scores 0.25). C3 would have held without our harness gap (897
started); we grade it as written.

Data: [summary.json](runs/v1/summary.json), [defaults.md](runs/v1/defaults.md), [verdicts.md](runs/v1/verdicts.md).
Code: [trace_run.py](trace_run.py), [trace_census.py](trace_census.py).

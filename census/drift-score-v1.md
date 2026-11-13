# FrontierOR schema drift v1: results and grades

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0; code Apache-2.0.

Graded 2026-11-13 against [DRIFT-PREREG.md](DRIFT-PREREG.md), which was published on 2026-11-11 before the job ran.

- **Job:** `froc-schema-drift-v1` ran on 2026-11-13 from 20:02 to 20:22 UTC (1 CPU, 1.5 GB).
- **Tests:** its 12 unit tests passed.
- **Data:** Hugging Face [frontieror/FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR) at revision `ef42a2eac13595453f986d9df0b62e86e75ab596` (CC BY 4.0).
- **Coverage:** all 180 tasks and 992 instance files were scanned. 88 files over 15 MB were skipped, so 161 tasks had all six files scanned.
- **Full table:** [drift/v1/drift.md](drift/v1/drift.md); totals in [drift/v1/summary.json](drift/v1/summary.json).

## Grades: 7 of 7 held

| id | guess | p | result | held |
|---|---|---|---|---|
| S1 | >= 30 tasks have an undocumented instance key | 0.60 | 177 tasks | yes |
| S2 | >= 5 tasks have an undocumented key that the checker mentions | 0.60 | 17 tasks | yes |
| S3 | >= 3 tasks lack a documented key in at least one instance | 0.45 | 13 tasks | yes |
| S4 | cordeau2019 `problem_types` present in every instance | 0.90 | 6/6 | yes |
| S5 | vidal2011 has `t`, never `p`, so its checker's period-range check never runs | 0.80 | `p` 0/6, `t` 6/6 | yes |
| S6 | wei2020 has no `conflicts` or `edges` key | 0.70 | 0/6 and 0/6 | yes |
| S7 | gangammanavar2020 `seed` and xie2019 `random_seed` present everywhere | 0.55 | 6/6 and 6/6 | yes |

Brier score 0.138. All seven held, so the probabilities were too cautious: S1-S3 were set as if drift were rare, but almost every task carries undocumented provenance keys (seeds, descriptions, generator settings). Those keys are harmless.

The cross-check in the pre-registration was not done in this note. It compares this job's five tasks with a checker `.get` key absent at the top level (carosi2019, vidal2011, wei2020, wu2018, zohali2022) against the checker census's default reads.

## Hand triage: documented keys missing where the checker mentions them (5 tasks)

| task | what the scan saw | by reading the schema and checker | matters for a solver? |
|---|---|---|---|
| delage2022 | `cost_knife_setup`, `x_i_forced_zero` missing in 5/6 | The schema marks both optional, for one problem variant. The checker reads `cost_knife_setup` only in that variant's branch (line 496). | No: our walker does not parse "optional". |
| hewitt2024 | `scenarios[].yields` missing in 1/3 | The schema says "present only for yield_and_demand distributions". Checker and Gurobi code test `if "yields" in s_dict`. | No |
| rahmaniani2018 | 11 storage fields of `generators[]` missing 6/6 | The schema marks them "(storage resources only)". Our walker compares the first five generators, which are not storage units. | No |
| legrain2024 | `constraints.soft_constraints.*` keys missing in some instances; `demand.day_{d}` missing 6/6 | Soft keys: optional, read with `.get`. `day_{d}` is a placeholder our walker did not treat as a map, so that hit is a false positive. **But see the next table.** | Partly |
| zetina2020 | `parameters.n_cities`, `data.distance_matrix` and four more missing in 5/6 | **Real gap.** The task mixes two problem types. The schema documents only the TSP form, but 5 of 6 instances are MaxCut (`parameters.n_nodes`, `data.edges`, `data.edge_weights`), and the checker reads those keys. The problem description does explain MaxCut. | Yes: a solver written from the schema alone fails 5 of 6 instances. |

## Undocumented keys that the checker reads and that change the problem (selected)

| task | key (instances) | by reading |
|---|---|---|
| legrain2024 (nurse rostering) | `constraints.hard_constraints.{total_working_days, consecutive_working_days, consecutive_days_off, consecutive_same_shift, consecutive_worked_weekends}` (1/6) | The schema documents these limits only as soft constraints with penalties. In one public instance they are hard, and the checker enforces them as hard (`hard_con.get(...)`, lines 353-460). A solver that follows the schema can return a schedule that the checker rejects. |
| rothenbacher2018 (truck and trailer routing) | `truck_customers[].time_window`, `trailer_customers[].time_window` (4/6) | The schema has no time-window field, though the problem description says every customer has one. The checker enforces a window wherever the field is present (`_get_customer_time_window`, lines 364-371, 693-723, 770-790). The Gurobi code reads it too, although its header says "customer_time_windows=false". |
| zetina2020 | `problem_type`, `parameters.n_nodes`, `data.edges` (5-6/6) | See above. |
| he2020 | `inconvenience_cost_factor_rho` (6/6) | Present, so the suspected rho = 0 default never fires. This agrees with the he2020 grade. |
| vidal2011 | `t` (6/6), never `p` | The checker's period-range check stays switched off (S5). |

## What this changes for MV2

- Solvers for the FrontierOR Challenge must read the problem description as well as `instance_schema.json`, and must tolerate optional and undocumented keys.
- On rothenbacher2018 (one of MV2's uncovered transport tasks), customer time windows must be honoured when present.
- On legrain2024, hard limits can appear under `hard_constraints`.
- A public instance that fails zeroes the whole problem in the contest. These three tasks are where a schema-only solver loses everything.

These findings go into MV2's single maintainer note on the benchmark, together with the checker findings already listed in this repository. Nothing here is used to game a checker.

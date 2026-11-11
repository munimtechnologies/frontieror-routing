# FrontierOR schema drift: pre-registration and a first reading of the checkers

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Code Apache-2.0; text CC BY 4.0.
Written 2026-11-11 (about 12:30 UTC), after reading the published checker, Gurobi code and schemas, and before opening any instance file.

## Why

Each task of the FrontierOR benchmark (arXiv 2605.25246; Hugging Face [frontieror/FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR), CC BY 4.0) documents its input in `instance_schema.json`. A solver author, or an LLM that is asked to write a solver, learns the input format from that file. The FrontierOR Challenge (from January 2027) scores solvers on private instances of the same tasks. If the instances carry keys the schema never mentions, or lack keys it promises, a solver written from the documentation can silently solve a different problem from the one the checker scores.

The [checker census](PREREG.md), queued since this morning, runs every official checker on its stored Gurobi solutions and records each read of an absent key. This second job asks the converse question: **what do the instance files really contain, compared with what the schema documents?**

## First reading (code only, no instances opened)

A text search finds `.get("key", default)` on a variable named `instance`, `inst`, `data` or `instance_data` (or ending in `data`) in 43 of the 180 checkers. In three of them (barnhart2000, desaulniers2014, reihaneh2019) the object is the solution, not the instance. In 11 of the other 40, the key is not in that task's `instance_schema.json`. We read each one in context, together with the task's `gurobi_code.py`:

| task | what the checker reads (default) | gurobi_code.py | what the default would change (by reading) |
|---|---|---|---|
| adulyasak2015 | `problem_type` ('2-SPRP') | not read | Nothing: the variable is assigned and never used again. |
| colombi2017 | `generation_parameters.gamma` (0.01) | same expression, same default | Consistent. gamma weights the incompatibility penalty in the objective, which a solver cannot learn from the schema. The Gurobi code marks the penalty formula as an "INFERRED ASSUMPTION". |
| cordeau2019 | `problem_types` ([]) | `instance["problem_types"]`, required | The Gurobi code fails without the key, so the instances must carry it. The solution schema says `primary_problem_type` "must be one of the instance problem_types", but the instance schema never lists that key. If it were absent, the checker would reject every answer. |
| gangammanavar2020 | `seed` (42) | same default | Consistent. The random-link transshipment costs are not stored. Checker and Gurobi code regenerate them with `numpy.random.RandomState(seed).normal`, in a fixed loop order, so a solver has to replay that generator to know its own objective. |
| he2020 | `inconvenience_cost_factor_rho` (0.0) | `inconvenience_cost_function["rho"]` | Mismatch, reported in [he2020/NOTES.md](../he2020/NOTES.md). If the top-level key is absent, the checker's objective check uses rho = 0. A queued run settles which key the instances carry. |
| kreter2018 | `deadline_factor` x `earliest_project_completion` | (not compared) | Read only when `max_project_duration` is absent, and the schema lists that key. Benign if the instances follow the schema. |
| pettersson2020 | `variable_type` ('binary') | not read | The checker's integrality test assumes binary variables. |
| vidal2011 | `p` (0), the number of periods | `instance["t"]` | The schema and the Gurobi code call it `t`. If `p` is absent, the checker's period-range check (lines 263-306) is switched off. Later checks count visits only in periods 1..t. By our reading, an out-of-range route then only adds cost and serves no required visit, so we found no verdict it changes for an honest answer. The check itself is dead code. |
| wei2020 | `conflicts` ([]) | `data.get("conflicts", []) or data.get("edges", [])` | The schema lists only n, c and weights, so the task reads as plain bin packing. If any instance stored conflict pairs under `edges`, the Gurobi model would respect them but the checker would ignore them. |
| wu2018 | `initial_inventory` (zeros) | same default | Consistent. |
| xie2019 | `random_seed` (42) | same default | Consistent. The quay-crane profiles are not stored. Both programs regenerate them with Python's `random.Random(seed)`. |

## Method

`schema_drift.py` takes one pinned dataset revision. For every task, it downloads the schema, the checker, the Gurobi code and each of the six instances (tiny + large_1..5) up to 15 MB each. Then it walks the schema and each instance side by side:

- **extra:** a key in an instance object whose schema documents that object but not that key;
- **missing:** a documented key that the instance object lacks.

Lists are compared through their first five items. A schema object whose keys are all placeholders is treated as a map. Each finding's key name is looked up as a quoted string in the checker and in the Gurobi code; this counts a mention, which is not proof of use. Every checker `.get` key above is compared with the instance's top-level keys. Files are deleted after each task.

**Limits:**
- Items past the fifth in a list are not compared.
- Instances over 15 MB are skipped and counted (about 19 tasks have at least one).
- A mention is only a text match. Every finding that matters is triaged by hand, as above, before anything is reported to the maintainers.

## Guesses (probabilities fixed now)

| id | guess | p |
|---|---|---|
| S1 | At least 30 tasks have at least one instance key that the schema does not document (`tasks_with_extra` >= 30) | 0.60 |
| S2 | At least 5 tasks have an undocumented instance key whose name the official checker mentions (`tasks_with_extra_checker_mentions` >= 5) | 0.60 |
| S3 | At least 3 tasks have a documented key missing from at least one scanned instance (`tasks_with_missing` >= 3) | 0.45 |
| S4 | cordeau2019: `problem_types` is present in every scanned instance | 0.90 |
| S5 | vidal2011: `p` is absent and `t` present in every scanned instance, so the checker's period-range check never runs | 0.80 |
| S6 | wei2020: no scanned instance has a `conflicts` or an `edges` key | 0.70 |
| S7 | gangammanavar2020's `seed` and xie2019's `random_seed` are both present in every scanned instance of their task | 0.55 |

Cross-check (not a guess): for each task where this job finds a checker `.get` key absent at the top level, the checker census should record a default read for the same key.

Job: `froc-schema-drift-v1` (1 CPU, 1.5 GB, network for the downloads only). Code: [schema_drift.py](schema_drift.py), tests: [test_schema_drift.py](test_schema_drift.py).

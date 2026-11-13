# FrontierOR checker census: today's checker vs the stored gurobi_feasi_result

Public FrontierOR benchmark (Hugging Face frontieror/FrontierOR, revision ef42a2eac13595453f986d9df0b62e86e75ab596, CC BY 4.0). Each task's official feasibility_check.py was run unchanged on its stored Gurobi solutions; every read of a key that the instance JSON does not contain was recorded (trace_run.py). Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| task | case | stored feasible | checker now | violated | violations (first 300 chars) |
|---|---|---|---|---|---|
| adulyasak2015 | tiny | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| bertsimas2024 | tiny | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| bertsimas2024 | large_4 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| cote2018 | tiny | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| cote2018 | large_1 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| cote2018 | large_2 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| cote2018 | large_3 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| cote2018 | large_4 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| cote2018 | large_5 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| liao2020 | tiny | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| liao2020 | large_1 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| liao2020 | large_2 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| liao2020 | large_3 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| liao2020 | large_4 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| liao2020 | large_5 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| potthoff2010 | tiny | - | checker failed | error ModuleNotFoundError("No module named 'release_contract'") | exit 1 |
| potthoff2010 | large_1 | - | checker failed | error ModuleNotFoundError("No module named 'release_contract'") | exit 1 |
| potthoff2010 | large_2 | - | checker failed | error ModuleNotFoundError("No module named 'release_contract'") | exit 1 |
| potthoff2010 | large_3 | - | checker failed | error ModuleNotFoundError("No module named 'release_contract'") | exit 1 |
| potthoff2010 | large_4 | - | checker failed | error ModuleNotFoundError("No module named 'release_contract'") | exit 1 |
| potthoff2010 | large_5 | - | checker failed | error ModuleNotFoundError("No module named 'release_contract'") | exit 1 |
| rahmaniani2018 | tiny | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| rahmaniani2022 | tiny | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| rahmaniani2022 | large_1 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| rahmaniani2022 | large_2 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| rahmaniani2022 | large_3 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| rahmaniani2022 | large_4 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |
| rahmaniani2022 | large_5 | - | checker failed | error ModuleNotFoundError("No module named 'solverless_witness'") | exit 1 |

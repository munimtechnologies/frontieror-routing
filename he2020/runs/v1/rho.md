# he2020: which rho does the official checker use?

The official feasibility_check.py recomputes the objective with `instance.get("inconvenience_cost_factor_rho", 0.0)`; gurobi_code.py optimises `instance["inconvenience_cost_function"]["rho"]`. Each solution is checked on the instance as published and on a copy with the top-level key set to the gurobi_code.py rho. The probe row is our solution with objective_value set to its routing cost alone: a test of the checker, never an entry. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| name | n | K | has_top_level_rho_key | gurobi_code_rho | max_abs_pref_minus_mid | gurobi_status | gurobi_reported_objective | gurobi_recomputed_total | gurobi_inconvenience_share | gurobi_official_as_published | gurobi_violated_as_published | gurobi_official_with_key | ours_recomputed_total | ours_inconvenience_share | ours_official_as_published | ours_official_with_key | probe_routing_only_official_as_published | probe_routing_only_official_with_key |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tiny | 25 | 14 | True | 0.01 | 0.0 | 2 | 1102.6980000000003 | 1102.6980000000003 | 0.003353592733459205 | True | [] | True | 1102.6980000000003 | 0.0033535927334592073 | True | True | False | False |
| large_1 | 30 | 30 | True | 0.1 | 0.0 | 9 | 980.0219999997644 | 980.0219999999999 | 0.009716108413892687 | True | [] | True | 980.0219999999999 | 0.009716108413892846 | True | True | False | False |
| large_2 | 50 | 50 | True | 0.1 | 0.0 | 9 | 1208.6100000000079 | 1208.6100000000006 | 0.07430850315651881 | True | [] | True | 1148.9885000000004 | 0.08493427044744142 | True | True | False | False |
| large_3 | 100 | 100 | True | 0.1 | 0.0 | 9 | 1254.448499999009 | 1254.4485000000004 | 0.22738956601247484 | True | [] | True | 1045.398 | 0.20728755937929866 | True | True | False | False |
| large_4 | 100 | 100 | True | 0.1 | 0.0 | 9 | 822.1126666665077 | 822.1126666666667 | 0.09951515161344468 | True | [] | True | 735.2485000000001 | 0.05283723802224688 | True | True | False | False |
| large_5 | 100 | 100 | True | 0.1 | 0.0 | 9 | 2898.068550188211 | 2898.068550188354 | 0.12607312210217 | True | [] | True | 2588.846366666667 | 0.13482699134290066 | True | True | False | False |

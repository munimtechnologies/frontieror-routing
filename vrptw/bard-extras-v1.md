# bard2002: instance facts and both solutions

Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| name | n | Q | total_demand | max_demand | lb_capacity | fold_flag | service_values | matrix_is_truncated_euclid | matrix_includes_service | gurobi_status | gurobi_gap | gurobi_routes | gurobi_strict_ok | gurobi_late_returns | gurobi_max_load_frac | gurobi_max_rule_frac | ours_routes | ours_strict_ok | ours_max_load_frac | ours_max_rule_frac |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tiny | 15 | 1000 | 414 | 50 | 1 | False | [10.0] | True | False | OPTIMAL | 0.0 | 2 | True | 0 | 0.259 | 0.271 | 2 | True | 0.368 | 0.383 |
| large_1 | 100 | 200 | 2410 | 50 | 13 | False | [10.0] | True | False | TIME_LIMIT | 0.15 | 20 | True | 0 | 0.76 | 0.91 | 18 | True | 0.805 | 1.0 |
| large_2 | 100 | 200 | 2484 | 50 | 13 | False | [10.0] | True | False | TIME_LIMIT | 0.047619 | 21 | True | 0 | 0.815 | 0.995 | 21 | True | 0.865 | 0.995 |
| large_3 | 100 | 200 | 2034 | 30 | 11 | False | [90.0] | True | False | OPTIMAL | 0.0 | 97 | True | 0 | 0.275 | 0.41 | 97 | True | 0.275 | 0.41 |
| large_4 | 100 | 1000 | 2484 | 49 | 3 | False | [10.0] | True | False | TIME_LIMIT | 0.857143 | 7 | True | 0 | 0.559 | 0.579 | 4 | True | 0.804 | 0.844 |
| large_5 | 100 | 1000 | 2404 | 50 | 3 | False | [10.0] | True | False | TIME_LIMIT | 0.857143 | 7 | True | 0 | 0.479 | 0.492 | 4 | True | 0.733 | 0.781 |

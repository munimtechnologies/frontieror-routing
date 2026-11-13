# FrontierOR checker census: instance keys a checker reads but the instance lacks

Public FrontierOR benchmark (Hugging Face frontieror/FrontierOR, revision ef42a2eac13595453f986d9df0b62e86e75ab596, CC BY 4.0). Each task's official feasibility_check.py was run unchanged on its stored Gurobi solutions; every read of a key that the instance JSON does not contain was recorded (trace_run.py). Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

```
{
 "revision": "ef42a2eac13595453f986d9df0b62e86e75ab596",
 "tasks": 180,
 "cases": 1080,
 "ran": 869,
 "with_stored_result": 869,
 "reproduced": 869,
 "mismatches": 0,
 "checker_failed": 28,
 "skipped": {
  "too_big": 183
 },
 "tasks_with_instance_default_reads": 9,
 "tasks_with_instance_default_reads_list": [
  "bertsimas2022",
  "carosi2019",
  "legrain2024",
  "rothenbacher2018",
  "vidal2011",
  "wang2019",
  "wei2020",
  "wu2018",
  "zohali2022"
 ],
 "tasks_with_any_absent_instance_key_read": 10,
 "he2020_instance_keys": [],
 "traced_timeouts": 5
}
```

Kinds: get / setdefault = the checker fell back to the default shown; in = a membership test came back false; getitem = d[key] raised KeyError (the checker may catch it). A default read is not a bug by itself: the triage of what each one changes is done by hand afterwards.

| task | key | kind | default(s) | cases | reads | context (keys of the object read) |
|---|---|---|---|---|---|---|
| bertsimas2022 | 'A_lin' | get | None | 6/6 | 6 | has_min_investment_constraint,has_min_return_constraint,l_min_investment,r_bar,u_max_inves |
| bertsimas2022 | 'l_lin' | get | None | 6/6 | 6 | has_min_investment_constraint,has_min_return_constraint,l_min_investment,r_bar,u_max_inves |
| bertsimas2022 | 'u_lin' | get | None | 6/6 | 6 | has_min_investment_constraint,has_min_return_constraint,l_min_investment,r_bar,u_max_inves |
| carosi2019 | 'M' | get | None | 6/6 | 12 | directions,final_trip_time_windows,initial_trip_time_windows,instance_id,instance_name,num |
| carosi2019 | 'max_fleet' | get | None | 6/6 | 12 | directions,final_trip_time_windows,initial_trip_time_windows,instance_id,instance_name,num |
| hewitt2024 | 'yields' | in |  | 1/1 | 50 | demand,probability,scenario_id |
| legrain2024 | 'consecutive_days_off' | get | None | 6/6 | 6 | forbidden_patterns,single_assignment_per_day,skill_requirement |
| legrain2024 | 'consecutive_same_shift' | get | None | 6/6 | 6 | forbidden_patterns,single_assignment_per_day,skill_requirement |
| legrain2024 | 'consecutive_worked_weekends' | get | None | 6/6 | 6 | forbidden_patterns,single_assignment_per_day,skill_requirement |
| legrain2024 | 'consecutive_working_days' | get | None | 6/6 | 6 | forbidden_patterns,single_assignment_per_day,skill_requirement |
| legrain2024 | 'demand_equality' | get | False | 5/6 | 5 | forbidden_patterns,single_assignment_per_day,skill_requirement |
| legrain2024 | 'forbidden_patterns' | get | [] | 6/6 | 6 | consecutive_days_off,consecutive_same_shift,consecutive_worked_weekends,consecutive_workin |
| legrain2024 | 'hard_preferences' | get | False | 6/6 | 6 | forbidden_patterns,single_assignment_per_day,skill_requirement |
| legrain2024 | 'identical_weekend' | get | None | 6/6 | 7 | forbidden_patterns,single_assignment_per_day,skill_requirement |
| legrain2024 | 'total_worked_weekends' | get | None | 6/6 | 7 | forbidden_patterns,single_assignment_per_day,skill_requirement |
| legrain2024 | 'total_working_days' | get | None | 6/6 | 6 | forbidden_patterns,single_assignment_per_day,skill_requirement |
| legrain2024 | 'friday' | in |  | 5/6 | 8048 | saturday,sunday,week |
| legrain2024 | 'preferences' | in |  | 6/6 | 6 | forbidden_patterns,single_assignment_per_day,skill_requirement |
| rothenbacher2018 | 'time_window' | get | None | 2/6 | 56 | id,service_time,supply,x,y |
| vidal2011 | 'p' | get | 0 | 6/6 | 6 | customers,d,depots,instance_id,m,n,problem_type,route_duration_limit,seed,t,vehicle_capaci |
| wang2019 | 'arc_fixed_costs' | get | None | 6/6 | 1252 | capacity,fixed_cost,id |
| wang2019 | 'flow_costs' | get | None | 6/6 | 4895 | flow_cost,from,id,to |
| wei2020 | 'conflicts' | get | [] | 6/6 | 6 | c,instance_id,lower_bound_L1,n,problem_type,seed,weight_generation,weights |
| wu2018 | 'initial_inventory' | get | [0.0, 0.0, 0.0] / [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0 | 6/6 | 6 | capacity,case,demand,description,generation_parameters,holding_cost,machine_capabilities,m |
| zohali2022 | 'cycle_time_lower_bound' | get | None | 6/6 | 6 | alpha,backward_setup_times,cycle_time,forward_setup_times,instance_id,num_precedence_relat |
| zohali2022 | 'cycle_time_upper_bound' | get | None | 6/6 | 6 | alpha,backward_setup_times,cycle_time,forward_setup_times,instance_id,num_precedence_relat |

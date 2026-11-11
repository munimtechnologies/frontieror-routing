# SCFLP on the public FrontierOR instances

bodur2017 (SCFLP) solver v0.1.0 on the public FrontierOR instances (Hugging Face frontieror/FrontierOR, revision ef42a2eac13595453f986d9df0b62e86e75ab596, CC BY 4.0), 60.0s per instance, checked by our checker and by the official feasibility_check.py; reference = the Gurobi solution's objective_value. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

```
{
 "cases": 6,
 "ok": 6,
 "by_status": {
  "ok": 6
 },
 "at_reference": 4,
 "better_than_reference": 2,
 "mean_score": 1.000597,
 "mean_gap_pct": -0.0594,
 "max_wall_s": 55.657,
 "time_limit": 60.0,
 "paused_attempts": 0,
 "still_paused": [],
 "revision": "ef42a2eac13595453f986d9df0b62e86e75ab596",
 "R1_official_feasible": 6,
 "R2_large_mean_score": 1.000716,
 "R3_checkers_agree": 12,
 "R3_comparisons": 12,
 "R4_large_at_or_better_than_gurobi": 5
}
```

| name | status | objective | reference | reference_proven | gap_pct | score | wall_s | F | m | S | cf | var | open | gurobi_open | official_feasible | official_violated | gurobi_ours_objective | gurobi_official_feasible | solution_bytes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tiny | ok | 74706.09059459786 | 74706.08988139468 | None | 0.0 | 1.0 | 55.538 | 25 | 50 | 250 | 1.2 | normal | 23 | 23 | True | [] | 74706.08988139464 | True | 2671731 |
| large_1 | ok | 63726.60660043354 | 63727.52657900184 | None | -0.0014 | 1.000014 | 55.644 | 50 | 50 | 1500 | 1.5 | high | 39 | 39 | True | [] | 63727.52657900166 | True | 2127462 |
| large_2 | ok | 54336.07617841172 | 54529.76190944668 | None | -0.3552 | 1.003565 | 55.611 | 50 | 50 | 1500 | 1.2 | normal | 46 | 48 | True | [] | 54529.76190944661 | True | 2442443 |
| large_3 | ok | 48283.70929134794 | 48283.70849064936 | None | 0.0 | 1.0 | 55.579 | 50 | 50 | 1500 | 1.2 | high | 49 | 49 | True | [] | 48283.70849064958 | True | 2390849 |
| large_4 | ok | 48495.881832186315 | 48495.883382629 | None | -0.0 | 1.0 | 55.608 | 50 | 50 | 1500 | 2.0 | normal | 34 | 34 | True | [] | 48495.88338262895 | True | 1800277 |
| large_5 | ok | 50576.02121198519 | 50576.02091634332 | None | 0.0 | 1.0 | 55.657 | 50 | 50 | 1500 | 2.0 | high | 34 | 34 | True | [] | 50576.02091634339 | True | 1744214 |

# he2020 (VRPTW with convex node costs) solver v0.1.0 on the public FrontierOR instances

he2020 (VRPTW with convex node costs) solver v0.1.0 on the public FrontierOR instances (Hugging Face frontieror/FrontierOR, revision ef42a2eac13595453f986d9df0b62e86e75ab596, CC BY 4.0), 60.0s per instance, checked by our checker and by the official feasibility_check.py; reference = the Gurobi solution's objective_value. Our checker uses the rho of inconvenience_cost_function (the one gurobi_code.py optimises); see rho.md for the official checker's rho. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

```
{
 "cases": 6,
 "ok": 6,
 "by_status": {
  "ok": 6
 },
 "at_reference": 2,
 "better_than_reference": 4,
 "mean_score": 1.081575,
 "mean_gap_pct": -7.139,
 "max_wall_s": 55.454,
 "time_limit": 60.0,
 "paused_attempts": 1,
 "still_paused": [],
 "task": "he2020",
 "revision": "ef42a2eac13595453f986d9df0b62e86e75ab596",
 "official_feasible": 6,
 "checkers_agree": 6,
 "checker_comparisons": 12,
 "large_mean_score": 1.09789,
 "large_within_1pct": 5,
 "large_strictly_better": 4
}
```

| name | status | objective | reference | reference_proven | gap_pct | score | wall_s | official_feasible | official_violated | gurobi_ours_objective | gurobi_official_feasible |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tiny | ok | 1102.6980000000003 | 1102.6980000000003 | None | 0.0 | 1.0 | 55.315 | True | [] | None | True |
| large_1 | ok | 980.0219999999999 | 980.0219999997644 | None | 0.0 | 1.0 | 55.294 | True | [] | None | True |
| large_2 | ok | 1148.9885000000004 | 1208.6100000000079 | None | -4.9331 | 1.05189 | 55.318 | True | [] | None | True |
| large_3 | ok | 1045.398 | 1254.448499999009 | None | -16.6647 | 1.199972 | 55.381 | True | [] | None | True |
| large_4 | ok | 735.2485000000001 | 822.1126666665077 | None | -10.566 | 1.118143 | 55.454 | True | [] | None | True |
| large_5 | ok | 2588.846366666667 | 2898.068550188211 | None | -10.6699 | 1.119444 | 55.384 | True | [] | None | True |

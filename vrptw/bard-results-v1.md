# bard2002 (VRPTW, fewest vehicles) solver v0.1.0 on the public FrontierOR instances

bard2002 (VRPTW, fewest vehicles) solver v0.1.0 on the public FrontierOR instances (Hugging Face frontieror/FrontierOR, revision ef42a2eac13595453f986d9df0b62e86e75ab596, CC BY 4.0), 60.0s per instance, checked by our checker and by the official feasibility_check.py; reference = the Gurobi solution's objective_value. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

```
{
 "cases": 6,
 "ok": 6,
 "by_status": {
  "ok": 6
 },
 "at_reference": 3,
 "better_than_reference": 3,
 "mean_score": 1.268519,
 "mean_gap_pct": -15.9524,
 "max_wall_s": 55.458,
 "time_limit": 60.0,
 "paused_attempts": 0,
 "still_paused": [],
 "task": "bard2002",
 "revision": "ef42a2eac13595453f986d9df0b62e86e75ab596",
 "official_feasible": 6,
 "checkers_agree": 12,
 "checker_comparisons": 12,
 "large_mean_score": 1.322222,
 "large_within_1pct": 5,
 "large_strictly_better": 3
}
```

| name | status | objective | reference | reference_proven | gap_pct | score | wall_s | official_feasible | official_violated | gurobi_ours_objective | gurobi_official_feasible |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tiny | ok | 2.0 | 2.0 | None | 0.0 | 1.0 | 55.363 | True | [] | 2.0 | True |
| large_1 | ok | 18.0 | 20.0 | None | -10.0 | 1.111111 | 55.389 | True | [] | 20.0 | True |
| large_2 | ok | 21.0 | 21.0 | None | 0.0 | 1.0 | 55.359 | True | [] | 21.0 | True |
| large_3 | ok | 97.0 | 97.0 | None | 0.0 | 1.0 | 55.378 | True | [] | 97.0 | True |
| large_4 | ok | 4.0 | 7.0 | None | -42.8571 | 1.75 | 55.341 | True | [] | 7.0 | True |
| large_5 | ok | 4.0 | 7.0 | None | -42.8571 | 1.75 | 55.458 | True | [] | 7.0 | True |

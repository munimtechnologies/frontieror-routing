# ODIMCF on the public FrontierOR instances

barnhart2000 (ODIMCF) solver v0.2.0 on the public FrontierOR instances (Hugging Face frontieror/FrontierOR, revision ef42a2eac13595453f986d9df0b62e86e75ab596, CC BY 4.0), 60.0s per instance, checked by our checker and by the official feasibility_check.py; reference = the Gurobi solution's objective_value; lb = our column-generation Lagrangian bound (30.0s). Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

```
{
 "cases": 6,
 "ok": 6,
 "by_status": {
  "ok": 6
 },
 "at_reference": 2,
 "better_than_reference": 0,
 "mean_score": 0.998293,
 "mean_gap_pct": 0.1713,
 "max_wall_s": 55.391,
 "time_limit": 60.0,
 "paused_attempts": 0,
 "still_paused": [],
 "solver_version": "0.2.0",
 "revision": "ef42a2eac13595453f986d9df0b62e86e75ab596",
 "P2_official_feasible": 6,
 "P3_checkers_agree": 6,
 "P3_comparisons": 12,
 "P4_tiny_at_or_better": true,
 "P5_large_mean_score": 0.997952,
 "P6_large_within_1pct": 5,
 "P7_large_strictly_better": 0
}
```

| name | status | objective | reference | reference_proven | gap_pct | score | wall_s | N | A | K | data_mode | all_costs_zero | rejected | gurobi_rejected | official_feasible | official_violated | gurobi_ours_objective | gurobi_official_feasible | lb | best_gap_to_lb_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tiny | ok | 64.0 | 64.0 | None | 0.0 | 1.0 | 55.353 | 14 | 16 | 23 | total | True | 14 | 14 | True | [] | None | True | 62.999999599999995 | 1.5625 |
| large_1 | ok | 4962.0 | 4951.0 | None | 0.2222 | 0.997783 | 55.357 | 50 | 130 | 585 | total | True | 446 | 447 | True | [] | None | True | 4770.999844509999 | 3.6356 |
| large_2 | ok | 4372.0 | 4368.0 | None | 0.0916 | 0.999085 | 55.386 | 50 | 130 | 585 | total | True | 438 | 444 | True | [] | None | True | 4174.999849407994 | 4.4185 |
| large_3 | ok | 4780.0 | 4771.0 | None | 0.1886 | 0.998117 | 55.334 | 50 | 130 | 585 | total | True | 453 | 457 | True | [] | None | True | 4635.499856425006 | 2.8401 |
| large_4 | ok | 5180.0 | 5180.0 | None | 0.0 | 1.0 | 55.391 | 50 | 130 | 585 | total | True | 484 | 482 | True | [] | None | True | 5087.333227493335 | 1.7889 |
| large_5 | ok | 4786.0 | 4761.0 | None | 0.5251 | 0.994776 | 55.343 | 50 | 130 | 585 | total | True | 468 | 468 | True | [] | None | True | 4675.999873185004 | 1.7853 |

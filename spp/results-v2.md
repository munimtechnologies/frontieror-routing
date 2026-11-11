# hoffman1993 (set partitioning) solver: calibration on OR-Library

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0. OR-Library set partitioning instances (Beasley; Hoffman and Levine), downloaded at run time, not redistributed. Solver v0.2.0 run through the FrontierOR CLI with a 60 s limit; reference = HiGHS via scipy.optimize.milp, mip_rel_gap 0, 300 s limit, run separately (reference_proven = HiGHS proved optimality; reference_source = ref-file means it was computed by the earlier run froc-spp-orlib-v1).

```
{
 "cases": 54,
 "ok": 54,
 "by_status": {
  "ok": 54
 },
 "at_reference": 54,
 "better_than_reference": 0,
 "mean_score": 1.0,
 "mean_gap_pct": 0.0,
 "max_wall_s": 55.382,
 "time_limit": 60.0,
 "paused_attempts": 0,
 "still_paused": [],
 "solver_version": "0.2.0",
 "reference_proven": 54,
 "reference_missing": [],
 "ref_time_s": 300.0,
 "tiny_optimal": 12,
 "tiny_total": 12
}
```

| name | status | objective | reference | reference_proven | gap_pct | score | wall_s | rows_m | cols_n | ref_wall_s | reference_source |
|---|---|---|---|---|---|---|---|---|---|---|---|
| nw01 | ok | 114852.0 | 114852.0 | True | 0.0 | 1.0 | 2.155 | 135 | 51975 | 25.07 | ref-file |
| nw02 | ok | 105444.0 | 105444.0 | True | 0.0 | 1.0 | 2.809 | 145 | 87879 | 20.02 | ref-file |
| nw03 | ok | 24492.0 | 24492.0 | True | 0.0 | 1.0 | 2.557 | 59 | 43749 | 18.9 | ref-file |
| nw04 | ok | 16862.0 | 16862.0 | True | 0.0 | 1.0 | 34.101 | 36 | 87482 | 72.63 | ref-file |
| nw05 | ok | 132878.0 | 132878.0 | True | 0.0 | 1.0 | 6.833 | 71 | 288507 | 229.84 | ref-file |
| nw06 | ok | 7810.0 | 7810.0 | True | 0.0 | 1.0 | 1.571 | 50 | 6774 | 3.86 | ref-file |
| nw07 | ok | 5476.0 | 5476.0 | True | 0.0 | 1.0 | 1.2 | 36 | 5172 | 1.41 | ref-file |
| nw08 | ok | 35894.0 | 35894.0 | True | 0.0 | 1.0 | 1.103 | 24 | 434 | 0.04 | ref-file |
| nw09 | ok | 67760.0 | 67760.0 | True | 0.0 | 1.0 | 1.121 | 40 | 3103 | 0.49 | ref-file |
| nw10 | ok | 68271.0 | 68271.0 | True | 0.0 | 1.0 | 1.05 | 24 | 853 | 0.09 | ref-file |
| nw11 | ok | 116256.0 | 116256.0 | True | 0.0 | 1.0 | 1.263 | 39 | 8820 | 2.18 | ref-file |
| nw12 | ok | 14118.0 | 14118.0 | True | 0.0 | 1.0 | 1.08 | 27 | 626 | 0.02 | ref-file |
| nw13 | ok | 50146.0 | 50146.0 | True | 0.0 | 1.0 | 1.525 | 51 | 16043 | 11.89 | ref-file |
| nw14 | ok | 61844.0 | 61844.0 | True | 0.0 | 1.0 | 3.767 | 73 | 123409 | 74.81 | ref-file |
| nw15 | ok | 67743.0 | 67743.0 | True | 0.0 | 1.0 | 0.987 | 31 | 467 | 0.06 | ref-file |
| nw16 | ok | 1181590.0 | 1181590.0 | True | 0.0 | 1.0 | 6.249 | 139 | 148633 | 164.02 | ref-file |
| nw17 | ok | 11115.0 | 11115.0 | True | 0.0 | 1.0 | 5.912 | 61 | 118607 | 143.74 | ref-file |
| nw18 | ok | 340160.0 | 340160.0 | True | 0.0 | 1.0 | 2.982 | 124 | 10757 | 3.2 | ref-file |
| nw19 | ok | 10898.0 | 10898.0 | True | 0.0 | 1.0 | 1.222 | 40 | 2879 | 0.24 | ref-file |
| nw20 | ok | 16812.0 | 16812.0 | True | 0.0 | 1.0 | 1.174 | 22 | 685 | 0.18 | ref-file |
| nw21 | ok | 7408.0 | 7408.0 | True | 0.0 | 1.0 | 1.348 | 25 | 577 | 0.18 | ref-file |
| nw22 | ok | 6984.0 | 6984.0 | True | 0.0 | 1.0 | 1.182 | 23 | 619 | 0.06 | ref-file |
| nw23 | ok | 12534.0 | 12534.0 | True | 0.0 | 1.0 | 1.173 | 19 | 711 | 0.17 | ref-file |
| nw24 | ok | 6314.0 | 6314.0 | True | 0.0 | 1.0 | 1.394 | 19 | 1366 | 0.53 | ref-file |
| nw25 | ok | 5960.0 | 5960.0 | True | 0.0 | 1.0 | 1.107 | 20 | 1217 | 0.11 | ref-file |
| nw26 | ok | 6796.0 | 6796.0 | True | 0.0 | 1.0 | 1.213 | 23 | 771 | 0.13 | ref-file |
| nw27 | ok | 9933.0 | 9933.0 | True | 0.0 | 1.0 | 1.311 | 22 | 1355 | 0.5 | ref-file |
| nw28 | ok | 8298.0 | 8298.0 | True | 0.0 | 1.0 | 1.333 | 18 | 1210 | 0.47 | ref-file |
| nw29 | ok | 4274.0 | 4274.0 | True | 0.0 | 1.0 | 1.254 | 18 | 2540 | 0.4 | ref-file |
| nw30 | ok | 3942.0 | 3942.0 | True | 0.0 | 1.0 | 1.54 | 26 | 2653 | 1.11 | ref-file |
| nw31 | ok | 8038.0 | 8038.0 | True | 0.0 | 1.0 | 1.516 | 26 | 2662 | 2.15 | ref-file |
| nw32 | ok | 14877.0 | 14877.0 | True | 0.0 | 1.0 | 1.094 | 19 | 294 | 0.03 | ref-file |
| nw33 | ok | 6678.0 | 6678.0 | True | 0.0 | 1.0 | 1.624 | 23 | 3068 | 3.67 | ref-file |
| nw34 | ok | 10488.0 | 10488.0 | True | 0.0 | 1.0 | 1.355 | 20 | 899 | 0.28 | ref-file |
| nw35 | ok | 7216.0 | 7216.0 | True | 0.0 | 1.0 | 1.333 | 23 | 1709 | 0.97 | ref-file |
| nw36 | ok | 7314.0 | 7314.0 | True | 0.0 | 1.0 | 1.415 | 20 | 1783 | 1.34 | ref-file |
| nw37 | ok | 10068.0 | 10068.0 | True | 0.0 | 1.0 | 1.204 | 19 | 770 | 0.04 | ref-file |
| nw38 | ok | 5558.0 | 5558.0 | True | 0.0 | 1.0 | 1.751 | 23 | 1220 | 0.54 | ref-file |
| nw39 | ok | 10080.0 | 10080.0 | True | 0.0 | 1.0 | 1.357 | 25 | 677 | 0.18 | ref-file |
| nw40 | ok | 10809.0 | 10809.0 | True | 0.0 | 1.0 | 1.255 | 19 | 404 | 0.05 | ref-file |
| nw41 | ok | 11307.0 | 11307.0 | True | 0.0 | 1.0 | 1.109 | 17 | 197 | 0.02 | ref-file |
| nw42 | ok | 7656.0 | 7656.0 | True | 0.0 | 1.0 | 1.572 | 23 | 1079 | 0.43 | ref-file |
| nw43 | ok | 8904.0 | 8904.0 | True | 0.0 | 1.0 | 1.229 | 18 | 1072 | 0.06 | ref-file |
| aa01 | ok | 56137.0 | 56137.0 | True | 0.0 | 1.0 | 55.382 | 823 | 8904 | 45.9 | ref-file |
| aa02 | ok | 30494.0 | 30494.0 | True | 0.0 | 1.0 | 1.523 | 531 | 5198 | 0.98 | ref-file |
| aa03 | ok | 49649.0 | 49649.0 | True | 0.0 | 1.0 | 3.04 | 825 | 8627 | 5.17 | ref-file |
| aa04 | ok | 26374.0 | 26374.0 | True | 0.0 | 1.0 | 52.027 | 426 | 7195 | 41.5 | ref-file |
| aa05 | ok | 53839.0 | 53839.0 | True | 0.0 | 1.0 | 6.36 | 801 | 8308 | 8.91 | ref-file |
| aa06 | ok | 27040.0 | 27040.0 | True | 0.0 | 1.0 | 5.514 | 646 | 7292 | 8.06 | ref-file |
| kl01 | ok | 1086.0 | 1086.0 | True | 0.0 | 1.0 | 2.128 | 55 | 7479 | 1.53 | ref-file |
| kl02 | ok | 219.0 | 219.0 | True | 0.0 | 1.0 | 11.694 | 71 | 36699 | 4.79 | ref-file |
| us02 | ok | 5965.0 | 5965.0 | True | 0.0 | 1.0 | 1.948 | 100 | 13635 | 35.48 | ref-file |
| us03 | ok | 5338.0 | 5338.0 | True | 0.0 | 1.0 | 5.219 | 77 | 85552 | 127.16 | computed |
| us04 | ok | 17854.0 | 17854.0 | True | 0.0 | 1.0 | 2.424 | 163 | 28016 | 18.46 | computed |

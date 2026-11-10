# nagy2015 (VRPDDP) solver: calibration on the Salhi-Nagy CMT X/Y instances

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.

Instances: Salhi and Nagy (1999) CMT X and Y sets, as published in github.com/falcopt/FSPD at commit de480ce4c59accc9f71c76c76f32b707ee7305ad, converted to the FrontierOR nagy2015 schema with distances rounded to the nearest integer. Route-length and service-time limits of CMT6-10, 13, 14 are ignored (nagy2015 has none), so those rows are not comparable with published VRPSPD tables. Each run is a subprocess call of solve.py exactly as the FrontierOR sandbox invokes it; every solution is re-checked independently.

- ddp_auto: the submission candidate (own construction, then PyVRP), 60 s
- ddp_own: the numpy-only fallback engine, 60 s
- spd_auto: the same instance without splitting (VRPSPD), 30 s; split saving = (spd - ddp) / spd

## Tally

```
{
 "instances_run": 28,
 "skipped": [],
 "auto_infeasible": [],
 "auto_overtime": [],
 "own_infeasible": [],
 "own_overtime": [],
 "auto_engines": [
  "own"
 ],
 "pyvrp_errors": [
  "TypeError: __init__(): incompatible constructor arguments. The following argument types are supported:\n    1. pyvrp._pyvrp.Depot(location: typing.SupportsInt, tw_early: int = 0, tw_late: int = 922337203685477580"
 ],
 "mean_own_over_auto": 1.00983,
 "max_own_over_auto": 1.08241,
 "ddp_le_spd": 8,
 "ddp_lt_spd": 8,
 "mean_split_saving_pct": -6.527,
 "max_split_saving_pct": 10.028,
 "tiny_auto_optimal": 0,
 "tiny_own_optimal": 0,
 "tiny_total": 12,
 "anchor_gaps_pct": {
  "CMTX/CMT1": 1.199,
  "CMTY/CMT1": 3.33
 }
}
```

## Per instance

| instance | n | ddp auto | ddp own | own/auto | spd auto | split saving % | auto wall s |
|---|---|---|---|---|---|---|---|
| CMTX/CMT1 | 50 | 476.0 | 488.0 | 1.02521 | 470.0 | -1.277 | 52.94 |
| CMTY/CMT1 | 50 | 496.0 | 491.0 | 0.98992 | 470.0 | -5.532 | 53.09 |
| CMTX/CMT2 | 75 | 837.0 | 814.0 | 0.97252 | 686.0 | -22.012 | 52.93 |
| CMTY/CMT2 | 75 | 839.0 | 784.0 | 0.93445 | 693.0 | -21.068 | 52.95 |
| CMTX/CMT3 | 100 | 793.0 | 835.0 | 1.05296 | 725.0 | -9.379 | 53.01 |
| CMTY/CMT3 | 100 | 767.0 | 779.0 | 1.01565 | 724.0 | -5.939 | 52.99 |
| CMTX/CMT4 | 150 | 1008.0 | 1014.0 | 1.00595 | 966.0 | -4.348 | 52.99 |
| CMTY/CMT4 | 150 | 991.0 | 992.0 | 1.00101 | 885.0 | -11.977 | 52.94 |
| CMTX/CMT5 | 199 | 1240.0 | 1338.0 | 1.07903 | 1107.0 | -12.014 | 52.96 |
| CMTY/CMT5 | 199 | 1142.0 | 1159.0 | 1.01489 | 1236.0 | 7.605 | 52.95 |
| CMTX/CMT6 | 50 | 476.0 | 476.0 | 1.0 | 470.0 | -1.277 | 52.95 |
| CMTY/CMT6 | 50 | 491.0 | 491.0 | 1.0 | 470.0 | -4.468 | 52.97 |
| CMTX/CMT7 | 75 | 801.0 | 798.0 | 0.99625 | 679.0 | -17.968 | 52.98 |
| CMTY/CMT7 | 75 | 760.0 | 789.0 | 1.03816 | 693.0 | -9.668 | 52.95 |
| CMTX/CMT8 | 100 | 793.0 | 793.0 | 1.0 | 721.0 | -9.986 | 52.94 |
| CMTY/CMT8 | 100 | 753.0 | 760.0 | 1.0093 | 716.0 | -5.168 | 52.94 |
| CMTX/CMT9 | 150 | 1016.0 | 1010.0 | 0.99409 | 966.0 | -5.176 | 52.99 |
| CMTY/CMT9 | 150 | 991.0 | 993.0 | 1.00202 | 885.0 | -11.977 | 52.99 |
| CMTX/CMT10 | 199 | 1262.0 | 1366.0 | 1.08241 | 1104.0 | -14.312 | 53.0 |
| CMTY/CMT10 | 199 | 1137.0 | 1137.0 | 1.0 | 1157.0 | 1.729 | 52.94 |
| CMTX/CMT11 | 120 | 937.0 | 936.0 | 0.99893 | 941.0 | 0.425 | 52.94 |
| CMTY/CMT11 | 120 | 917.0 | 916.0 | 0.99891 | 921.0 | 0.434 | 52.94 |
| CMTX/CMT12 | 100 | 646.0 | 672.0 | 1.04025 | 718.0 | 10.028 | 52.93 |
| CMTY/CMT12 | 100 | 797.0 | 808.0 | 1.0138 | 670.0 | -18.955 | 53.0 |
| CMTX/CMT13 | 120 | 937.0 | 934.0 | 0.9968 | 946.0 | 0.951 | 53.04 |
| CMTY/CMT13 | 120 | 915.0 | 915.0 | 1.0 | 921.0 | 0.651 | 52.97 |
| CMTX/CMT14 | 100 | 669.0 | 650.0 | 0.9716 | 695.0 | 3.741 | 52.94 |
| CMTY/CMT14 | 100 | 776.0 | 808.0 | 1.04124 | 670.0 | -15.821 | 52.94 |

## Literature anchor (VRPSPD, unrounded distances, 30 s)

| instance | ours | published optimum | gap % |
|---|---|---|---|
| CMTX/CMT1 | 472.368678426 | 466.77 | 1.199 |
| CMTY/CMT1 | 482.312093358 | 466.77 | 3.33 |

## Tiny random instances vs exact optimum (10 s each)

| seed | n | optimum | auto | own |
|---|---|---|---|---|
| 1 | 4 | 244.0 | 178.0 | 178.0 |
| 2 | 4 | 356.0 | 185.0 | 185.0 |
| 3 | 4 | 280.0 | 185.0 | 185.0 |
| 4 | 4 | 210.0 | 128.0 | 128.0 |
| 5 | 4 | 164.0 | 112.0 | 112.0 |
| 6 | 4 | 356.0 | 255.0 | 255.0 |
| 7 | 5 | 196.0 | 149.0 | 149.0 |
| 8 | 5 | 254.0 | 166.0 | 166.0 |
| 9 | 5 | 181.0 | 162.0 | 162.0 |
| 10 | 5 | 158.0 | 119.0 | 119.0 |
| 11 | 5 | 171.0 | 115.0 | 115.0 |
| 12 | 5 | 128.0 | 106.0 | 106.0 |

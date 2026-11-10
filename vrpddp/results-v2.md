# nagy2015 (VRPDDP) solver v2: calibration on the Salhi-Nagy CMT X/Y instances

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.

Instances: Salhi and Nagy (1999) CMT X and Y sets, as published in github.com/falcopt/FSPD at commit de480ce4c59accc9f71c76c76f32b707ee7305ad, converted to the FrontierOR nagy2015 schema with distances rounded to the nearest integer. Route-length and service-time limits of CMT6-10, 13, 14 are ignored (nagy2015 has none), so those rows are not comparable with published VRPSPD tables. Each run is a subprocess call of solve.py exactly as the FrontierOR sandbox invokes it; every solution is re-checked independently.

- ddp_auto: the submission candidate (portfolio: PyVRP divisible, PyVRP non-divisible, own), 60 s
- ddp_own: the numpy-only fallback engine (non-divisible first, then divisible), 60 s
- spd_auto: the same instance without splitting (VRPSPD), 30 s; split saving = (spd - ddp) / spd

## Tally

```
{
 "instances_run": 24,
 "skipped": [
  "CMTY/CMT1",
  "CMTY/CMT2",
  "CMTY/CMT3",
  "CMTY/CMT4"
 ],
 "auto_infeasible": [
  "CMTX/CMT4",
  "CMTY/CMT10"
 ],
 "auto_overtime": [
  "CMTX/CMT4",
  "CMTY/CMT10"
 ],
 "own_infeasible": [
  "CMTX/CMT6",
  "CMTY/CMT13"
 ],
 "own_overtime": [
  "CMTX/CMT6",
  "CMTY/CMT13"
 ],
 "auto_engines": [
  "None",
  "own",
  "pyvrp",
  "pyvrp_spd"
 ],
 "auto_pyvrp_ran": 22,
 "pyvrp_errors": [],
 "mean_own_over_auto": 1.03237,
 "max_own_over_auto": 1.09566,
 "ddp_le_spd": 12,
 "ddp_lt_spd": 11,
 "mean_split_saving_pct": -0.379,
 "max_split_saving_pct": 1.458,
 "tiny_auto_optimal": 12,
 "tiny_own_optimal": 12,
 "tiny_below_optimum": 0,
 "tiny_total": 12,
 "anchor_gaps_pct": {
  "CMTX/CMT1": 1.199,
  "CMTY/CMT1": null
 }
}
```

## Per instance

| instance | n | ddp auto | engine | ddp own | own/auto | spd auto | split saving % | auto wall s |
|---|---|---|---|---|---|---|---|---|
| CMTX/CMT1 | 50 | 470.0 | pyvrp | 479.0 | 1.01915 | 469.0 | -0.213 | 52.97 |
| CMTY/CMT1 | | | | | | | skipped: file missing | |
| CMTX/CMT2 | 75 | 676.0 | pyvrp | 690.0 | 1.02071 | 686.0 | 1.458 | 52.95 |
| CMTY/CMT2 | | | | | | | skipped: file missing | |
| CMTX/CMT3 | 100 | 713.0 | pyvrp | 730.0 | 1.02384 | 715.0 | 0.28 | 53.0 |
| CMTY/CMT3 | | | | | | | skipped: file missing | |
| CMTX/CMT4 | 150 | NO: timeout | None | 924.0 | None | 849.0 | None | 170.63 |
| CMTY/CMT4 | | | | | | | skipped: file missing | |
| CMTX/CMT5 | 199 | 1014.0 | own | 1111.0 | 1.09566 | 1021.0 | 0.686 | 52.96 |
| CMTY/CMT5 | 199 | 1027.0 | pyvrp_spd | 1047.0 | 1.01947 | 1019.0 | -0.785 | 52.94 |
| CMTX/CMT6 | 50 | 470.0 | pyvrp | NO: timeout | None | 469.0 | -0.213 | 52.96 |
| CMTY/CMT6 | 50 | 464.0 | pyvrp_spd | 472.0 | 1.01724 | 464.0 | 0.0 | 52.95 |
| CMTX/CMT7 | 75 | 676.0 | pyvrp | 690.0 | 1.02071 | 686.0 | 1.458 | 53.03 |
| CMTY/CMT7 | 75 | 683.0 | own | 694.0 | 1.01611 | 685.0 | 0.292 | 52.95 |
| CMTX/CMT8 | 100 | 713.0 | pyvrp | 727.0 | 1.01964 | 715.0 | 0.28 | 53.02 |
| CMTY/CMT8 | 100 | 716.0 | own | 731.0 | 1.02095 | 710.0 | -0.845 | 52.94 |
| CMTX/CMT9 | 150 | 844.0 | own | 924.0 | 1.09479 | 849.0 | 0.589 | 52.94 |
| CMTY/CMT9 | 150 | 845.0 | own | 866.0 | 1.02485 | 849.0 | 0.471 | 52.95 |
| CMTX/CMT10 | 199 | 1014.0 | own | 1099.0 | 1.08383 | 1021.0 | 0.686 | 53.03 |
| CMTY/CMT10 | 199 | NO: timeout | None | 1042.0 | None | 1018.0 | None | 1238.93 |
| CMTX/CMT11 | 120 | 866.0 | own | 909.0 | 1.04965 | 833.0 | -3.962 | 52.93 |
| CMTY/CMT11 | 120 | 868.0 | own | 866.0 | 0.9977 | 853.0 | -1.758 | 52.96 |
| CMTX/CMT12 | 100 | 670.0 | pyvrp_spd | 688.0 | 1.02687 | 663.0 | -1.056 | 52.98 |
| CMTY/CMT12 | 100 | 665.0 | own | 685.0 | 1.03008 | 669.0 | 0.598 | 52.97 |
| CMTX/CMT13 | 120 | 866.0 | own | 913.0 | 1.05427 | 833.0 | -3.962 | 52.96 |
| CMTY/CMT13 | 120 | 869.0 | own | NO: timeout | None | 853.0 | -1.876 | 53.01 |
| CMTX/CMT14 | 100 | 670.0 | pyvrp_spd | 688.0 | 1.02687 | 663.0 | -1.056 | 52.94 |
| CMTY/CMT14 | 100 | 665.0 | own | 655.0 | 0.98496 | 669.0 | 0.598 | 52.98 |

## Literature anchor (VRPSPD, unrounded distances, 30 s)

| instance | ours | published optimum | gap % |
|---|---|---|---|
| CMTX/CMT1 | 472.368678426 | 466.77 | 1.199 |
| CMTY/CMT1 | None | None | None |

## Tiny random instances vs exact optimum (10 s each)

| seed | n | optimum | non-divisible optimum | auto | own |
|---|---|---|---|---|---|
| 1 | 4 | 178.0 | 178.0 | 178.0 | 178.0 |
| 2 | 4 | 185.0 | 185.0 | 185.0 | 185.0 |
| 3 | 4 | 185.0 | 185.0 | 185.0 | 185.0 |
| 4 | 4 | 128.0 | 128.0 | 128.0 | 128.0 |
| 5 | 4 | 112.0 | 112.0 | 112.0 | 112.0 |
| 6 | 4 | 255.0 | 255.0 | 255.0 | 255.0 |
| 7 | 5 | 149.0 | 149.0 | 149.0 | 149.0 |
| 8 | 5 | 166.0 | 166.0 | 166.0 | 166.0 |
| 9 | 5 | 162.0 | 162.0 | 162.0 | 162.0 |
| 10 | 5 | 119.0 | 119.0 | 119.0 | 119.0 |
| 11 | 5 | 115.0 | 115.0 | 115.0 | 115.0 |
| 12 | 5 | 106.0 | 106.0 | 106.0 | 106.0 |

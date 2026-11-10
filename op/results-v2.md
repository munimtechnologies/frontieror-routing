# fischetti1998 (Orienteering Problem) solver v2: OPLib calibration

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.

OPLib commit 823ac3e8c156d45e868c295ee1c95c3fee05bdd2; reference = EA4OP route from OPLib, re-scored with depot prize 0 and re-costed with TSPLIB nint distances. Time limit 60 s per instance, run as the FrontierOR sandbox does (subprocess, solve.py CLI). The v1 column is the earlier solver's result on the same instance (run froc-op-oplib-v1).

## Tally

```
{
 "time_limit_s": 60,
 "instances_run": 39,
 "skipped": [],
 "infeasible": [
  "kroA150-gen1-50",
  "pr76-gen3-50"
 ],
 "overtime": [
  "kroA150-gen1-50",
  "pr76-gen3-50"
 ],
 "with_valid_reference": 37,
 "mean_ratio": 0.98322,
 "min_ratio": 0.84915,
 "matched_or_better": 16,
 "better": 7,
 "exact_small_matched": 10,
 "exact_small_total": 12,
 "v1_compared": 37,
 "v2_better_than_v1": 9,
 "v2_worse_than_v1": 13,
 "mean_v2_over_v1": 0.99045
}
```

## Per instance

| instance | n | t0 | EA4OP ref | v1 | v2 | v2/ref | v2/v1 | feasible | wall s |
|---|---|---|---|---|---|---|---|---|---|
| eil51-gen1-50 | 51 | 213 | 28.0 | 28 | 28.0 | 1.0 | 1.0 | yes | 51.49 |
| berlin52-gen1-50 | 52 | 3771 | 36.0 | 35 | 36.0 | 1.0 | 1.02857 | yes | 51.48 |
| st70-gen1-50 | 70 | 338 | 42.0 | 42 | 42.0 | 1.0 | 1.0 | yes | 51.48 |
| eil76-gen1-50 | 76 | 269 | 45.0 | 45 | 45.0 | 1.0 | 1.0 | yes | 51.37 |
| pr76-gen1-50 | 76 | 54080 | 48.0 | 48 | 47.0 | 0.97917 | 0.97917 | yes | 51.42 |
| rat99-gen1-50 | 99 | 606 | 51.0 | 51 | 51.0 | 1.0 | 1.0 | yes | 51.47 |
| kroA100-gen1-50 | 100 | 10641 | 54.0 | 55 | 55.0 | 1.01852 | 1.0 | yes | 51.71 |
| eil101-gen1-50 | 101 | 315 | 63.0 | 63 | 62.0 | 0.98413 | 0.98413 | yes | 51.77 |
| kroA150-gen1-50 | 150 | 13262 | 85.0 | 81 | None | None | None | NO (timeout) | 966.14 |
| kroA200-gen1-50 | 200 | 14684 | 116.0 | 112 | 108.0 | 0.93103 | 0.96429 | yes | 51.53 |
| tsp225-gen1-50 | 225 | 1958 | 126.0 | 121 | 122.0 | 0.96825 | 1.00826 | yes | 51.44 |
| a280-gen1-50 | 280 | 1290 | 142.0 | 145 | 145.0 | 1.02113 | 1.0 | yes | 51.47 |
| lin318-gen1-50 | 318 | 21015 | 201.0 | 178 | 178.0 | 0.88557 | 1.0 | yes | 51.47 |
| eil51-gen2-50 | 51 | 213 | 1594.0 | 1594 | 1600.0 | 1.00376 | 1.00376 | yes | 51.38 |
| berlin52-gen2-50 | 52 | 3771 | 1823.0 | 1795 | 1795.0 | 0.98464 | 1.0 | yes | 51.4 |
| st70-gen2-50 | 70 | 338 | 2211.0 | 2211 | 2211.0 | 1.0 | 1.0 | yes | 51.38 |
| eil76-gen2-50 | 76 | 269 | 2476.0 | 2455 | 2400.0 | 0.96931 | 0.9776 | yes | 51.41 |
| pr76-gen2-50 | 76 | 54080 | 2634.0 | 2627 | 2627.0 | 0.99734 | 1.0 | yes | 51.49 |
| rat99-gen2-50 | 99 | 606 | 2870.0 | 2853 | 2853.0 | 0.99408 | 1.0 | yes | 51.41 |
| kroA100-gen2-50 | 100 | 10641 | 3138.0 | 3138 | 3138.0 | 1.0 | 1.0 | yes | 51.4 |
| eil101-gen2-50 | 101 | 315 | 3581.0 | 3573 | 3573.0 | 0.99777 | 1.0 | yes | 51.42 |
| kroA150-gen2-50 | 150 | 13262 | 4828.0 | 4799 | 4501.0 | 0.93227 | 0.9379 | yes | 51.54 |
| kroA200-gen2-50 | 200 | 14684 | 6460.0 | 6250 | 6169.0 | 0.95495 | 0.98704 | yes | 51.61 |
| tsp225-gen2-50 | 225 | 1958 | 6862.0 | 6590 | 6626.0 | 0.96561 | 1.00546 | yes | 51.46 |
| a280-gen2-50 | 280 | 1290 | 8230.0 | 7686 | 7709.0 | 0.9367 | 1.00299 | yes | 51.42 |
| lin318-gen2-50 | 318 | 21015 | 10792.0 | 9246 | 9164.0 | 0.84915 | 0.99113 | yes | 51.43 |
| eil51-gen3-50 | 51 | 213 | 1398.0 | 1398 | 1399.0 | 1.00072 | 1.00072 | yes | 51.42 |
| berlin52-gen3-50 | 52 | 3771 | 1034.0 | 1036 | 1036.0 | 1.00193 | 1.0 | yes | 51.39 |
| st70-gen3-50 | 70 | 338 | 2108.0 | 2108 | 2093.0 | 0.99288 | 0.99288 | yes | 51.45 |
| eil76-gen3-50 | 76 | 269 | 2467.0 | 2462 | 2467.0 | 1.0 | 1.00203 | yes | 51.39 |
| pr76-gen3-50 | 76 | 54080 | 2430.0 | 2426 | None | None | None | NO (timeout) | 1440.96 |
| rat99-gen3-50 | 99 | 606 | 2886.0 | 2868 | 2880.0 | 0.99792 | 1.00418 | yes | 51.58 |
| kroA100-gen3-50 | 100 | 10641 | 3180.0 | 3211 | 3192.0 | 1.00377 | 0.99408 | yes | 51.36 |
| eil101-gen3-50 | 101 | 315 | 3345.0 | 3335 | 3343.0 | 0.9994 | 1.0024 | yes | 51.48 |
| kroA150-gen3-50 | 150 | 13262 | 5019.0 | 5019 | 5019.0 | 1.0 | 1.0 | yes | 51.99 |
| kroA200-gen3-50 | 200 | 14684 | 6114.0 | 6029 | 5903.0 | 0.96549 | 0.9791 | yes | 51.64 |
| tsp225-gen3-50 | 225 | 1958 | 7584.0 | 7671 | 7496.0 | 0.9884 | 0.97719 | yes | 51.89 |
| a280-gen3-50 | 280 | 1290 | 7720.0 | 9681 | 8987.0 | 1.16412 | 0.92831 | yes | 52.04 |
| lin318-gen3-50 | 318 | 21015 | 10273.0 | 10227 | 9156.0 | 0.89127 | 0.89528 | yes | 51.82 |

## Exactness on 12 random 10-city instances (10 s each)

| seed | optimum | v2 | matched | v1 matched |
|---|---|---|---|---|
| 1 | 54.0 | 54.0 | True | True |
| 2 | 70.0 | 70.0 | True | True |
| 3 | 57.0 | 57.0 | True | True |
| 4 | 35.0 | 35.0 | True | True |
| 5 | 60.0 | 60.0 | True | True |
| 6 | 82.0 | 75.0 | False | False |
| 7 | 65.0 | 64.0 | False | False |
| 8 | 69.0 | 69.0 | True | True |
| 9 | 43.0 | 43.0 | True | True |
| 10 | 71.0 | 71.0 | True | True |
| 11 | 92.0 | 92.0 | True | True |
| 12 | 59.0 | 59.0 | True | True |

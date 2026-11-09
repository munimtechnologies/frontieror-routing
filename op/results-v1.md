# fischetti1998 (Orienteering Problem) solver: OPLib calibration

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0.

OPLib commit 823ac3e8c156d45e868c295ee1c95c3fee05bdd2; reference = EA4OP route from OPLib, re-scored with depot prize 0 and re-costed with TSPLIB nint distances. Time limit 60 s per instance, run as the FrontierOR sandbox does (subprocess, solve.py CLI).

## Tally

```
{
 "time_limit_s": 60,
 "instances_run": 39,
 "skipped": [
  "ch130-gen1-50",
  "ch150-gen1-50",
  "ch130-gen2-50",
  "ch150-gen2-50",
  "ch130-gen3-50",
  "ch150-gen3-50"
 ],
 "infeasible": [],
 "overtime": [],
 "with_valid_reference": 39,
 "mean_ratio": 0.99231,
 "min_ratio": 0.85675,
 "matched_or_better": 18,
 "better": 6,
 "exact_small_matched": 10,
 "exact_small_total": 12
}
```

## Per instance

| instance | n | t0 | EA4OP ref | ours | ratio | feasible | wall s |
|---|---|---|---|---|---|---|---|
| eil51-gen1-50 | 51 | 213 | 28.0 | 28.0 | 1.0 | yes | 51.47 |
| berlin52-gen1-50 | 52 | 3771 | 36.0 | 35.0 | 0.97222 | yes | 51.43 |
| st70-gen1-50 | 70 | 338 | 42.0 | 42.0 | 1.0 | yes | 51.44 |
| eil76-gen1-50 | 76 | 269 | 45.0 | 45.0 | 1.0 | yes | 51.59 |
| pr76-gen1-50 | 76 | 54080 | 48.0 | 48.0 | 1.0 | yes | 51.46 |
| rat99-gen1-50 | 99 | 606 | 51.0 | 51.0 | 1.0 | yes | 51.37 |
| kroA100-gen1-50 | 100 | 10641 | 54.0 | 55.0 | 1.01852 | yes | 51.49 |
| eil101-gen1-50 | 101 | 315 | 63.0 | 63.0 | 1.0 | yes | 51.49 |
| ch130-gen1-50 | | | | | | skipped: instance file missing | |
| ch150-gen1-50 | | | | | | skipped: instance file missing | |
| kroA150-gen1-50 | 150 | 13262 | 85.0 | 81.0 | 0.95294 | yes | 51.45 |
| kroA200-gen1-50 | 200 | 14684 | 116.0 | 112.0 | 0.96552 | yes | 51.47 |
| tsp225-gen1-50 | 225 | 1958 | 126.0 | 121.0 | 0.96032 | yes | 51.39 |
| a280-gen1-50 | 280 | 1290 | 142.0 | 145.0 | 1.02113 | yes | 51.44 |
| lin318-gen1-50 | 318 | 21015 | 201.0 | 178.0 | 0.88557 | yes | 51.45 |
| eil51-gen2-50 | 51 | 213 | 1594.0 | 1594.0 | 1.0 | yes | 51.36 |
| berlin52-gen2-50 | 52 | 3771 | 1823.0 | 1795.0 | 0.98464 | yes | 51.38 |
| st70-gen2-50 | 70 | 338 | 2211.0 | 2211.0 | 1.0 | yes | 51.38 |
| eil76-gen2-50 | 76 | 269 | 2476.0 | 2455.0 | 0.99152 | yes | 51.39 |
| pr76-gen2-50 | 76 | 54080 | 2634.0 | 2627.0 | 0.99734 | yes | 51.38 |
| rat99-gen2-50 | 99 | 606 | 2870.0 | 2853.0 | 0.99408 | yes | 51.37 |
| kroA100-gen2-50 | 100 | 10641 | 3138.0 | 3138.0 | 1.0 | yes | 51.38 |
| eil101-gen2-50 | 101 | 315 | 3581.0 | 3573.0 | 0.99777 | yes | 51.35 |
| ch130-gen2-50 | | | | | | skipped: instance file missing | |
| ch150-gen2-50 | | | | | | skipped: instance file missing | |
| kroA150-gen2-50 | 150 | 13262 | 4828.0 | 4799.0 | 0.99399 | yes | 51.37 |
| kroA200-gen2-50 | 200 | 14684 | 6460.0 | 6250.0 | 0.96749 | yes | 51.36 |
| tsp225-gen2-50 | 225 | 1958 | 6862.0 | 6590.0 | 0.96036 | yes | 51.44 |
| a280-gen2-50 | 280 | 1290 | 8230.0 | 7686.0 | 0.9339 | yes | 51.43 |
| lin318-gen2-50 | 318 | 21015 | 10792.0 | 9246.0 | 0.85675 | yes | 51.44 |
| eil51-gen3-50 | 51 | 213 | 1398.0 | 1398.0 | 1.0 | yes | 51.44 |
| berlin52-gen3-50 | 52 | 3771 | 1034.0 | 1036.0 | 1.00193 | yes | 51.41 |
| st70-gen3-50 | 70 | 338 | 2108.0 | 2108.0 | 1.0 | yes | 51.45 |
| eil76-gen3-50 | 76 | 269 | 2467.0 | 2462.0 | 0.99797 | yes | 51.43 |
| pr76-gen3-50 | 76 | 54080 | 2430.0 | 2426.0 | 0.99835 | yes | 51.36 |
| rat99-gen3-50 | 99 | 606 | 2886.0 | 2868.0 | 0.99376 | yes | 51.37 |
| kroA100-gen3-50 | 100 | 10641 | 3180.0 | 3211.0 | 1.00975 | yes | 51.46 |
| eil101-gen3-50 | 101 | 315 | 3345.0 | 3335.0 | 0.99701 | yes | 51.52 |
| ch130-gen3-50 | | | | | | skipped: instance file missing | |
| ch150-gen3-50 | | | | | | skipped: instance file missing | |
| kroA150-gen3-50 | 150 | 13262 | 5019.0 | 5019.0 | 1.0 | yes | 51.46 |
| kroA200-gen3-50 | 200 | 14684 | 6114.0 | 6029.0 | 0.9861 | yes | 51.43 |
| tsp225-gen3-50 | 225 | 1958 | 7584.0 | 7671.0 | 1.01147 | yes | 51.43 |
| a280-gen3-50 | 280 | 1290 | 7720.0 | 9681.0 | 1.25402 | yes | 51.43 |
| lin318-gen3-50 | 318 | 21015 | 10273.0 | 10227.0 | 0.99552 | yes | 51.45 |

## Exactness on 12 random 10-city instances (10 s each)

| seed | optimum | ours | matched |
|---|---|---|---|
| 1 | 54.0 | 54.0 | True |
| 2 | 70.0 | 70.0 | True |
| 3 | 57.0 | 57.0 | True |
| 4 | 35.0 | 35.0 | True |
| 5 | 60.0 | 60.0 | True |
| 6 | 82.0 | 75.0 | False |
| 7 | 65.0 | 64.0 | False |
| 8 | 69.0 | 69.0 | True |
| 9 | 43.0 | 43.0 | True |
| 10 | 71.0 | 71.0 | True |
| 11 | 92.0 | 92.0 | True |
| 12 | 59.0 | 59.0 | True |

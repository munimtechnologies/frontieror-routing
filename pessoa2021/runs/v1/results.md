# pessoa2021 (robust CVRP) solver v0.1.0 on the public FrontierOR instances, official checker

Repository munimtechnologies/frontieror-routing at ab8189c944560facaab73150a017956dd685ec92 (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). score = min(2, Gurobi's stored objective / ours); gap = 100 * (ours - Gurobi) / Gurobi, negative = better than Gurobi. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| variant | official accepts | mean score, 5 large | large better than Gurobi | large matched or better | per instance: ours / Gurobi |
|---|---|---|---|---|---|
| v010-60s | 6/6 | 1.0 | 0 | 5 | large_1 2698.0 / 2698.0; large_2 2315.0 / 2315.0; large_3 2698.0 / 2698.0; large_4 2312.0 / 2312.0; large_5 2702.0 / 2702.0; tiny 380.0 / 380.0 |
| v010-10s | 6/6 | 0.999667 | 0 | 3 | large_1 2698.0 / 2698.0; large_2 2318.0 / 2315.0; large_3 2698.0 / 2698.0; large_4 2312.0 / 2312.0; large_5 2703.0 / 2702.0; tiny 380.0 / 380.0 |
| v010-1w-60s | 6/6 | 0.999926 | 0 | 4 | large_1 2698.0 / 2698.0; large_2 2315.0 / 2315.0; large_3 2698.0 / 2698.0; large_4 2312.0 / 2312.0; large_5 2703.0 / 2702.0; tiny 380.0 / 380.0 |
| v010-seed7-60s | 6/6 | 1.0 | 0 | 5 | large_1 2698.0 / 2698.0; large_2 2315.0 / 2315.0; large_3 2698.0 / 2698.0; large_4 2312.0 / 2312.0; large_5 2702.0 / 2702.0; tiny 380.0 / 380.0 |
| v010-300s | 6/6 | 1.0 | 0 | 5 | large_1 2698.0 / 2698.0; large_2 2315.0 / 2315.0; large_3 2698.0 / 2698.0; large_4 2312.0 / 2312.0; large_5 2702.0 / 2702.0; tiny 380.0 / 380.0 |

Checker disagreements (ours vs official): 0

## Instance facts

| instance | customers | vehicles | capacity | Gamma | symmetric | nominal / (m C) | nominal + deviation / (m C) | Gurobi status, runtime s |
|---|---|---|---|---|---|---|---|---|
| large_1 | 80 | 37 | 276 | 6 | True | 0.1987 | 0.2583 | feasible, 29.49 |
| large_2 | 75 | 31 | 223 | 5 | True | 0.2879 | 0.3171 | feasible, 3601.37 |
| large_3 | 80 | 37 | 313 | 6 | True | 0.1752 | 0.2629 | optimal, 8.54 |
| large_4 | 75 | 31 | 257 | 3 | True | 0.2498 | 0.3251 | feasible, 3601.34 |
| large_5 | 80 | 37 | 276 | 8 | True | 0.1987 | 0.2583 | feasible, 3600.65 |
| tiny | 12 | 3 | 131 | 3 | True | 0.6972 | 0.9059 | optimal, 0.58 |

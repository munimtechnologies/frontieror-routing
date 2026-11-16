# vidal2011 (MDPVRP) solver v0.1.0 on the public FrontierOR instances, official checker

Repository munimtechnologies/frontieror-routing at e873819ae0345efd528d874ec2509cf67141bd3a (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). score = min(2, Gurobi's stored objective / ours); gap = 100 * (ours - Gurobi) / Gurobi, negative = better than Gurobi. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| variant | official accepts | mean score, 5 large | large better than Gurobi | per instance: ours / Gurobi |
|---|---|---|---|---|
| v010-60s | 6/6 | 1.001304 | 1 | large_1 10454.18 / 10454.18; large_2 4675.68 / 4675.67; large_3 7498.64 / 7547.53; large_4 8401.46 / 8401.46; large_5 1150.75 / 1150.75; tiny 5113.63 / 5113.63 |
| v010-10s | 6/6 | 1.001304 | 1 | large_1 10454.18 / 10454.18; large_2 4675.68 / 4675.67; large_3 7498.64 / 7547.53; large_4 8401.46 / 8401.46; large_5 1150.75 / 1150.75; tiny 5113.63 / 5113.63 |
| v010-300s | 6/6 | 1.001304 | 1 | large_1 10454.18 / 10454.18; large_2 4675.68 / 4675.67; large_3 7498.64 / 7547.53; large_4 8401.46 / 8401.46; large_5 1150.75 / 1150.75; tiny 5113.63 / 5113.63 |
| v010-1w-60s | 6/6 | 1.000826 | 1 | large_1 10454.18 / 10454.18; large_2 4675.68 / 4675.67; large_3 7516.5 / 7547.53; large_4 8401.46 / 8401.46; large_5 1150.75 / 1150.75; tiny 5113.63 / 5113.63 |

Checker disagreements (ours vs official): 0

## Instance facts

| instance | n | d | t | m | Q | T | visits | patterns (mean/max) | route lower bound | route slots | fleet load share |
|---|---|---|---|---|---|---|---|---|---|---|---|
| large_1 | 20 | 6 | 6 | 3 | 80 | 3800 | 37 | 2.9/6 | 9 | 108 | 0.081 |
| large_2 | 20 | 6 | 6 | 3 | 90 | 3800 | 31 | 3.45/6 | 11 | 108 | 0.094 |
| large_3 | 20 | 6 | 6 | 3 | 90 | 3800 | 32 | 3.3/6 | 11 | 108 | 0.1 |
| large_4 | 20 | 6 | 6 | 3 | 80 | 3800 | 32 | 2.8/6 | 10 | 108 | 0.09 |
| large_5 | 20 | 6 | 6 | 3 | 90 | 3800 | 33 | 3.25/6 | 9 | 108 | 0.081 |
| tiny | 9 | 2 | 2 | 2 | 70 | 3800 | 13 | 1.11/2 | 5 | 8 | 0.6 |

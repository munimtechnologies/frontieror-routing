# fischetti1997 (E-GTSP) solver v0.1.0 on the public FrontierOR instances, official checker

Repository munimtechnologies/frontieror-routing at b8ef7e3ad07b64d8933db73a44b3a237a444c569 (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). score = min(2, Gurobi's stored objective / ours); gap = 100 * (ours - Gurobi) / Gurobi, negative = better than Gurobi. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| variant | official accepts | mean score, 5 large | large better than Gurobi | large matched or better | per instance: ours / Gurobi |
|---|---|---|---|---|---|
| v010-60s | 6/6 | 1.0074 | 2 | 3 | large_1 51230 / 51215.0; large_2 51290 / 52705.0; large_3 51532 / 52197.0; large_4 50027 / 49867.0; large_5 57541 / 57540.99977205023; tiny 1083 / 1083.0 |
| v010-10s | 6/6 | 1.005076 | 2 | 3 | large_1 51230 / 51215.0; large_2 51290 / 52705.0; large_3 52097 / 52197.0; large_4 50059 / 49867.0; large_5 57541 / 57540.99977205023; tiny 1083 / 1083.0 |
| v010-1w-60s | 6/6 | 1.003963 | 2 | 3 | large_1 51344 / 51215.0; large_2 51290 / 52705.0; large_3 51831 / 52197.0; large_4 50489 / 49867.0; large_5 57541 / 57540.99977205023; tiny 1083 / 1083.0 |
| v010-seed7-60s | 6/6 | 1.007732 | 2 | 3 | large_1 51344 / 51215.0; large_2 51256 / 52705.0; large_3 51524 / 52197.0; large_4 49875 / 49867.0; large_5 57541 / 57540.99977205023; tiny 1083 / 1083.0 |

Checker disagreements (ours vs official): 0

## Instance facts

| instance | n | m | cluster size min / mean / max | singletons |
|---|---|---|---|---|
| large_1 | 442 | 89 | 1 / 4.97 / 14 | 3 |
| large_2 | 442 | 89 | 1 / 4.97 / 15 | 4 |
| large_3 | 442 | 89 | 1 / 4.97 / 21 | 13 |
| large_4 | 442 | 89 | 2 / 4.97 / 9 | 0 |
| large_5 | 442 | 89 | 1 / 4.97 / 123 | 50 |
| tiny | 30 | 6 | 3 / 5.0 / 9 | 0 |

# archetti2007 (inventory routing, order-up-to) solver v0.1.0 on the public FrontierOR instances, official checker

Repository munimtechnologies/frontieror-routing at ab8189c944560facaab73150a017956dd685ec92 (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). score = min(2, Gurobi's stored objective / ours); gap = 100 * (ours - Gurobi) / Gurobi. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| variant | official accepts | mean score, 5 large | large better than Gurobi | large within 1% | per instance: ours / Gurobi |
|---|---|---|---|---|---|
| v010-60s | 6/6 | 0.999972 | 1 | 5 | large_1 29161.983737 / 29383.970492; large_2 39023.773163000005 / 38884.936163; large_3 72941.716092 / 72941.716092; large_4 43432.142437999995 / 43425.08474599999; large_5 27622.441523999998 / 27511.084588000005; tiny 1750.321712 / 1750.321712 |
| v010-10s | 6/6 | 0.996492 | 1 | 4 | large_1 29103.139117 / 29383.970492; large_2 39187.463642999995 / 38884.936163; large_3 72941.716092 / 72941.716092; large_4 43432.142437999995 / 43425.08474599999; large_5 28052.722966 / 27511.084588000005; tiny 1750.321712 / 1750.321712 |
| v010-1w-60s | 6/6 | 0.996874 | 1 | 4 | large_1 29132.069938 / 29383.970492; large_2 39059.031672 / 38884.936163; large_3 72951.54091899999 / 72941.716092; large_4 43425.084746 / 43425.08474599999; large_5 28063.567286999998 / 27511.084588000005; tiny 1750.321712 / 1750.321712 |
| v010-seed7-60s | 6/6 | 1.002419 | 3 | 5 | large_1 29013.825464999998 / 29383.970492; large_2 38916.781857 / 38884.936163; large_3 72941.716092 / 72941.716092; large_4 43423.768538000004 / 43425.08474599999; large_5 27507.681849 / 27511.084588000005; tiny 1750.321712 / 1750.321712 |

Checker disagreements (ours vs official): 0

## Instance facts and the stored Gurobi answers

| instance | n | H | C / sum r | B0 / sum r | latest-delivery plan fits | Gurobi status, runtime s, MIP gap | Gurobi lower bound |
|---|---|---|---|---|---|---|---|
| large_1 | 50 | 6 | 1.4998 | 2.4063 | False | None, None, None | None |
| large_2 | 50 | 6 | 1.5 | 3.0743 | False | None, None, None | None |
| large_3 | 50 | 6 | 1.4998 | 7.1144 | True | None, None, None | None |
| large_4 | 50 | 6 | 1.6114 | 3.8495 | True | None, None, None | None |
| large_5 | 50 | 6 | 1.4987 | 3.7015 | False | None, None, None | None |
| tiny | 5 | 3 | 1.4975 | 2.6418 | False | None, None, None | None |

# ropke2009 (PDPTW) solver v0.1.0 on the public FrontierOR instances, official checker

Repository munimtechnologies/frontieror-routing at 9bd98c474e95557bd01e80a43877cf7789ef1670 (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). score = min(2, Gurobi's stored objective / ours); gap = 100 * (ours - Gurobi) / Gurobi, negative = better than Gurobi. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| variant | official accepts | mean score, 5 large | large better than Gurobi | large at cap 2 | per instance gap (%) |
|---|---|---|---|---|---|
| ropke-v010-60s | 6/6 | 1.359494 | 5 | 0 | large_1 -47.638, large_2 -28.249, large_3 -16.1017, large_4 -20.182, large_5 -4.6902, tiny 0.0 |
| ropke-v010-10s | 6/6 | 1.358557 | 5 | 0 | large_1 -47.5374, large_2 -28.0967, large_3 -16.1017, large_4 -20.3251, large_5 -4.6612, tiny 0.0 |

Checker disagreements (ours vs official): 0

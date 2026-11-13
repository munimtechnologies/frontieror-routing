# guo2021 solver v0.1.0 on the public FrontierOR instances, official checker

Repository munimtechnologies/frontieror-routing at afcf087a663b19afaf96ce0f3fee9b73b0849024 (kit). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). gap = 100 * (ours - Gurobi's stored objective) / |Gurobi|; negative = better than Gurobi. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| variant | official accepts | mean gap, 5 large (%) | large better than Gurobi | per instance gap (%) |
|---|---|---|---|---|
| guo-v010-60s | 6/6 | -1243.0689 | 5 | large_1 -8.3669, large_2 -1867.8387, large_3 -4.8061, large_4 -7.7495, large_5 -4326.5832, tiny -0.0 |
| guo-v010-10s | 6/6 | -1233.2501 | 5 | large_1 -8.2476, large_2 -1867.6164, large_3 -4.6052, large_4 -7.5871, large_5 -4278.1941, tiny -0.0 |

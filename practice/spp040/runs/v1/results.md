# hoffman1993 (set partitioning) v0.4.0 on the public FrontierOR instances, official checker

Repository munimtechnologies/frontieror-routing at 4aee588752d2039a666903bd88fee3340f0c8b7b; 60.0s per instance; official_score = min(2, Gurobi objective / ours) when the official feasibility_check.py accepts the file and the run finished in time, else 0. v0.3.0 scored 0.273929 (3 of 5 large instances with no output). FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| variant | official accepts | no output / overtime | mean official score (5 large) | per instance |
|---|---|---|---|---|
| spp-v040 | 5/6 | large_4 | 0.593228 | large_1 0.397459, large_2 1.0, large_3 0.568681, large_4 0.0, large_5 1.0, tiny 1.0 |
| spp-v040-highs | 5/6 | large_4 | 0.593228 | large_1 0.397459, large_2 1.0, large_3 0.568681, large_4 0.0, large_5 1.0, tiny 1.0 |
| spp-v040-dfs | 5/6 | large_4 | 0.596586 | large_1 0.41425, large_2 1.0, large_3 0.568681, large_4 0.0, large_5 1.0, tiny 1.0 |

Submission folders: 35128 bytes zipped (limit 4 MB: True); errors: none

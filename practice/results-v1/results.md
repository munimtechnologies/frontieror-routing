# MV2's FrontierOR practice solvers on the real public instances, official checkers

Repository munimtechnologies/frontieror-routing at 36131580d332b820baed72df5f323b279abbacf3; 60.0s per instance; official_score = contest score vs the stored Gurobi objective when the official feasibility_check.py accepts the file, else 0. FrontierOR benchmark: Hugging Face frontieror/FrontierOR (CC BY 4.0). Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| version | task | official accepts | rejected | mean official score (5 large) | Gurobi refs accepted |
|---|---|---|---|---|---|
| spp-v030 | hoffman1993 | 3/6 | - | 0.273929 | 6 |
| spp-v020 | hoffman1993 | 3/6 | - | 0.273929 | 6 |
| darp-v3 | cordeau2006 | 6/6 | - | 1.012069 | 6 |
| darp-v2 | cordeau2006 | 4/6 | large_2, large_5 | 0.609549 | 6 |
| nagy-v3 | nagy2015 | 6/6 | - | 1.100338 | 6 |
| nagy-v2 | nagy2015 | 3/6 | large_2, large_3, large_4 | 0.421414 | 6 |
| op-v1 | fischetti1998 | 6/6 | - | 0.893785 | 6 |

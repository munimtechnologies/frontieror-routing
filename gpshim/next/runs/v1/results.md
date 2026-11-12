# gpshim census: FrontierOR's reference models on open-source HiGHS

Benchmark revision ef42a2eac13595453f986d9df0b62e86e75ab596 (Hugging Face frontieror/FrontierOR, CC BY 4.0); repository munimtechnologies/frontieror-routing at a5d4e7be76148477afe198c9acf56aa147e82bd1; highspy present. Each task's own gurobi_code.py ran unchanged with gpshim standing in for gurobipy, the contest way; the official feasibility_check.py judged every output. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| stage | runs | accepted | score >= 0.99 | median score (accepted) | mean score (all runs) | statuses |
|---|---|---|---|---|---|---|
| tiny | 37 | 24 | 23 | 1.0 | 0.648649 | accepted 24, crash 4, no_solution 5, overtime 1, rejected 3 |
| large_1 | 28 | 5 | 1 | 0.890494 | 0.121865 | accepted 5, crash 8, no_solution 10, overtime 2, overtime_no_output 2, rejected 1 |

## Most common failures (tiny)

- 1: `gpshim.GurobiError: gpshim: quadratic constraint 'norm_N' has a term that is neither a product with a binary variable nor a bounded convex square` (amaldi2013)
- 1: `gpshim.GurobiError: gpshim: quadratic constraint 'persp_N' has a term that is neither a product with a binary variable nor a bounded convex square` (bertsimas2022)
- 1: `gpshim.GurobiError: gpshim: quadratic constraint 'weymouth_N_N' has a term that is neither a product with a binary variable nor a bounded convex square` (byeon2022)
- 1: `gpshim.GurobiError: gpshim: the objective has a quadratic term that is neither a product with a binary variable nor a bounded convex square (or the model is a M` (hassannayebi2016)

# refgap v0.1.0: how strong are FrontierOR's stored Gurobi references? Pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0, text CC BY 4.0.
Written 2026-11-13 at about 19:45 UTC, before the run `froc-refgap-v1` was filed. Its first step waits until this
file is public here. Results go in `score-v1.md` next to this file, whether the guesses hold or not.

## Why
The FrontierOR Challenge scores each answer against a reference objective, capped at 2. On guo2021, MV2's 60 s
heuristic scored a mean of 1.44 over the 5 large public instances ([score](../orsched/guo2021/score-v1.md)), because
Gurobi's stored one-hour answer was far from good on two of them. The benchmark's own hard-set inputs say only whether
Gurobi timed out, not how far from its bound it stopped. This census measures that for every task. It shows where a
fast, problem-specific heuristic can score well above 1, and so which solvers to build next. We have not seen this
measured in public for FrontierOR.

## What `refgap.py` does
For every task of the public benchmark (Hugging Face `frontieror/FrontierOR`, revision `ef42a2eac135`, CC BY 4.0):
reads the task's `gurobi_code.py` to tell minimise from maximise, and reads the scalar fields (objective, MIP gap,
status, runtime) of every stored Gurobi solution. Files up to 3 MB are read whole; bigger ones only by their first and
last 64 KB. It also reads the benchmark's `metadata/gurobi_references.csv.gz`. For each case it takes
bound = objective -/+ gap x |objective| (Gurobi's definition of the gap) and the **ceiling** = the contest score an
answer equal to that bound would get. Ceiling 1 means Gurobi proved its answer optimal. Ceiling 2 means even the cap
may be reachable. The ceiling is an upper limit, not a forecast: reaching Gurobi's bound is usually impossible.

## Guesses (probabilities written before any result)
| id | guess | p |
|---|---|---|
| H1 | All unit tests pass. | 0.90 |
| H2 | At least 170 of the 180 tasks are read without error, and at least 90% of large-instance solution files give an objective. | 0.70 |
| H3 | At least 80% of large cases have a usable gap (a stored MIP gap, a stored bound, or an optimal status). | 0.55 |
| H4 | guo2021 large_2 and large_5 both have ceiling 2. | 0.75 |
| H5 | At least 10 of the 50 hard-set tasks have a large case with gap >= 10%. | 0.60 |
| H6 | Besides guo2021, at least 5 tasks have at least one large case with ceiling 2. | 0.50 |
| H7 | At least one task whose application field is "Transportation & Logistics" is in the top 15 by mean large ceiling. | 0.55 |

## What we will do with the result
- Tasks with a mean large ceiling of at least 1.3 that have no hand-built solver yet become the next build targets,
  in ceiling order, with ties broken by how small the instances are.
- The table is published in full (`runs/v1/`) so anyone can check it against the benchmark.
- Honest limits: the contest scores private instances against its own frozen best-known values, which may be stronger
  than these public Gurobi answers. A gap read from a file's first and last 64 KB may miss a key stored in the middle.
  The sense is read from code text and may be wrong for a task that sets it unusually; such tasks are listed.

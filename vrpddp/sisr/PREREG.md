# nagy2015 on the real FrontierOR instances: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; text CC BY 4.0.

Written on 2026-11-14 (UTC) in run 20261114T002909Z. At this point:
- the new SISR engine in this folder had not been run anywhere, not even its own tests;
- [`vrpddp/nagy2015/solve.py`](../nagy2015/solve.py) v0.2.0 had been run only on the literature CMT X/Y instances ([score](../score-v2.md)), never on FrontierOR's own instances or under the official checker.

## The task

[FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR) (CC BY 4.0) task `nagy2015` is the vehicle routing problem with divisible deliveries and pickups (Nagy, Wassan, Speranza and Archetti, Transportation Science 2015).
- Each customer has a delivery from the depot and a pickup back to it.
- The two may be served on separate visits, even by different vehicles, but each one is served whole in a single visit.
- The load on board must never exceed the capacity. That load is the deliveries still to drop plus the pickups already collected.
- The objective is to minimise total distance.

The benchmark ranks it 5th hardest of its 180 tasks.
- **Gurobi's model:** a two-index formulation with arc flows. On the large instances (199 customers, 398 visit nodes) it has about 477,600 variables, with no subtour cuts beyond 2-cycles. Gurobi stopped at its one-hour limit on all five large instances.
- **MV2's general-purpose engine:** HiGHS behind a Gurobi-style shim found no answer on large_1 in 60 s.
- **One checker rule worth noting:** no arc may go from a customer's pickup node n+i straight to its own delivery node i (constraint 15).

## What runs (job `froc-nagy2015-v1`)

The job runs on the 6 public instances (tiny + large_1..5), the contest way, and the official `feasibility_check.py` judges each output.
- **`v020-auto-60s`:** `vrpddp/nagy2015/solve.py` v0.2.0 as published, at the commit the job downloads. Its default engine is a portfolio: PyVRP on the divisible model, PyVRP on the non-divisible model, then its own numpy search. The job installs numpy and PyVRP.
- **`sisr-60s` and `sisr-10s`:** this folder's new engine, standard library only.
  - **Model:** the checker's own expanded graph.
  - **Insertion check:** O(1) per position, using prefix and suffix maxima of the route's load profile. A test checks this rule against direct simulation.
  - **Search:** SISR ruin and recreate (Christiaens & Vanden Berghe 2020), with string and split-string removals, insertion with 1% blinks, and simulated annealing.
  - **Checker rule:** it never writes an arc pickup(i) -> delivery(i). Swapping the two visits costs no distance and only lowers the load.
  - **Mirror:** `verify()` repeats the official checks.

Score = min(2, Gurobi's stored objective / ours). That is the contest's formula, but here it is applied against the stored Gurobi answer. The contest's own frozen reference may be stronger, so no score here is a contest claim.

## Guesses (probabilities fixed now)

| id | guess | p |
|---|---|---|
| N1 | Every unit test passes in the job's first test step (TestContestWay is skipped there) | 0.65 |
| N2 | The official checker accepts all 6 cases of `sisr-60s` | 0.85 |
| N3 | The official checker accepts all 6 cases of `v020-auto-60s` | 0.55 |
| N4 | Our `verify()` agrees with the official checker on every run that wrote an answer and on all 6 stored Gurobi solutions | 0.80 |
| N5 | `sisr-60s`: mean score over the 5 large instances >= 1.05 | 0.65 |
| N6 | `sisr-60s`: strictly better than Gurobi on at least 4 of the 5 large instances | 0.70 |
| N7 | The better of the two 60 s variants has mean large score >= 1.25 | 0.35 |
| N8 | `v020-auto-60s` mean large score >= `sisr-60s` mean large score | 0.55 |
| N9 | tiny, `sisr-60s`: objective = 948 (the optimum HiGHS proved for this model in MV2's run froc-gpshim02-v1) | 0.85 |
| N10 | Mean large score of `sisr-10s` >= that of `sisr-60s` minus 0.03 | 0.55 |
| N11 | No run in any variant ends overtime, with no output, or crashed | 0.80 |
| N12 | TestContestWay passes: the solver's tiny answer is accepted by the official checker, and both checkers agree on all 80 mutated tiny solutions | 0.70 |

Grading uses `summary.json` (`official_feasible`, `ours_agree_official`, `gurobi_ours_feasible`, `gurobi_official_feasible`, `status`, `objective`, `large_mean_score`, `large_strictly_better`, `back_to_line_arcs`), `tests.txt` and `tests-official.txt`. A failure of v0.2.0 under the official checker is a finding about v0.2.0, not a reason to drop it. It will be reported as it is.

## Limits

- **Pure-Python speed:** the SISR engine manages about 10^4 iterations in 60 s on 398 nodes. Published SISR results use millions of iterations.
- **Single CPU:** one process; the contest machine has 2 vCPUs.
- **Stored references only:** beating Gurobi's stored one-hour answer does not mean beating the contest's frozen best-known reference.

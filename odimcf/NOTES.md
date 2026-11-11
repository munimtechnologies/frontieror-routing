# odimcf/: barnhart2000 (origin-destination integer multicommodity flow)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; this text CC BY 4.0.

v0.1.0 was pre-registered 2026-11-10 ~17:00 UTC, before the calibration job `froc-odimcf-synth-v1` ran, and is graded
in [score-v1.md](score-v1.md). v0.2.0 and its guesses P1-P7 were written 2026-11-11 ~01:00 UTC, before the job
`froc-odimcf-real-v1` was filed. The guesses are graded as written, including any that fail.

## The problem

From the public FrontierOR problem page (https://frontieror-challenge.com/problems/barnhart2000; Barnhart, Hane and
Vance, "Using Branch-and-Price-and-Cut to Solve Origin-Destination Integer Multicommodity Flow Problems", Operations
Research 48(2), 2000). Each commodity (origin, destination, demand) travels unsplit on one path of a directed network
with arc capacities, or is rejected onto an artificial arc whose cost is its lost revenue. The aim is to minimise
routing cost plus rejected revenue. Physical arcs cost nothing on the page's instances; the solver handles nonzero
costs anyway. The time limit is 60 s.

**The rejection penalty (settled).** The page says both that the artificial arc's cost "equals the commodity's lost
revenue" and that the objective is demand x per-unit arc cost. The official `feasibility_check.py`, published with
the FrontierOR benchmark on Hugging Face (`frontieror/FrontierOR`, CC BY 4.0), settles it: a rejected commodity costs
`artificial_arc_cost x demand`, always. It also counts a commodity that is neither rejected nor given at least one
arc as unassigned, and it needs only `arc_id` in each path entry. v0.1.0 had guessed differently when
`artificial_arc_cost` equals `revenue`; v0.2.0 follows the official checker.

## The solver (barnhart2000/solve.py)

1. Reject everything, which is always feasible, and write that at once.
2. Three greedy insertions (value per unit of demand, the same per hop, plain value) on the cheapest, then shortest,
   path through the remaining capacity.
3. Column generation on the path LP (HiGHS through SciPy), priced with one Dijkstra per origin and demand class.
   Every pricing round also gives a Lagrangian lower bound, sum_k min(penalty_k, demand_k x shortest path_k(cost + mu))
   - sum_a mu_a capacity_a, which is valid for any mu >= 0. When the incumbent reaches it, the solver stops early with
   a proof of optimality.
4. LP rounding, then the restricted master problem solved as a MIP over every path generated (price-and-branch, not
   full branch-and-price).
5. For the rest of the time, ruin and recreate: route a rejected commodity on the path that is cheapest to clear,
   evict the cheapest blockers, re-insert them and up to 40 other rejected commodities, and keep the move if the
   objective does not get worse.

v0.2.0 changes only the rules, not the search: the penalty is `artificial_arc_cost x demand`, and a commodity whose
origin equals its destination is always rejected (the official checker would count it as unassigned otherwise).

Tools: `odimcf_check.py` (an independent checker sharing no code with the solver; v0.2.0 follows the official rules
above but stays stricter on one point: a path must be simple, while the official checker tests flow conservation),
`odimcf_exact.py` (an arc-based MIP and a brute force), `odimcf_gen.py` (the instance generator), `odimcf_eval.py`
(the synthetic calibration through `kit/harness.py`), `odimcf_real.py` (the run on the public FrontierOR instances)
and `test_odimcf.py`.

## v0.1.0 calibration on synthetic data (graded in score-v1.md)

We found no public copies of the Barnhart-Hane-Vance instances (search 2026-11-10; the paper does not link data), so
v1 used 20 deterministic synthetic instances (`odimcf_gen.CASES`: S 16-25 nodes and 20-40 commodities, M 36-64 and
80-150, L 100-225 and 400-1,200), with references from the arc MIP (S, M; HiGHS 180 s) or the same solver at 300 s
(L). Result: 20 of 20 feasible, 5 of 7 proven optima matched, never worse than greedy; 5 of 7 guesses held, Brier
0.135.

| id | guess | p | result |
|---|---|---|---|
| O1 | Both test steps pass | 0.75 | held |
| O2 | All 20 feasible, stated = recomputed objective | 0.85 | held |
| O3 | At least 12 of 14 S+M at the arc-MIP reference | 0.60 | did not hold (10) |
| O4 | Mean contest score on S+M >= 0.98 | 0.70 | held (1.092; 1.022 without the weak m8 reference) |
| O5 | At least 4 of 6 L within 1% of the 300 s result | 0.60 | held (4 of the 5 valid; l3's reference run was paused by the host) |
| O6 | Mean gap to the bound on L <= 5% | 0.50 | did not hold (16.5%) |
| O7 | No worse than greedy-only on all 20 | 0.95 | held |

## v0.2.0 on the public FrontierOR instances: guesses written before the job

Job `froc-odimcf-real-v1`: the six public barnhart2000 instances of the FrontierOR benchmark (tiny_instance and
large_instance_1..5, about 118 kB each), downloaded at a pinned dataset revision. Each is solved through the CLI at
60 s, checked by our checker and by the official `feasibility_check.py`, and scored as min(2, Gurobi / ours) against
the objective_value of the published Gurobi solution (which may or may not be the contest's frozen reference). The
Gurobi solutions are re-checked by both checkers too. Then a 30 s column-generation bound, the unit tests, and, as an
optional last step, a 120 s arc-MIP bound on instances with at most 200,000 variables.

We have not seen these instances: their sizes, how tight the capacities are and how good the Gurobi solutions are
(the logs are small, so Gurobi may have stopped on a time limit) are unknown when these guesses are written.

| id | guess | p |
|---|---|---|
| P1 | The unit test step passes (`python odimcf/test_odimcf.py -v`) | 0.80 |
| P2 | The official checker finds all 6 of our solutions feasible | 0.85 |
| P3 | Our checker and the official one agree on all 12 solutions (6 ours + 6 Gurobi) | 0.70 |
| P4 | On the tiny instance we match or beat the Gurobi objective | 0.85 |
| P5 | Mean contest score over the 5 large instances >= 0.98 | 0.55 |
| P6 | At least 3 of the 5 large instances within 1% of Gurobi (or better) | 0.50 |
| P7 | At least 1 large instance strictly better than Gurobi | 0.25 |

MV2, Munim, Inc., mv2@munimtech.com

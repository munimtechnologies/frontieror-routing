# odimcf/: barnhart2000 (origin-destination integer multicommodity flow), v0.1.0

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; this text CC BY 4.0.

Pre-registered 2026-11-10 ~17:00 UTC, before the calibration job `froc-odimcf-synth-v1` ran. The guesses below are
graded as written, including any that fail.

## The problem

From the public FrontierOR problem page (https://frontieror-challenge.com/problems/barnhart2000; Barnhart, Hane and
Vance, "Using Branch-and-Price-and-Cut to Solve Origin-Destination Integer Multicommodity Flow Problems", Operations
Research 48(2), 2000). Each commodity (origin, destination, demand) travels unsplit on one path of a directed network
with arc capacities, or is rejected onto an artificial arc whose cost is its lost revenue. The aim is to minimise
routing cost plus rejected revenue. Physical arcs cost nothing on the page's instances; the solver handles nonzero
costs anyway. The time limit is 60 s.

**Open question (the rejection penalty).** The page says both that the artificial arc's cost "equals the commodity's
lost revenue" and that the objective is demand x per-unit arc cost. The instances carry both `revenue` and
`artificial_arc_cost`. The solver and the checker both take the reading under which the penalty equals `revenue`:
`artificial_arc_cost` if it equals `revenue` for every commodity, otherwise `artificial_arc_cost x demand`. This has to
be checked against the official `feasibility_check.py` before any real submission, because a stated objective that
differs from the recomputed one scores 0. The routing does not change; only the stated value would.

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

Tools: `odimcf_check.py` (an independent checker sharing no code with the solver), `odimcf_exact.py` (an arc-based
MIP and a brute force), `odimcf_gen.py` (the instance generator), `odimcf_eval.py` (the contest-style calibration
through `kit/harness.py`) and `test_odimcf.py`.

## Calibration data

We found no public copies of the Barnhart-Hane-Vance instances (search 2026-11-10; the paper does not link data).
Alvelos and Valério de Carvalho (INOC 2003) list generated unsplittable-flow instances at an old university URL, not
yet checked. So v1 uses 20 deterministic synthetic instances (`odimcf_gen.CASES`):

- **S** (6): 16-25 nodes, 20-40 commodities;
- **M** (8): 36-64 nodes, 80-150 commodities;
- **L** (6): 100-225 nodes, 400-1,200 commodities.

They mix grid and random geometric networks, both penalty conventions and some nonzero arc costs. Capacities are
0.5-0.7 times the load of min-hop routing, with noise.

**References.** S and M use the arc MIP (HiGHS, 180 s; proven where it says so). L uses the same solver given 300 s,
which is not proven. **Bound:** the column-generation Lagrangian bound (30 s), or the MIP's dual bound if higher.
**Score:** min(2, reference / objective), as the contest does when minimising.

## Pre-registered guesses (probability that each holds)

| id | guess | p |
|---|---|---|
| O1 | Both test steps pass (`python odimcf/test_odimcf.py -v`) | 0.75 |
| O2 | All 20 runs are feasible under our checker, with a stated objective equal to the recomputed one | 0.85 |
| O3 | At least 12 of the 14 S+M cases reach the arc-MIP reference (gap <= 1e-6) | 0.60 |
| O4 | Mean contest score on S+M >= 0.98 | 0.70 |
| O5 | On at least 4 of the 6 L cases, the 60 s result is within 1% of the 300 s result | 0.60 |
| O6 | Mean gap to the bound on L <= 5% | 0.50 |
| O7 | The solver is no worse than greedy-only on all 20 cases | 0.95 |

These will be graded in `score-v1.md`, with Brier scores.

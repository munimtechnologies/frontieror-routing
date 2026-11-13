# bode2012 (capacitated arc routing) solver v0.1.0: predictions, written before the first run

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-13, before job `froc-bode2012-v1` has run. Nobody has seen any output of this solver on the public
instances. Results will be graded here, in a separate score file, whichever way they go.

## Why this task

FrontierOR task `bode2012` is the capacitated arc-routing problem (CARP) in the two-index formulation of Bode and
Irnich (Operations Research 2012): a fixed fleet of identical vehicles services every required edge of an undirected
network exactly once, each vehicle's route being a closed walk from the depot; cost = service costs (a constant) +
deadheading.

- The benchmark's hard-selection file (`metadata/hardset/hard_selection_inputs_180.csv`) lists it with 0 of 5 large
  instances "timeout or non-optimal": Gurobi proved every large instance optimal (median 1.86 s, mean 130.5 s,
  maximum 416.3 s). So the best possible contest score here is 1.0 per instance; the point is **coverage**.
- Its Gurobi reference (`gurobi_code.py`) adds the subtour-elimination constraints as lazy constraints in a Gurobi
  callback. MV2's generic engine gpshim 0.2 (the reference model on free solvers) gave **no answer** on large_1
  within 60 s (census `froc-gpshim02-v1`, 2026-11-12). Today a large bode2012 instance scores 0 for MV2.

## What the solver does

Standard library only. Each required edge is a task with two directions; a route is a sequence of directed tasks
joined by shortest deadheading paths (Dijkstra from every node). Any connected even multigraph through the depot is
a closed walk, so this arc-sequence model has the same optimum as the two-index model the checker enforces. Search:
slack induction by string removals (SISR, Christiaens & Vanden Berghe 2020) adapted to arcs: each removed task is
reinserted at its cheapest position **and direction**; simulated annealing on a clock schedule; capacity overload
penalised far above any travel cost. New bests are polished per route (2-opt with direction flips, relocation in
both directions), checked by `verify()` (the official checker's rules) and written atomically. Exactly
`num_vehicles` routes; never more working vehicles than the fleet. A forked second search uses another seed. Stops
at min(0.9 T, T - 3) s.

A note for anyone adapting a vehicle-routing insertion heuristic to arc routing: inserting a task can **lower** the
route cost (the vehicle already deadheads along that edge), so the usual "skip a route whose capacity penalty alone
exceeds the best insertion" shortcut must allow for a saving of up to the edge's shortest end-to-end distance.
`test_insertion_delta_is_exact` checks the chosen insertion against every route, position and direction.

## Inferred instance sizes (not yet seen)

For K vehicles, R required edges, E edges and N nodes the reference model has K(R + E + N) variables (all integer)
and R + K N + K constraints (before lazy cuts). The hard-selection averages are 350 variables, 350 integer variables
and 112 constraints. The five large files are all about 4.5 kB, so if they share one size, K must divide 350 and the
only fits with roughly 25-45 edges (what 4.5 kB of compact JSON holds) are K = 5 (N about 16-20) or K = 7
(N about 13-14). Not pinned down; only B12 depends on it.

## Predictions (probabilities are ours, stated now)

| # | prediction | p |
|---|---|---|
| B1 | All unit tests pass before the run (tests-pre.txt ends `exit=0`). | 0.80 |
| B2 | At 60 s the official checker accepts all 6 answers (tiny + 5 large). | 0.90 |
| B3 | At 10 s the official checker accepts all 6 answers. | 0.90 |
| B4 | v010-60s mean contest score over the 5 large instances is at least 0.995. | 0.85 |
| B5 | v010-60s matches Gurobi's stored (proven optimal) objective exactly on all 5 large instances. | 0.70 |
| B6 | v010-10s mean large score is at least 0.99. | 0.80 |
| B7 | No answer of ours, in any variant, beats Gurobi's stored objective by more than 1e-6 (Gurobi proved optimality; a "win" would mean a modelling or checking difference, to be investigated, not claimed). | 0.95 |
| B8 | Our verify() and the official checker never disagree (0 disagreements over all variants, our answers and Gurobi's). | 0.85 |
| B9 | Fleet probe (`fleet_probe` in summary.json): the official checker ACCEPTS an answer with two working vehicles on a synthetic instance whose fleet is one vehicle, and rejects the honest one-vehicle answer that is over capacity. | 0.85 |
| B10 | Every stored Gurobi answer uses at most K working vehicles and passes our strict verify(). | 0.90 |
| B11 | tests.txt (run with the official checker available) ends `exit=0` and the agreement test ran (not skipped). | 0.75 |
| B12 | Every large instance has at most 60 edges. | 0.85 |

B9 is about the checker, not the solver. The problem text fixes the fleet and the reference model has exactly K
vehicles, but `feasibility_check.py` never counts routes. If B9 holds, an entry could undercut the reference on a
capacity-tight instance by adding vehicles. MV2's solver never does that, and the gap goes to the benchmark
maintainers rather than being used.

Scoring rule used: contest score = min(2, Gurobi's stored objective / ours), 0 for no answer or a rejected one.
Objectives include the constant service-cost part, as the checker computes them. Brier score over B1-B12 will be
reported.

## Limits

Public instances only; the challenge scores private instances. The task's contest time class is not known to us,
so 10 s and 60 s are both run. One run per variant, so seed luck is only checked by v010-seed7-60s and the 1-worker
variant.

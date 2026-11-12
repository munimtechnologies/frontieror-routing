# vidal2011 (multi-depot periodic VRP) solver v0.1.0: pre-registered guesses

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; this text CC BY 4.0.

Written on 2026-11-12 at about 16:30 UTC, before the job `froc-vidal2011-v1` ran. Nobody had seen the instance files or a single run of this code at that point. No test has been run yet; the job runs them for the first time. The guesses will be graded as written, failures included, in `score-v1.md`.

## The task

`vidal2011` in the public FrontierOR benchmark (Hugging Face `frontieror/FrontierOR`, CC BY 4.0) is the multi-depot periodic vehicle routing problem (MDPVRP; Vidal, Crainic, Gendreau, Lahrichi and Rei, CIRRELT-2011-05, Annex 7.1). It is #23 of the benchmark's 50-task hard set. Its stored Gurobi reference stopped at the one-hour limit on all five large instances (`timeout_or_nonoptimal_frac = 1.0`, median Gurobi time 3601 s in `hard_selection_inputs_180.csv`). MV2's generic engine gpshim got no solution at all on this task (its 2026-11-12 census reports "no optimize() logged: no_solution"), because the reference model needs Gurobi's lazy-constraint callback. Until now MV2 had no coverage here.

The rules, as the official `feasibility_check.py` applies them:

- Each customer gets exactly one (depot, visit pattern) pair from its own list. On each period of that pattern it is visited exactly once, by a route of that depot. On every other period it is not visited at all.
- Each depot has m vehicles, numbered 1..m. Each vehicle departs at most once per period.
- Route load must be at most Q. Route duration (travel plus service) must be at most the limit.
- Cost = Euclidean distance on the raw coordinates, with no rounding. The checker recomputes the objective, with a 0.1% tolerance.
- One quirk was noted before the run: the checker's period-domain test reads `instance["p"]`, but the instance schema names the number of periods `t`. If `p` is absent, the period range of routes is never checked. The job records `has_p_key`. Nothing exploits this, and the solver only writes periods 1..t.

## The solver (solve.py, standard library only)

1. Each (depot, period) has m route slots. While searching, a solution may break capacity or duration, at a penalty that adapts every 300 moves. Only solutions that pass `verify()` are written, and every write is atomic. `verify()` is an independent copy of the official rules with a tighter tolerance.
2. Construction: each customer goes to its cheapest (depot, pattern) option, using cheapest penalised insertion.
3. Simulated annealing with eight moves: relocate (best or random), swap, 2-opt, 2-opt* (both reconnections), moving one customer to another (depot, pattern) option (best or random), and ruin-and-recreate of 2 to 12 nearby customers.
4. Four phases: one from the construction, two restarts from the best feasible solution at lower temperatures, and a polish at a 10,000× penalty.
5. With 2 CPUs, a forked child searches with a second seed and hands its best solution back. The deadline is min(0.9 T, T − 3).

`vidal_real.py` runs the solver the contest way on the tiny instance and the five large public instances, with four variants: 60 s, 10 s, 300 s, and 60 s with one worker. Reference = the stored Gurobi objective. Score = min(2, Gurobi / ours).

## Guesses (probability that each holds)

| id | guess | p |
|---|---|---|
| V1 | All tests in `test_vidal2011.py` pass, with the official checker available. These include optimality against brute force on 4 tiny instances and verdict agreement with the official checker on 300 randomly broken solutions | 0.60 |
| V2 | Variant v010-60s: the official checker accepts all 6 solutions, each written within the limit | 0.80 |
| V3 | No checker disagreement is recorded anywhere in the job (ours vs official, our solutions and Gurobi's) | 0.85 |
| V4 | v010-60s: mean contest score on the 5 large instances >= 1.0 | 0.75 |
| V5 | v010-60s: mean contest score on the 5 large instances >= 1.3 | 0.45 |
| V6 | v010-60s: strictly better than the stored Gurobi solution on at least 4 of the 5 large instances | 0.65 |
| V7 | v010-60s on the tiny instance: within 0.1% of Gurobi's objective, or better | 0.85 |
| V8 | Mean large score: v010-300s >= v010-60s, and v010-10s >= 0.97 × v010-60s | 0.65 |
| V9 | Mean large score: v010-60s (2 workers) >= v010-1w-60s (1 worker) | 0.60 |

## Decision rules

- **V2 or V3 fails:** fix the broken rule first and make it a v0.1.1 job.
- **V4 holds:** vidal2011 joins the contest folder's hand solvers (it has no other engine).
- **V4 fails, with all solutions accepted:** read Gurobi's routes against ours to see whether the loss comes from assignment (depot or pattern) or from routing. The next version adds the matching neighbourhood: exact pattern re-optimisation, or a PyVRP per-(depot, period) polish.
- **V8 fails at 10 s:** the 10 s class needs a faster construction-plus-descent path. Then pick the phase split by time class.
- **V9 fails:** the forked child isn't worth it on 2 vCPUs. Drop it and give the parent the time.

MV2, Munim, Inc., mv2@munimtech.com

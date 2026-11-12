# desaulniers2010 (split-delivery VRPTW) solver v0.1.0: pre-registered guesses

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; this text CC BY 4.0.

Written on 2026-11-12 at about 14:00 UTC, before the job `froc-desaulniers-v1` ran and before anyone had seen the instance files or a single run of this code. No test has been run yet; the job runs them for the first time. The guesses are graded as written, failures included, in `score-v1.md`.

## The task

`desaulniers2010` in the public FrontierOR benchmark (Hugging Face `frontieror/FrontierOR`, CC BY 4.0) is the split-delivery vehicle routing problem with time windows (SDVRPTW; Desaulniers, Operations Research 58(1), 2010). It is in the benchmark's 50-task hard set, and Gurobi did not prove optimality on any of its instances (timeout_or_nonoptimal_frac = 1.0 in `hard_selection_inputs_180.csv`). The official `feasibility_check.py` contains these rules:

- A route is 0 → customers → n+1. Travel time = distance (truncated to one decimal) + service time at the origin. Service starts at max(window open, arrival) and must start by window close, including the return depot.
- A vehicle may deliver any quantity up to min(d_i, Q) to a customer it visits. Per vehicle, the total is at most Q. Each customer must receive at least d_i in total. Splitting a delivery is allowed.
- The objective is total distance, and the checker recomputes it (tolerance 0.1%). `num_vehicles_used` must equal `len(routes)`.

## The solver (solve.py)

1. Each customer with d_i > Q first gets floor(d_i / Q) out-and-back routes, each carrying a full load.
2. Construction: singleton routes (written at once), then cheapest feasible insertion.
3. Unsplit VRPTW search with PyVRP's iterated local search (pip package pyvrp, MIT) on an **exact** integer copy. Every distance has one decimal, so ×10 makes all times and costs integers. A forked child runs a second seed. Without pyvrp, a pure-Python relocate + 2-opt* search runs instead.
4. Split-delivery improvement:
   - route elimination by split re-insertion (empty a route, then spread each delivery over routes with spare capacity; this is free where the customer is already on the route, otherwise it costs the cheapest feasible insertion);
   - visit removal by split re-insertion;
   - intra-route or-opt.

   A move is kept only if the total distance drops. Every candidate is re-checked by `verify()`, an independent copy of the official constraints with a tighter tolerance, before it is written.

`desaulniers_real.py` runs three variants on the tiny instance and the five large public instances: PyVRP at 60 s, PyVRP at 10 s, and no PyVRP at 60 s. Each solution goes through the official checker, both as a program and as a function. Reference = the stored Gurobi solution's objective. Score = min(2, Gurobi / ours).

## Guesses (probability that each holds)

| id | guess | p |
|---|---|---|
| D1 | All tests in `test_desaulniers2010.py` pass (official checker available) | 0.55 |
| D2 | Variant v010-60s: the official checker accepts all 6 solutions, each written within 60 s | 0.70 |
| D3 | Our verify() and the official checker agree on every verdict in the job (no recorded disagreement) | 0.75 |
| D4 | Variant v010-60s: mean contest score on the 5 large instances >= 1.0 | 0.70 |
| D5 | Variant v010-60s: strictly better than the stored Gurobi solution on at least 3 of the 5 large instances | 0.60 |
| D6 | Variant v010-60s: the split step strictly lowers the unsplit best on at least 1 large instance (`split_customers` >= 1 and final < unsplit_best) | 0.65 |
| D7 | Mean large score of v010-60s >= that of v010-nopyvrp-60s | 0.85 |
| D8 | Mean large score of v010-10s >= 0.97 × that of v010-60s | 0.70 |

## Decision rules

- **D2 or D3 fails:** fix the rule that broke before anything else, and make it a v0.1.1 job.
- **D4 holds:** desaulniers2010 joins the contest folder's hand solvers. If it fails on some instances, run gpshim (HiGHS/CP-SAT) on them, and use whichever engine scores higher per instance.
- **D6 fails, with the scores still low:** the split step is not where the gain is. The next version spends the time on more PyVRP seeds instead.
- **D7 fails:** PyVRP is not worth the extra package for this task; keep the pure-Python path.

MV2, Munim, Inc., mv2@munimtech.com

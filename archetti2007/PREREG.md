# archetti2007 solver v0.1.0: predictions, published before the first run

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Written 2026-11-13, before `froc-archetti2007-v1` ran. Nobody has run this solver on the real instances yet; it
has not been run anywhere. Its tests run for the first time in the publish lane and in that job.

## Task

FrontierOR task `archetti2007` (Hugging Face `frontieror/FrontierOR`, CC BY 4.0): vendor-managed inventory routing
with the order-up-to policy and one vehicle (Archetti, Bertazzi, Laporte and Speranza 2007, Transportation Science
41(3)). A supplier serves n retailers over H periods. Every visit fills a retailer to its maximum stock, no retailer
may run out through period H + 1, one vehicle with capacity C drives one tour per period, and the supplier must
hold what it ships. The cost is supplier holding + retailer holding + travel.

Why this task: the benchmark's hard-selection file gives 8,613 variables on average, Gurobi timed out on 2 of 5
large instances (fraction 0.4, mean 2,434 s), and MV2's general Gurobi stand-in (gpshim) returned no answer on the
large instances, because the reference model needs Gurobi's lazy subtour callback. So MV2 scores 0 here today.

## Method (solve.py, standard library only)

Under the order-up-to rule, a retailer's plan is fixed by which periods it is visited. Each retailer gets every
stockout-free visit pattern that ships something at each visit (at most 2^H), with its exact holding cost
(retailer holding minus the supplier holding its shipments remove). Simulated annealing changes one retailer's
pattern at a time and prices all its patterns at once (holding + exact removal / cheapest insertion per period,
exact tours up to 4 retailers + an adaptive penalty for capacity and supplier excess), then a strict descent. Two
workers when fork is available. Output is written only after `verify()` (the checker's rules) accepts it.

## Predictions (graded against `froc-archetti2007-v1`, out/archetti2007/)

- **A1** `tests-pre.txt` ends `exit=0`: every test passes in the container before the real run.
- **A2** v010-60s: the official checker accepts 6 of 6 (tiny + 5 large).
- **A3** 0 disagreements between `verify()` and the official checker, over all variants and the stored Gurobi
  files; `tests.txt` (run with `ARCH_OFFICIAL`) ends `exit=0`, including the 40+ case agreement test.
- **A4** All 5 large instances have n = 50 and H = 6. (Inferred, not read: with H = 6 the Gurobi model has
  3n(n+1) + 19n + 13 variables, which is 8,613 at n = 50, the benchmark's average.)
- **A5** The stored Gurobi answers: 3 of 5 large are OPTIMAL and 2 are TIME_LIMIT.
- **A6** v010-60s: mean score over the 5 large instances is at least 0.95.
- **A7** v010-60s: no large instance scores below 0.90.
- **A8** In every variant, no objective of ours is below a proven Gurobi bound (its objective minus the MIP gap on
  TIME_LIMIT answers; its objective times 0.9999 on OPTIMAL ones). Any `below_gurobi_bound = true` would mean a
  modelling difference between us and the checker, never a win, and would be investigated.
- **A9** Tiny instance: v010-60s matches Gurobi's objective within 0.01%.
- **A10** v010-10s: mean large score at least 0.93, and not more than 0.002 above v010-60s.
- **A11** All 24 runs finish inside their limits (status ok), and on every large instance the first feasible plan
  comes within 2 s (`first_feasible_s` <= 2 in v010-60s).
- **A12** Vehicle capacity is 1.45 to 1.55 times the total demand per period on all 5 large instances
  (`C_over_sum_r`), as in the original paper's generator, as far as we remember it.

Not predicted, reported as found: how many large instances beat Gurobi (only TIME_LIMIT ones can), whether the
latest-possible-delivery plan fits the capacity, the one-worker and seed-7 variants.

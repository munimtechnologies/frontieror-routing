# laporte2003 (travelling purchaser) solver v0.1.0: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-12 (about 22:30 UTC), before the run `froc-laporte2003-v1`. Not edited after the run; the grade
goes in `score-v1.md` next to this file.

## Why this task

FrontierOR task laporte2003 is the undirected travelling purchaser problem (Laporte, Riera-Ledesma and
Salazar-González 2003): leave a depot, visit some markets on one simple cycle, buy every product's full demand
(each market sells some products, at its own price, up to its own supply), and minimise travel plus purchase cost.
The benchmark's metadata (`metadata/hardset/hard_selection_inputs_180.csv`) gives on average 10,091 variables (5,050
integer) and 5,440 constraints for its large instances. That fits about 100 vertices, 100 products and about 50
markets per product. Gurobi, running the reference branch-and-cut model, stopped without proving optimality on
2 of the 5 large instances (median 438 s, max 3,601 s).

The reference model adds subtour cuts through a lazy-constraint callback. MV2's gpshim 0.2.0 (the reference models on
open-source HiGHS) returned no answer on large_1 in 60 s ([`../gpshim/next/score-v1.md`](../gpshim/next/score-v1.md)).
So before this solver, MV2's coverage of laporte2003 at contest sizes was zero.

## Method ([`solve.py`](solve.py), standard library only)

For a fixed set of visited markets, the cheapest purchase plan is exact: each product is bought greedily from the
cheapest visited markets (a fractional knapsack per product). The search is therefore over the market set and the
tour:
- construction: the checker's mandatory markets by cheapest insertion, then a repair that adds the market with the
  best (insertion + purchase) cost per unit of missing demand covered; a second construction starts from every useful
  market and lets the drop moves thin it out;
- local search: 2-opt, node relocation, DROP, ADD (cheapest insertion) and SWAP with one of the 12 nearest unvisited
  markets in place, with exact incremental purchase deltas;
- iterated local search with three perturbations (drop k and repair, add k, double bridge), a forked second search on
  the second CPU that starts from the other construction, and a stop at min(0.9 T, T - 3). Every answer is checked
  against the official checker's rules before it is written.

The instance is read the way the official `feasibility_check.py` and `gurobi_code.py` read it: `purchase_costs` keys
as "market,product" and `supplies` keys as "product,market". (`instance_schema.json` documents `purchase_costs` keys
as "{product},{market}"; the run records which reading the files actually use.)

[`test_laporte2003.py`](test_laporte2003.py): key conventions, the mandatory-market rule against the checker's
formula, verify() on valid and broken answers, incremental add/drop/swap deltas against full recomputation (exact
bookkeeping after every move), local search never worsening, the full search against brute-force optima on 7-8 market
instances (limited and unlimited supply, Euclidean and random costs), the command line within its time limit (two
workers, one worker, a 3-second limit), and, once the data are downloaded, verify() against the official checker on
valid and broken answers (at least 40). Written without being run.

## Run

`froc-laporte2003-v1` runs the tests, then [`laporte_real.py`](laporte_real.py): the tiny instance and the 5 large
instances at 60 s, at 10 s, at 60 s with one worker, and at 60 s with seed 7. The official checker judges every
answer; score = min(2, Gurobi's stored objective / ours), the contest's rule when minimising.

## Predictions

| id | prediction | p |
|---|---|---|
| L1 | all tests pass (both the first run and the run with the official checker) | 0.65 |
| L2 | 60 s: the official checker accepts all 6 answers | 0.85 |
| L3 | no disagreement between verify() and the official checker, in any variant, including on Gurobi's files | 0.85 |
| L4 | 60 s: mean score over the 5 large instances >= 0.99 | 0.55 |
| L5 | 60 s: at least 3 of the 5 large instances within 1% of Gurobi's stored answer | 0.70 |
| L6 | 60 s: at least one large instance strictly better than Gurobi's stored answer | 0.25 |
| L7 | 10 s: mean large score >= 0.97 | 0.65 |
| L8 | every run in every variant ends before its time limit (no timeout status) | 0.90 |
| L9 | tiny: our 60 s objective equals Gurobi's | 0.70 |
| L10 | the instance files key purchase_costs as "market,product" (the checker's reading) on every key of all 6 instances, so instance_schema.json's "{product},{market}" description is wrong | 0.65 |

## Decision rules

- If L2 and L3 hold and L5 holds, this solver becomes MV2's laporte2003 entry in the contest kit (replacing gpshim's
  zero on large instances).
- If L4 misses, the next version adds a market-set exact step (re-solve which markets to keep for the current tour
  order) and Or-opt segments, and is pre-registered again.
- If L10 misses (files keyed "product,market"), the checker and Gurobi both read prices at swapped keys; that goes into
  MV2's single FrontierOR maintainer note as a data-contract finding, and is never exploited.
- Any answer the official checker rejects is a bug, never an entry.

## Limits

Five public instances, one run each per variant on one shared 2-CPU machine. The contest scores private instances,
whose sizes may differ. Gurobi's stored answers are proven optima on 3 of the 5 large instances, so a score above 1.0
is possible only on the other 2.

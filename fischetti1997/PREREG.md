# fischetti1997 (generalized TSP) solver v0.1.0: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-12 (about 21:20 UTC), before the run `froc-fischetti1997-v1`. Not edited after the run; the grade
goes in `score-v1.md` next to this file.

## Why this task

FrontierOR task fischetti1997 is the symmetric generalized travelling salesman problem with exactly one node per
cluster (Fischetti, Salazar-González and Toth 1997). Its public large instances are GTSPLIB-sized: about 440 nodes in
about 88 clusters, integer rounded Euclidean costs. The benchmark's metadata
(`metadata/hardset/hard_selection_inputs_180.csv`) shows that Gurobi, running the reference branch-and-cut model,
stopped at its time limit without proving optimality on 4 of the 5 large instances (median 3,603 s); the task ranks
38th of 180 in the benchmark's hardness list.

The reference model adds subtour cuts through a lazy-constraint callback. MV2's gpshim 0.2.0 (which runs the
reference models on open-source HiGHS) solves the tiny instance this way, but on large_1 it returned no answer in
60 s ([`../gpshim/next/score-v1.md`](../gpshim/next/score-v1.md)). So, before this solver, MV2's contest coverage on
fischetti1997 at contest sizes was zero.

## Method ([`solve.py`](solve.py), standard library only)

Iterated local search: nearest-neighbour construction; then, until nothing improves, 2-opt on the tour, relocation
of one cluster to its best position with its best node there, and an exact dynamic programme that picks the best node
in every cluster for the current cyclic cluster order; perturbation by a local double bridge; back to the best tour
after 50 failures, a fresh construction after 300. A forked child runs a second seed on the second CPU. Every answer
is checked against the official checker's rules before it is written, and the run stops at min(0.9 T, T - 3).

[`test_fischetti1997.py`](test_fischetti1997.py): the distance indexing against the official checker's formula, the
dynamic programme against brute force, every move keeps the tour valid and never makes it worse, the full search
against brute-force optima on 6-cluster instances, the command line within its time limit (two workers, one worker,
a 3-second limit), and, once the data are downloaded, verify() against the official checker on up to 42 valid and broken
solutions (at least 30). Written without being run.

## Run

`froc-fischetti1997-v1` runs the tests, then [`fischetti_real.py`](fischetti_real.py): the tiny instance and the 5 large
instances at 60 s, at 10 s, at 60 s with one worker, and at 60 s with seed 7. The official checker judges every
answer; score = min(2, Gurobi's stored objective / ours), the contest's rule when minimising.

## Predictions

| id | prediction | p |
|---|---|---|
| F1 | all tests pass (both the first run and the run with the official checker) | 0.70 |
| F2 | 60 s: the official checker accepts all 6 answers | 0.85 |
| F3 | no disagreement between verify() and the official checker, in any variant, including on Gurobi's files | 0.85 |
| F4 | 60 s: mean score over the 5 large instances >= 0.99 | 0.75 |
| F5 | 60 s: at least one large instance strictly better than Gurobi's stored answer | 0.55 |
| F6 | 60 s: mean large score >= 1.000 | 0.45 |
| F7 | 10 s: mean large score >= 0.98 | 0.65 |
| F8 | 60 s: every run ends within 57 s wall clock | 0.90 |
| F9 | one worker at 60 s scores no higher on mean large score than two workers at 60 s | 0.75 |
| F10 | tiny: our objective equals Gurobi's (proven optimal on tiny) | 0.90 |

## Decision rules

- If F2 and F3 hold and F4 holds, this solver becomes MV2's fischetti1997 entry in the contest kit (replacing
  gpshim's zero on large instances), and a 300 s variant is measured next.
- If F4 misses, the next version adds Or-opt moves of 2-3 clusters and a GA/memetic layer, and is pre-registered again.
- Any answer the official checker rejects is a bug, never an entry.

## Limits

Five public instances, one run each per variant on one shared 2-CPU machine. The contest scores private instances,
whose sizes may differ. Gurobi's stored answers are its incumbents at a 1-hour limit, not proven optima, on 4 of the 5.

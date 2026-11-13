# lee1996 (Steiner tree-star) solver v0.1.0: pre-registration

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Code Apache-2.0; text CC BY 4.0.
Written 2026-11-13 (about 11:30 UTC), before any run of this solver. Job: `froc-lee1996-v1`.

## Why this task

FrontierOR task `lee1996` (Hugging Face [frontieror/FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR),
CC BY 4.0; Lee, Chiu and Ryan, INFORMS Journal on Computing 8(3), 1996). MV2's general engine, gpshim, solves its
tiny instance but gave no answer on a large one in 60 s (the reference model needs a lazy-constraint callback), so the
task scores 0 for him today. The benchmark's metadata lists no Gurobi timeouts on its large instances (median
runtime 10 s), so the stored references are probably optimal and the best possible score is about 1.0. This is a
coverage solver: the goal is to match Gurobi on every instance.

## Method

Once the set S of active hubs is fixed, everything else is exact: each target goes to its cheapest active hub, and
the cheapest tree on S is its minimum spanning tree. So the search runs over S only, and every candidate is priced
exactly (add / drop / swap one hub, iterated local search). Moves are pruned only with valid bounds: in a metric,
adding a hub can at most halve the tree (an MST is at most twice a Steiner tree), and dropping a hub lowers the tree by
at most its cheapest edge to another active hub. The tests check every delta against a full recomputation, check that
pruned moves never improve, and check the search against a brute force over all hub sets on small instances.

## Reading the official checker (before running it)

`feasibility_check.py` never checks that an edge joins two different hubs. A self-loop `[j, j]` counts as an edge in
the "edges = active hubs - 1" test, and the connectivity test then compares the largest component plus one more hub
with a bound that the self-loop also satisfies. We therefore expect it to accept a forest in which the missing edges
are replaced by self-loops, which is cheaper than any tree. Our solver never writes self-loops, and our verify()
rejects them. The run measures this with a probe (a test of the checker, never an entry): our own solution with its
most expensive edge replaced by a self-loop. Two control probes: the edge simply removed (must be rejected), and the
objective reported 0.05% low (inside the checker's 0.1% tolerance).

## Guesses (probabilities fixed now)

| id | guess | p |
|---|---|---|
| E1 | all unit tests pass on the first run (before the instances) | 0.70 |
| E2 | the official checker accepts our 60 s solution on 6/6 instances | 0.85 |
| E3 | 60 s: our objective equals the stored Gurobi objective (within 1e-6 relative) on at least 4 of the 5 large instances | 0.70 |
| E4 | 60 s: mean score on the 5 large instances is at least 0.995 | 0.85 |
| E5 | 10 s: mean score on the 5 large instances is at least 0.99 | 0.80 |
| E6 | our objective is never below Gurobi's stored best bound (that would mean a modelling difference) | 0.95 |
| E7 | the official checker accepts the self-loop probe on every instance probed | 0.75 |
| E8 | the official checker rejects the removed-edge probe on every instance probed | 0.90 |
| E9 | the official checker accepts the 0.05%-low objective probe on every instance probed | 0.85 |
| E10 | every stored Gurobi solution reports status OPTIMAL | 0.80 |

If E7 holds, it goes into one note to the benchmark's maintainers, with the other checker findings MV2 has confirmed by
running them. It is never used in a solution.

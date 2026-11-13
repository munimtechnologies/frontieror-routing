# roberti2015 (fixed charge transportation) solver v0.1.0: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-13 (about 17:00 UTC), before the run `froc-roberti2015-v1`. The job's first step waits until this
file is public in this repository and records whether it was (`prereg-check.json`). This file is not edited after
the run. The grade goes in `score-v1.md`, next to this file.

## Why this task

FrontierOR task roberti2015 is the fixed charge transportation problem (FCTP). m sources ship their whole supply to
n sinks that need exactly their demand. Each route costs a per-unit price times the quantity, plus a fixed charge
whenever it carries anything. The benchmark's metadata (`metadata/hardset/hard_selection_inputs_180.csv`) gives
9,800 variables on average (4,900 binary), which is m x n = 4,900 routes. Gurobi stopped at its one-hour limit on
**all 5 large instances**, so its stored answers are incumbents, not proven optima. Until now MV2 had no answer for
this task at contest size.

## Method ([`solve.py`](solve.py), standard library only)

The cost is concave in the flows, so some optimal answer is a vertex of the transportation polytope: a basic
solution whose m + n - 1 basic routes form a spanning tree. The solver moves from tree to tree:

- **Construction:** a least-cost greedy on c_ij + f_ij / q_ij, where q_ij is what the route can still carry. Each
  step crosses out one source or sink, so the result is always a spanning tree.
- **Local search:** network-simplex pivots. For a route outside the tree, its cycle is found by climbing the tree.
  The exact change in total cost is computed: variable costs, plus the fixed charges of routes that open or close.
  The search makes only improving pivots (first improvement, random order).
- **Iterated local search:** the perturbation is either 2-6 random non-degenerate pivots, or a local search on fixed
  costs randomly perturbed by up to ±20/40/60%. The true-cost local search follows. A result no worse than the
  current one is accepted. The search goes back to the best solution after 40 failures and restarts from a noisy
  greedy after 200.
- **Workers:** a forked second worker runs another seed, and the better answer is kept.
- **Output:** every answer is checked against the official checker's rules before it is written.

This is our own simple design. The published state of the art is the reduced-cost ILS of Buson, Roberti and Toth
(Operations Research 62(5), 2014), which uses reduced costs to guide its restarts. Ours does not yet.

[`test_roberti2015.py`](test_roberti2015.py) checks:
- the greedy always gives a feasible spanning tree, including 1 x n, m x 1 and degenerate instances;
- each pivot's predicted cost change equals the real change, over hundreds of random pivots;
- local search ends at a true local optimum;
- the search finds the exact optimum on 6 small instances (at least 5 of 6), found by enumerating every spanning-tree
  basis;
- the command line within its time limit, with and without the second worker;
- once the data are downloaded, agreement with the official checker on 35 valid and broken answers, including the
  0.1% objective tolerance and the checker's undocumented `swapped` field.

The tests were written without being run.

## Run

`froc-roberti2015-v1` runs the tests, then [`roberti_real.py`](roberti_real.py) on the tiny instance and the 5 large
ones, in 4 variants: 60 s, 10 s, 60 s with seed 7, and 300 s. Then it runs the tests again, this time with the official
checker. The official `feasibility_check.py` judges every answer. Score = min(2, Gurobi's stored objective / ours).
The run also records Gurobi's stored `mip_gap` and the lower bound it implies.

## Predictions

| id | prediction | p |
|---|---|---|
| F1 | all tests pass, in both test runs | 0.70 |
| F2 | 60 s: the official checker accepts all 6 answers | 0.90 |
| F3 | no disagreement between our checker and the official one, in any variant, including on Gurobi's files | 0.85 |
| F4 | tiny: our objective within 0.01% of Gurobi's | 0.85 |
| F5 | 60 s: mean score over the 5 large instances >= 0.97 | 0.65 |
| F6 | 60 s: mean large score >= 1.00 | 0.35 |
| F7 | 60 s: at least 1 of the 5 large instances strictly better than Gurobi's stored objective | 0.45 |
| F8 | 300 s: mean large score >= the 60 s mean | 0.85 |
| F9 | 10 s: mean large score >= 0.93 | 0.60 |
| F10 | every run ends before its limit (wall clock < T) | 0.90 |
| F11 | Gurobi's stored mip_gap is above 1% on all 5 large instances | 0.70 |
| F12 | no answer of ours is below the lower bound implied by Gurobi's mip_gap | 0.95 |

## Decision rules

- If F2, F3 and F5 hold, this becomes MV2's roberti2015 entry, and its 60 s answers replace "no answer".
- If F6 misses with F5 held, v0.2 adds reduced-cost-guided restarts (after Buson, Roberti and Toth) and a faster
  pivot evaluation. It is pre-registered again.
- If F5 misses, the iteration counts in the solver log decide the fix. Few iterations mean speed comes first; many
  iterations mean the perturbation comes first.
- Any answer the official checker rejects is a bug, never an entry. If F12 misses, it is a modelling difference to
  explain, never a claim.

## Limits

5 public instances, one run per variant, on a shared 2-CPU machine, in pure Python. Gurobi's stored answers are
one-hour single-thread incumbents, not optima, and the contest scores private instances. A score above 1 here means
better than a time-limited Gurobi run. It does not mean better than the published exact methods, which solve
instances of this size to optimality.

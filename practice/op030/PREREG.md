# Orienteering (fischetti1998) solver v0.3.0: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-11 (about 21:30 UTC), before the run `froc-op030-v1`. The predictions below are not edited after the run.
The grade will go in `score-v1.md` next to this file.

## Why

In the 11 Nov practice run ([../score-v1.md](../score-v1.md)), the published orienteering solver v1
(`op/fischetti1998/solve.py`: greedy prize/time insertion, 2-opt, remove-and-reinsert iterated local search) was accepted
by the official checker on all 6 public FrontierOR instances. On the five 500-city instances it collected 3.8% to 13.8%
less prize than the benchmark's stored Gurobi solutions: contest scores 0.8625, 0.8663, 0.8732, 0.9046 and 0.9624, mean
0.8938. Prediction O2 (mean >= 0.95) missed. v0.2.0 (`op/v2/`) was not better than v1 on OPLib, so v1 stays the core.

## What v0.3.0 does

[`op/fischetti1998/solve.py`](op/fischetti1998/solve.py), with v1 unchanged next to it as `op_core.py`:

1. **Anytime start.** v1's greedy tour is built and written to the output first.
2. **Second search on the second CPU** (the contest sandbox has 2 vCPUs, and v1 uses one). A forked child runs OR-Tools
   routing: one vehicle, the budget t0 as the capacity of a time dimension, and one disjunction per city with penalty
   prize × M. M = budget + 1 (in integer time units), so one unit of prize outweighs any tour length within the
   budget: OR-Tools maximises prize first, then shortens the tour. It uses guided local search seeded with the greedy
   tour. Meanwhile the parent runs v1's iterated local search. The better tour (prize, then length) is written.
3. Every tour is re-checked with the instance's own times (closed at the depot, distinct cities, at least three
   cities, length <= t0) before it can be written.

Variants in the same job, same machine, 60 s per instance, the contest way (`kit/frontieror_real.run_task`, official
`feasibility_check.py`):

| variant | what |
|---|---|
| op-v030 | default: v1 search ∥ OR-Tools GLS |
| op-v030-ortools | OR-Tools GLS only, one process |
| op-v030-ops | as op-v030, plus OR-Tools' relocate-and-make-active and extended swap-active neighbourhoods |
| op-v1 | the published v1, unchanged (baseline rerun) |

official_score = min(2, our prize / Gurobi's) when the official checker accepts the file and the run finished in time,
else 0. "mean" = mean over large_1..large_5.

## Predictions

| id | prediction | p |
|---|---|---|
| P1 | op-v030: the official checker accepts all 6 | 0.90 |
| P2 | op-v030: mean official score >= 0.95 | 0.55 |
| P3 | op-v030 mean >= op-v1 mean (same job) + 0.02 | 0.80 |
| P4 | op-v030: official score >= 1.0 on at least one large instance (ties or beats Gurobi) | 0.20 |
| P5 | op-v030 logs: OR-Tools' tour is the one written ("chosen": "ortools") on >= 3 of the 5 large instances | 0.65 |
| P6 | op-v030-ortools mean >= op-v1 mean | 0.70 |
| P7 | op-v030-ops mean >= op-v030 mean - 0.005 (the extra neighbourhoods do not hurt) | 0.55 |
| P8 | op-v1 rerun mean within ±0.02 of 0.8938 | 0.75 |
| P9 | none of the 24 runs is overtime or writes no output | 0.85 |
| P10 | `test_op030.py` passes (valid tours in all modes, official checker on 9 random tours, brute-force optimum bound; OR-Tools mode optimal on >= 8 of 10 eight-city instances) | 0.75 |

Brier score over P1-P10 will be reported.

## Decision rules (fixed now)

- v0.3.0 replaces v1 in `op/fischetti1998/` (and in the contest submission folder) only if its best variant is accepted
  6/6 by the official checker and its mean beats op-v1's mean in this job.
- The default (`DEFAULT_CONFIG` in solve.py) becomes the variant with the best mean, if that beats op-v030 by >= 0.005;
  otherwise op-v030 stays the default.
- If P2 misses, the next step is a stronger dedicated search (prize-ratio insertion with segment ILS in the child, or
  a kNN-sparsified MIP), not more tuning of the same pieces.

## Limits

Five public instances, one machine, one run each. Times are wall-clock, so results can move with machine load. The
contest scores private instances, so this is a practice estimate, not a contest result.

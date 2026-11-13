# fischetti1997 solver v0.1.0 at 300 s: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-13 (about 15:00 UTC), before the run `froc-fischetti300-v1`, and published before it can start. The
grade goes in `score-300.md` next to this file.

## Why

The 60 s grade ([score-v1.md](score-v1.md)) met the pre-registered rule for a 300 s measurement. The FrontierOR
contest gives each problem class a limit of 10 s, 60 s or 5 minutes, and we do not know yet which class this task
falls in. This run answers one question: how much does five times the time buy on the public instances?

## Method

[`run300.py`](run300.py) downloads this repository at the current commit of `main`. It loads the published
`fischetti1997/fischetti_real.py` and replaces only its list of variants: 300 s with seed 1, and 300 s with seed 7
(two workers each, as at 60 s). The solver, its time budget rule (it stops at min(0.9 T, T - 3), so 270 s), the
official checker and the scoring are unchanged. Tiny plus 5 large instances, one run each.

## Predictions

| id | prediction | p |
|---|---|---|
| G1 | the official checker accepts all 12 answers | 0.90 |
| G2 | 300 s seed 1: mean large score >= the 60 s seed 1 mean (1.0074) | 0.85 |
| G3 | 300 s seed 1: mean large score >= 1.010 | 0.50 |
| G4 | 300 s seed 1: at least 4 of the 5 large instances equal to or better than Gurobi's stored objective | 0.35 |
| G5 | every 300 s run ends within 285 s wall clock | 0.90 |
| G6 | the best of the two 300 s runs on large_4 is <= 49,867 (Gurobi's stored objective) | 0.45 |

## Decision rules

- If G2 misses, the 60 s and 300 s answers are close enough that a better use of time is more diversity (more seeds or
  a population), not longer runs. v0.2 is then built that way and pre-registered.
- If G3 holds, the 300 s variant is the entry for the 5-minute class.
- Any answer the official checker rejects is a bug, never an entry.

## Limits

Five public instances, one run per seed, on a shared machine. Gurobi's stored answers stopped at a one-hour limit on 4
of the 5 instances, so they are not proven optima. The contest scores private instances.

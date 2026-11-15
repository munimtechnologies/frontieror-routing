# rothenbacher2018 v0.1.1: pre-registered guesses for the second real-instance run

Written on 2026-11-15 during run 20261115T130739Z (started 13:07 UTC), after grading v0.1.0
([score-v1.md](score-v1.md)) and before v0.1.1 has run anywhere: not on any instance and not even its tests. The
job's first step (`wait_prereg.py rothenbacher2018/PREREG-v2.md`) waits until this file is public here and records
whether it was. Made with AI agents working in MV2's name (MV2 of Munim, Inc.). CC BY 4.0.

## What changed from v0.1.0

v0.1.0 beat Gurobi's one-hour answers on all 5 large instances (mean score 1.252 at 60 s). But it could not turn
two solo trucks into one truck with its trailer, so on the tiny instance it stayed 15.2% above Gurobi's optimum and
a brute-force unit test failed. v0.1.1 adds:

- **A "pair" move** (4% of iterations): empty two routes (a random one and, 70% of the time, the route nearest to
  it) and rebuild them.
- **A "big" reinsertion mode**: a new route is opened only with the largest-capacity class that is still available.
  Pair moves use it half the time, route removals a quarter of the time and SISR moves 5% of the time.
- **Big-mode constructions**: 4 of the 8 starting constructions use big mode.

Nothing else changes: the model, the conservative choices (at most one parking per route, customer windows and
service times at the parking copies), the checker mirror and the output format. The unit tests are the published
v0.1.0 file, unchanged, which the job downloads from this repository.

## The run (job froc-rothenbacher2018-v2)

1. The unit tests, then `rothenbacher_real.py`, which runs the contest CLI on the tiny and 5 large public instances
   in three variants:
   - `ttr-60s`: seed 1, 60 s;
   - `ttr-10s`: seed 1, 10 s;
   - `ttr-60s-seed7`: seed 7, 60 s.
2. The official-checker tests (TestContestWay).

Score = min(2, Gurobi's stored objective / ours), against the stored Gurobi answers, as in v1.

## Guesses

| # | guess |
|---|---|
| V1 | The unit tests pass: `tests.txt` reports OK, with no failure or error, including `test_finds_brute_force_optimum_tiny`. Graded on unittest's OK / FAILED line, because the `exit=` line is not reliable in this job layout. |
| V2 | The official checker accepts all 18 answers (3 variants x 6 instances). |
| V3 | Tiny at 60 s, seed 1: within 0.5% of Gurobi's optimum 345.846, so at most 347.58. |
| V4 | `ttr-60s`: the mean score on the 5 large instances is at least 1.25. |
| V5 | Stretch: `ttr-60s` mean large score at least 1.30. |
| V6 | Strictly cheaper than Gurobi on all 5 large instances, in both `ttr-60s` and `ttr-60s-seed7`. |
| V7 | `ttr-10s`: the mean large score is at least 1.15. |
| V8 | Seed robustness: the `ttr-60s-seed7` mean large score is within 0.05 of the `ttr-60s` mean. |
| V9 | All 18 runs end with status ok, inside their time limits. |
| V10 | The new move matters: in `ttr-60s`, the pair move records at least one new best (`moves.pair[2] >= 1` in the solver log) on at least 3 of the 5 large instances. |
| V11 | TestContestWay passes again: 100 of 100 mutations agree, all 4 synthetic answers are accepted, and Gurobi's tiny answer gets the same verdict from both checkers. |

## Grading rules

- Each guess is graded exactly as written in `rothenbacher2018/score-v2.md`, from `out/ttr/summary.json`,
  `out/ttr/tests.txt` and `out/ttr/tests-official.txt`.
- Every score above 1.05 is re-checked by hand, as in v1.
- A score above 1 is claimed only where the official checker accepts the answer.
- **Version choice.** v0.1.1 replaces v0.1.0 as the contest candidate only if V2 and V9 hold, and its `ttr-60s`
  mean large score is at least v0.1.0's 1.252 minus 0.02. Otherwise v0.1.0 stays, and this run is reported as a
  negative result.
- **Limits.** Public instances only; one run per variant on a shared machine.

MV2, Munim, Inc., mv2@munimtech.com

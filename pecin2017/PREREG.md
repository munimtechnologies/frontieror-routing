# pecin2017 (VRPTW) solver v0.1.1: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written 2026-11-13 (about 15:05 UTC), before the run `froc-pecin2017-v1`. The job's first step waits until this file
is public in the repository and records whether it was (`prereg-check.json`). Not edited after the run; the grade
goes in `score-v1.md` next to this file.

## Why this task, and what happened before

FrontierOR task pecin2017 is the vehicle routing problem with time windows: minimise total Euclidean distance, any
number of vehicles. In the benchmark's metadata (`metadata/hardset/hard_selection_inputs_180.csv`), Gurobi stopped at
its one-hour limit **on all 5 large instances** (about 40,600 variables on average). Those stored answers are
therefore incumbents, not optima, and a strong heuristic can score up to the contest's cap of 2.

v0.1.0 of this solver (folder `vrptw/` before this one, guesses V1-V6 in `vrptw/NOTES.md`) never ran on the
instances. Its first job stopped in setup on our own version-print line, because pyvrp has no `__version__`. Its
second job was refused by our job runner, because its working folder was outside its run's folder. So V1-V6 are void,
not graded. This folder is a self-contained copy, and the guesses below replace them.

## Method ([`solve.py`](solve.py))

Unchanged from v0.1.0: one route per customer, then cheapest feasible insertion, then PyVRP 0.14 (MIT) iterated local
search on an integer copy scaled by 1,000 with conservative rounding. Travel and service times and window openings
are rounded up, and window closings are rounded down, so every schedule PyVRP accepts is feasible on the exact data.
Every route is re-checked in floating point before it is offered, and the objective is always recomputed exactly.
v0.1.1 only silences PyVRP's log, falls back to a plain `solve()` if the improvement callback cannot be set up, reads
the seed from `MV2_PECIN_SEED`, and records the pyvrp version from package metadata. One worker (the second CPU is
unused).

[`test_pecin.py`](test_pecin.py) checks:
- our checker's rules;
- that insertion is feasible;
- that the scaling is conservative (travel times, window openings and closings);
- the brute-force optimum on 5 six-customer instances (4 of 5 within 0.01 when pyvrp is installed);
- the command line within its limit, and the solver log;
- once the data are downloaded, agreement with the official checker on at least 18 valid and broken solutions.

The tests were written without being run.

## Run

`froc-pecin2017-v1`: the tests, then [`pecin_real.py`](pecin_real.py) on the tiny instance and the 5 large ones. It
runs 4 variants: 60 s, 10 s, 60 s with seed 7, and 300 s. Then the tests again, this time with the official checker.
The official `feasibility_check.py` judges every answer. Score = min(2, Gurobi's stored objective / ours).

## Predictions

| id | prediction | p |
|---|---|---|
| P1 | all tests pass, in both test runs (pyvrp installed) | 0.65 |
| P2 | 60 s: the official checker accepts all 6 answers | 0.85 |
| P3 | no disagreement between our checker and the official one, in any variant, including on Gurobi's files | 0.85 |
| P4 | 60 s: the PyVRP phase runs on all 6 instances (no `pyvrp_error`, callback mode) | 0.75 |
| P5 | 60 s: mean score over the 5 large instances >= 1.00 | 0.70 |
| P6 | 60 s: at least 3 of the 5 large instances strictly better than Gurobi's stored objective | 0.65 |
| P7 | 60 s: mean large score >= 1.10 | 0.40 |
| P8 | 300 s: mean large score >= the 60 s mean | 0.85 |
| P9 | 10 s: mean large score >= 0.95 | 0.60 |
| P10 | tiny: our objective within 0.01% of Gurobi's | 0.80 |
| P11 | every run ends before its limit (wall clock < T) | 0.90 |

## Decision rules

- If P2, P3 and P5 hold, this becomes MV2's pecin2017 entry. The same adapter (exact float re-check around PyVRP with
  conservative rounding) is then ported to the other VRPTW-family tasks where MV2 has no answer at contest size:
  reinhardt2016, spliet2015 and rothenbacher2018. Each port is pre-registered.
- If P4 misses, the PyVRP call is fixed first (read the installed version's API) and re-run as v2.
- If P5 misses with P4 held, the next version adds a second worker with another seed (as in fischetti1997) and a
  route-minimising restart, and is pre-registered again.
- Any answer the official checker rejects is a bug, never an entry.

## Limits

5 public instances, one run per variant, on a shared 2-CPU machine. Gurobi's stored answers are one-hour incumbents,
not optima. The contest scores private instances. A score above 1 here means "better than a time-limited Gurobi run".
It does not mean better than the best published VRPTW solutions.

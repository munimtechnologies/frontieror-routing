# archetti2007 v0.1.0: graded against its pre-registration (A1-A12)

Graded on 2026-11-15 (run 20261115T130739Z) from job `froc-archetti2007-v1`, which ran from 12:29 to 12:50 UTC. The
guesses in [PREREG.md](PREREG.md) were published on 2026-11-13, before the run. Raw outputs are in
[runs/v1/](runs/v1/): `results.md`, `summary.json`, `tests-pre.txt` and `tests.txt`. Made with AI agents working in
MV2's name (MV2 of Munim, Inc.). Text CC BY 4.0, code Apache-2.0.

## Result in one line

On vendor-managed inventory routing with the order-up-to policy, the standard-library pattern solver **lands within
0.41% of Gurobi's stored answer on all 5 large public instances**. Its mean score is **0.99997 at 60 s** and
**1.0024 with seed 7**, and it beats Gurobi on 1 to 3 instances depending on the variant. Before this, MV2 scored 0
on this task, because the reference model needs Gurobi's lazy subtour callback. The official checker accepted all
24 answers. **Of 12 guesses: 9 held, 1 failed (A12), and 2 (A5, A8) cannot be graded**, because the stored Gurobi
files carry no status, runtime or MIP gap.

## Grades

| # | guess | result | grade |
|---|---|---|---|
| A1 | `tests-pre.txt` passes before the real run | OK (10 tests, official-checker test skipped there as planned) | held |
| A2 | 60 s: official checker accepts 6/6 | 6/6 (and 6/6 in all 4 variants) | held |
| A3 | 0 disagreements; `tests.txt` with the official checker passes | 0 disagreements; `tests.txt` 10/10 OK including the agreement test | held |
| A4 | All 5 large instances have n = 50 and H = 6 | 5/5 | held |
| A5 | Stored Gurobi answers: 3 OPTIMAL, 2 TIME_LIMIT | the stored solution files carry no status, runtime or gap | not gradable |
| A6 | 60 s mean large score at least 0.95 | 0.999972 | held |
| A7 | 60 s: no large instance below 0.90 | lowest 0.995969 (large_5) | held |
| A8 | No objective below a proven Gurobi bound | no bound can be computed (no status or gap stored), so the check had nothing to test | not gradable |
| A9 | Tiny at 60 s within 0.01% of Gurobi | 1750.321712 = 1750.321712 | held |
| A10 | 10 s mean at least 0.93 and at most 0.002 above the 60 s mean | 0.996492 (60 s: 0.999972) | held |
| A11 | All 24 runs ok; first feasible plan within 2 s on every large instance | 24/24 ok; first feasible at most 0.011 s | held |
| A12 | Vehicle capacity 1.45-1.55 x total demand per period on all 5 large | 1.4998, 1.5000, 1.4998, **1.6114**, 1.4987 | **failed** (large_4) |

## Per instance (ours / Gurobi; score = Gurobi / ours)

| instance | Gurobi | 60 s | 10 s | 60 s, 1 worker | 60 s, seed 7 |
|---|---|---|---|---|---|
| large_1 | 29383.97 | 29161.98 (1.0076) | 29103.14 (1.0096) | 29132.07 | 29013.83 (1.0128) |
| large_2 | 38884.94 | 39023.77 (0.9964) | 39187.46 | 39059.03 | 38916.78 (0.9992) |
| large_3 | 72941.72 | 72941.72 (1.0000) | 72941.72 | 72951.54 | 72941.72 (1.0000) |
| large_4 | 43425.08 | 43432.14 (0.9998) | 43432.14 | 43425.08 | 43423.77 (1.00003) |
| large_5 | 27511.08 | 27622.44 (0.9960) | 28052.72 | 28063.57 | 27507.68 (1.0001) |
| mean large score | | 0.999972 | 0.996492 | 0.996874 | 1.002419 |

## Reading

- **Close to the ceiling.** Gurobi's answers here are near-optimal. The differences between seeds (up to 0.5%)
  are as large as the differences from Gurobi, so this task is mainly coverage: about 1.0 instead of 0.
- **Room left.** The seed-7 run shows the solver can beat Gurobi slightly on 3 of 5 instances. So the next step is
  better use of the 2 CPUs (independent restarts and keeping the best), not a new model.
- **Nothing suspicious in the gains.** The improvements over Gurobi are small (at most 1.3%), every answer is
  accepted by the official checker, and our checker mirror agrees with it everywhere.
- **Gurobi log versus stored answers.** The Gurobi log files hold lower objective values than the stored answers
  (for example 26027.85 at 2.1 s on large_5, against the stored 27511.08). These are most likely candidate solutions
  that the lazy subtour callback later rejected, not better feasible answers. We do not use them as references.

## Limits

- **Public instances only.**
- **Small sample.** One run per variant, on a shared machine.
- **Two guesses ungradable.** A5 and A8 could not be graded with the stored files.

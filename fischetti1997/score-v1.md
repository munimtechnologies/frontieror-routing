# fischetti1997 (generalized TSP) solver v0.1.0: grade of `froc-fischetti1997-v1`

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Graded 2026-11-13 (about 14:50 UTC) against [`PREREG.md`](PREREG.md), published on 2026-11-12 before the run and not
edited since. Run: 2026-11-13 11:12-11:35 UTC on one shared machine (2 CPUs, 1 GB, peak memory 0.05 GB),
`python:3.12`, solver from this repository at `b8ef7e3`, benchmark revision `ef42a2eac135` (Hugging Face
[frontieror/FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR), CC BY 4.0). Both test runs passed
(12 tests; the comparison with the official checker was skipped the first time because the data were not downloaded
yet, and passed the second time).

## Results

score = min(2, Gurobi's stored objective / ours), the contest's rule when minimising. Every answer below was accepted
by the official `feasibility_check.py`.

| instance | Gurobi (stored) | ours, 60 s | ours, 10 s | ours, 60 s one worker | ours, 60 s seed 7 |
|---|---|---|---|---|---|
| tiny | 1,083 | 1,083 | 1,083 | 1,083 | 1,083 |
| large_1 | 51,215 | 51,230 (+0.03%) | 51,230 | 51,344 | 51,344 |
| large_2 | 52,705 | **51,290 (-2.68%)** | **51,290** | **51,290** | **51,256** |
| large_3 | 52,197 | **51,532 (-1.27%)** | **52,097** | **51,831** | **51,524** |
| large_4 | 49,867 | 50,027 (+0.32%) | 50,059 | 50,489 | 49,875 |
| large_5 | 57,541 | 57,541 (equal) | 57,541 | 57,541 | 57,541 |
| **mean score, 5 large** | | **1.0074** | 1.0051 | 1.0040 | 1.0077 |

Each large instance has 442 nodes in 89 clusters. Gurobi's stored answers come from a one-hour limit and were not
proven optimal on 4 of the 5. On large_2 and large_3, the 60 s heuristic is 2.7% and 1.3% cheaper than that hour of
Gurobi. On large_1 and large_4 it is slightly worse (by 0.03% and 0.32%). Every variant reached 57,541 on large_5. The
best of all four variants is below Gurobi or within 0.03% of it on all five instances.

## Predictions

| id | prediction | p | result |
|---|---|---|---|
| F1 | all tests pass (both runs) | 0.70 | **held** |
| F2 | 60 s: the official checker accepts all 6 answers | 0.85 | **held** (6/6, and 24/24 over all variants) |
| F3 | no disagreement between verify() and the official checker, incl. Gurobi's files | 0.85 | **held** (0 disagreements) |
| F4 | 60 s: mean large score >= 0.99 | 0.75 | **held** (1.0074) |
| F5 | 60 s: at least one large instance strictly better than Gurobi | 0.55 | **held** (2: large_2, large_3) |
| F6 | 60 s: mean large score >= 1.000 | 0.45 | **held** |
| F7 | 10 s: mean large score >= 0.98 | 0.65 | **held** (1.0051) |
| F8 | 60 s: every run ends within 57 s wall clock | 0.90 | **held** (54.1-54.4 s) |
| F9 | one worker at 60 s scores no higher than two workers | 0.75 | **held** (1.0040 vs 1.0074) |
| F10 | tiny: equal to Gurobi's proven optimum | 0.90 | **held** (1,083) |

10 of 10 held. Brier score 0.091 (always saying 0.5 scores 0.25). Every guess held, which suggests these
probabilities were set too low, not that the solver is better than expected.

## What the run shows

- Most of the gain comes in the first seconds. At 10 s each worker runs about 200-250 iterations against
  about 1,850-1,950 at 60 s, yet the mean score is only 0.002 lower.
- The second CPU helps a little. Two workers (two seeds) beat one worker by 0.0034 in mean score, and the child
  process gave the best answer in 3 of 5 large instances.
- Seeds matter as much as time. Seed 7 found 49,875 on large_4 (Gurobi 49,867) where seed 1 found 50,027.
- Logging bug, ours: each worker's improvement log lists its first five events twice. The solutions and scores are not
  affected; it will be fixed in the next version.

## Decision (rule fixed in PREREG.md)

F2, F3 and F4 held, so this solver becomes MV2's fischetti1997 entry in the contest kit, replacing gpshim's empty
answer on large instances. As pre-registered, a 300 s measurement is next: [`PREREG-300.md`](PREREG-300.md).

Data: [results.md](runs/v1/results.md), [summary.json](runs/v1/summary.json), our 60 s solutions in
[runs/v1/solutions/](runs/v1/solutions/).

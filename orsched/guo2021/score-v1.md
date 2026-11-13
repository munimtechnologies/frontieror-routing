# guo2021 (stochastic distributed operating room scheduling) solver v0.1.0: grade of `froc-guo2021-v1`

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Graded 2026-11-13 (about 19:30 UTC) against [`PREREG.md`](PREREG.md), which went public here on 2026-11-12 at
04:28 UTC, about 37 hours before the run, and has not been edited since. Run: 2026-11-13 17:06-17:22 UTC on one
shared machine (2 CPUs, 2 GB, peak memory 0.11 GB), `python:3.12`, benchmark revision `ef42a2eac135` (Hugging Face
[frontieror/FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR), CC BY 4.0), kit from this repository
at `afcf087`. All 8 unit tests passed ([tests.txt](runs/v1/tests.txt)).

## Results

The FrontierOR Challenge scores a feasible answer against a reference objective, capped at 2
([scoring rules](https://frontieror-challenge.com/docs/main/scoring)). When minimising with both values negative, the
score is ours / reference. When the two values have opposite signs, a better answer scores 2. Every answer below was
accepted by the task's official `feasibility_check.py`. Its constraint 11 recomputes the best possible
cancellation cost for our first-stage plan and checks that the stated objective is within 0.5% of it.

| instance | Gurobi (stored, 1 h limit) | ours, 60 s | score 60 s | ours, 10 s | score 10 s |
|---|---|---|---|---|---|
| tiny | -38,094.0 | -38,094.0 | 1.0000 | -38,094.0 | 1.0000 |
| large_1 | -732,149.2 | **-793,407.6** | 1.0837 | -792,534.0 | 1.0825 |
| large_2 | **+32,031.0** | **-566,256.4** | 2 (sign) | -566,185.2 | 2 (sign) |
| large_3 | -811,118.6 | **-850,101.8** | 1.0481 | -848,472.2 | 1.0461 |
| large_4 | -742,197.8 | **-799,714.2** | 1.0775 | -798,509.0 | 1.0759 |
| large_5 | -19,170.0 | **-848,576.0** | 2 (cap) | -839,299.8 | 2 (cap) |
| **mean, 5 large** | | | **1.4418** | | **1.4409** |

Each large instance has 75 patients, 3 hospitals, 5 days, 5 operating rooms per hospital and 100 duration
scenarios. The benchmark lists the deterministic-equivalent model at about 568,000 binary variables, and Gurobi did not
prove an optimum on any of the 5 large instances within its hour. In 60 s our answer is cheaper than Gurobi's stored
answer on all five: by 4.8-8.4% on large_1, large_3 and large_4, where Gurobi's answer is reasonable. On large_2 and
large_5 the stored Gurobi answer is far from good. On large_2 it is a net cost, while ours is a net benefit of 566,256.
Gurobi's stored solution files for those two instances are about a third smaller than for the other three (2.6 KB
against 3.8-3.9 KB). That fits an answer that schedules fewer patients, but we have not checked it patient by patient.
Without those two capped instances, the 60 s mean over the other three is 1.0698.

Each run stops at min(0.85 T, T - 4 s): 51.2 s wall clock at T = 60 s, 6.2 s at T = 10 s. Most of the gain comes in
the first 2-5 seconds (see the improvement logs in [summary.json](runs/v1/summary.json)).

## Predictions

| id | prediction | p | result |
|---|---|---|---|
| G1 | all unit tests pass | 0.85 | **held** (8/8) |
| G2 | the official checker accepts all 12 runs; none over time or missing | 0.80 | **held** (12/12) |
| G3 | 60 s: mean gap over the 5 large instances at most +1.0% | 0.60 | **held** (mean gap -1243%, i.e. better on all) |
| G4 | 60 s: at least 3 of 5 large instances strictly better than Gurobi | 0.45 | **held** (5 of 5) |
| G5 | tiny (60 s) within 0.01% of Gurobi's objective or better | 0.70 | **held** (equal: -38,094) |
| G6 | the 10 s mean large gap is within 0.5 percentage points of the 60 s one | 0.55 | **missed** (9.8 points) |
| G7 | the official checker accepts all 6 stored Gurobi solutions | 0.90 | **held** |

6 of 7 held. Brier score 0.133 (always saying 0.5 scores 0.25). G6 missed as written: the mean gap in percent is
dominated by large_5, whose reference (-19,170) is so close to zero that a 1.1% change in our objective moves its gap by
48 points. On the three instances with a reasonable reference, the 10 s gap is within 0.12-0.20 points of the 60 s
gap. We chose a gap measure that was a poor fit for this task, so G6 is graded as a miss.

## Decision (rule fixed in PREREG.md)

G2 and G3 held, so this solver becomes MV2's guo2021 entry (`solve.py` alone, numpy only). It replaces the general
MIP layer, which is unlikely to give a useful answer for a model this size in the contest's time.

Honest limits:
- The contest scores private instances against a frozen best-known value, which may be stronger than the Gurobi answer
  stored with the public instances. A score of 2 on large_2 and large_5 reflects a weak stored reference, not a strong
  solver.
- The time class for guo2021 in the contest is not known to us; the 10 s and 60 s results are close.
- We have no lower bound, so we cannot say how far from optimal these answers are.

Data: [results.md](runs/v1/results.md), [summary.json](runs/v1/summary.json) (per-instance improvement logs and sizes),
our 60 s solutions in [runs/v1/solutions/](runs/v1/solutions/).

MV2, Munim, Inc., mv2@munimtech.com

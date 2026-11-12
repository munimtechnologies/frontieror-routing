# gpshim 0.2.0 candidate: grade of run 1 (`froc-gpshim02-v1`)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Graded 2026-11-12 (about 20:40 UTC) against [`PREREG.md`](PREREG.md), which was published before the run and is not
edited. Run: 2026-11-12 16:41-17:13 UTC, one shared 2-CPU machine, `python:3.12`, HiGHS 1.16.0 (pip, unpinned),
benchmark revision `ef42a2eac135` (Hugging Face frontieror/FrontierOR, CC BY 4.0), repository commit `a5d4e7be`.
The job's run steps all exited 0. The runner still marked the job "failed" because one child process hit the 2 GB
memory cap (peak recorded for the job: 0.53 GB). The census records every run as it finishes, so none were lost.

## Results

| stage | runs | accepted by the official checker | score >= 0.99 | median score (accepted) | statuses |
|---|---|---|---|---|---|
| tiny (20 s) | 37 | 24 | 23 | 1.0 | accepted 24, no answer 5, refused/crash 4, rejected 3, overtime 1 |
| large_1 (60 s, files <= 1.5 MB) | 28 | 5 | 1 | 0.89 | accepted 5, no answer 10, crash 8, overtime 4, rejected 1 |

Tiny, by group (0.1 refused every one of these models except the computeIIS ones and gschwind2021):

- **Lazy-constraint callbacks (17):** 12 accepted, all at score 1.0: alba2013, archetti2007, colombi2017, cordeau2014,
  fischetti1997, fischetti1998, fragkos2021, furini2021, kobeaga2024, laporte2003, lee1996, pessoa2021. No answer in
  time: bode2012, cote2019, vidal2011. Overtime: cherkesly2015. Rejected: adulyasak2015 (see below).
- **Quadratic (12):** 7 accepted: bergman2019, castro2021, fleszar2022b, lai2021, yang2013, zetina2020 at 1.0, and
  kobayashi2021, where both objectives are negative (ours -1.706905, Gurobi -1.707153, 0.015% worse; our harness
  scores negative references as 0, so we report it as "accepted, not matched"). Refused by design (`GurobiError`):
  amaldi2013, bertsimas2022, byeon2022, hassannayebi2016. No answer: buchheim2018. Rejected: he2020 (see below).
- **Other:** gualandi2012 (max constraint), pettersson2020 (multiple objectives), nagy2015 and rothenbacher2018
  (computeIIS) accepted at 1.0. frey2017 accepted with objective 0 = reference 0 (the census formula prints 2.0 for a
  zero reference; under our sense rule this is "matched", not a win). kress2019: no answer. gschwind2021: rejected
  (the known checker gap: the stored Gurobi file itself writes a count the checker recomputes differently).

large_1: accepted cote2019 (1.0), zetina2020 (0.976), bergman2019 (0.890), furini2021 (0.545) and colombi2017 (a
feasible all-zero answer, score 0). Row generation, one fresh HiGHS solve per round, rarely finishes on the large
instances: 10 callback models gave no answer in 60 s.

## Two failures, looked at closely

- **he2020 (tiny) is our bug, and it is small.** The answer is feasible; the checker rejected only the reported
  objective: 1102.70471 against its own recomputation 1102.69881 (|diff| 0.0059, tolerance 0.0055). gpshim 0.2.0
  replaces each squared term by a 32-piece secant, which over-estimates the square, and then reported the secant
  model's value as `ObjVal`. Gurobi reports the objective as written. Fix: [0.2.1](../v021/) evaluates the true
  objective at the solution; re-run queued with fresh predictions.
- **adulyasak2015 (tiny) is not understood yet.** Our objective, 1395.7593777311158, equals the stored Gurobi
  objective to every digit, but the official checker exited with code 1 and wrote no verdict, so the census counted
  it as rejected. We did not record the checker's error text. The 0.2.1 run runs the checker on our file and on the
  stored Gurobi file and keeps both outputs.

## Predictions

| id | prediction | p | result |
|---|---|---|---|
| R1 | all 30 tests pass | 0.45 | **held** (30/30) |
| R2 | at least 26 of 30 pass | 0.75 | **held** |
| R3 | tiny: >= 8 of 17 callback models accepted | 0.55 | **held** (12) |
| R4 | tiny: no callback model's output rejected by the checker | 0.70 | **missed** (adulyasak2015: checker exit 1 on an output with the reference objective; counted as rejected) |
| R5 | tiny: >= 5 of 12 quadratic models accepted | 0.55 | **held** (7) |
| R6 | bertsimas2022, hassannayebi2016, amaldi2013 refused with `GurobiError` | 0.65 | **held** (byeon2022 too) |
| R7 | tiny: >= 18 of 37 accepted | 0.50 | **held** (24) |
| R8 | tiny: median score of accepted runs >= 0.99 | 0.75 | **held** (1.0) |
| R9 | large_1: >= 5 models accepted with score >= 0.99 | 0.45 | **missed** (1: cote2019) |

7 of 9 held. Brier score 0.211 (lower is better; always saying 0.5 scores 0.25).

## Decision (per the pre-registered rules)

R2 held and no accepted run is worse than 0.1 on the same task (0.1 refused all of them). The candidate is the new
floor for these 24 tasks on tiny instances. It is *not* promoted over `gpshim/gpshim.py` yet: 0.2.1 (the objective fix)
is queued, and promotion waits for it. The he2020 rejection is listed as a bug and fixed. No answer is ever submitted
from a run the checker rejected.

What this means for the contest: on tiny instances, gpshim now covers most callback and quadratic reference models
at Gurobi's quality, but on large instances the callback models mostly give no answer within 60 s. Hand-built
heuristics remain the only way to cover them at contest sizes (vidal2011's is queued).

Data: [`results.md`](runs/v1/results.md), [`summary.json`](runs/v1/summary.json), [`rows.jsonl`](runs/v1/rows.jsonl),
[`tests.txt`](runs/v1/tests.txt).

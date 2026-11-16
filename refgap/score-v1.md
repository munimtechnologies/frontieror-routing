# refgap v0.1.0: how strong are FrontierOR's stored Gurobi references? Score

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0.
Graded 2026-11-16 from the job `froc-refgap-v1`. The guesses in [PREREG.md](PREREG.md) were public before the run:
`prereg-check.json` found the file at commit 4aee588 on the first try. The run read benchmark revision
`ef42a2eac135` (Hugging Face `frontieror/FrontierOR`, CC BY 4.0) from 05:34 to 05:53 UTC.
Full outputs are in [runs/v1/](runs/v1/): tasks.csv, cases.csv, summary.json, summary.md, tests.txt, log.txt.

## What was measured
Every stored Gurobi solution of all 180 tasks (1,080 files) was read. Each gives an objective, and most give a MIP
gap or a bound. For each case, bound = objective -/+ gap x |objective|. The **ceiling** is the contest score
an answer equal to that bound would get, capped at 2. It is an upper limit, not a forecast.

- 180 tasks, 1,080 files, 0 errors; 987 files read whole, 93 big ones by their first and last 64 KB.
- 711 of the 900 large cases (79.0%) carry a usable gap.
- 25 of the 50 hard-set tasks have a large case with a gap of 10% or more.
- 25 tasks have at least one large case with ceiling 2.
- 9 tasks have a gap of 100% or more: adulyasak2015, bergman2019, fleszar2022b, guo2021, kobeaga2024, roshanaei2017,
  segundo2019b, yang2013, zetina2019.
- The sense (minimise or maximise) could not be read from the code text of 6 tasks: cordeau2019, furini2017,
  gschwind2021, lozano2017, mehrotra1996, zetina2020.

## Guesses
| id | guess | p | result | held |
|---|---|---|---|---|
| H1 | All unit tests pass | 0.90 | 14 of 14 pass | yes |
| H2 | >= 170 of 180 tasks read without error, >= 90% of large files give an objective | 0.70 | 180 of 180; every file has `objective_value` | yes |
| H3 | >= 80% of large cases have a usable gap | 0.55 | 711 of 900 = 79.0% | **no** |
| H4 | guo2021 large_2 and large_5 both have ceiling 2 | 0.75 | both 2 (gaps 3,347 and 6,349 times the objective) | yes |
| H5 | >= 10 of the 50 hard-set tasks have a large case with gap >= 10% | 0.60 | 25 | yes |
| H6 | besides guo2021, >= 5 tasks have a large case with ceiling 2 | 0.50 | 24 | yes |
| H7 | a "Transportation & Logistics" task is in the top 15 by mean large ceiling | 0.55 | kress2019 (#3) and martin-iradi2024 (#4); rothenbacher2018, ropke2009 and he2020 also in the top 11 | yes |

6 of 7 held. Brier score 0.154 (0 is perfect; always saying 0.5 gives 0.25). H3 missed by 9 cases. Many tasks store
only a status and an objective, so no gap can be read from their files.

## Top transit and logistics targets
Mean ceiling over large cases with a gap. "Ours" is MV2's mean large score at 60 s where a solver exists.

| task | hard rank | mean ceiling | large cases at 2 | ours |
|---|---|---|---|---|
| kress2019 (container terminal) | - | 2.000 (2 of 5 cases have a gap) | 2/5 | none |
| martin-iradi2024 (berth allocation) | 39 | 2.000 | 5/5 | v0.1.0 run queued |
| rothenbacher2018 (truck and trailer) | 4 | 1.994 | 4/5 | 1.252 |
| ropke2009 (pickup and delivery) | 6 | 1.931 | 3/5 | 1.359 |
| borndorfer2007 (line planning, public transit) | 15 | 1.832 | 4/5 | none, so it is the next build ([PREREG](../borndorfer2007/PREREG.md)) |
| he2020 (VRPTW, convex node costs) | 28 | 1.760 | 3/5 | 1.098 |
| ji2019 | - | 1.579 | 1/5 | none |
| spliet2015 | 48 | 1.554 | 1/5 | none |
| hassannayebi2016 (transit) | - | 1.506 | 0/5 | none |
| bard2002 (VRPTW, fleet size) | 45 | 1.445 | 2/5 | 1.322 |
| letelier2022 | 30 | 1.369 | 1/5 | none |
| colombi2017 | - | 1.351 | 0/5 | none |
| reihaneh2019 | 37 | 1.337 | 0/5 | run queued |
| nagy2015 | 5 | 1.278 | 0/5 | run queued |
| roberti2018 | 41 | 1.157 | 0/5 | run queued |

## How well the ceiling predicts what a heuristic gets (not pre-registered)
This comparison was not among the guesses, so treat it as an observation. Seven tasks have both a full set of gaps
and an MV2 score. On those seven, the rank correlation (Spearman) between ceiling and score is 0.50. The share of the
headroom reached, (score - 1) / (ceiling - 1), varies widely:

| task | ceiling | MV2 score | share of headroom reached |
|---|---|---|---|
| guo2021 | 1.492 | 1.442 | 0.90 |
| bard2002 | 1.445 | 1.322 | 0.72 |
| ropke2009 | 1.931 | 1.359 | 0.39 |
| rothenbacher2018 | 1.994 | 1.252 | 0.25 |
| he2020 | 1.760 | 1.098 | 0.13 |
| bodur2017 | 1.0012 | 1.0007 | 0.6 of a tiny headroom |
| archetti2007 | 1.006 | 0.99997 | below 1 |

Where Gurobi's answer itself was poor (guo2021's net cost against a net benefit), we reached most of the headroom. In
the routing tasks with big-M models, much of the gap is a weak bound, not a weak answer. A ceiling near 1 reliably
means little room. A high ceiling means room may exist, not that it does. On fischetti1997 and pessoa2021 only one
large case carries a gap. Their ceiling of 1.0 covers that case alone (fischetti1997 scored 1.0074 overall).

## What changes
- borndorfer2007 is the next build. It is the highest-ceiling transit task without a solver and is built this run.
- Of tasks without a solver, kress2019, ji2019, spliet2015, hassannayebi2016, letelier2022 and colombi2017 follow,
  in that order.
- he2020 and rothenbacher2018 have the most unused headroom among solved tasks, so improving them may pay more than a
  new task near 1.0.

## Limits
- The contest scores private instances against its own frozen best-known values, which may be stronger than these
  public Gurobi answers.
- A gap read from the first and last 64 KB of a big file can miss a key stored in the middle.
- The sense comes from code text, and 6 tasks could not be read that way.

MV2, Munim, Inc., mv2@munimtech.com

# reinhardt2016 (edge set cost VRPTW): pre-registered guesses for the first real-instance run

Written on 2026-11-14 during run 20261114T022553Z (which started at 02:25 UTC), before this solver had run anywhere: not on any FrontierOR instance and not even its own tests. The job's first step (`wait_prereg.py reinhardt2016/PREREG.md`) waits until this file is public here and records whether it was. Made with AI agents working in MV2's name (MV2 of Munim, Inc.). CC BY 4.0.

Publication note: run 20261114T022553Z stopped (an API rate limit) before it could publish anything. This file is published unchanged, apart from this note, by run 20261114T161850Z (started 16:18 UTC on 2026-11-14), about 14 hours after it was written. At that time the job froc-reinhardt2016-v1 had produced no results (its results folder did not exist; checked at about 16:40 UTC), so the guesses below still come before any run of the solver. The job record `out/esv/prereg-check.json` shows whether this file was public when the job started.

## The task

FrontierOR task `reinhardt2016`: Reinhardt, Jepsen and Pisinger, "The Edge Set Cost of the Vehicle Routing Problem with Time Windows", Transportation Science 50(2) (2016). It is a VRPTW from one depot, with one twist. Every edge is either free or belongs to an edge set. The first use of any edge in a set costs that set's access cost once, and after that every edge in the set is open to all vehicles. The objective is travel distance plus the access costs of the sets used.

It is on FrontierOR's hard list (rank 17 of 180): the stored Gurobi run hit its one-hour limit on all 5 large instances. The large instances are small (about 40 customers), but the benchmark's model is a three-index formulation with one copy of every arc per vehicle (about 67,000 binaries) and big-M time constraints. Stored Gurobi objectives (official checker, all accepted): tiny 369.3; large 1 to 5 = 1053.4, 855.7, 1021.6, 766.0, 1017.9.

## The solver (v0.1.0, standard library only)

- **One search on the true objective.** The search keeps, for every edge set, how many arcs in use need it. That gives the exact change in total cost of putting a customer anywhere in O(1): the distance change, plus the access cost of any set that becomes used, minus the cost of any set that stops being used.
- **Time windows in O(1) per position**, from each route's earliest service starts and latest feasible starts.
- **Search:** slack induction by string removals (SISR; Christiaens and Vanden Berghe 2020) with simulated annealing.
- **Two edge-set moves:**
  - drop: take out every customer touching a used set's arcs, then re-insert them with that set banned (unless a customer has nowhere else to go);
  - open: take out some customers that an unused set covers, then re-insert them as if that set were free.
- **Checked before writing.** Every written answer passes `verify()`, a line-by-line mirror of the official `feasibility_check.py`.

## The run (job froc-reinhardt2016-v1)

- **Tests first:** the unit tests, which include brute-force optimum checks on 5-customer instances and brute-force checks of every single insertion.
- **Then the real instances:** `reinhardt_real.py` runs the solver the contest way on the tiny instance and the 5 large public instances, at 60 s and at 10 s. Each answer is checked by the official checker and by our mirror.
- **Then the official-checker tests:** 100 mutated solutions on the tiny instance, plus the stored Gurobi tiny solution.
- **Score:** min(2, Gurobi's stored objective / ours), against the stored Gurobi answer (the contest scores private instances against its own frozen references).

## Guesses

| # | guess |
|---|---|
| E1 | All unit tests pass (TestInsertion, TestVerify, TestSearch). |
| E2 | The official checker accepts our 60 s answer on all 6 public instances. |
| E3 | Our mirror agrees with the official checker on every comparison the runner makes (12 of ours + Gurobi's, both variants), and TestContestWay passes (100 of 100 mutations agree; Gurobi's tiny answer gets the same verdict from both). |
| E4 | At 60 s, the mean score on the 5 large instances is at least 1.05. |
| E5 | At 60 s, we are strictly cheaper than Gurobi's stored answer on at least 4 of the 5 large instances. |
| E6 | Stretch: at 60 s, the mean score on the 5 large instances is at least 1.15. |
| E7 | Tiny instance at 60 s: our objective is at most Gurobi's 369.3 + 0.1%. |
| E8 | At 10 s, the mean large score is at least 0.98 times the 60 s mean large score. |
| E9 | All 12 runs end with status ok, within the time limit (no overtime, no missing output). |
| E10 | Sanity check: every stored large Gurobi solution has status "feasible" (not "optimal"), as the hard-set table says. |
| E11 | Low confidence: on at least 3 of the 5 large instances, our 60 s answer spends no more on access costs than Gurobi's. |

## Grading rules

- Each guess is graded exactly as written, from `out/esv/summary.json`, `out/esv/tests.txt` and `out/esv/tests-official.txt`, in `reinhardt2016/score-v1.md`.
- Any score above 1.05 is re-checked by hand: the official checker's verdict, the recomputed objective, and the split into distance and access cost.
- A score above 1 is only claimed where the official checker accepts the answer.
- If the job fails for a reason of ours (setup, a crash), it is reported as such. The fix gets a new version and new guesses where they change.
- Limits: one seed, one run per instance, on a shared machine; public instances only.

MV2, Munim, Inc., mv2@munimtech.com

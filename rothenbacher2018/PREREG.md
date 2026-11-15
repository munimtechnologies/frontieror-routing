# rothenbacher2018 (truck-and-trailer routing with time windows): pre-registered guesses for the first real-instance run

Written on 2026-11-15 during run 20261115T070638Z (started 07:06 UTC), before this solver had run anywhere: not on any FrontierOR instance and not even its own tests. The job's first step (`wait_prereg.py rothenbacher2018/PREREG.md`) waits until this file is public here and records whether it was. Made with AI agents working in MV2's name (MV2 of Munim, Inc.). CC BY 4.0.

## The task

FrontierOR task `rothenbacher2018`: Rothenbächer, Drexl and Irnich, "Branch-and-Price-and-Cut for the Truck-and-Trailer Routing Problem with Time Windows", Transportation Science 52(5) (2018). A mixed fleet of trucks, each used alone or with a trailer, collects supply from customers. Truck customers can only be reached by a truck without its trailer. A truck with a trailer can park the trailer at a trailer customer or a transshipment location, serve a subtour with the truck alone, and come back to couple. The objective is fixed truck costs plus distance costs (with a towing surcharge while the trailer is attached) plus coupling and decoupling costs.

It is rank 4 of 180 on FrontierOR's hard list: the stored Gurobi runs hit their one-hour limit on all 5 large instances. The benchmark's own model (its `gurobi_code.py`, a compact arc-flow MIP that the benchmark wrote because the paper only gives a branch-and-price model) has about 268,000 variables and 1.07 million constraints per large instance. We have not seen the stored Gurobi objectives: they are only inside the job's data copy, so the run will record them.

## How the official checker judges an answer (read on 2026-11-14/15)

- Answers use the benchmark's expanded node ids: the decouple copy of parking location P[i] is n_orig + i and the couple copy is n_orig + len(P) + i, with P = sorted(trailer customers + transshipment locations).
- Customer time windows are checked on the service start times that the answer reports in `arrival_times`. The windows are in an optional `time_window` field that the published schema does not list.
- Loading is simulated step by step: trailer first while it is attached, everything into the truck while it is parked, and as much as fits into the trailer at coupling.
- The objective is recomputed exactly from `route_sequence`, using the benchmark's rule for which arcs pay the towing surcharge.

## The solver (v0.1.0, standard library only)

- **Routes.** A route is a vehicle class, a main tour, and at most one parking with its truck-only subtour.
- **Fast insertion checks.** For every route the solver keeps earliest departures, latest feasible arrivals and load prefixes. So inserting a customer into the main tour, into the subtour, or as a new subtour with its own parking is checked for time, load and access, and priced exactly by the checker's cost rule, in O(1) per position.
- **Search.** Slack induction by string removals (SISR) with simulated annealing, plus three more moves: removing a whole route, changing a route's vehicle class, and re-parking a subtour.
- **Conservative choices.** Every answer is also a feasible point of the benchmark's own MIP:
  - at most one parking per route;
  - no class used more often than its `num_available`;
  - at a decouple or couple copy of a trailer customer, that customer's time window and service time apply, as they do in `gurobi_code.py`.
- **Checked before writing.** Every written answer passes `verify()`, our mirror of the official checker.

## The run (job froc-rothenbacher2018-v1)

- **Tests first:**
  - an independent route evaluator, written separately, compared with the solver on random routes;
  - a brute-force check of every possible insertion;
  - brute-force optimum checks on 4-customer instances;
  - a contest-way run.
- **Then the real instances:** `rothenbacher_real.py` runs the solver the contest way on the tiny instance and the 5 large public instances, at 60 s and at 10 s. The official checker and our mirror check each answer.
- **Then the official-checker tests:**
  - 100 mutated answers on the tiny instance;
  - 4 synthetic instances;
  - the stored Gurobi tiny answer.
- **Score:** min(2, Gurobi's stored objective / ours), against the stored Gurobi answer. The contest scores private instances against its own frozen references.

## Guesses

| # | guess |
|---|---|
| T1 | All unit tests pass (TestRoute, TestInsertion, TestVerify, TestSearch). |
| T2 | The official checker accepts our 60 s answer on all 6 public instances. |
| T3 | Our mirror agrees with the official checker on every comparison the runner makes. TestContestWay passes: 100 of 100 mutations agree, all 4 synthetic answers are accepted, and Gurobi's tiny answer gets the same verdict from both checkers. |
| T4 | At 60 s, we are strictly cheaper than Gurobi's stored answer on at least 4 of the 5 large instances. |
| T5 | At 60 s, the mean score on the 5 large instances is at least 1.10. |
| T6 | Stretch: at 60 s, the mean score on the 5 large instances is at least 1.30. |
| T7 | Tiny instance at 60 s: our objective is within 0.5% of Gurobi's stored answer, either way. |
| T8 | At 10 s, the mean large score is at least the 60 s mean large score minus 0.10. |
| T9 | All 12 runs end with status ok, within the time limit (no overtime, no missing output). |
| T10 | Our 60 s answers park a trailer (at least one decoupling) on at least 3 of the 5 large instances. |
| T11 | On at least 4 of the 5 large instances, our 60 s answer uses no more vehicles (routes) than Gurobi's. |
| T12 | Sanity check: no stored large Gurobi solution has status "optimal". |

## Grading rules

- Each guess is graded exactly as written in `rothenbacher2018/score-v1.md`, from `out/ttr/summary.json`, `out/ttr/tests.txt` and `out/ttr/tests-official.txt`.
- Any score above 1.05 is re-checked by hand: the official checker's verdict, the recomputed objective, the number of routes and parkings, and the fixed-cost share.
- A score above 1 is claimed only where the official checker accepts the answer.
- If the job fails for a reason of ours (setup, a crash, a failing test), it is reported as such. The fix gets a new version, with new guesses where they change.
- Limits: one seed and one run per instance, on a shared machine; public instances only.

MV2, Munim, Inc., mv2@munimtech.com

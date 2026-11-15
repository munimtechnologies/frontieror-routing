# rothenbacher2018 v0.1.0: graded against its pre-registration (T1-T12)

Graded on 2026-11-15 (run 20261115T130739Z, about 13:30 UTC) from job `froc-rothenbacher2018-v1`, which ran from
12:47 to 12:57 UTC. Before it started, the job confirmed that the pre-registration was public (`PREREG.md` at commit
ab8189c, checked 12:50 UTC). Raw outputs are in [runs/v1/](runs/v1/): `results.md`, `summary.json`, `tests.txt` and
`tests-official.txt`. Made with AI agents working in MV2's name (MV2 of Munim, Inc.). Text CC BY 4.0, code
Apache-2.0.

## Result in one line

In 60 seconds, the standard-library engine is cheaper than Gurobi's stored one-hour answer on **all 5 large public
instances, by 10.7% to 27.8%**, with a mean contest-style score of **1.252** (1.0 = matching Gurobi, cap 2). The
official checker accepted all 12 answers. **9 of 12 guesses held.** The 3 that failed have one cause: the search
cannot turn two solo trucks into one truck with its trailer. So on the tiny instance it stays 15.2% above Gurobi's
proven optimum, and one brute-force unit test fails.

## Grades

| # | guess | result | grade |
|---|---|---|---|
| T1 | All unit tests pass | 10 tests: 6 OK, 3 official-checker tests skipped in this step (they ran and passed in step 4), and `test_finds_brute_force_optimum_tiny` FAILED at seed 1 (ours 187.143, brute-force optimum 150.300) | **failed** |
| T2 | Official checker accepts all 6 answers at 60 s | 6/6 (and 6/6 at 10 s) | held |
| T3 | Mirror agrees with the official checker on everything; TestContestWay passes | 6/6 agree in each variant; TestContestWay 3/3 OK (100 mutations, 4 synthetic answers, Gurobi's tiny answer) | held |
| T4 | Strictly cheaper than Gurobi on at least 4 of 5 large at 60 s | 5 of 5 | held |
| T5 | Mean large score at 60 s at least 1.10 | 1.251749 | held |
| T6 | Stretch: mean large score at 60 s at least 1.30 | 1.251749 | **failed** |
| T7 | Tiny at 60 s within 0.5% of Gurobi | 398.570 vs 345.846 (+15.24%) | **failed** |
| T8 | 10 s mean at least the 60 s mean minus 0.10 | 1.198426 vs threshold 1.151749 | held |
| T9 | All 12 runs status ok, within the limit | 12/12 ok; 53.1-53.2 s of 60, 6.1-6.2 s of 10 | held |
| T10 | Parks a trailer on at least 3 of 5 large at 60 s | 5 of 5 (3, 4, 4, 3 and 5 parkings) | held |
| T11 | No more routes than Gurobi on at least 4 of 5 large at 60 s | 5 of 5 (9 vs 11, 10 vs 14, 11 vs 13, 11 vs 17, 8 vs 13) | held |
| T12 | No stored large Gurobi answer is "optimal" | all 5 are `time_limit_with_solution` (gaps 49-74%) | held |

## Per instance (60 s, seed 1)

| instance | ours | Gurobi (1 h) | Gurobi bound | gap | score | ours: routes / parkings / fixed share | Gurobi: routes / parkings / fixed share |
|---|---|---|---|---|---|---|---|
| large_1 | 1722.447 | 2107.680 | 741.1 | -18.28% | 1.2237 | 9 / 3 / 30.8% | 11 / 2 / 33.7% |
| large_2 | 2062.752 | 2399.929 | 1011.1 | -14.05% | 1.1635 | 10 / 4 / 28.1% | 14 / 1 / 35.0% |
| large_3 | 1401.755 | 1570.066 | 796.0 | -10.72% | 1.1201 | 11 / 4 / 43.5% | 13 / 0 / 46.5% |
| large_4 | 2003.555 | 2775.561 | 1040.9 | -27.81% | 1.3853 | 11 / 3 / 30.4% | 17 / 4 / 36.4% |
| large_5 | 1574.788 | 2151.540 | 560.0 | -26.81% | 1.3662 | 8 / 5 / 27.9% | 13 / 1 / 36.7% |
| tiny | 398.570 | 345.846 (optimal) | | +15.24% | 0.8677 | 2 / 0 / 120 fixed | 1 / 1 / 50 fixed |

At 10 s the large scores are 1.1610, 1.2108, 1.0432, 1.4420 and 1.1352 (mean 1.1984), all still better than Gurobi.

## Hand re-check of every score above 1.05 (as the pre-registration requires)

- **Official verdict.** The official `feasibility_check.py` accepted every one of these answers. Our mirror gave the
  same verdict each time.
- **Objective.** Each objective is the checker's own recomputation from `route_sequence`. Each score is the stored
  Gurobi objective divided by ours (for example 2107.680 / 1722.447 = 1.2237).
- **Not just fewer trucks.** We use fewer trucks than Gurobi (fixed costs 440-610 against 710-1010). We also spend
  less on distance plus handling on every large instance: 1192 vs 1398, 1483 vs 1560, 792 vs 840, 1394 vs 1766 and
  1135 vs 1362.
- **Consistent with the bounds.** Every one of our objectives sits above Gurobi's proven lower bound for that
  instance.
- **Conservative choices.** The answers use at most one parking per route and apply a trailer customer's time
  window and service time at its decouple and couple copies, as the benchmark's own model does. So each is also a
  feasible point of that model, not only of the checker.

## What failed and why

The tiny instance and the failing unit test share one cause. In v0.1.0, greedy reinsertion always opened a new route
with the class whose one-customer route was cheapest, which is a small solo truck. A class change to a truck with
its trailer was tried only for routes that held trailer customers alone. So a solution built from two solo trucks
could never become one complete vehicle that parks its trailer and serves the truck customers on a subtour, and
that is exactly Gurobi's optimal tiny answer (1 route, 1 parking, fixed cost 50 against our 120). The solver log
shows it: on tiny, 0 improvements in 777,512 iterations after the first construction.

**Fix (v0.1.1, pre-registered separately in [PREREG-v2.md](PREREG-v2.md)):**
- A new "pair" move empties two nearby routes and rebuilds them.
- Reinsertion can run in a "big" mode, which opens any new route with the largest-capacity class still available.
- Half of the constructions use big mode.

Nothing else changes: the model, the checker mirror, the output and the conservative choices are the same.

## Limits

- **Public instances only.** The challenge scores private instances against its own frozen references, which may be
  stronger than the stored Gurobi answers used here.
- **Small sample.** One seed and one run per instance, on a shared machine.
- **Single-parking model.** The model allows one parking per route and no transfers at transshipment locations, so
  some cheaper solutions are out of reach by construction.

MV2, Munim, Inc., mv2@munimtech.com

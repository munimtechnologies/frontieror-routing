# VRPDDP solver v2 (nagy2015): scored, with the v1 bug story

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Text CC BY 4.0.

Problem: the vehicle routing problem with divisible deliveries and pickups (Nagy, Wassan, Speranza and Archetti
2015). Each customer has a delivery and a pickup, which may be served by one visit or split into two visits (by the
same or different vehicles). Instances: Salhi and Nagy (1999) CMT X and Y sets from github.com/falcopt/FSPD at commit
de480ce, distances rounded to the nearest integer. Full table: [results-v2.md](results-v2.md); v1 table:
[results-v1.md](results-v1.md).

## v1 (2026-11-09) failed its tests, for two reasons

1. **PyVRP API.** PyVRP 0.14.1 builds clients and depots on separate `Location` objects
   (`Client(location=...)`, `ProblemData(locations, clients, depots, vehicle_types, ...)`). v1 passed x/y
   coordinates as in older versions, so every PyVRP call raised a TypeError. The portfolio fell back to our own
   engine on all 28 instances, and PyVRP never ran.
2. **The "exact" checker was wrong.** For the tiny instances, `exact()` required every subset of a route's requests
   to be load-feasible on its own. That rules out routes that deliver first and pick up later, so the "optima" were
   too high, and the solver appeared to beat them.

## v2 changes

PyVRP 0.14 `Location` API (with a fallback to the old one); routes read from the schedule's activities and checked
independently; `exact()` fixed, plus a test that the exact value is never above any checked solution; our own engine
solves the non-divisible problem first and seeds the divisible search with it; portfolio = PyVRP divisible (50% of
the time), PyVRP non-divisible (20%), own engine for the rest. 18 unit tests, all passed in the job.

## Guesses written before the run (private run notes, 2026-11-09)

| | guess | how sure | result |
|---|---|---|---|
| W1 | the unit test step passes | 0.75 | held (18 tests) |
| W2 | PyVRP ran on all 28 instances | 0.80 | did not hold as worded: 22 of 24 run. The FSPD copy had no CMTY1-4 files this time (v1 had read them), and 2 runs were frozen by the host |
| W3 | divisible result at or below the non-divisible one on at least 26 of 28 | 0.65 | did not hold: 12 of 22 |
| W4a | tiny instances: portfolio optimal on 12 of 12 | 0.85 | held |
| W4b | tiny instances: no result below the optimum | 0.97 | held |
| W5 | both literature anchors within 0.5% | 0.75 | did not hold: CMTX/CMT1 1.20%, CMTY/CMT1 missing |
| W6 | mean v2 divisible result at least 3% below v1 | 0.60 | held: v2/v1 = 0.904 on average over the 22 rows both solved (9.6% lower) |

Brier score over the seven: (0.0625 + 0.64 + 0.4225 + 0.0225 + 0.0009 + 0.5625 + 0.16) / 7 = 0.267.

## What it shows

- **The fixes worked.** PyVRP now runs, and the portfolio's divisible result is 9.6% better than v1's on the same
  rows. The biggest gains came on CMTX/CMT2, CMT5, CMT7 and CMT10 (about 16-20% better).
- **Splitting is not paying off yet.** Allowing a customer to be split can only make the best possible cost lower
  or equal. But our 60 s divisible result beat our own 30 s non-divisible result on only 11 of 22 instances, and the
  mean "saving" is -0.38%. So the divisible search is weaker than the non-divisible one, even though it is seeded
  with it. One row shows what is possible: v1's own engine found 646 on CMTX/CMT12 (divisible), below v2's 670 and
  below the 663 of the non-divisible run.
- **Timeouts were host pauses.** All four runs reported as over time coincide one-for-one with container freezes in
  the runner's log (pause length + 7-33 s of solving = 170.6, 208.2, 1,238.9 and 973.6 s of wall time). They are not
  solver failures. Later harnesses detect a freeze and re-run the instance.

## Next

A divisible-specific move: split a customer whose pickup no longer fits, and merge split pairs back when a single
visit becomes feasible. Guard: never return a divisible solution worse than the non-divisible one found in the same
run, since every non-divisible solution is also divisible-feasible.

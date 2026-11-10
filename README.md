# frontieror-routing

Practice solvers for the routing problems of the [FrontierOR Challenge](https://frontieror-challenge.com/), built and calibrated on public benchmark instances by MV2 of Munim, Inc.

Made with AI agents working in MV2's name. License: Apache-2.0 (code); notes and numbers CC BY 4.0.

Each solver follows the FrontierOR Main-track contract (`python solve.py --problem <slug> --instance in.json --output out.json --time-limit 60`): Python only, no network, 2 vCPUs, and it stops a few seconds before the limit. Each one is calibrated by running it as a subprocess, the same way the contest sandbox does. Every solution is then re-checked by an independent checker in the harness. The benchmark instances are downloaded at run time from their own repositories at pinned commits. They are not copied here; only our own numbers are. Guesses about each run are written down before it runs and scored afterwards, including the ones that fail.

These are practice solvers. They are not an official FrontierOR baseline, and the input and output conventions follow the public problem pages. Where a page leaves a key name open, the guess is marked in the code.

## Contents

| folder | FrontierOR slug | problem | status |
|---|---|---|---|
| [op/](op/) | fischetti1998 | Orienteering Problem | v1 is the solver: 39/39 feasible on OPLib, mean 0.992 of the EA4OP reference ([results](op/results-v1.md), [score](op/score-v1.md)). v2 was worse (0.990 of v1) and is kept only for the record ([score](op/score-v2.md)) |
| [vrpddp/](vrpddp/) | nagy2015 | VRP with divisible deliveries and pickups | v2: tests pass, PyVRP portfolio 9.6% better than v1; splitting does not pay off yet ([results](vrpddp/results-v2.md), [score](vrpddp/score-v2.md)) |
| [darp/](darp/) | cordeau2006 | Dial-a-ride | v2: 42/42 Cordeau (2006) instances feasible, mean gap 1.11% (a) and 0.72% (b) to the optimal or best known values, 14 within 0.1%; all six guesses held ([notes and score](darp/NOTES.md), [results](darp/results-v2.md)) |
| [spp/](spp/) | hoffman1993 | Set partitioning (airline crew scheduling) | v0.1.0 failed its first calibration: on 4 of 52 OR-Library instances (the widest, up to 288,507 columns) it wrote no solution within 60 s; 3 of the 4 scorable guesses failed. v0.2.0 (LP, Lagrangian bound, restricted MIP, exact reduced-cost pruning) is being calibrated against new guesses ([NOTES.md](spp/NOTES.md)) |
| [odimcf/](odimcf/) | barnhart2000 | Origin-destination integer multicommodity flow (unsplittable routing with rejection) | v0.1.0 (column generation with a Lagrangian bound, price-and-branch MIP, ruin-and-recreate) is being calibrated on 20 synthetic instances against arc-MIP optima; 7 guesses pre-registered before the run ([NOTES.md](odimcf/NOTES.md)). Code is published once its tests pass |
| [oplib-audit/](oplib-audit/) | (benchmark data) | OPLib consistency census | 337 of 344 stored EA4OP routes agree with their instance files. The other 7 were scored with the instance files as they were before OPLib's 2020 score fix: each earns exactly its stated score on the pre-fix file ([census](oplib-audit/score.md), [follow-up](oplib-audit/score-2.md)). Reported to the maintainers in [bcamath-ds/OPLib#2](https://github.com/bcamath-ds/OPLib/issues/2) |

## What the calibration runs have shown so far

- **Orienteering:** a simple insertion + 2-opt + iterated local search (v1) is within 1% of EA4OP on average at 60 s. Adding heavier moves (v2) made it worse, because each restart got slower.
- **VRPDDP:** pin and read the exact API of the version you install. PyVRP 0.14 changed how coordinates are passed, and v1 silently ran without it.
- **Dial-a-ride:** a pruning rule that looked like a lower bound was not one, because it ignored waiting before a pickup. With the rule fixed and tested against a brute force over every position, v2 serves every user on all 42 instances and is better than v1 on 32 of the 34 both solved.
- **Set partitioning:** a branch-and-cut solver that proves optimality in minutes can still produce nothing at all in 60 s on a wide instance. In a contest where no output scores 0, get a feasible solution first (a restricted problem on the most promising columns), then use the remaining time to improve it.
- **Benchmark data:** re-score stored reference solutions before comparing with them. In OPLib, 7 stored EA4OP routes (all Gen3, 50% budget) do not earn their stated score on the current instance files. The follow-up confirmed that they earn exactly that score on the files as they were before OPLib's commit 8e9cd01 (2020) changed those instances' node scores ([score-2](oplib-audit/score-2.md)). Our first write-up missed that commit.
- **Host pauses:** every run reported as over time in these jobs (6 of 6) coincided with the host freezing the container, not with the solver. Harnesses now detect a freeze and re-run the instance.

## Credits

- OPLib: Kobeaga, Merino and Lozano, "An efficient evolutionary algorithm for the orienteering problem", Computers & Operations Research 90 (2018); instances and EA4OP solutions from github.com/bcamath-ds/OPLib. Problem: Fischetti, Salazar González and Toth, "Solving the orienteering problem through branch-and-cut", INFORMS Journal on Computing 10 (1998). RB&C: Kobeaga, Merino and Lozano, "A revisited branch-and-cut algorithm for large-scale orienteering problems" (EJOR 2023; arXiv 2011.02743).
- VRPDDP: Nagy, Wassan, Speranza and Archetti, "The vehicle routing problem with divisible deliveries and pickups", Transportation Science 49 (2015); instances from Salhi and Nagy (1999), as published in github.com/falcopt/FSPD.
- DARP: Cordeau, "A branch-and-cut algorithm for the dial-a-ride problem", Operations Research 54 (2006); Ropke and Pisinger (2006); reference values from Ho et al. (2018); instance mirror github.com/garciparedes/jinete (MIT).
- Set partitioning: Hoffman and Padberg, "Solving airline crew scheduling problems by branch-and-cut", Management Science 39 (1993); instances from J. E. Beasley's OR-Library (contributed by Hoffman and Levine). HiGHS (MIT) through SciPy (BSD-3-Clause); OR-Tools CP-SAT (Apache-2.0).
- ODIMCF: Barnhart, Hane and Vance, "Using Branch-and-Price-and-Cut to Solve Origin-Destination Integer Multicommodity Flow Problems", Operations Research 48(2) (2000). Synthetic instances generated by our own odimcf_gen.py.
- PyVRP (MIT), Wouda, Lan and Kool, used as an optional engine in vrpddp/.

MV2, Munim, Inc., mv2@munimtech.com

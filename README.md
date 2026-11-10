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
| [darp/](darp/) | cordeau2006 | Dial-a-ride | v1 left users unserved on 8 of 42 Cordeau instances because of an insertion bug; fixed in v2, which is queued ([notes and score](darp/NOTES.md), [v1 results](darp/results-v1.md)) |
| [oplib-audit/](oplib-audit/) | (benchmark data) | OPLib consistency census | predictions written before the run ([PREREG.md](oplib-audit/PREREG.md)); job queued |

## What the calibration runs have shown so far

- **Orienteering:** a simple insertion + 2-opt + iterated local search (v1) is within 1% of EA4OP on average at 60 s. Adding heavier moves (v2) made it worse, because each restart got slower.
- **VRPDDP:** pin and read the exact API of the version you install. PyVRP 0.14 changed how coordinates are passed, and v1 silently ran without it.
- **Dial-a-ride:** a pruning rule that looked like a lower bound was not one, because it ignored waiting before a pickup. Tests now compare the insertion routine with a brute force over every position.
- **Benchmark data:** two of 39 EA4OP routes stored in OPLib do not match the scores in their own instance files (tsp225-gen3-50, a280-gen3-50). A full census is queued; see [oplib-audit/PREREG.md](oplib-audit/PREREG.md).
- **Host pauses:** every run reported as over time in these jobs (6 of 6) coincided with the host freezing the container, not with the solver. Harnesses now detect a freeze and re-run the instance.

## Credits

- OPLib: Kobeaga, Merino and Lozano, "An efficient evolutionary algorithm for the orienteering problem", Computers & Operations Research 90 (2018); instances and EA4OP solutions from github.com/bcamath-ds/OPLib. Problem: Fischetti, Salazar González and Toth, "Solving the orienteering problem through branch-and-cut", INFORMS Journal on Computing 10 (1998). RB&C: Kobeaga, Merino and Lozano, "A revisited branch-and-cut algorithm for large-scale orienteering problems" (EJOR 2023; arXiv 2011.02743).
- VRPDDP: Nagy, Wassan, Speranza and Archetti, "The vehicle routing problem with divisible deliveries and pickups", Transportation Science 49 (2015); instances from Salhi and Nagy (1999), as published in github.com/falcopt/FSPD.
- DARP: Cordeau, "A branch-and-cut algorithm for the dial-a-ride problem", Operations Research 54 (2006); Ropke and Pisinger (2006); reference values from Ho et al. (2018); instance mirror github.com/garciparedes/jinete (MIT).
- PyVRP (MIT), Wouda, Lan and Kool, used as an optional engine in vrpddp/.

MV2, Munim, Inc., mv2@munimtech.com

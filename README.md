# frontieror-routing

Practice solvers for the routing problems of the [FrontierOR Challenge](https://frontieror-challenge.com/), built and calibrated on public benchmark instances by MV2 of Munim, Inc.

Made with AI agents working in MV2's name. License: Apache-2.0.

Each solver follows the FrontierOR Main-track contract (`python solve.py --problem <slug> --instance in.json --output out.json --time-limit 60`): Python only, no network, 2 vCPUs, and it stops a few seconds before the limit. Each one is calibrated by running it as a subprocess, the same way the contest sandbox does. Every solution is then re-checked by an independent checker in the harness. The benchmark instances are downloaded at run time from their own repositories at pinned commits. They are not copied here; only our own numbers are.

These are practice solvers. They are not an official FrontierOR baseline, and the input and output conventions follow the public problem pages. Where a page leaves a key name open, the guess is marked in the code.

## Contents

| folder | FrontierOR slug | problem | status |
|---|---|---|---|
| [op/](op/) | fischetti1998 | Orienteering Problem | v1 calibrated on 39 OPLib instances ([results](op/results-v1.md), [score](op/score-v1.md)); v2 queued |
| vrpddp/ | nagy2015 | VRP with divisible deliveries and pickups | v1 calibration found two bugs; v2 queued; published once it passes its tests |
| darp/ | cordeau2006 | Dial-a-ride | calibration on the Cordeau (2006) instances queued |

## Orienteering (op/), v1 in one paragraph

The solver builds a tour by greedy prize-per-extra-time insertion, then runs 2-opt and an iterated local search that removes part of the tour and re-inserts greedily (in the spirit of Vansteenwegen et al. 2009). It used 60 s per instance on 39 OPLib instances (Kobeaga, Merino and Lozano 2018; generations 1-3, 50% budget, 51-318 cities). All 39 tours were feasible and none ran over time. The mean prize ratio against the EA4OP reference tours stored in OPLib was 0.992 (lowest 0.857, on lin318-gen2). The solver matched or beat the reference on 18 instances and beat it on 6. On 12 random 10-city instances it found the proven optimum 10 times. Two of the four guesses written before the run failed; see [op/score-v1.md](op/score-v1.md).

## Credits

- OPLib: Kobeaga, Merino and Lozano, "An efficient evolutionary algorithm for the orienteering problem", Computers & Operations Research 90 (2018); instances and EA4OP solutions from github.com/bcamath-ds/OPLib. Problem: Fischetti, Salazar González and Toth, "Solving the orienteering problem through branch-and-cut", INFORMS Journal on Computing 10 (1998).
- VRPDDP: Nagy, Wassan, Speranza and Archetti, "The vehicle routing problem with divisible deliveries and pickups", Transportation Science 49 (2015); instances from Salhi and Nagy (1999), as published in github.com/falcopt/FSPD.
- DARP: Cordeau, "A branch-and-cut algorithm for the dial-a-ride problem", Operations Research 54 (2006); Ropke and Pisinger (2006); reference values from Ho et al. (2018); instance mirror github.com/garciparedes/jinete (MIT).
- PyVRP (MIT), Wouda, Lan and Kool, used as an optional engine in vrpddp/.

MV2, Munim, Inc., mv2@munimtech.com

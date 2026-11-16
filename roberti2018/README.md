# roberti2018: two-echelon capacitated VRP with grouping constraints (2E-CVRPGC)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0 (code); text CC BY 4.0.

A solver for FrontierOR task `roberti2018`, written to the contest's Main-track contract:

    python solve.py --problem roberti2018 --instance in.json --output out.json --time-limit 60

It uses the standard library only, runs on 2 CPUs (a forked second search), stops at min(0.9 T, T - 3), and writes only answers that pass its own copy of the official rules.

**The problem.**
- First echelon: trucks carry freight from a depot to satellites. A satellite may be split between trucks.
- Second echelon: small vehicles serve every customer from a satellite. Every group of customers must be served from one satellite.
- Limits: truck and vehicle capacities, satellite throughput, and fleet sizes.
- Cost = truck travel + handling at satellites + small-vehicle travel.

**How it works.**
- **First echelon.** For any vector of satellite loads, the truck plan comes from a subset DP over "blocks". A block is one tour if its load fits a truck; otherwise its optimal tour is cut into full-truck segments. With two loaded satellites (and enough trucks), this plan is provably optimal. Plans are cached per load vector, so the search prices every move's effect on truck and handling cost exactly.
- **Second echelon.** Simulated annealing over the group -> satellite assignment and the routes, with adaptive penalties on capacities and fleet. Moves include relocate, swap, 2-opt, 2-opt*, moving or swapping groups between satellites, and ruin-and-recreate at customer and group level.

**Files.**
- `solve.py`: the solver, with `verify()`, an independent copy of the official checker's rules.
- `test_roberti2018.py`: the tests. They cover:
  - brute-force optima on tiny instances;
  - the first-echelon plan against exhaustive search;
  - verdict agreement with the official checker on mutated solutions;
  - a contest-way run on the public tiny instance.
- `roberti_real.py`: runs the solver on the public FrontierOR instances under the official checker and scores it against the stored Gurobi answers.
- `PREREG.md`: guesses about the first real run, written before it.
- `wait_prereg.py`: makes the graded job wait until those guesses are public.

**Status.** v0.1.0. The first run on the public instances is queued, and its 13 guesses are published first ([PREREG.md](PREREG.md)).

**Credits.** Problem and formulation: Liu, Luo, Qin and Lim, "A branch-and-cut algorithm for the two-echelon capacitated vehicle routing problem with grouping constraints", European Journal of Operational Research 266(2) (2018), as encoded in the FrontierOR benchmark (Hugging Face frontieror/FrontierOR, CC BY 4.0; instances and checkers are downloaded at run time and not copied here).

MV2, Munim, Inc., mv2@munimtech.com

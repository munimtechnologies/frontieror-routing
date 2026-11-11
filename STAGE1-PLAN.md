# FrontierOR Challenge Stage 1: plan by problem family

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. CC BY 4.0. Written 2026-11-11.

Stage 1 of the FrontierOR Challenge runs from 2027-01-04 to 2027-02-01: four weekly rounds of 15 problems. The public
FrontierOR benchmark (arXiv 2605.25246; Hugging Face `frontieror/FrontierOR`, CC BY 4.0) has 180 tasks, each with a
description, schemas, an official `feasibility_check.py`, a tiny and five large instances and Gurobi reference
solutions. All six of the challenge's public practice problems are benchmark tasks, so we expect the 60 Stage 1
problems to come mostly from these 180. That is an expectation, not something the organisers have said.

## The 180 tasks by family (from metadata/paper_meta_info.json; counts approximate)

| family | tasks | in the 50-task hard set | engine |
|---|---|---|---|
| Vehicle routing (VRPTW 11, CVRP/VRP 7, inventory/production routing 5, pickup-and-delivery/DARP 5, orienteering 3, arc routing 2, TSP variants 3, multi-depot, location-routing) | ~37 | 17 | PyVRP core + one adapter per task; own code for the variants PyVRP cannot model (done: op, vrpddp, darp) |
| Scheduling (parallel machine 9, unit commitment 7, project 5, rostering 4, crew 3, vehicle scheduling 4, job/flow shop 4, cumulative 4, other) | ~45 | 12 | OR-Tools CP-SAT models with a quick greedy start; MIP (HiGHS) for unit commitment |
| Knapsack and selection (0-1, quadratic, multiple, multiple-choice, portfolio) | ~17 | 1 | greedy + local search, DP where small, MIP |
| Graph optimisation (colouring 6, max clique 7, partitioning, interdiction) | ~17 | 4 | greedy + tabu (colouring), branch-and-bound/heuristic clique |
| Facility location (capacitated, uncapacitated, hub, p-median, covering) | ~14 | 3 | MIP + local search (done: scflp) |
| Network flow and design (multicommodity, fixed charge, Steiner, capacity expansion) | ~14 | 3 | column generation / MIP (done: odimcf) |
| Lot sizing and inventory | ~10 | 3 | MIP with relax-and-fix |
| Packing and cutting | ~9 | 3 | first-fit decreasing + column generation |
| Assignment, clustering, other | ~17 | 4 | MIP + local search |

## Order of work

1. **VRPTW engine** (11 tasks, 7 in the hard set): pecin2017 first (pure VRPTW), then bard2002, he2020,
   rothenbacher2018, reinhardt2016, spliet2015, desaulniers2010. Each adapter is checked on the task's six public
   instances with the official checker against Gurobi.
2. **CVRP / multi-depot** (mingozzi1999, pessoa2021, roberti2018, kang2021, roberti2021, vidal2011): same engine.
3. **CP-SAT scheduling core** (parallel machine, job shop, project scheduling).
4. Packing, knapsack, colouring/clique: fast generic heuristics.
5. Re-run the six practice solvers (op, vrpddp, darp, spp, odimcf, scflp) on their public instances with the official
   checkers.

Every solver keeps the contest contract: Python only, 2 vCPUs, 4 GB, no network, stop before the limit, write a
feasible answer first.

MV2, Munim, Inc., mv2@munimtech.com

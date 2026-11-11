# frontieror-routing

Practice solvers for the routing and network-design problems of the [FrontierOR Challenge](https://frontieror-challenge.com/), built and calibrated on public benchmark instances by MV2 of Munim, Inc.

Made with AI agents working in MV2's name. License: Apache-2.0 (code); notes and numbers CC BY 4.0.

**The contest contract.** Each solver follows the FrontierOR Main-track contract (`python solve.py --problem <slug> --instance in.json --output out.json --time-limit 60`): Python only, no network, 2 vCPUs, and it stops a few seconds before the limit.

**How each solver is calibrated:**
- it is run as a subprocess, the same way the contest sandbox does;
- every solution is re-checked by an independent checker in the harness;
- the benchmark instances are downloaded at run time from their own repositories at pinned commits. They are not copied here; only our own numbers are.

Guesses about each run are written down before it runs and scored afterwards, including the ones that fail.

These are practice solvers. They are not an official FrontierOR baseline, and the input and output conventions follow the public problem pages. Where a page leaves a key name open, the guess is marked in the code.

## Contents

| folder | FrontierOR slug | problem | status |
|---|---|---|---|
| [kit/](kit/) | (all) | Shared runtime and calibration harness | `frontier_runtime.py` keeps time, writes the best solution so far atomically, and has a watchdog that exits before the limit. `harness.py` runs a solver the way the contest does, re-checks the output, scores it against a reference, and re-runs a case when the host froze the container. `frontieror_hf.py` and `frontieror_real.py` download a benchmark task at a pinned revision and run a solver on its public instances with the official checker |
| [op/](op/) | fischetti1998 | Orienteering Problem | v1 is the solver: 39/39 feasible on OPLib, mean 0.992 of the EA4OP reference ([results](op/results-v1.md), [score](op/score-v1.md)). v2 was worse (0.990 of v1) and is kept only for the record ([score](op/score-v2.md)) |
| [vrpddp/](vrpddp/) | nagy2015 | VRP with divisible deliveries and pickups | v2: tests pass. The PyVRP portfolio is 9.6% better than v1, but splitting deliveries does not pay off yet ([results](vrpddp/results-v2.md), [score](vrpddp/score-v2.md)) |
| [darp/](darp/) | cordeau2006 | Dial-a-ride | v2: feasible on all 42 Cordeau (2006) instances. Mean gap to the optimal or best known values is 1.11% on set (a) and 0.72% on set (b), and 14 instances are within 0.1%. All six guesses held ([notes and score](darp/NOTES.md), [results](darp/results-v2.md)) |
| [spp/](spp/) | hoffman1993 | Set partitioning (airline crew scheduling) | v0.2.0 reaches the proven optimum on all 54 OR-Library instances within 60 s, including the 4 widest (up to 288,507 columns) where v0.1.0 wrote nothing. All six guesses held, Brier 0.070 ([score](spp/score-v2.md), [results](spp/results-v2.md), [notes](spp/NOTES.md)) |
| [odimcf/](odimcf/) | barnhart2000 | Origin-destination integer multicommodity flow (unsplittable routing with rejection) | v0.1.0: feasible on 20/20 synthetic instances, matched 5 of 7 proven optima, never worse than greedy. 5 of 7 guesses held, Brier 0.135 ([score](odimcf/score-v1.md), [results](odimcf/results-v1.md)). v0.2.0 follows the official checker's rejection penalty and is queued on the six public FrontierOR instances, with 7 guesses pre-registered ([NOTES.md](odimcf/NOTES.md)) |
| [scflp/](scflp/) | bodur2017 | Two-stage stochastic capacitated facility location | v0.1.0: all 11 pre-registered guesses held, Brier 0.130 ([score](scflp/score-v1.md)). The official checker accepts all 6 public FrontierOR instances. Mean score against the stored Gurobi solutions is 1.0007 on the 5 large ones; on large_2 we are 0.36% cheaper ([real results](scflp/results-real-v1.md)). Synthetic: proven optimum on all 6 small cases, and 3 of 8 medium cases beat a 150 s HiGHS run ([synthetic results](scflp/results-v1.md)) |
| [vrptw/](vrptw/) | pecin2017, bard2002 (2 of 11 VRPTW tasks) | Vehicle routing with time windows | pecin2017 (distance) v0.1.0 is queued on the six public instances, 6 guesses pre-registered ([NOTES.md](vrptw/NOTES.md)). bard2002 (fewest vehicles) v0.1.0 is queued too, with 8 guesses pre-registered ([BARD-NOTES.md](vrptw/BARD-NOTES.md)). Reading the official bard2002 checker shows that its load constraint uses a big-M of Q - q_j, which rejects some loads that fit in the vehicle; a probe with the official checker itself is part of the run. Code is published once its tests pass |
| [he2020/](he2020/) | he2020 | VRPTW with convex node costs (quadratic penalty for serving away from each customer's preferred time) | v0.1.0 is queued on the six public instances, with 7 guesses pre-registered ([NOTES.md](he2020/NOTES.md)). For a fixed route, the best service times are found exactly by a bounded isotonic regression (pool-adjacent-violators). Reading the code shows that the official checker reads rho from a top-level key the instance schema does not list (default 0), while the Gurobi model reads `inconvenience_cost_function.rho`; the run checks which one the instances carry |
| [census/](census/) | (all 180 tasks) | FrontierOR checker census | Pre-registered, 4 guesses ([PREREG.md](census/PREREG.md)). Each task's official checker is run unchanged on its stored Gurobi solutions, with every read of an absent instance key recorded. The census asks two questions: which defaults the checkers silently use, and whether today's checkers still accept the stored references |
| [oplib-audit/](oplib-audit/) | (benchmark data) | OPLib consistency census | 337 of 344 stored EA4OP routes agree with their instance files. The other 7 were scored with the instance files as they were before OPLib's 2020 score fix: each earns exactly its stated score on the pre-fix file ([census](oplib-audit/score.md), [follow-up](oplib-audit/score-2.md)). Reported to the maintainers in [bcamath-ds/OPLib#2](https://github.com/bcamath-ds/OPLib/issues/2) |

Plan for the challenge's Stage 1 (from 2027-01-04), by problem family across the benchmark's 180 tasks: [STAGE1-PLAN.md](STAGE1-PLAN.md).

## What the calibration runs have shown so far

- **Orienteering:** a simple insertion + 2-opt + iterated local search (v1) is within 1% of EA4OP on average at 60 s. Adding heavier moves (v2) made it worse, because each restart got slower.
- **VRPDDP:** pin and read the exact API of the version you install. PyVRP 0.14 changed how coordinates are passed, and v1 silently ran without them.
- **Dial-a-ride:** a pruning rule that looked like a lower bound was not one, because it ignored waiting before a pickup. With the rule fixed and tested against a brute force over every position, v2 serves every user on all 42 instances. It beats v1 on 32 of the 34 instances both versions solved.
- **Set partitioning:** a branch-and-cut solver that proves optimality in minutes can still produce nothing at all in 60 s on a wide instance. In a contest where no output scores 0, get a feasible solution first (a restricted problem on the most promising columns), then spend the remaining time improving it. v0.2.0 adds an LP-dual Lagrangian bound and exact reduced-cost pruning. With them it solved the widest OR-Library instance (nw05, 288,507 columns) to the optimum in 6.8 s, where HiGHS on the full problem needed 230 s.
- **Multicommodity flow:** check the references before scoring against them. In the synthetic run, a host pause cut one 300 s reference short, and one time-limited MIP reference was far from optimal. Both are flagged and left out of the grading where they would distort it.
- **Stochastic facility location:** once the open set is fixed, the problem splits into one min-cost flow per scenario. So a 60 s search over open sets, with every candidate evaluated exactly, can match or beat a time-limited Gurobi or HiGHS run on the full model. It matched the stored Gurobi solution on 4 of the 5 large public instances and beat it on the fifth.
- **Benchmark data:** re-score stored reference solutions before comparing with them. In OPLib, 7 stored EA4OP routes (all Gen3, 50% budget) do not earn their stated score on the current instance files. The follow-up confirmed that they earn exactly that score on the files as they were before OPLib's commit 8e9cd01 (2020) changed those instances' node scores ([score-2](oplib-audit/score-2.md)). Our first write-up missed that commit.
- **Host pauses:** every run reported as over time in these jobs coincided with the host freezing the container, not with the solver. Harnesses now detect a freeze and re-run the instance.
- **The official checkers are public. Read them line by line.** All the practice problems are tasks of the FrontierOR benchmark (arXiv 2605.25246), published on Hugging Face as [frontieror/FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR) (CC BY 4.0). It has 180 tasks, each with its `feasibility_check.py`, instances and Gurobi reference solutions. Calibrations now also run on those instances, with the official checker, at a pinned dataset revision. Four examples of what the checkers decide:
  - barnhart2000: a rejected commodity costs `artificial_arc_cost x demand`.
  - bard2002: the depot-to-customer and return legs are not timed at all.
  - bard2002: a route's load plus its first customer's demand must fit in the vehicle, which is stricter than plain capacity.
  - he2020: the objective check reads rho from `inconvenience_cost_factor_rho` (default 0), not from the `inconvenience_cost_function` object the schema describes. A run is queued to check which key the instances carry.

## Credits

- OPLib: Kobeaga, Merino and Lozano, "An efficient evolutionary algorithm for the orienteering problem", Computers & Operations Research 90 (2018); instances and EA4OP solutions from github.com/bcamath-ds/OPLib. Problem: Fischetti, Salazar González and Toth, "Solving the orienteering problem through branch-and-cut", INFORMS Journal on Computing 10 (1998). RB&C: Kobeaga, Merino and Lozano, "A revisited branch-and-cut algorithm for large-scale orienteering problems" (EJOR 2023; arXiv 2011.02743).
- VRPDDP: Nagy, Wassan, Speranza and Archetti, "The vehicle routing problem with divisible deliveries and pickups", Transportation Science 49 (2015); instances from Salhi and Nagy (1999), as published in github.com/falcopt/FSPD.
- DARP: Cordeau, "A branch-and-cut algorithm for the dial-a-ride problem", Operations Research 54 (2006); Ropke and Pisinger (2006); reference values from Ho et al. (2018); instance mirror github.com/garciparedes/jinete (MIT).
- Set partitioning: Hoffman and Padberg, "Solving airline crew scheduling problems by branch-and-cut", Management Science 39 (1993); instances from J. E. Beasley's OR-Library (contributed by Hoffman and Levine). HiGHS (MIT) through SciPy (BSD-3-Clause); OR-Tools CP-SAT (Apache-2.0).
- ODIMCF: Barnhart, Hane and Vance, "Using Branch-and-Price-and-Cut to Solve Origin-Destination Integer Multicommodity Flow Problems", Operations Research 48(2) (2000). Synthetic instances generated by our own odimcf_gen.py.
- SCFLP: Bodur, Dash, Günlük and Luedtke, "Strengthened Benders Cuts for Stochastic Integer Programs with Continuous Recourse", INFORMS Journal on Computing 29(1) (2017). Synthetic instances generated by our own scflp_gen.py, following the capacitated facility location recipe of Cornuéjols, Sridharan and Thizy (EJOR 1991). Min-cost flows by OR-Tools (Apache-2.0).
- VRPTW: Bard, Kontoravdis and Yu, "A Branch-and-Cut Procedure for the Vehicle Routing Problem with Time Windows", Transportation Science 36(2) (2002); Pecin, Contardo, Desaulniers and Uchoa, "New Enhancements for the Exact Solution of the Vehicle Routing Problem with Time Windows", INFORMS Journal on Computing 29(3) (2017); route elimination after Nagata and Bräysy, "A powerful route minimization heuristic for the vehicle routing problem with time windows", Operations Research Letters 37(5) (2009).
- VRPTW with convex node costs: He, Irnich and Song, "Branch-and-Cut-and-Price for the Vehicle Routing Problem with Time Windows and Convex Node Costs", Transportation Science (2019). Pool-adjacent-violators for separable convex isotonic regression: Ahuja and Orlin, "A fast scaling algorithm for minimizing separable convex functions subject to chain constraints", Operations Research 49(5) (2001).
- PyVRP (MIT), Wouda, Lan and Kool, used as an optional engine in vrpddp/, vrptw/ and he2020/.
- FrontierOR benchmark: "FrontierOR: Benchmarking LLMs' Capacity for Efficient Algorithm Design in Large-Scale Optimization" (arXiv 2605.25246); code github.com/Minw913/FrontierOR; tasks, checkers, instances and Gurobi references from the Hugging Face dataset frontieror/FrontierOR (CC BY 4.0), downloaded at run time and not copied here.

MV2, Munim, Inc., mv2@munimtech.com

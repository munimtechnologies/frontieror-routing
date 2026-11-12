# vidal2011: multi-depot periodic vehicle routing (MDPVRP) solver

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; text CC BY 4.0.

This is a candidate solver for task `vidal2011` of the public FrontierOR benchmark (Hugging Face `frontieror/FrontierOR`, CC BY 4.0), the source of the FrontierOR Challenge's problems.

In this task, every customer must be given one depot and one visit pattern (a set of days) from its own list. Then, for each depot and day, at most m vehicle routes visit exactly the customers due that day. Each route must respect vehicle capacity and a route-duration limit. The goal is to minimise total Euclidean travel. Gurobi's stored reference stopped at its one-hour limit on all five large instances. MV2's generic gpshim engine found no solution at all, because the reference model relies on Gurobi's lazy-constraint callback.

| file | what it is |
|---|---|
| `solve.py` | the solver: contest command line, standard library only, atomic writes, deadline min(0.9 T, T − 3) |
| `test_vidal2011.py` | tests: brute-force optimality on tiny instances, our checker vs the official one on 300 randomly broken solutions, the CLI time limit |
| `vidal_real.py` | runs the solver the contest way on the tiny instance and the five large public instances at 10 s, 60 s and 300 s, and at 60 s with one worker, judged by the official `feasibility_check.py` |
| `PREREG.md` | nine guesses and decision rules, published before the first run |

Run it: `python solve.py --problem vidal2011 --instance large_instance_1.json --output solution.json --time-limit 60`

How it works: each (depot, day) has m route slots. The search may break capacity or duration, at an adaptive penalty, but only solutions that pass an independent copy of the official rules are written. Construction puts each customer on its cheapest (depot, pattern) option by penalised insertion. Simulated annealing then works with eight moves: relocate, swap, 2-opt, 2-opt*, reassigning one customer to another (depot, pattern) option, and ruin-and-recreate of nearby customers. It runs from the construction, then from the best solution twice at lower temperatures, and finishes with a high-penalty polish. On 2 CPUs a forked second seed hands back its best solution before the deadline.

Results will be graded against `PREREG.md` in `score-v1.md` once the queued run finishes.

MV2, Munim, Inc., mv2@munimtech.com

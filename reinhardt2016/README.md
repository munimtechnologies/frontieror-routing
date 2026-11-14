# reinhardt2016: edge set cost VRPTW (MV2 ESVRPTW engine v0.1.0)

FrontierOR task `reinhardt2016` (Reinhardt, Jepsen and Pisinger, Transportation Science 50(2), 2016). It is a VRPTW from one depot. Every edge is either free or belongs to an edge set, and the first use of any edge in a set costs that set's access cost once. The objective is travel distance plus the access costs of the sets used. It is on the benchmark's hard list: the stored Gurobi run hit its one-hour limit on all 5 large instances.

Made with AI agents working in MV2's name (MV2 of Munim, Inc., mv2@munimtech.com). Code Apache-2.0; text CC BY 4.0.

## Files

| file | what it is |
|---|---|
| `solve.py` | The solver, standard library only. Run it the contest way: `python solve.py --problem reinhardt2016 --instance in.json --output out.json --time-limit 60 [--seed 1]` |
| `test_reinhardt2016.py` | Unit tests. They check single insertions against brute force (including banned and free edge sets), check optimum on 5-customer instances against brute force, and run the official-checker mirror on hand-made bad answers. With `MV2_FROC_HF=<copy of the Hugging Face benchmark>`, `TestContestWay` also compares the mirror with the official checker on 100 mutated answers. |
| `reinhardt_real.py` | The runner for the real public instances (tiny + 5 large, at 60 s and 10 s), with the official checker, through `kit/`. |
| `wait_prereg.py` | The graded job's first step. It waits until `PREREG.md` is public here and records whether it was. |
| `PREREG.md` | 11 guesses (E1-E11), published before the first run. |

## Method

- **One search on the true objective.** For every edge set, the solution keeps a count of the arcs in use that need it. That gives the exact change in total cost (distance plus the access cost of sets that become used or stop being used) of putting a customer anywhere, in O(1).
- **Time windows in O(1) per position**, from each route's earliest service starts and latest feasible starts.
- **Slack induction by string removals** (Christiaens and Vanden Berghe 2020) with simulated annealing, plus two edge-set moves:
  - drop: remove the customers on a used set's arcs and re-insert them with that set banned;
  - open: remove customers that an unused set covers and re-insert them as if that set were free.
- **Every written answer passes `verify()`**, a line-by-line mirror of the official `feasibility_check.py`.

## Status

The first run on the real instances (job `froc-reinhardt2016-v1`) is queued. Its grade will be in `score-v1.md`. Nothing here claims a score yet.

## Limits

- If an edge is listed in more than one edge set, the solver pays for every set that lists it. The official checker asks only for the last one listed. This can only make the solver's answers dearer, never infeasible; the runner's log counts such arcs (`multi_set_arcs`).
- One seed and public instances only. The contest scores private instances against its own frozen references.

Benchmark: Hugging Face `frontieror/FrontierOR` (CC BY 4.0).

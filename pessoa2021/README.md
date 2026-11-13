# pessoa2021: robust CVRP solver for the FrontierOR benchmark

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

FrontierOR task `pessoa2021` (Pessoa, Poss, Sadykov and Vanderbeck, *Branch-cut-and-price for the robust
capacitated vehicle routing problem with knapsack uncertainty*, Operations Research 69(3), 2021): a fleet of
exactly m identical vehicles leaves one depot; every customer is visited once; each route must stay within the
vehicle capacity for every demand scenario in which at most Gamma customers rise from their nominal demand to
nominal + deviation. Minimise total travel cost.

For one route, the worst case is the sum of its nominal demands plus its Gamma largest deviations (this is the
rule the task's official `feasibility_check.py` applies).

## Files

- `solve.py`: the solver (standard library only). `python solve.py --problem pessoa2021 --instance in.json
  --output out.json --time-limit 60`.
- `test_pessoa2021.py`: unit tests: the robust-load rule against brute force over the budget's vertices; the O(1)
  insertion price against recomputation; cache consistency through 1,200 ruin-and-recreate steps; brute-force
  optima on small instances (including tight capacity, Gamma = 0, Gamma above route size, asymmetric costs and
  n < m); verify() rejections; agreement with the official checker when `PESSOA_OFFICIAL` points to it; and the
  CLI's time budget.
- `pessoa_real.py`: runs the solver the contest way on the six public instances and judges every answer with the
  official checker.
- `PREREG.md`: 12 predictions written before the first run (R12 probes whether the official checker accepts
  answers padded with empty routes; the solver itself never pads).

## Method

Slack induction by string removals (SISR, Christiaens & Vanden Berghe, Transportation Science 2020), written from the
paper's description: remove short strings of consecutive customers from a few routes near a random customer,
reinsert them one by one at the cheapest position (skipping each position with a 1% chance), accept by simulated
annealing on a clock schedule. Per route we keep the nominal sum, the sum of the Gamma largest deviations and the
Gamma-th largest deviation, so the worst-case demand after inserting customer c is
`nominal + d_c + top + max(0, dev_c - threshold)`. Over-capacity and empty routes are penalised far above any travel
cost. New bests are polished (exact 2-opt and relocation per route), checked and written atomically; a forked second
search with another seed uses the second CPU.

Benchmark data: Hugging Face `frontieror/FrontierOR` (CC BY 4.0), not redistributed here.

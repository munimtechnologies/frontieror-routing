# reihaneh2019 (vehicle routing with demand allocation): pre-registered guesses for the first real-instance run

Written 2026-11-15 (UTC), before MV2's engine v0.1.0 has ever run on any FrontierOR reihaneh2019 instance, public or
private. Made with AI agents working in MV2's name (MV2 of Munim, Inc.). Text CC BY 4.0, code Apache-2.0.

## The task

FrontierOR task reihaneh2019 (Reihaneh and Ghoniem, "A branch-and-price algorithm for a vehicle routing with demand
allocation problem", EJOR 2019). Vehicles leave one depot and visit a chosen subset of candidate delivery sites; each
customer is assigned to one opened site and collects its order there. A site is on at most one tour, and the demand
of all customers collected on a tour must fit in the vehicle. Minimise routing cost plus customer-to-site assignment
cost. In the benchmark's hard-set inputs, the stored Gurobi run of the compact vehicle-indexed model (gurobi_code.py,
one thread) hit its one-hour limit on all 5 large public instances (hard-set rank 37 of 180).

## The engine (v0.1.0, `solve.py`, standard library only)

Ruin and recreate with simulated annealing over (tours, customer-to-site assignment): customers are removed by
location, at random, by site or by tour; sites left empty are closed; each customer goes back to its cheapest option
(an opened site whose tour has room, or a closed site opened at its cheapest position in a tour with room or on a new
tour). Extra moves move a site with all its customers to another tour, or swap an opened site for a nearby closed one.
Tours are re-sequenced by 2-opt and relocation; near-best states get a customer relocation pass. `verify()` mirrors
the official feasibility_check.py (constraints 4b-4l and the objective check) and every written answer passes it.

## The run (job froc-reihaneh2019-v1)

Its first step waits until this file is public. Then: the unit tests (`test_reihaneh2019.py`, including a brute-force
optimum check on small instances); then `reihaneh_real.py` runs `solve.py` the contest way on the tiny and 5 large
public instances in three variants: `vrdap-60s` (seed 1, 60 s), `vrdap-10s` (seed 1, 10 s) and `vrdap-60s-seed7`
(seed 7, 60 s); every answer is judged by the official checker and by `verify()`. Score = min(2, Gurobi's stored
objective / ours), the contest's rule for a minimised positive objective, here against the stored Gurobi answer (the
contest uses its own frozen references on private instances). "Mean score" = mean over the 5 large instances.

## Guesses

| id | guess |
|---|---|
| R1 | The unit tests pass in the job (`OK` line in tests.txt; skips allowed). |
| R2 | The official checker accepts all 18 of our answers (6 instances x 3 variants). |
| R3 | `verify()` agrees with the official checker on every comparison the runner makes (our 18 answers and Gurobi's stored answers). |
| R4 | Tiny instance, `vrdap-60s`: our objective equals Gurobi's stored tiny objective within 0.01%. |
| R5 | `vrdap-60s` mean score is at least 1.000. |
| R6 | `vrdap-60s` is strictly better than Gurobi's stored answer on at least 3 of the 5 large instances. |
| R7 | No large-instance score at `vrdap-60s` reaches 1.5 (a guess that, on instances this small, the time-limited references are not far off). |
| R8 | The `vrdap-10s` mean score is within 0.01 of the `vrdap-60s` mean score. |
| R9 | The `vrdap-60s-seed7` mean score is within 0.01 of the `vrdap-60s` mean score. |
| R10 | Size guess, inferred from the hard-set averages (12,800 variables, 5,150 integer): the 5 large instances average 20-30 candidate sites and 40-60 customers. |
| R11 | All 18 runs finish within their time limit (runner status `ok`). |
| R12 | On each of the 5 large instances, our `vrdap-60s` answer uses no more tours than Gurobi's stored answer. |

Guesses that fail are reported as failed. Results go in `score-v1.md` and the raw outputs in `runs/v1/`.

MV2, Munim, Inc., mv2@munimtech.com

# he2020 solver v0.1.0: grade of run 1 (`froc-he2020-real-v1`)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Graded 2026-11-13 (about 10:45 UTC) against [`NOTES.md`](NOTES.md), whose guesses H1-H7 were published on 2026-11-11
before the run and are not edited. Run: 2026-11-13 09:55-10:18 UTC, one shared 2-CPU machine, `python:3.12`, PyVRP
installed, 60 s per instance, benchmark revision `ef42a2eac135` (Hugging Face
[frontieror/FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR), CC BY 4.0). All 9 unit tests passed
in the same job, including the one that runs the official checker on a solver output.

## Results on the six public instances

| instance | n | our total cost | stored Gurobi total | Gurobi status | score (Gurobi / ours) | official checker | wall (s) |
|---|---|---|---|---|---|---|---|
| tiny | 25 | 1102.698 | 1102.698 | 2 (optimal) | 1.000 | feasible | 55.3 |
| large_1 | 30 | 980.022 | 980.022 | 9 (time limit) | 1.000 | feasible | 55.3 |
| large_2 | 50 | 1148.989 | 1208.610 | 9 (time limit) | 1.052 | feasible | 55.3 |
| large_3 | 100 | 1045.398 | 1254.449 | 9 (time limit) | 1.200 | feasible | 55.4 |
| large_4 | 100 | 735.249 | 822.113 | 9 (time limit) | 1.118 | feasible | 55.5 |
| large_5 | 100 | 2588.846 | 2898.069 | 9 (time limit) | 1.119 | feasible | 55.4 |

Mean score on the five large instances: **1.098**. We match Gurobi on tiny and large_1, and are 4.9% to 16.7% cheaper
on the other four, where Gurobi stopped at its one-hour limit. Our own checker and the official one agreed on all 12
comparisons (ours and Gurobi's solution on each instance). One instance was re-run once because the host froze the
container; the re-run is the one reported.

**Sense check (scores above 1.05).** These are not a checker or modelling difference. The official checker recomputes
the objective (routing cost plus rho × squared deviation from each customer's preferred time) and requires the
reported value to match it, and it accepted all four. Both totals were recomputed with the same rho and the same
formula. Gurobi's status on all five large instances is 9 (time limit), so its stored solutions are not proven
optimal, and the benchmark's own metadata lists he2020 as timing out on 5 of 5 large instances. Our solutions are
published next to this file ([runs/v1/solutions/](runs/v1/solutions/)) so anyone can re-check them with the official
`feasibility_check.py`.

## The rho question is settled: there is no gap

Before the run we wrote that the official checker reads rho from a top-level key, `inconvenience_cost_factor_rho`
(default 0), that the schema does not list. **All six instances carry that key**, with the same value as
`inconvenience_cost_function.rho` (0.01 on tiny, 0.1 on the large instances). So the checker uses the right rho. The
probe confirms it: our solution with `objective_value` set to its routing cost alone (a test of the checker, never an
entry) is **rejected** on all six instances. The schema simply does not document a key the instances do have. We
withdraw the "possible gap" from our list; the schema omission is minor.

## Guesses

| id | guess | p | result |
|---|---|---|---|
| H1 | our checker accepts our solution on 6/6 within 60 s | 0.85 | **held** (6/6; slowest 55.5 s) |
| H2 | none of the 6 instances has a top-level `inconvenience_cost_factor_rho` key | 0.60 | **missed** (all 6 have it) |
| H3 | with that key set to the gurobi_code.py rho, the official checker accepts ours on 6/6 | 0.85 | **held** |
| H4 | if H2 holds: official checker rejects ours on >= 5 of 6, constraint 7 only | 0.65 | not applicable (H2 missed) |
| H5 | the official checker still says "feasible" for all 6 stored Gurobi solutions | 0.55 | **held** |
| H6 | our total cost is lower than Gurobi's on >= 2 of the 5 large instances | 0.60 | **held** (4 of 5) |
| H7 | every preferred_time equals its window midpoint within 1e-9 | 0.90 | **held** (max difference 0.0) |

5 of 6 gradable guesses held; H4 was conditional on H2 and is not graded. Brier score over the six: 0.130 (lower is
better; always saying 0.5 scores 0.25).

## What it means

he2020 was a task where MV2's general engine (gpshim) gave no accepted answer on large instances. This solver covers
all six public instances and beats the time-limited Gurobi reference on four. What made the difference is the exact
per-route schedule: for a fixed customer order, the best service times are a bounded isotonic regression, solved
exactly by pool-adjacent-violators, so the search compares routes on their true cost.

Limits: one run per instance on one shared machine; the contest scores private instances, which may differ in size
and time limit; 55.5 s of a 60 s limit leaves 4.5 s of margin.

Data: [results.md](runs/v1/results.md), [rho.md](runs/v1/rho.md), [results.json](runs/v1/results.json),
[solutions](runs/v1/solutions/).

# martin-iradi2024 berth solver v0.1.0: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; text CC BY 4.0.

Written on 2026-11-13 (UTC), in run 20261113T220630Z. At that point the solver had not been run anywhere, on any instance, not even its own tests.

## The task

[FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR) (CC BY 4.0) task `martin-iradi2024` is the multi-port continuous berth allocation problem. A shipping line's container ships each follow a fixed route of port calls. At every call the line chooses where along the quay the ship berths and when berthing starts, and on every leg it picks one of a set of discrete sailing speeds. No two ships, whether the line's own or fixed external ones, may overlap in quay space and time. Handling takes longer the further a ship berths from its ideal position. The cost is waiting + handling + delay past the expected finish + a penalty past the latest finish + fuel (cubic in speed).

It is in the benchmark's hard set. The stored Gurobi model has about 9,100 variables, 8,500 of them integer: big-M disjunctions for every pair of ships at a port. Gurobi stopped at its one-hour limit on all five large instances. MV2's general-purpose engine returns no answer on them, so this is his first coverage of the task.

## The solver (standard library only)

- **One ship at a time, with everything else fixed:** a label DP along the ship's route.
  - For each label and each speed on the next leg, the call goes to its cheapest quay position: the ideal position, a quay end, or flush against another ship's edge, each with the earliest free start.
  - Label dominance is exact for the waiting cost. An earlier departure can always copy a later one by waiting in port.
  - Up to 8 labels are kept per call.
- **Construction:** ships are planned one by one, in order of their first earliest start.
- **Improvement:** ruin and recreate. It removes 1-4 ships that share a port and a time span, re-plans them in random order, and accepts by simulated annealing that cools to zero. The last fifth of the time continues greedily from the best solution found.
- **First call (`--first-arrival`):**
  - The problem description and the official checker only require the first call's arrival to be no later than its start, so by default the first call carries no waiting cost.
  - The stored Gurobi model fixes that arrival to the earliest start time, an "INFERRED ASSUMPTION" in its code.
  - Variant `est` follows Gurobi's rule. It is the like-for-like comparison.

## Job `froc-martin2024-v1`

The job runs on the 6 public instances (tiny + large_1..5) the contest way. Each output is judged by the official `feasibility_check.py`. Variants:
- `berth-v010-60s`: 60 s, description rule;
- `berth-v010-60s-est`: 60 s, Gurobi's rule;
- `berth-v010-10s`: 10 s, description rule.

Score = min(2, Gurobi's stored objective / ours). This is the contest's formula, but applied against the stored Gurobi answer. The contest's own frozen reference may be stronger, so no score here is a contest claim.

## Guesses (probabilities fixed now)

| id | guess | p |
|---|---|---|
| M1 | Every unit test passes in the job's first test step | 0.55 |
| M2 | The official checker accepts all 6 cases of `berth-v010-60s` | 0.80 |
| M3 | The official checker accepts all 18 runs, and our `verify()` agrees with it on all 18 runs and all 6 stored Gurobi solutions (24/24) | 0.70 |
| M4 | `berth-v010-60s-est`: mean score over the 5 large instances >= 1.00 | 0.50 |
| M5 | `berth-v010-60s-est`: strictly better than Gurobi on at least 3 of the 5 large instances | 0.50 |
| M6 | Mean large score of `berth-v010-60s` >= that of `berth-v010-60s-est` | 0.85 |
| M7 | Mean large score of `berth-v010-10s` >= that of `berth-v010-60s` minus 0.02 | 0.60 |
| M8 | In every one of the 6 stored Gurobi solutions, every first call has arrival = earliest start time | 0.90 |
| M9 | tiny, `berth-v010-60s-est`: our objective is within 0.1% of Gurobi's, or better | 0.75 |
| M10 | No run in any variant ends overtime, with no output or crashed | 0.85 |

Grading uses `summary.json` (`large_mean_score`, `large_strictly_better`, `official_feasible`, `ours_agree_official`, `status`, `gurobi_first_calls`) and `tests.txt`.

## Limits

- **Single-ship DP:** it keeps only the cheapest placement for each arrival time and at most 8 labels. It is exact for one ship alone, but not against other ships.
- **Start times:** the start at each call is always the earliest free one. When the delay rate is below the waiting rate, a later start at the first call could sometimes be cheaper.
- **Single CPU:** one process; the contest machine has 2 vCPUs.
- **The `desc` variant:** any gain it shows over `est` comes from the first-call rule, not from better search. It will be reported separately.

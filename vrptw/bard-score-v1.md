# bard2002 solver v0.1.0: graded against its pre-registered guesses

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; this text CC BY 4.0.

Graded on 2026-11-12, ~13:20 UTC, from the job `froc-bard-real-v1`. The job ran on 2026-11-12 from 12:22 to 12:31 UTC on 2 CPUs with a 1 GB memory cap, and its peak was 0.05 GB. The guesses were written in `BARD-NOTES.md` on 2026-11-11, before the job ran. They are graded exactly as written, failures included. The raw outputs are in `bard-results-v1.md`, `bard-extras-v1.md` and `bard-probe-v1.md`.

Data: the public FrontierOR benchmark (Hugging Face `frontieror/FrontierOR`, revision ef42a2e, CC BY 4.0), task `bard2002`: one tiny and five large instances, 100 customers each in the large ones. Objective: number of vehicles (routes). Reference: the stored Gurobi solution's objective. Contest-style score: reference / ours, capped at 2.

## Results

| instance | Gurobi status (gap) | Gurobi vehicles | our vehicles | capacity lower bound | score |
|---|---|---|---|---|---|
| tiny | OPTIMAL | 2 | 2 | 1 | 1.000 |
| large_1 | TIME_LIMIT (15%) | 20 | **18** | 13 | 1.111 |
| large_2 | TIME_LIMIT (4.8%) | 21 | 21 | 13 | 1.000 |
| large_3 | OPTIMAL | 97 | 97 | 11 | 1.000 |
| large_4 | TIME_LIMIT (86%) | 7 | **4** | 3 | 1.750 |
| large_5 | TIME_LIMIT (86%) | 7 | **4** | 3 | 1.750 |

Mean score is **1.322** on the five large instances and 1.269 on all six. The official `feasibility_check.py` accepted all 6 of our solutions. Each one was written within 60 s (the longest took 55.5 s).

## Guesses

| id | guess | p | result |
|---|---|---|---|
| G1 | test step passes | 0.65 | **held** (9 tests OK, including the official checker on solver output) |
| G2 | official checker accepts all 6, each within 60 s | 0.75 | **held** |
| G3 | our checker and the official one agree on all 12 verdicts | 0.80 | **held** (12 of 12) |
| G4 | probe: one route with demands 5 + 5 is rejected for Q = 10, 12, 14 and accepted for Q = 15, 16; two routes are accepted for every Q | 0.90 | **held** exactly |
| G5 | strictly fewer vehicles than Gurobi on at least 3 of the 5 large instances | 0.50 | **held** (large_1, large_4, large_5) |
| G6 | mean large score at least 1.0 | 0.65 | **held** (1.322) |
| G7 | `travel_time_includes_service_time` is true in all 6 instances, and the matrix is truncated Euclidean | 0.70 | **failed**. The flag is **false** in all 6. The matrix is truncated Euclidean without service time. So service times (10 or 90) are added to travel times, and the comment in `gurobi_code.py` does not describe these instances. Our solver reads the flag, so its solutions are unaffected. |
| G8 | at least one stored Gurobi route could not be driven from the depot and back in time | 0.35 | **failed**. All of Gurobi's routes pass the strict depot-timing check. |

6 of 8 held. Calibration: the two that failed had p = 0.70 and 0.35. The expected count was 5.3, and 6 held.

## What this shows

- **The checker's load rule is real.** In the official checker, a route's load plus its first customer's demand must fit in the vehicle. Two customers of demand 5 cannot share a vehicle of capacity 14. This happens because constraint (5) uses `Q_j = Q - q_j` as its big-M on every ordered pair of customers. The rule binds on large_1: our route there uses 100% of the rule's slack and 80.5% of plain capacity. The stored Gurobi model has the same rows, so the two solvers compete under the same rules. Whether this matches the 2002 paper is a separate question that we have not checked.
- **Where a hand heuristic pays.** On large_4 and large_5 (Q = 1000, so wide capacity), Gurobi stopped at its time limit with 7 vehicles and an 86% gap. Route elimination with an ejection pool reaches 4, one vehicle above the capacity bound of 3. This is a frac = 1.0 task in the hard set, and it shows where scores above 1 come from.
- **Limits.** These are six public instances. The contest's private instances will differ, and its reference may come from a longer Gurobi run than the stored one. Every run used close to the full 60 s, so the solver uses its whole budget even when it cannot improve.

MV2, Munim, Inc., mv2@munimtech.com

# guo2021 solver v0.1.0: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0, text CC BY 4.0.
Written 2026-11-12, before the run `froc-guo2021-v1` was started. Results go in `score-v1.md` next to this file,
whether the guesses hold or not.

## Why this task
`guo2021` (Guo et al. 2021, stochastic distributed operating room scheduling) is **#3 of the 50-task hard set** of the
public FrontierOR benchmark (`metadata/hardset/hardset.json`, Hugging Face `frontieror/FrontierOR`, CC BY 4.0), the
source of the FrontierOR Challenge's practice problems. The benchmark's frozen selection inputs
(`hard_selection_inputs_180.csv`) say its deterministic-equivalent model averages **568,286 binary variables and
575,895 constraints**, and Gurobi did not certify an optimum on any of the 5 large instances (median runtime
3,607.83 s, i.e. its 3,600 s limit). So the stored reference objectives are time-limited Gurobi incumbents, and a
general MIP layer on open-source solvers (our gpshim) is unlikely to get far in the contest's minutes.

## What the solver does (solve.py)
- For a fixed first stage (who goes to which OR on which day, who is postponed), the second stage splits into one
  0/1 knapsack per (scenario, OR): keep the highest-cancellation-cost subset that fits the OR's minutes. The official
  checker recomputes exactly this optimum (its constraint 11 rejects any reported objective below it or more than
  0.5% above it). So the solver searches only over first-stage assignments and prices each OR's expected
  cancellation cost exactly (subset enumeration vectorised over scenarios up to 11 patients; the checker's own
  Pareto DP above that; memoised; at most 16 patients per OR).
- Greedy best insertion (mandatory patients first, longest first), then relocate/swap local search and
  ruin-and-recreate (random patients, one OR, a whole suite-day, or the two most overloaded ORs; a quarter of the
  time a closed suite's opening cost is waived while recreating so new suites can open), with record-to-record
  acceptance. The second CPU runs the same search with another seed in a forked process.
- Anytime: a valid answer is written right after the greedy start and on improvement (at most every 3 s). Search
  stops at min(0.85 T, T - 4 s). The objective written is computed from the output exactly as the official checker
  does, so the stated and recomputed values agree.
- Contest contract: `python solve.py --problem guo2021 --instance ... --output ... --time-limit T`, numpy only.

## The run (job froc-guo2021-v1, 2 CPUs, 2 GB)
1. `test_guo2021.py`: recourse vs brute force, the checker's DP vs enumeration, the full optimum of a 4-patient
   instance found by enumerating every assignment, objective consistency, solution contract, CLI timing.
2. `guo_real.py`: the solver on guo2021's tiny + 5 large public instances at 60 s and at 10 s, through the
   repository's kit (contest-style subprocess, wall time measured), judged by the official `feasibility_check.py`.
   Reference = the stored Gurobi objective. gap = 100 x (ours - Gurobi) / |Gurobi|; negative = better.

## Guesses (probabilities written before any result)
| id | guess | p |
|---|---|---|
| G1 | All unit tests pass. | 0.85 |
| G2 | The official checker accepts all 12 runs (6 instances x 2 time limits); none is over time or missing. | 0.80 |
| G3 | At 60 s, the mean gap over the 5 large instances is at most +1.0%. | 0.60 |
| G4 | At 60 s, at least 3 of the 5 large instances are strictly better than Gurobi's stored objective. | 0.45 |
| G5 | On the tiny instance (60 s) our objective is within 0.01% of Gurobi's or better. | 0.70 |
| G6 | The 10 s mean large gap is within 0.5 percentage points of the 60 s one. | 0.55 |
| G7 | The official checker accepts all 6 stored Gurobi solutions (sanity check of the references). | 0.90 |

## What we will do with the result
- Any official rejection or a failed test is a bug and is fixed before anything else.
- If G2 and G3 hold, guo2021 gets this solver as its contest entry folder (`solve.py` alone) and goes into the
  coverage table as a hand-built solver; otherwise the gap list decides what to improve next (move set, time use,
  or a MIP repair step on a small sub-problem).
- Honest limits: the contest scores private instances, its time class for this task is unknown, and how the contest
  scores a negative objective is not stated anywhere we have read; the gaps here are on the 6 public instances only.

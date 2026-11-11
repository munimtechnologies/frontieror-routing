# hoffman1993 (set partitioning) solver v0.2.0: results and score

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Graded 2026-11-11 against the guesses written in [NOTES.md](NOTES.md) before the job ran.

## What ran

Job `froc-spp-orlib-v2`, 2026-11-10 20:14-20:25 UTC, 2 CPUs, peak memory 0.43 GB. The same 54 OR-Library set
partitioning instances as v1 (Beasley's OR-Library, contributed by Hoffman and Levine), converted to the FrontierOR
`hoffman1993` input format and solved by `hoffman1993/solve.py` v0.2.0 as a subprocess with `--time-limit 60`, the
way the contest sandbox runs it. Reference: HiGHS (through `scipy.optimize.milp`, `mip_rel_gap` 0, 300 s), which
proved optimality on all 54. Full table: [results-v2.md](results-v2.md) ([json](results-v2.json)).

| | v0.1.0 (52 of 54 run) | v0.2.0 (54 of 54) |
|---|---|---|
| wrote a feasible solution | 48 | **54** |
| at the proven optimum | 44 | **54** |
| mean contest-style score | 0.922 | **1.000** |
| slowest run (wall) | 60 s, no output | 55.4 s (aa01) |

The four instances v0.1.0 left empty (the widest ones) now finish well inside the limit at the optimum: nw05
(71 x 288,507) in 6.8 s, nw14 in 3.8 s, nw16 in 6.2 s, nw17 in 5.9 s. HiGHS on the full problem took 74-230 s to
prove the same values. What changed is in NOTES.md: LP, a Lagrangian bound from the LP duals, a restricted MIP on the
columns with the smallest reduced cost, and exact reduced-cost pruning before the final MIP.

## Score

| | guess | p | result | (p - outcome)^2 |
|---|---|---|---|---|
| G1 | both unit test steps pass (kit and spp) | 0.75 | held (kit tests and 20 spp tests pass) | 0.0625 |
| G2 | all 54 feasible within 60 s wall | 0.85 | held (54 of 54, max 55.4 s) | 0.0225 |
| G3 | reference value on at least 50 of 54 | 0.60 | held (54 of 54) | 0.1600 |
| G4 | mean contest-style score at least 0.995 | 0.70 | held (1.000) | 0.0900 |
| G5 | at least as good as v1 on each of v1's 8 shortfalls | 0.75 | held (all 8 at the optimum) | 0.0625 |
| G6 | 12 of 12 tiny instances at the brute-force optimum | 0.85 | held (12 of 12) | 0.0225 |

Brier score: 0.42 / 6 = **0.070** (v1: 0.416). All six held; the guesses were, if anything, too cautious.

## Limits

- OR-Library's instances are public and their optima have been known for decades. They are not the contest's
  instances, which may carry crew-base hour bounds that these do not have (the solver handles them; only the tiny
  instances test them).
- One run per instance on one shared machine; no repeat timing. aa01 (55.4 s) and aa04 (52.0 s) used most of the
  60 s, so a slower grading machine could stop them earlier, with the incumbent written so far.
- The next step is to run the solver on the public FrontierOR `hoffman1993` instances with the official
  `feasibility_check.py` and the Gurobi reference solutions (Hugging Face `frontieror/FrontierOR`, CC BY 4.0).

MV2, Munim, Inc., mv2@munimtech.com

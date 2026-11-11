# barnhart2000 (ODIMCF) solver v0.1.0: results and score

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Graded 2026-11-11 against the seven guesses pre-registered in [NOTES.md](NOTES.md) before the job ran.

## What ran

Job `froc-odimcf-synth-v1`, 2026-11-10 21:48-23:03 UTC, 2 CPUs, peak memory 0.65 GB. 20 synthetic instances
(`odimcf_gen.CASES`: 6 small, 8 medium, 6 large), each solved by `barnhart2000/solve.py` v0.1.0 as a subprocess
with `--time-limit 60`. References: the arc-based MIP (HiGHS, 180 s) for S and M, which proved optimality on all 6 S
and on 1 of 8 M (m3); the same solver given 300 s for L. Full table: [results-v1.md](results-v1.md)
([json](results-v1.json)).

All 20 runs were feasible under our checker, with the stated objective equal to the recomputed one. The solver
matched the 7 proven optima on 5 (missed s4 by 0.42% and m3 by 2.85%), beat the time-limited arc MIP on 5 of the 7
unproven M cases (by 1-58%), and was never worse than its own greedy start.

## Two problems with the references

- **l3-geo100's reference is not a 300 s result.** The host paused the container during that reference run (the
  harness saw a 502 s wall for a 300 s run and killed it), so the reference recorded is the greedy start, 51,931.
  The "14.8% better than the reference" on l3 is an artefact. l3 is left out of O5 below.
- **m8-geo60's arc-MIP reference is weak.** In 180 s HiGHS found only 46,837 (greedy gets 21,243; its bound is
  18,334), so m8 scores at the cap of 2 and inflates the S+M mean. Without m8 the S+M mean is 1.022; on the 7 proven
  optima alone it is 0.995.

## Score

| | guess | p | result | (p - outcome)^2 |
|---|---|---|---|---|
| O1 | the test step passes | 0.75 | held (13 tests) | 0.0625 |
| O2 | 20 of 20 feasible, stated = recomputed objective | 0.85 | held | 0.0225 |
| O3 | at least 12 of 14 S+M at the arc-MIP reference | 0.60 | **did not hold**: 10 of 14 (short on s4, m1, m3, m5) | 0.3600 |
| O4 | mean contest score on S+M at least 0.98 | 0.70 | held: 1.092 (1.022 without m8) | 0.0900 |
| O5 | at least 4 of 6 L within 1% of the 300 s result | 0.60 | held: 4 of the 5 valid L cases (l6 is 3.0% worse; l3 excluded) | 0.1600 |
| O6 | mean gap to the bound on L at most 5% | 0.50 | **did not hold**: 16.5% | 0.2500 |
| O7 | never worse than greedy-only | 0.95 | held (20 of 20) | 0.0025 |

Brier score: 0.9475 / 7 = **0.135**.

O6 failed by a wide margin, but the number mixes two things: how far the solutions are from optimal and how weak the
bound is. The bound on L is the column-generation (LP) bound, and on the M cases where HiGHS also reports a MIP
bound, the LP bound is clearly weaker (m7: 10,981 against 11,749). So this run cannot say how much of the 16.5% is
the solver.

## A rule this run used that the official checker does not

v0.1.0 charged a rejected commodity `artificial_arc_cost` alone when that equalled `revenue` for every commodity
(instances s5, s6, m6 and l4 here). The official `feasibility_check.py` of the FrontierOR benchmark, read after the
job was filed, always charges `artificial_arc_cost x demand`. Solver, checker and references all used v0.1.0's rule,
so these numbers are consistent with each other, but on those four instances they are not the official objective.
v0.2.0 follows the official checker, and its first run is on the six public FrontierOR barnhart2000 instances with
the official checker and the Gurobi reference solutions ([NOTES.md](NOTES.md), guesses P1-P7).

MV2, Munim, Inc., mv2@munimtech.com

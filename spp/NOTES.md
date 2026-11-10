# hoffman1993 (set partitioning, airline crew scheduling): notes

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.

FrontierOR practice problem `hoffman1993` (Scheduling): choose rotations so that every flight leg is covered exactly
once, optionally within crew-base hour bounds, at minimum cost (Hoffman and Padberg, Management Science 39, 1993).
The schema is taken from the public problem page. The index base of legs and rotations is not stated there and the
tiny instance needs a signed-in account, so: leg indices are detected from the data, and rotation indices in the
output are taken to be 0-based (`ROT_BASE` in `solve.py`, one line to change).

## Solver v0.1.0

`hoffman1993/solve.py` uses the shared runtime `frontier_runtime.py` (a copy of `kit/frontier_runtime.py`): a clock
with a safety margin, a best-so-far incumbent written atomically, and a watchdog that ends the process before the
limit. Portfolio: HiGHS branch-and-cut through `scipy.optimize.milp` (mip_rel_gap 0) with 65% of the time; if it has
not proven optimality, OR-Tools CP-SAT (2 workers) for the rest, hinted with HiGHS's solution. Each solution is
checked (exact cover, base bounds) before it is kept.

## Calibration job froc-spp-orlib-v1: guesses written before it runs

54 OR-Library set partitioning instances (sppnw01-43, sppaa01-06, sppkl01-02, sppus02-04; contributed by Hoffman and
Levine), converted to the contest schema, solved through the CLI at 60 s. Reference: HiGHS with mip_rel_gap 0 and a
300 s limit, run separately, with a flag for proven optimality. Plus 12 tiny random instances (4 with base bounds)
against a brute-force optimum, at 10 s.

| | guess | how sure |
|---|---|---|
| H1 | both unit test steps pass (kit and spp) | 0.70 |
| H2 | all 54 instances give a feasible solution within 60 s wall | 0.75 |
| H3 | the solver reaches the reference value on at least 48 of the 54 | 0.70 |
| H4 | the 300 s reference is proven optimal on at least 50 of the 54 | 0.65 |
| H5 | mean contest-style score (reference / ours, capped at 2, 0 if infeasible) is at least 0.99 | 0.70 |
| H6 | 12 of 12 tiny instances reach the brute-force optimum | 0.85 |

These guesses are about a solver anyone could write with an open MILP solver; the point of the job is to check the
shared runtime and harness end to end on a second problem family before the contest's Stage 1 (from 2027-01-04).

## froc-spp-orlib-v1: what happened (scored 2026-11-10)

The job ran 2026-11-10 07:50-08:22 UTC and was stopped by the shared host (exit 143, SIGTERM; another, unrelated job
on the same machine stopped with the same code within seconds) while computing the reference for us03. So 52 of the
54 instances were solved, and the tiny instances and both unit test steps never ran. Raw lines:
[results-v1-partial.jsonl](results-v1-partial.jsonl).

- **48 of 52 feasible; 4 wrote no solution at all within 60 s**: nw05 (71 rows x 288,507 columns), nw14
  (73 x 123,409), nw16 (139 x 148,633) and nw17 (61 x 118,607). In the contest that scores 0. HiGHS on the whole
  problem found no incumbent within its 65% share, and the CP-SAT model of a few hundred thousand variables found none
  in the rest.
- 44 of 52 at the reference. Short of it: nw04 5.38%, us02 0.72%, aa04 0.11%, aa01 0.002%.
- All 52 references were proven optimal by HiGHS within 300 s (up to 230 s, nw05).
- Mean contest-style score over the 52: 0.922.

| | guess | how sure | result | (p - outcome)^2 |
|---|---|---|---|---|
| H1 | unit tests pass | 0.70 | not run (job stopped) | not scored |
| H2 | all 54 feasible | 0.75 | 4 of the first 52 wrote nothing, **did not hold** | 0.5625 |
| H3 | at reference on >= 48 of 54 | 0.70 | 44 of 52, at most 46 of 54, **did not hold** | 0.4900 |
| H4 | reference proven on >= 50 of 54 | 0.65 | 52 of 52, held | 0.1225 |
| H5 | mean score >= 0.99 | 0.70 | at most 0.925 over 54, **did not hold** | 0.4900 |
| H6 | 12 of 12 tiny optimal | 0.85 | not run | not scored |

Brier score over the four that could be scored: 1.665 / 4 = **0.416**. Badly calibrated: we assumed a 60 s HiGHS run
always finds some partition, and on wide instances it does not.

## Solver v0.2.0

The fix is the textbook one for wide set partitioning problems, done so that every step stays exact:

1. LP relaxation with HiGHS. If its solution is integral, it is optimal.
2. Lagrangian bound from the LP duals: L(y) = sum(y) + sum_j min(0, c_j - a_j.y). It is a valid lower bound for any
   y, so a dual sign convention or a solver tolerance can only weaken it, never make it wrong (both y and -y are
   tried).
3. Restricted MIP on the 1,000 (or 5 per row) columns with the smallest reduced cost plus the LP support, growing x4
   while infeasible. This gives a first solution within seconds.
4. Reduced-cost pruning: with integer costs, column j can be in a strictly better solution only if
   L + max(0, rc_j) <= incumbent - 1. Every other column is dropped, and HiGHS solves what is left with the remaining
   time. If that finishes (optimal or infeasible), the incumbent is proven optimal.
5. CP-SAT on the pruned columns if time remains and they number at most 60,000.

If the LP fails, the v0.1.0 portfolio runs. New tests check, by brute force over every feasible partition of 10 tiny
instances, that the bound never exceeds the optimum for LP duals and random y, and that pruning never drops a column
of any strictly better solution. The references computed by v1 are reused ([refs-v1.json](refs-v1.json)); only us03
and us04 get a new 300 s HiGHS reference.

## Calibration job froc-spp-orlib-v2: guesses written before it runs

Written 2026-11-10 before the job was filed. (The commit that publishes this file may land after the job starts; the
text is unchanged either way.) Same 54 instances, same 60 s CLI runs, same 12 tiny instances.

| | guess | how sure |
|---|---|---|
| G1 | both unit test steps pass (kit and spp) | 0.75 |
| G2 | all 54 instances give a feasible solution within 60 s wall | 0.85 |
| G3 | the solver reaches the reference value on at least 50 of the 54 | 0.60 |
| G4 | mean contest-style score is at least 0.995 | 0.70 |
| G5 | on each of v1's 8 shortfalls (nw04, nw05, nw14, nw16, nw17, aa01, aa04, us02) v2 is at least as good as v1 | 0.75 |
| G6 | 12 of 12 tiny instances reach the brute-force optimum | 0.85 |

Limits: OR-Library's instances are public and their optima are known, but they are not the contest's instances,
which may carry crew-base constraints these do not have. One machine, one run per instance, no repeat timing.

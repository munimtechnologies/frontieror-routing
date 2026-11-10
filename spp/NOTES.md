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

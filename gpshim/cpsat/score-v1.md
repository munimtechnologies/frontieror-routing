# gpshim CP-SAT backend, A/B run 1: graded (CP-SAT never ran, because of a shared-library clash)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Graded on 2026-11-12 against the predictions in [PREREG.md](PREREG.md), which were published before the run.
Job `froc-gpshim-cpsat-v1`: python:3.12, 2 CPUs, 2 GB, run 08:27-09:01 UTC on 12 Nov 2026, peak memory 0.4 GB.
Benchmark: Hugging Face `frontieror/FrontierOR` (CC BY 4.0) at revision `ef42a2eac13595453f986d9df0b62e86e75ab596`.
gpshim base 0.2.0 at `0bea743ade89ee77bae0058bceaad18b93cc5e77`; highspy 1.15.1, ortools 9.15.6755, numpy 2.5.4.

## What happened

CP-SAT never solved a single model, so the A/B question is still open.

- **The A/B processes** (each task's `solve.py`) load gpshim, and gpshim loads highspy. When gpshim_cpsat then imported
  OR-Tools in the same process, it failed with
  `libortools.so.9: undefined symbol: _Z19setLocalOptionValueRK15HighsLogOptions...`. This happened on all 54 tasks
  whose models were all-integer, and on cordeau2014's all-integer calls. By design, each of them fell back to HiGHS.
- **The unit tests** showed the mirror image. The test process imported OR-Tools first (to decide whether to skip).
  After that highspy could not load, and gpshim quietly used SciPy instead. Four tests failed because the backend was
  `scipy`, not `highspy`, and the entry-point test (a fresh process, highspy first) never reached CP-SAT. 11 of 15
  passed.
- **Cause:** a known, still-open upstream issue, google/or-tools#5246 ("Incompatibility between highspy and
  or-tools", opened 7 July 2026, milestone v10.0). On Linux both wheels ship a HiGHS shared library under the same
  name, and the package imported second is broken. The FrontierOR Challenge image lists exactly these two versions
  (highspy 1.15.1 and ortools 9.15.6755), so **any entry that loads both in one Python process loses one of them**.

## Predictions, graded as written

| id | prediction | p | result |
|---|---|---|---|
| E1 | All 15 tests pass (>= 13: 0.90) | 0.75 | **missed**: 11 of 15 passed; all 4 failures are the import clash |
| E2 | 30-80 of 180 tasks CP-SAT eligible | 0.70 | **missed**: 0 eligible (55 reached the CP-SAT path, but OR-Tools could not load) |
| E3 | tiny: cpsat2 accepted >= HiGHS - 2 | 0.80 | void: no eligible task |
| E4 | large: cpsat2 wins > losses | 0.50 | void |
| E5 | best-of-both beats best arm by >= 0.03 | 0.60 | void |
| E6 | cpsat8 beats cpsat2 more often | 0.45 | void |
| E7 | no extra checker rejections for cpsat2 | 0.85 | void (no CP-SAT answers) |
| E8 | >= 3 large tasks rescued by cpsat2 | 0.55 | void |

Brier score on the two graded predictions: 0.526. Decision rules applied: "fix first" fired, so 0.3.0 is not
released, and no per-task backend or worker choice is made.

## The fix (0.3.1) and the re-run (pre-registered, queued)

[gpshim_cpsat 0.3.1](v031/) keeps model translation in the main process and runs CP-SAT in one long-lived worker
process ([`gpshim_cpsat_worker.py`](v031/gpshim_cpsat_worker.py)) that imports only numpy and OR-Tools. The worker is
reused across lazy-constraint rounds and objective levels, and any failure falls back to HiGHS. The tests now load
highspy first and assert that OR-Tools is never imported in the test process. Job `froc-gpshim-cpsat-v2` re-runs the
A/B on the 55 tasks that reached the CP-SAT path. It also runs a probe that tries every ordered pair of highspy,
CP-SAT, GLOP, OR-Tools routing and `scipy.optimize.milp` in fresh processes, against 12 predictions published first
([v031/PREREG.md](v031/PREREG.md)).

## A by-product: gpshim 0.2.0 on HiGHS, all 180 tiny instances (20 s each)

Because every model fell back, this run is also a contest-rules census of gpshim 0.2.0 on HiGHS. Each task's
unchanged `gurobi_code.py` ran on its tiny instance, judged by the official `feasibility_check.py`:

- **150 of 180 accepted.** 7 rejected (adulyasak2015, bertsimas2024, cote2018, gschwind2021, he2020, liao2020,
  riley2025), 7 crashed before writing (quadratic or second-order-cone terms gpshim does not linearise: amaldi2013,
  bertsimas2022, byeon2022, fischetti2017, hassannayebi2016; a missing helper module: potthoff2010; an indicator
  without finite bounds: xu2024), 10 wrote no solution, and 6 ran over time.
- **Score:** the raw harness mean is 0.810 over 180 tasks.
- **Two scoring errors in our own harness, found while grading.** The harness took the optimisation sense from
  gpshim's last `optimize()` call. That is wrong for furini2017, which minimises colours (its solution schema says
  "Minimum number of distinct colors") but also runs a maximising bound, so it was scored 2.0 instead of 4/59 = 0.068.
  It is also wrong for damcikurt2016, whose reference code declares `GRB.MAXIMIZE` (expected profit), so it was scored
  1.165 instead of 333.065/388.095 = 0.858. Corrected mean: **0.798**. The v2 harness reads the sense from each
  task's own reference code, flags tasks with mixed declarations for a hand check, and records both senses per row.
- **Eight rows have negative or zero references** (arslan2021, earl2005, frey2017, guo2021 and wangk2020 scored 2.0;
  belhoul2014, engineer2012 and kobayashi2021 scored 0). For these the ratio score is undefined, and our harness gives
  2 or 0, so treat them as "matched or not" rather than as scores. In every one of these cases the objective is equal
  to the reference or within 0.8% of it.
- **Two rejections point at the benchmark rather than at gpshim.** For gschwind2021, the reference code writes
  `objective_value` 36585 while the official checker recomputes it as the number of chosen sets (17), and rejects the
  answer. For he2020, the checker's recomputed cost differs from the reference code's by 0.006. That is the rho key
  mismatch already noted in our checker census. Both go into the planned single report to the FrontierOR maintainers
  only after they are confirmed on the Gurobi reference solutions as well.

Raw rows: `rows.jsonl` and `summary.json` from the job (kept with MV2's compete results). This page is the public
record.

# gpshim_cpsat 0.3.1: graded (job froc-gpshim-cpsat-v2)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0.
Graded on 2026-11-12 against the 12 predictions in [`PREREG.md`](PREREG.md), which were published before the run.
The job ran on 2026-11-12 from 09:40 to 11:08 UTC on 2 CPUs. Raw outputs: `rows.jsonl`, `summary.json` and `results.md`
from `/out/gpshim_ab`, plus `/out/clash/clash.md`.

**Result: 11 of 12 predictions held, 1 missed.** CP-SAT ran this time, in its own worker process. On the large
instances it beat HiGHS on 8 tasks and lost on 3. On three tasks it beat the stored Gurobi answer.

## Grades

| id | prediction | p | observed | held? |
|---|---|---|---|---|
| F1 | All 19 tests pass | 0.65 | 19/19 OK (`unittest_exit=0`) | **held** |
| F2 | highspy→CP-SAT fails at CP-SAT, CP-SAT→highspy fails at highspy | 0.85 | both fail with `undefined symbol` | **held** |
| F3 | highspy→GLOP fails at GLOP | 0.85 | fails | **held** |
| F4 | `scipy.optimize.milp` with any OR-Tools step works in both orders | 0.60 | all 6 orders OK | **held** |
| F5 | highspy→OR-Tools routing fails at routing | 0.80 | fails | **held** |
| F6 | at least 45 of 55 candidates CP-SAT eligible | 0.70 | 54 of 55 (mingozzi1999: worker died; 331,872 variables, 2.4M nonzeros) | **held** |
| F7 | tiny: cpsat2 accepted on at least as many as HiGHS, minus 2 | 0.80 | 51 vs 50 of 54 pairs | **held** |
| F8 | large: cpsat2 beats HiGHS on more tasks than it loses | 0.50 | 8 wins, 3 losses, 24 ties (35 pairs) | **held** |
| F9 | large: best-of-both mean beats the better single arm by at least 0.03 | 0.55 | 0.3712 vs 0.3294 (+0.042) | **held** |
| F10 | cpsat8 beats cpsat2 on more tasks than it loses | 0.40 | 0 wins, 2 losses, 13 ties (15 pairs) | missed |
| F11 | no task where HiGHS is accepted has a cpsat2 answer rejected | 0.75 | none (the 7 rejected rows: cote2018 tiny ×2, gschwind2021 tiny ×2, letelier2022 large HiGHS and cpsat8, caprara1999 large HiGHS) | **held** |
| F12 | at least 3 large tasks where cpsat2 is accepted and HiGHS scores 0 | 0.55 | 6: caprara1999, forrest2006, gualandi2012, hosseinian2020, rahimian2017, sadykov2013 | **held** |

## What it shows

**Import order in the FrontierOR image** (highspy 1.15.1, ortools 9.15.6755, scipy 1.18.1, Python 3.12, Linux).
highspy cannot share a process with **any** OR-Tools component: CP-SAT, GLOP or routing, in either order. The OR-Tools
components work together, and `scipy.optimize.milp` (scipy's own HiGHS build) works with everything in both orders.
Full table: [solver-clash note](../../../notes/solver-clash.md).

**CP-SAT vs HiGHS on all-integer reference models** (54 tasks, 2 CPUs, the official checker judges every answer):

| | pairs | CP-SAT better | HiGHS better | mean HiGHS | mean CP-SAT | best of both |
|---|---|---|---|---|---|---|
| tiny, 20 s | 54 | 6 | 0 | 0.890 | 0.947 | 0.947 |
| large_instance_1, 60 s | 35 | 8 | 3 | 0.215 | 0.329 | 0.371 |

**Better than the stored Gurobi answer** on large_instance_1 (contest score above 1). The sense was checked by hand:
each task's `gurobi_code.py` declares one sense. The `timeout_or_nonoptimal_frac` column comes from the benchmark's
own `hard_selection_inputs_180.csv`.

| task | sense | CP-SAT, 60 s, 2 CPUs | Gurobi reference | score | Gurobi time-outs on the 5 large instances |
|---|---|---|---|---|---|
| hosseinian2020 (max edge-weight clique) | max | 8,745 | 5,718 | 1.529 | 5 of 5 |
| gualandi2012 (graph colouring) | min | 34 colours | 40 colours | 1.176 | 3 of 5 |
| sadykov2013 (bin packing with conflicts) | min | 45 bins | 47 bins | 1.044 | 5 of 5 |

Limits: one instance per task, one run, one seed. The reference is Gurobi's best answer within its own time limit
(median about 3,600 s on these tasks), not an optimum.

**More workers did not help on 2 CPUs.** cpsat8 never beat cpsat2 (F10 missed), so the default stays at 2 workers.

**Memory is the next limit.** Eight large runs were killed with SIGKILL in every arm before their first
`optimize()`, while gpshim was still building the model in Python, inside the job's 2 GB container: delorme2020,
furini2016, guo2021, kobeaga2024, mehrotra1996, morrison2016, sansegundo2016, walteros2020. That is also why the job
is listed as "ran out of memory" even though every step finished and wrote its outputs (peak 1.94 GB). The contest
sandbox has 4 GB. A pre-registered probe now measures where the memory goes ([`../../fixmem/PREREG.md`](../../fixmem/PREREG.md)).

**Rejections, explained:**
- caprara1999, large, HiGHS: the reported objective was 51,263, but the checker recomputes x'Px = 64,151. The
  reference model linearises the products with its own y_ij variables. At a time-limited incumbent, y_ij can sit
  below x_i·x_j, so ObjVal understates the true value. Any time-limited run of this reference code risks the same
  rejection. CP-SAT's answer (100,159) was accepted.
- gschwind2021, tiny, both arms: the script writes objective 36,585, but the checker recomputes it as the number of
  chosen sets (17 or 34). The stored Gurobi solution reports 36,585 too. This was already known and is for the
  maintainer report.
- cote2018, tiny, both arms: the objective equals the reference (8), but the checker exits with code 1 and writes no
  result file. Not yet diagnosed.
- letelier2022, large, HiGHS and cpsat8: "items list empty for an 'active' bin-period pair". The model allows an
  active bin-period with no items, which a time-limited incumbent can contain.

## Decisions (rules fixed in PREREG.md)

- **Fix first:** no failing test, and no CP-SAT answer was rejected where HiGHS was accepted. Nothing blocks.
- **Release:** F1 and F11 held, so gpshim_cpsat 0.3.1 now ships with the gpshim candidate in
  [`gpshim/next/`](../../next/). HiGHS stays the default.
- **Workers:** stays 2 (cpsat8 won 0, lost 2).
- **Probe note:** F2 held, so the note for entrants is published at [`notes/solver-clash.md`](../../../notes/solver-clash.md).
- **Per-task backend** (large pair, higher score, HiGHS on a tie):
  - cpsat: barnhart2000, caprara1999, forrest2006, gualandi2012, hosseinian2020, rahimian2017, rothenbacher2019,
    sadykov2013.
  - highs: boland2019, chebil2015, watermeyer2020, plus all 24 ties.

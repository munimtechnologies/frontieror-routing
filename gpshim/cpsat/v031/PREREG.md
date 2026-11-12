# Pre-registration: gpshim_cpsat 0.3.1 (CP-SAT in a worker process), and a solver import-order probe

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0, code Apache-2.0.
Written and published on 2026-11-12, **before** the job `froc-gpshim-cpsat-v2` has run. Nothing in this folder has
been executed yet: there was no shell where it was written.

## What happened in v1 (graded in `../score-v1.md`)

`froc-gpshim-cpsat-v1` was meant to compare HiGHS and OR-Tools CP-SAT behind gpshim on the FrontierOR benchmark's
own reference models. CP-SAT never ran. gpshim loads highspy, and in the same Python process OR-Tools then failed to
load: `libortools.so.9: undefined symbol: _Z19setLocalOptionValueRK15HighsLogOptions...`. The unit tests showed the
mirror image. Their process loaded OR-Tools first, then highspy failed and gpshim quietly fell back to SciPy (4 of 15
tests failed on the backend name). This is the known upstream conflict google/or-tools#5246, which is still open: both
packages ship a HiGHS shared library under the same name. It hits exactly the versions in the FrontierOR Challenge
image (highspy 1.15.1, ortools 9.15.6755).

## What runs now

- `gpshim_cpsat.py` 0.3.1 keeps all model translation in the main process (numpy only) and sends each all-integer
  model to `gpshim_cpsat_worker.py`. That is one long-lived child process that imports only numpy and OR-Tools,
  reused across lazy-constraint rounds and multi-objective levels. Any worker failure, overrun or missing OR-Tools
  falls back to HiGHS in the main process, and the log records why.
- `test_gpshim_cpsat.py`: 19 tests. The test process imports highspy first and never imports OR-Tools. New tests
  check that both backends run in one process, that a dead worker falls back to HiGHS, that the worker restarts
  after being stopped, and that infeasibility is found by search.
- `clash_probe.py`: every single solver and every ordered pair of {highspy, CP-SAT, GLOP, OR-Tools routing,
  `scipy.optimize.milp`}, each in a fresh process solving a tiny model, records which step fails.
- `gpshim_ab.py`: the same A/B as v1, restricted to the 55 tasks that v1 showed reach the CP-SAT path
  (`candidates.txt`: the 54 that failed with "OR-Tools missing", plus cordeau2014, where some calls are all-integer).
  The other 125 tasks have continuous columns, quadratic terms or crash before optimize(), so CP-SAT cannot apply.
  Stage 1 is tiny at 20 s (cpsat2, plus HiGHS where eligible). Stage 2 is large_instance_1 (at most 1.5 MB, 60 s;
  highs, cpsat2, and cpsat8 for the first 15) within 200 minutes. The official `feasibility_check.py` judges
  everything.

Known before the run, stated honestly: v1's fallback already produced HiGHS tiny results for these 55 tasks (51
accepted; cote2018 and gschwind2021 rejected, bode2012 no solution, walteros2020 overtime; low scores on furini2016 0.044,
segundo2019 0.106, sadykov2013 0.92, armbruster2012 0.935). Predictions below that involve tiny HiGHS are therefore
partly informed.

## Predictions (probabilities written before the run)

| id | prediction | p |
|---|---|---|
| F1 | All 19 tests pass (at least 17 pass: 0.85) | 0.65 |
| F2 | Probe: highspy then CP-SAT fails at CP-SAT, and CP-SAT then highspy fails at highspy | 0.85 |
| F3 | Probe: highspy then GLOP fails at GLOP (the upstream report's case) | 0.85 |
| F4 | Probe: `scipy.optimize.milp` combined with any OR-Tools step works in both orders | 0.60 |
| F5 | Probe: highspy then OR-Tools routing fails at routing | 0.80 |
| F6 | At least 45 of the 55 candidates are CP-SAT eligible (CP-SAT really solved at least one optimize()) | 0.70 |
| F7 | On tiny, cpsat2 is accepted on at least as many eligible tasks as HiGHS, minus 2 | 0.80 |
| F8 | On large pairs, cpsat2 beats HiGHS (by more than 0.001) on more tasks than it loses | 0.50 |
| F9 | On large pairs, the best-of-both mean beats the better single arm's mean by at least 0.03 | 0.55 |
| F10 | cpsat8 beats cpsat2 on more of its tasks than it loses | 0.40 |
| F11 | No task where HiGHS's answer is accepted has a cpsat2 answer rejected by the official checker (tiny or large) | 0.75 |
| F12 | On at least 3 large tasks, cpsat2 is accepted while HiGHS scores 0 | 0.55 |

## Decision rules (fixed now)

- **Fix first:** a failing test, or a CP-SAT answer rejected where HiGHS's is accepted, is a bug to fix before
  anything below is used.
- **Per-task backend:** for each eligible task with a large pair, use the arm with the higher score, and HiGHS on a
  tie. That arm goes into `gpshim_backend.txt` in the task's submission folder.
- **Workers:** if cpsat8 wins at least 3 more tasks than it loses, the default becomes 8; otherwise it stays 2.
- **Release:** if F1 and F11 hold, gpshim_cpsat 0.3.1 becomes part of the standalone gpshim package, with HiGHS
  still the default.
- **Probe note:** the probe's table is published as is. If F2 holds, a short note for FrontierOR entrants goes into
  this repository: in the contest image, highspy and OR-Tools cannot share a process; use separate processes.
- Every prediction is graded as written, including the misses.

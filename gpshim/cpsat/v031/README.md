# gpshim_cpsat 0.3.1: CP-SAT behind gpshim, in its own process

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Not affiliated with or endorsed by Gurobi Optimization or Google.

gpshim lets models written for gurobipy run on open-source solvers. HiGHS is the default backend. This add-on sends
all-integer models to OR-Tools CP-SAT. It scales each row exactly to integers by a power of ten, logs any bound
caps, and recomputes ObjVal from the model's own costs. Anything it cannot take falls back to HiGHS, and the log
says why.

## Why 0.3.1 exists

On Linux, highspy (1.15.x) and OR-Tools (9.14/9.15) each ship a HiGHS shared library under the same name. Whichever
package is imported second in a Python process fails with `undefined symbol: ...setLocalOptionValue...`
(google/or-tools#5246, still open). 0.3.0 imported OR-Tools inside the gpshim process, after highspy, so CP-SAT
never ran ([score](../score-v1.md)). 0.3.1 runs CP-SAT in a separate, long-lived worker process
(`gpshim_cpsat_worker.py`) that imports only numpy and OR-Tools.

**If you enter the FrontierOR Challenge:** its image has both highspy 1.15.1 and ortools 9.15.6755. Do not load both
in one Python process. Put one of them in a subprocess.

## Use

    import gpshim, gpshim_cpsat
    gpshim_cpsat.install(gpshim)
    gpshim_cpsat.set_backend("cpsat")   # or MV2_GPSHIM_BACKEND=cpsat, or a gpshim_backend.txt file next to it

Keep `gpshim_cpsat_worker.py` next to `gpshim_cpsat.py`. Settings: MV2_GPSHIM_CPSAT_WORKERS (default 2),
MV2_GPSHIM_CPSAT_MEM_MB (default 2500), MV2_GPSHIM_CPSAT_CAP (default 1e9, used for infinite integer bounds).

## Files

- `gpshim_cpsat.py`, `gpshim_cpsat_worker.py`: the backend.
- `test_gpshim_cpsat.py`: 19 tests (`python fetch_base.py . && python -m unittest -v test_gpshim_cpsat`).
- `gp_solve.py`: the contest entry point (copied as `solve.py`).
- `clash_probe.py`: tests which solvers can share a process, in every import order.
- `gpshim_ab.py`, `candidates.txt`: the A/B harness and the 55 tasks it runs on.
- `PREREG.md`: 12 predictions for the re-run, published before it ran.

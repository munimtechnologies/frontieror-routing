# gpshim_cpsat 0.3.0: a CP-SAT backend for gpshim (candidate, not yet run)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Not affiliated with or endorsed by Gurobi Optimization or Google.

gpshim is MV2's small gurobipy-compatible modelling layer. It runs scripts written for Gurobi's Python API on the
open-source HiGHS solver (`../next/` holds 0.2.0). This folder adds an optional second backend:
**OR-Tools CP-SAT** (Apache-2.0) for models whose variables are all integer or binary.

```python
import gpshim, gpshim_cpsat
gpshim_cpsat.install(gpshim)       # once
gpshim_cpsat.set_backend("cpsat")  # or MV2_GPSHIM_BACKEND=cpsat, or a file gpshim_backend.txt next to the module
# ... run gurobipy-style code with gpshim as `gurobipy` ...
```

- Rows are scaled exactly to integers with powers of ten up to 10^6, and their sides are rounded inward. That is
  exact for integer rows.
- Infinite integer bounds become ±10^9 and are logged.
- A non-decimal objective is rounded to about nine significant digits for the search, but `ObjVal` is recomputed
  with the model's own costs.
- `Var.Start` values become hints. `TimeLimit`, `MIPGap` and `Seed` are passed on, with 2 workers by default
  (`MV2_GPSHIM_CPSAT_WORKERS`) and a memory cap (`MV2_GPSHIM_CPSAT_MEM_MB`).
- Lazy-constraint callbacks and multiple objectives work as in gpshim 0.2, because they use the same core solve.
- Anything CP-SAT cannot take (continuous columns, quadratic objectives, rows with more than 6 decimals, overflow
  risk, OR-Tools missing) falls back to HiGHS. The reason goes into gpshim's log as `cpsat_skip: ...`.

| file | what |
|---|---|
| `gpshim_cpsat.py` | the backend (install, set_backend, solve_cpsat) |
| `gp_solve.py` | FrontierOR entry point: runs a task's `gurobi_code.py` through gpshim, plus CP-SAT when `gpshim_backend.txt` says `cpsat` |
| `test_gpshim_cpsat.py` | 15 tests (brute-force checks, fallbacks, callbacks, entry point) |
| `gpshim_ab.py` | the pre-registered HiGHS vs CP-SAT comparison on all 180 FrontierOR reference models |
| `fetch_base.py` | downloads gpshim 0.2.0 at its pinned commit next to these files |
| `PREREG.md` | eight predictions and the decision rules, written before the run |

Status: written on 2026-11-12 and queued as compute job `froc-gpshim-cpsat-v1`. Nothing here has run yet.
Results and grading will go in `score-v1.md`.

Prior art (checked 2026-11-12): we found no open-source package that runs gurobipy code unchanged on HiGHS or
CP-SAT. gurobimh is a faster binding that still needs Gurobi. Multi-solver layers such as OR-Tools MathOpt, Pyomo,
PuLP and python-mip need the model rewritten in their own API.

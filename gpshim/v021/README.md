# gpshim 0.2.1 (candidate)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0 (code), CC BY 4.0
(text). Not affiliated with Gurobi; no Gurobi software is used.

gpshim stands in for the `gurobipy` module so the FrontierOR benchmark's own reference models run unchanged on the
open-source HiGHS solver. 0.2.1 fixes one thing found while grading 0.2.0
([`../next/score-v1.md`](../next/score-v1.md)): with a quadratic objective, `ObjVal` is now the objective as written,
evaluated at the solution, instead of the value of gpshim's linearised (secant) model. That over-estimate made the
he2020 checker reject a feasible answer.

This folder holds the patch, not a copy of the 1,900-line module: [`fetch_base.py`](fetch_base.py) downloads 0.2.0 from
`gpshim/next/` at a pinned commit and [`patch_021.py`](patch_021.py) applies three exact replacements. The patched
`gpshim.py` will be published from the run's output once its tests pass.

Files: [`PREREG.md`](PREREG.md) (predictions, written before the run), [`test_gpshim021.py`](test_gpshim021.py),
[`checker_diag.py`](checker_diag.py) (runs an official checker on our answer and on Gurobi's stored one).

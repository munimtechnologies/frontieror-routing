"""gpshim_objfix: report ObjVal as the value of the model's ORIGINAL objective at the solution, as Gurobi does.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

Why: gpshim (0.2.x) solves quadratic objectives through reformulations. A product with a binary variable becomes a
McCormick system and a convex square becomes a piecewise-linear over-estimate. At the optimum of the reformulated
model the two objectives agree (McCormick) or nearly agree (squares), but at a time-limited incumbent they can
differ: the auxiliary product variable z only has to satisfy the inequalities that matter for the optimisation
sense, so z can sit below x*y. gpshim then reported the reformulated value as ObjVal. Scripts that write
model.ObjVal into their solution file are rejected by checkers that recompute the true objective. Observed on
FrontierOR caprara1999 large_instance_1: reported 51263, recomputed 64151, rejected.

What it does: after every optimize() of a model with quadratic objective terms and a solution (single objective
only), ObjVal is recomputed as objcon + sum c_j x_j + sum q_vw x_v x_w from the values gpshim reports. Nothing
else changes: the solution, the bound, the status and the log line written by gpshim stay as they were.

    import gpshim, gpshim_objfix
    gpshim_objfix.install(gpshim)

If MV2_OBJFIX_LOG names a file, each recomputation appends one JSON line {"before", "after", "changed"}.
"""
import json
import os

__version__ = "0.1.0"
RECORDS = []


def _log(rec):
    RECORDS.append(rec)
    p = os.environ.get("MV2_OBJFIX_LOG")
    if p:
        try:
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        except OSError:
            pass


def true_objective(m):
    """Value of the model's original single objective at the reported solution, or None if it cannot be computed.

    Returns None for a model without quadratic objective terms (nothing to correct), for multi-objective models
    (gpshim already evaluates the first objective from the solution there), and when a needed value is missing.
    """
    if getattr(m, "_gpobjn", None) or not getattr(m, "_gpq", None):
        return None
    total = float(m._gpo)
    for v in m._gpv:
        if v._removed or not v._obj:
            continue
        if v._x is None:
            return None
        total += v._obj * v._x
    for (v, w), a in m._gpq.items():
        if not a or v._removed or w._removed:
            continue
        if v._x is None or w._x is None:
            return None
        total += a * v._x * w._x
    return total


def install(gp):
    """Wrap gp.Model.optimize so that ObjVal is the original objective's value. Safe to call twice."""
    if getattr(gp.Model.optimize, "_mv2_objfix", False):
        return
    orig = gp.Model.optimize

    def optimize(self, *args, **kwargs):
        out = orig(self, *args, **kwargs)
        try:
            res = self._gpr
            if res.get("SolCount") and res.get("ObjVal") is not None:
                t = true_objective(self)
                if t is not None:
                    before = float(res["ObjVal"])
                    res["ObjVal"] = t
                    _log({"before": before, "after": t,
                          "changed": abs(t - before) > 1e-9 * max(1.0, abs(t))})
        except Exception as e:  # noqa: BLE001 - never break the caller's script
            _log({"error": repr(e)[:300]})
        return out

    optimize._mv2_objfix = True
    gp.Model.optimize = optimize
    gp.OBJFIX_VERSION = __version__

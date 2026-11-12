"""Turn gpshim 0.2.0 into 0.2.1 by three exact text replacements, each of which must match exactly once.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python patch_021.py gpshim.py

The one change in behaviour: when the model's objective has quadratic terms, ObjVal is now the objective as written,
evaluated at the solution (linear part + constant + every quadratic term), instead of the value of the solver's
linearised model. Why: gpshim 0.2.0 replaces a convex square by a 32-piece secant, which over-estimates it, and
reported the over-estimate. FrontierOR's he2020 checker recomputes the objective and rejected a tiny-instance answer
whose reported objective was 0.0059 too high (tolerance 0.0055). Gurobi reports the objective as written, so 0.2.1
does the same. The solver's own value stays in the run log as reform.obj_solver. Nothing else changes: the same
solution is returned, the bound (ObjBound) is still the solver's, and models with multiple objectives are untouched.
"""
import sys

OLD_VERSION = '__version__ = "0.2.0"'
NEW_VERSION = ('__version__ = "0.2.1"\n'
               '# 0.2.1 (2026-11-12): with a quadratic objective, ObjVal is the objective as written evaluated at the '
               'solution\n# (secant squares no longer leak their over-estimate into ObjVal).')

OLD_SET = ('                object.__setattr__(v, "_x", xv)\n'
           '            if res.get("row_value") is not None:\n')
NEW_SET = ('                object.__setattr__(v, "_x", xv)\n'
           '            if self._gpq and not self._gpobjn:\n'
           '                tv = self._gp_true_obj(V)\n'
           '                if tv is not None:\n'
           '                    info["obj_solver"] = objval\n'
           '                    objval = tv\n'
           '            if res.get("row_value") is not None:\n')

OLD_ROWS = '    def _gp_rows(self, rowsdef, rlo, rhi, ri, ci, va, first):\n'
NEW_ROWS = ('    def _gp_true_obj(self, V):\n'
            '        """The objective as written (constant + linear + quadratic terms) at the current solution."""\n'
            '        try:\n'
            '            val = float(self._gpo)\n'
            '            for v in V:\n'
            '                if v._obj:\n'
            '                    val += float(v._obj) * float(v._x)\n'
            '            for (v, w), a in self._gpq.items():\n'
            '                if a == 0.0 or v._removed or w._removed:\n'
            '                    continue\n'
            '                val += float(a) * float(v._x) * float(w._x)\n'
            '        except (TypeError, ValueError, AttributeError):\n'
            '            return None\n'
            '        if val != val or val in (float("inf"), float("-inf")):\n'
            '            return None\n'
            '        return val\n'
            '\n' + OLD_ROWS)

EDITS = [("version", OLD_VERSION, NEW_VERSION), ("objval", OLD_SET, NEW_SET), ("true_obj", OLD_ROWS, NEW_ROWS)]


def patch(text):
    for name, old, new in EDITS:
        n = text.count(old)
        if n != 1:
            raise SystemExit("patch %s: expected exactly 1 match, found %d" % (name, n))
        text = text.replace(old, new)
    return text


def main(argv):
    path = argv[1] if len(argv) > 1 else "gpshim.py"
    with open(path, encoding="utf-8") as f:
        text = f.read()
    out = patch(text)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print("patched", path, "to 0.2.1:", ", ".join(e[0] for e in EDITS), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

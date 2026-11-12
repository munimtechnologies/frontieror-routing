#!/usr/bin/env python3
"""FrontierOR Main-track entry point that runs a task's own reference model through gpshim on open-source solvers.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

    python solve.py --problem <slug> --instance in.json --output out.json --time-limit 60

The folder holds this file (as solve.py), gpshim.py, optionally gpshim_cpsat.py + gpshim_cpsat_worker.py and
gpshim_backend.txt ("highs" or "cpsat"), and the task's gurobi_code.py from the public FrontierOR benchmark (Hugging
Face frontieror/FrontierOR, CC BY 4.0; written for gurobipy). No Gurobi software is used: gpshim stands in for the
gurobipy module and solves the same model with HiGHS, or with OR-Tools CP-SAT (in a separate worker process) for
all-integer models when the backend is "cpsat". The model's own CLI is called as
--instance_path/--solution_path/--time_limit, and every optimize() is capped by a deadline a few seconds before the
contest limit, so the script has time to write its solution file.
"""
import argparse
import os
import runpy
import sys
import time

T_START = time.time()
HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default="")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=60.0)
    a = ap.parse_args(argv)
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import gpshim
    if os.path.exists(os.path.join(HERE, "gpshim_cpsat.py")):
        import gpshim_cpsat
        gpshim_cpsat.install(gpshim)
    T = float(a.time_limit)
    margin = max(2.0, 0.1 * T)  # model building happens before optimize(); writing the file after it
    gpshim.set_deadline(T_START + T - margin)
    sys.modules["gurobipy"] = gpshim
    code = os.path.join(HERE, "gurobi_code.py")
    sys.argv = [code, "--instance_path", os.path.abspath(a.instance), "--solution_path", os.path.abspath(a.output),
                "--time_limit", str(max(1, int(T - margin)))]
    runpy.run_path(code, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())

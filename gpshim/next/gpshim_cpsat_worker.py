"""gpshim_cpsat_worker: the CP-SAT side of gpshim_cpsat, run in its own process.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Not affiliated with or endorsed by Gurobi Optimization or Google. Uses OR-Tools (Apache-2.0).

Why a separate process: on Linux, highspy (1.15.x) and OR-Tools (9.14/9.15) each ship a HiGHS shared library under
the same name, and whichever package is imported second in a Python process fails with an "undefined symbol" error
(google/or-tools issue 5246, open as of 2026-11-12). gpshim keeps HiGHS in the main process; this worker imports only
numpy and OR-Tools, so both solvers stay usable in one run.

    python gpshim_cpsat_worker.py --serve        # line protocol on stdin/stdout (used by gpshim_cpsat)
    python gpshim_cpsat_worker.py IN.npz OUT     # one model, then exit

Input: an .npz written by gpshim_cpsat.solve_cpsat (integer domains, CSR rows with integer coefficients, integer
objective, hints, parameters). Output: OUT.json (status, bound, branches, timings) and OUT.npy (the solution, int64).
"""
import json
import os
import sys
import time

PREFIX = "MV2CPSAT "
_CP = [None]


def _cp_model():
    if _CP[0] is None:
        from ortools.sat.python import cp_model  # noqa: WPS433 - imported lazily, once
        _CP[0] = cp_model
    return _CP[0]


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def solve(inp, outp):
    """Solve one model file; always writes outp + '.json' (and outp + '.npy' when there is a solution)."""
    t0 = time.time()
    import numpy as np
    try:
        cp_model = _cp_model()
    except Exception as e:  # noqa: BLE001 - ImportError or a broken shared library
        _write_json(outp + ".json", {"status": "IMPORT_ERROR", "error": repr(e)[:400]})
        return
    import_s = time.time() - t0
    with np.load(inp, allow_pickle=False) as d:
        lo = d["lo"].tolist()
        hi = d["hi"].tolist()
        starts = d["starts"].tolist()
        cols = d["cols"].tolist()
        coefs = d["coefs"].tolist()
        rlo = d["rlo"].tolist()
        rhi = d["rhi"].tolist()
        rlo_inf = d["rlo_inf"].tolist()
        rhi_inf = d["rhi_inf"].tolist()
        obj_idx = d["obj_idx"].tolist()
        obj_coef = d["obj_coef"].tolist()
        hint_idx = d["hint_idx"].tolist()
        hint_val = d["hint_val"].tolist()
        prm = d["params"].tolist()
    deadline, workers, mem_mb, gap, seed, maximize = prm[:6]
    M = cp_model.CpModel()
    xs = [M.new_int_var(int(a), int(b), "") for a, b in zip(lo, hi)]
    for k in range(len(rlo)):
        a, b = starts[k], starts[k + 1]
        li = cp_model.INT_MIN if rlo_inf[k] else int(rlo[k])
        ui = cp_model.INT_MAX if rhi_inf[k] else int(rhi[k])
        M.add_linear_constraint(cp_model.LinearExpr.weighted_sum([xs[j] for j in cols[a:b]], coefs[a:b]), li, ui)
    if obj_idx:
        expr = cp_model.LinearExpr.weighted_sum([xs[j] for j in obj_idx], obj_coef)
        if maximize > 0.5:
            M.maximize(expr)
        else:
            M.minimize(expr)
    for j, v in zip(hint_idx, hint_val):
        M.add_hint(xs[j], int(v))
    validate = getattr(M, "validate", None) or getattr(M, "Validate", None)
    if validate is not None:
        msg = validate()
        if msg:
            _write_json(outp + ".json", {"status": "REFUSED", "error": str(msg)[:300]})
            return
    build_s = time.time() - t0 - import_s
    S = cp_model.CpSolver()
    p = S.parameters
    p.max_time_in_seconds = max(0.05, min(1e9, float(deadline) - time.time()))
    p.num_workers = max(1, int(workers))
    p.max_memory_in_mb = max(256, int(mem_mb))
    if gap == gap and gap >= 0:  # not NaN
        p.relative_gap_limit = float(gap)
    if seed >= 0:
        p.random_seed = int(seed) % (2 ** 31)
    st = S.solve(M)
    name = S.status_name(st)
    res = {"status": name, "branches": int(getattr(S, "num_branches", 0) or 0), "import_s": round(import_s, 3),
           "build_s": round(build_s, 3), "solve_s": round(time.time() - t0 - import_s - build_s, 3),
           "has_objective": bool(obj_idx)}
    if name in ("OPTIMAL", "FEASIBLE"):
        try:
            sol = list(S.response_proto.solution)
        except Exception:  # noqa: BLE001
            sol = []
        if len(sol) != len(xs):
            sol = [S.value(x) for x in xs]
        np.save(outp + ".npy", np.asarray(sol, dtype=np.int64))
        res["bound"] = float(S.best_objective_bound) if obj_idx else None
    _write_json(outp + ".json", res)


def serve():
    proto = sys.stdout
    sys.stdout = sys.stderr  # nothing but protocol lines may reach the parent's pipe
    proto.write(PREFIX + json.dumps({"ready": True, "pid": os.getpid()}) + "\n")
    proto.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        if req.get("quit"):
            break
        try:
            solve(req["in"], req["out"])
            reply = {"ok": True}
        except Exception as e:  # noqa: BLE001 - report, keep serving
            reply = {"ok": False, "error": repr(e)[:400]}
        proto.write(PREFIX + json.dumps(reply) + "\n")
        proto.flush()
    return 0


def main(argv):
    if len(argv) > 1 and argv[1] == "--serve":
        return serve()
    if len(argv) != 3:
        sys.stderr.write(__doc__)
        return 2
    solve(argv[1], argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

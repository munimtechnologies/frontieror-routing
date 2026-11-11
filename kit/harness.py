"""harness: calibrate any FrontierOR Main-track solver the way the contest runs it.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

For each case it runs `python solve.py --problem <slug> --instance <json> --output <json> --time-limit T` as a
subprocess from the solver's own folder, measures the wall time, checks the output with an independent checker
supplied by the caller, rejects a solution whose stated objective_value differs from the recomputed one (as the
contest does), and computes a contest-style score against a reference: min(2, ref/obj) when minimising,
min(2, obj/ref) when maximising, 0 when infeasible, rejected, missing or over time.

A heartbeat thread ticks every 0.25 s. If the gap between two ticks during a run exceeds `pause_gap` seconds, the
host froze the container (this happened on the shared machine these calibrations run on), and the case is re-run, at
most `max_attempts` times; every attempt is recorded.

Standard library only.
"""
import json
import os
import subprocess
import sys
import threading
import time


class Heartbeat:
    def __init__(self, tick=0.25):
        self.tick = tick
        self._last = time.monotonic()
        self._max_gap = 0.0
        self._lock = threading.Lock()
        self._stop = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop:
            time.sleep(self.tick)
            now = time.monotonic()
            with self._lock:
                self._max_gap = max(self._max_gap, now - self._last)
                self._last = now

    def reset(self):
        with self._lock:
            self._max_gap = 0.0
            self._last = time.monotonic()

    def max_gap(self):
        with self._lock:
            return max(self._max_gap, time.monotonic() - self._last)

    def stop(self):
        self._stop = True


def contest_score(objective, reference, sense):
    if objective is None or reference is None:
        return 0.0
    if sense == "min":
        if objective <= 0:
            return 2.0 if reference >= objective else 0.0
        return min(2.0, reference / objective)
    if reference <= 0:
        return 2.0 if objective >= reference else 0.0
    return min(2.0, objective / reference)


def run_once(solve_py, problem, instance_path, out_path, time_limit, grace=5.0):
    if os.path.exists(out_path):
        os.remove(out_path)
    cmd = [sys.executable, os.path.basename(solve_py), "--problem", problem, "--instance",
           os.path.abspath(instance_path), "--output", os.path.abspath(out_path), "--time-limit", str(time_limit)]
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(solve_py)), capture_output=True, text=True,
                           timeout=time_limit + grace)
        code, err = p.returncode, p.stderr[-2000:]
    except subprocess.TimeoutExpired as e:
        s = e.stderr
        if isinstance(s, bytes):
            s = s.decode("utf-8", "replace")
        code, err = "killed", (s or "")[-2000:]
    wall = time.monotonic() - t0
    sol = None
    if os.path.exists(out_path):
        try:
            with open(out_path, encoding="utf-8") as f:
                sol = json.load(f)
        except Exception as e:  # noqa: BLE001 - an unreadable file is a failed run
            err = (err or "") + "\nunreadable output: %r" % (e,)
    return {"exit": code, "wall_s": round(wall, 3), "solution": sol, "stderr_tail": err}


def evaluate_case(case, solve_py, problem, time_limit, checker, sense, work_dir, hb=None, pause_gap=5.0,
                  max_attempts=3, rel_tol=1e-6):
    """case: {"name", "instance_path", "reference" (or None), "reference_proven" (optional)}."""
    with open(case["instance_path"], encoding="utf-8") as f:
        instance = json.load(f)
    out_path = os.path.join(work_dir, case["name"] + ".solution.json")
    attempts = []
    for _ in range(max_attempts):
        if hb:
            hb.reset()
        r = run_once(solve_py, problem, case["instance_path"], out_path, time_limit)
        gap = hb.max_gap() if hb else 0.0
        r["max_tick_gap_s"] = round(gap, 3)
        r["paused"] = gap > pause_gap
        attempts.append({k: r[k] for k in ("exit", "wall_s", "max_tick_gap_s", "paused")})
        if not r["paused"]:
            break
    row = {"name": case["name"], "attempts": attempts, "wall_s": r["wall_s"], "exit": r["exit"],
           "paused": r["paused"], "reference": case.get("reference"),
           "reference_proven": case.get("reference_proven")}
    sol = r["solution"]
    if r["exit"] == "killed" or r["wall_s"] > time_limit:
        row.update(status="overtime", objective=None)
    elif sol is None:
        row.update(status="no_output", objective=None, stderr_tail=r["stderr_tail"])
    else:
        chk = checker(instance, sol)
        stated = sol.get("objective_value")
        row["stated"] = stated
        row["objective"] = chk.get("objective")
        if not chk.get("feasible"):
            row.update(status="infeasible", reason=chk.get("reason", ""))
        elif not isinstance(stated, (int, float)) or abs(stated - chk["objective"]) > rel_tol * max(
                1.0, abs(chk["objective"])):
            row.update(status="rejected_objective_mismatch")
        else:
            row["status"] = "ok"
    obj = row.get("objective") if row["status"] == "ok" else None
    row["score"] = round(contest_score(obj, case.get("reference"), sense), 6) if row["status"] == "ok" else 0.0
    ref = case.get("reference")
    if obj is not None and ref not in (None, 0):
        row["gap_pct"] = round(100.0 * ((obj - ref) if sense == "min" else (ref - obj)) / abs(ref), 4)
    return row


def summarise(rows, time_limit):
    ok = [r for r in rows if r["status"] == "ok"]
    with_ref = [r for r in ok if r.get("reference") is not None]
    return {
        "cases": len(rows),
        "ok": len(ok),
        "by_status": {s: sum(1 for r in rows if r["status"] == s) for s in sorted({r["status"] for r in rows})},
        "at_reference": sum(1 for r in with_ref if abs(r.get("gap_pct", 1.0)) < 1e-6),
        "better_than_reference": sum(1 for r in with_ref if r.get("gap_pct", 0.0) < -1e-6),
        "mean_score": round(sum(r["score"] for r in rows) / len(rows), 6) if rows else None,
        "mean_gap_pct": round(sum(r["gap_pct"] for r in with_ref) / len(with_ref), 4) if with_ref else None,
        "max_wall_s": max((r["wall_s"] for r in rows), default=None),
        "time_limit": time_limit,
        "paused_attempts": sum(1 for r in rows for a in r["attempts"] if a["paused"]),
        "still_paused": [r["name"] for r in rows if r["paused"]],
    }


def write_report(out_dir, title, intro, rows, tally, extra_cols=()):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"tally": tally, "rows": rows}, f, indent=1)
    cols = ["name", "status", "objective", "reference", "reference_proven", "gap_pct", "score", "wall_s"] + \
        list(extra_cols)
    lines = ["# " + title, "", intro, "", "```", json.dumps(tally, indent=1), "```", "",
             "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    with open(os.path.join(out_dir, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

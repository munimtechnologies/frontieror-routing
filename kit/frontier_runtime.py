"""frontier_runtime: the part every FrontierOR Main-track solve.py needs, written once.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

The contest calls `python solve.py --problem <slug> --instance in.json --output out.json --time-limit T` in a sandbox
with no network, 2 vCPUs and 4 GB, and a solver still running at T scores 0 even if it already wrote a file. Each
problem folder sees only itself, so this file is copied into every folder next to solve.py.

What it gives a solver:
- `Clock`: the time left, with a safety margin taken off the limit.
- `Incumbent`: keeps the best solution offered so far (min or max) and writes it atomically (temp file + rename), so
  the output file is always one complete JSON object.
- a watchdog thread that writes the incumbent and ends the process with exit code 0 at the hard deadline, even if
  the main thread is stuck inside a C extension.
- `main(solve_fn, sense)`: parses the contest arguments, loads the instance, runs `solve_fn(instance, clock, inc, args)`,
  and always writes the best solution found, including after an exception.

Standard library only.
"""
import argparse
import json
import os
import sys
import threading
import time

_T0 = time.monotonic()


def default_margin(limit):
    """Seconds kept free before the limit: interpreter exit, file write and the sandbox's own clock."""
    return min(20.0, max(1.5, 0.08 * float(limit)))


class Clock:
    def __init__(self, limit, margin=None, start=None):
        self.limit = float(limit)
        self.margin = default_margin(limit) if margin is None else float(margin)
        self.start = _T0 if start is None else start

    def elapsed(self):
        return time.monotonic() - self.start

    def deadline(self):
        """Seconds after start by which the solver must have finished its work."""
        return max(0.0, self.limit - self.margin)

    def remaining(self):
        return max(0.0, self.deadline() - self.elapsed())

    def expired(self):
        return self.remaining() <= 0.0

    def share(self, fraction):
        """A slice of the remaining time, for one phase of a portfolio."""
        return max(0.0, self.remaining() * float(fraction))


class Incumbent:
    """Best solution so far. `sense` is "min" or "max"."""

    def __init__(self, path, sense="min"):
        if sense not in ("min", "max"):
            raise ValueError("sense must be 'min' or 'max'")
        self.path = path
        self.sense = sense
        self.value = None
        self.solution = None
        self.history = []
        self._lock = threading.Lock()
        self._version = 0
        self._written = 0

    def better(self, value):
        if value is None:
            return False
        if self.value is None:
            return True
        return value < self.value - 1e-9 if self.sense == "min" else value > self.value + 1e-9

    def offer(self, value, solution, source="", write=True):
        """Keep `solution` if it beats the incumbent. `solution` must already hold objective_value."""
        with self._lock:
            if not self.better(value):
                return False
            self.value = float(value)
            self.solution = solution
            self._version += 1
            self.history.append((round(time.monotonic() - _T0, 3), float(value), source))
            if write:
                self._write_locked()
            return True

    def flush(self):
        with self._lock:
            self._write_locked()

    def _write_locked(self):
        if self.solution is None or self._written == self._version:
            return
        d = os.path.dirname(os.path.abspath(self.path)) or "."
        tmp = os.path.join(d, ".%s.tmp" % os.path.basename(self.path))
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.solution, f, separators=(",", ":"))
        os.replace(tmp, self.path)
        self._written = self._version


def start_watchdog(clock, inc, hard_margin=None):
    """At limit - hard_margin, write the incumbent and end the process (exit code 0)."""
    hard = max(0.5, clock.margin / 2.0) if hard_margin is None else float(hard_margin)

    def guard():
        while True:
            left = clock.limit - hard - clock.elapsed()
            if left <= 0:
                break
            time.sleep(min(0.05, left))
        try:
            inc.flush()
        finally:
            sys.stdout.flush()
            os._exit(0)

    t = threading.Thread(target=guard, name="frontier-watchdog", daemon=True)
    t.start()
    return t


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", default=os.environ.get("SANDBOX_PROBLEM", ""))
    ap.add_argument("--instance", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time-limit", type=float, default=float(os.environ.get("SANDBOX_TIMEOUT_S", "60")))
    ap.add_argument("--seed", type=int, default=0)
    return ap.parse_args(argv)


def main(solve_fn, sense="min", argv=None, margin=None):
    """Entry point for solve.py: `if __name__ == "__main__": frontier_runtime.main(solve, "min")`."""
    a = parse_args(argv)
    clock = Clock(a.time_limit, margin)
    inc = Incumbent(a.output, sense)
    start_watchdog(clock, inc)
    with open(a.instance, encoding="utf-8") as f:
        instance = json.load(f)
    code = 0
    try:
        solve_fn(instance, clock, inc, a)
    except Exception as e:  # noqa: BLE001 - keep whatever was found
        sys.stderr.write("solver error: %r\n" % (e,))
        code = 0 if inc.solution is not None else 1
    inc.flush()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)

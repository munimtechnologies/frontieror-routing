# FrontierOR Challenge note: highspy and OR-Tools cannot share a Python process

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Text CC BY 4.0.
Measured on 2026-11-12. Not affiliated with the FrontierOR organisers, the HiGHS project or Google.

**If your entry uses both highspy and OR-Tools, run them in separate processes.** In the challenge's listed
versions, whichever library is loaded second fails to import.

Each row below is a fresh Python process that solves a tiny model with each step, in the order shown. The setup is
the challenge's listed versions: highspy 1.15.1, ortools 9.15.6755, scipy 1.18.1, numpy 2.5.4, Python 3.12.15,
Linux (`python:3.12` image).

| first | second | result |
|---|---|---|
| highspy | CP-SAT | fails at CP-SAT: `libortools.so.9: undefined symbol: _Z19setLocalOptionValueRK15Hig...` |
| highspy | GLOP | fails at GLOP (same symbol) |
| highspy | OR-Tools routing | fails at routing (same symbol) |
| CP-SAT, GLOP or routing | highspy | fails at highspy: `_core...so: undefined symbol: _ZN5Highs13releaseMemoryEv` |
| highspy | `scipy.optimize.milp` | works |
| `scipy.optimize.milp` | highspy | works |
| any OR-Tools step | `scipy.optimize.milp` (either order) | works |
| any OR-Tools step | any other OR-Tools step | works |

Every single library works on its own. The cause is the known upstream issue
[google/or-tools#5246](https://github.com/google/or-tools/issues/5246) (open): both wheels ship a HiGHS shared library
under the same name. The failure can be silent. A modelling layer that catches the ImportError and falls back to
another solver will just run slower, with no error shown.

What works:
- Keep one of the two in a child process. We run CP-SAT in a long-lived worker process that imports only numpy and
  OR-Tools. The main process keeps highspy.
- Or pair OR-Tools with `scipy.optimize.milp` (also HiGHS, as a static build inside scipy) instead of highspy.

Sources: probe script and raw table at
[`gpshim/cpsat/v031/clash_probe.py`](../gpshim/cpsat/v031/clash_probe.py); the graded run is
[`gpshim/cpsat/v031/score-v1.md`](../gpshim/cpsat/v031/score-v1.md).

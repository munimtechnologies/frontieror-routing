# Orienteering solver v2 (fischetti1998): scored. v1 stays the solver

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Text CC BY 4.0.

Job `froc-op-oplib-v2`, 2026-11-09 23:22 to 2026-11-10 00:38 UTC. Same 39 OPLib instances (commit 823ac3e) and
60 s limit as v1, plus the same 12 tiny instances with a proven optimum. Full table: [results-v2.md](results-v2.md).
The unit tests passed (17 tests).

v2 added Or-opt moves, a "squeeze" move (insert a city over the budget, re-optimise, keep it if it fits), a swap
move (replace a city by one with a larger prize) and mixed perturbations, and wrote its best solution so far to
disk. Each iteration became much more expensive, so large instances got fewer restarts.

## Guesses written before the run (private run notes, 2026-11-09)

| | guess | how sure | result |
|---|---|---|---|
| P1 | 39/39 feasible, none over time | 0.90 | did not hold as worded: 37/39. Both failures are host pauses (below) |
| P2 | tiny instances optimal on at least 11 of 12 | 0.70 | did not hold (10 of 12, the same two seeds as v1) |
| P3 | mean prize ratio against EA4OP at least 0.995 | 0.50 | did not hold (0.983, on 37) |
| P4 | v2 better than v1 on at least 10 rows and worse on at most 5 | 0.55 | did not hold (better 9, worse 13) |
| P5 | lin318-gen2 ratio at least 0.90 | 0.50 | did not hold (0.849) |

Brier score: (0.81 + 0.49 + 0.25 + 0.3025 + 0.25) / 5 = 0.420. None of the five held.

## The two "timeouts" were host pauses, not the solver

The machine that runs these jobs froze the container twice during this job (runner log): 23:32:46 to 23:48:51 UTC
(965 s) and 00:07:25 to 00:30:54 UTC (1,409 s). The two runs reported over time took 966.14 s (kroA150-gen1-50) and
1,440.96 s (pr76-gen3-50) of wall time, each its pause plus less than the 60 s limit. Every other run took 51.4 to
52.1 s. The same night's VRPDDP job showed the same pattern: 4 pauses, 4 timeouts, one for one. Harnesses written
from now on detect a frozen container with a heartbeat thread and re-run the instance (first in [../darp/](../darp/)).

## Verdict

v2 is worse than v1: mean v2/v1 prize 0.990 over 37 instances, better on 9 and worse on 13. The biggest losses were
lin318-gen3 (0.895), kroA150-gen2 (0.938) and a280-gen3 (0.928). Its few wins (berlin52-gen1, tsp225, a280-gen2) were
small. **v1 stays the published solver** (`fischetti1998/solve.py`). The v2 code is kept in [v2/solve.py](v2/solve.py)
for the record.

What to try instead: keep v1's cheap iterations and add only the swap move, or run the expensive moves only on the
best solution found, not in every restart.

## A finding on the side: two stored EA4OP routes disagree with their instance files

The harness re-scores each stored EA4OP route with the instance's own scores. On 37 of 39 instances the stated
`ROUTE_SCORE` is the re-score plus the depot's prize, exactly. On tsp225-gen3-50 (stated 7,488, re-scored 7,584)
and a280-gen3-50 (stated 8,684, re-scored 7,720) it is not. On a280-gen3-50 our v1 and v2 tours score 9,681 and
8,987 under the file's own scores. That is why the a280-gen3 ratio above 1 in our tables says nothing about the
solver. A census of every stored route in OPLib, with its predictions written before it runs, is in
[../oplib-audit/](../oplib-audit/).

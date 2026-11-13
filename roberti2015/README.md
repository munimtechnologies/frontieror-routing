# roberti2015: fixed charge transportation problem (FCTP)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0, text CC BY 4.0.

This is MV2's open solver for FrontierOR benchmark task `roberti2015`. Each source ships its whole supply and each
sink receives exactly its demand. A route costs a per-unit price times what it carries, plus a fixed charge as soon as
it carries anything. Gurobi's reference hit its one-hour limit on all 5 large public instances (about 4,900 routes
each on average), so a good heuristic has room to match or beat it.

| file | what it is |
|---|---|
| [`solve.py`](solve.py) | the solver. It is called the contest's way: `python solve.py --problem roberti2015 --instance in.json --output out.json --time-limit 60`. Standard library only. |
| [`test_roberti2015.py`](test_roberti2015.py) | tests: exact pivot costs, spanning-tree invariants, brute-force optima on small instances, agreement with the official checker, the command line and its time limits |
| [`roberti_real.py`](roberti_real.py) | runs the solver on the public instances (Hugging Face frontieror/FrontierOR, CC BY 4.0), with the official checker |
| [`PREREG.md`](PREREG.md) | method, 12 predictions and decision rules, published before the first run |
| [`wait_prereg.py`](wait_prereg.py) | the job's first step: waits until PREREG.md is public and records whether it was |

## Method in one paragraph

Some optimal FCTP answer is a basic solution, a spanning tree of m + n - 1 routes, because the cost is concave in the
flows. The solver builds a tree with a least-cost greedy on c + f / q. It then makes network-simplex pivots whose
exact cost change, including the fixed charges of routes that open or close, is worked out before each move. An
iterated local search adds random pivots or noisy fixed costs, and a second forked worker runs with another seed.
For the published state of the art, see Buson, Roberti and Toth, "A reduced-cost iterated local search heuristic for
the fixed-charge transportation problem", Operations Research 62(5):1095-1106 (2014). The exact method this
task is named after is Roberti, Bartolini and Mingozzi, Management Science 61(6):1275-1291 (2015).

## Checker notes (read, not exploited)

- The official `feasibility_check.py` accepts an objective up to 0.1% away from the recomputed cost. MV2's solver
  always reports the exact recomputed cost.
- The checker reads an optional `swapped` field that the solution schema does not mention: when it is true, `flow`
  and `arcs_used` are read as n x m and transposed. MV2's solver never sets it. The tests check that our checker
  agrees with the official one on it.

Results: `score-v1.md` (after the run `froc-roberti2015-v1`).

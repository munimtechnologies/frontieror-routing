# lee1996: Steiner tree-star solver (v0.1.0)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

A FrontierOR Main-track solver for the benchmark task `lee1996` (Lee, Chiu and Ryan, "A Branch and Cut Algorithm for
a Steiner Tree-Star Problem", INFORMS Journal on Computing 8(3), 1996; task files from the Hugging Face dataset
[frontieror/FrontierOR](https://huggingface.co/datasets/frontieror/FrontierOR), CC BY 4.0).

```
python solve.py --problem lee1996 --instance in.json --output out.json --time-limit 60
```

Standard library only. It writes a verified solution within a fraction of a second, rewrites it whenever it improves,
and stops by min(0.9 T, T - 3) seconds.

**How it works.** Choosing the active hubs is the whole problem: given them, each target's cheapest active hub and the
minimum spanning tree over the hubs are optimal. The solver searches over hub sets (add, drop, swap; iterated local
search) and prices each one exactly. See [PREREG.md](PREREG.md) for the bounds it prunes with and the tests.

**Files.** `solve.py` (solver and `verify()`), `test_lee1996.py` (tests: brute-force MST and optimum, exact deltas,
verify() rejections, a contest-style run), `lee_real.py` (the run on the six public instances with the official
checker, plus three pre-registered checker probes), [PREREG.md](PREREG.md) (guesses fixed before the run).

Status: run on the public instances queued; results will be graded against PREREG.md and published here.

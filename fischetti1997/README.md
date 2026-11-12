# fischetti1997: generalized TSP solver (candidate v0.1.0)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0 (code), CC BY 4.0
(text).

A contest-format solver for FrontierOR task fischetti1997 (symmetric generalized TSP, exactly one node per cluster),
built because MV2's generic engine (gpshim on HiGHS) gives no answer on its large instances within 60 s, and Gurobi's
reference stopped at its time limit on 4 of 5.

    python solve.py --problem fischetti1997 --instance in.json --output out.json --time-limit 60

Standard library only. Iterated local search with 2-opt, cluster relocation with node re-choice, and an exact
cluster-node dynamic programme; a forked second seed on the second CPU. See [`PREREG.md`](PREREG.md) for the method,
the tests and the 10 predictions, published before the first run on the public instances.

Files: [`solve.py`](solve.py), [`test_fischetti1997.py`](test_fischetti1997.py), [`fischetti_real.py`](fischetti_real.py)
(runs it on the public FrontierOR instances with the official checker, using this repository's `kit/`).

Data: FrontierOR benchmark, Hugging Face frontieror/FrontierOR (CC BY 4.0). Not affiliated with the FrontierOR
organisers.

# laporte2003: travelling purchaser solver (candidate v0.1.0)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0 (code), CC BY 4.0
(text).

A contest-format solver for FrontierOR task laporte2003 (the undirected travelling purchaser problem). It was built
because MV2's generic engine (gpshim on HiGHS) gives no answer on the task's large instances within 60 s, and Gurobi's
reference stopped without proving optimality on 2 of the 5.

    python solve.py --problem laporte2003 --instance in.json --output out.json --time-limit 60

Standard library only. For a fixed set of markets the purchase plan is exact (greedy per product), so the search is
over which markets to visit and in what order: iterated local search with 2-opt, relocation, drop, add and swap moves
with exact incremental purchase costs, and a forked second search on the second CPU. See [`PREREG.md`](PREREG.md) for
the method, the tests and the 10 predictions, published before the first run on the public instances.

Files: [`solve.py`](solve.py), [`test_laporte2003.py`](test_laporte2003.py), [`laporte_real.py`](laporte_real.py)
(runs it on the public FrontierOR instances with the official checker, using this repository's `kit/`).

Data: FrontierOR benchmark, Hugging Face frontieror/FrontierOR (CC BY 4.0). Not affiliated with the FrontierOR
organisers.

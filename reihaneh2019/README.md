# reihaneh2019: vehicle routing with demand allocation (VRDAP)

MV2's practice solver for FrontierOR task `reihaneh2019`. Made with AI agents working in MV2's name (MV2 of Munim,
Inc.). License: Apache-2.0 (code); notes and numbers CC BY 4.0.

Vehicles leave one depot and visit a chosen subset of candidate delivery sites. Each customer is assigned to one
opened site and picks up its order there. Each site is on at most one tour, and a tour's collected demand must fit in
the vehicle. The goal is the lowest routing cost plus assignment cost. The benchmark's one-thread Gurobi run of the
compact model hit its one-hour limit on all 5 large public instances.

```
python solve.py --problem reihaneh2019 --instance in.json --output out.json --time-limit 60 [--seed 1]
python -m unittest -v test_reihaneh2019
python reihaneh_real.py --hf-dir /data/hf --out-dir /out    # public instances + official checker
```

- `solve.py`: the v0.1.0 engine, standard library only. It uses ruin and recreate with simulated annealing over the tours and the customer-to-site assignment, with exact insertion costs and 2-opt re-sequencing. `verify()` mirrors the official checker.
- `test_reihaneh2019.py`: brute-force optima on small instances, an independent cost and rule check, rejection cases for the checker mirror, the command-line contract, and a tight-capacity fallback. `TestContestWay` runs the official checker when `MV2_FROC_HF` points at the dataset.
- `PREREG.md`: guesses written before the first run on the public instances.

Credits: Reihaneh and Ghoniem, "A branch-and-price algorithm for a vehicle routing with demand allocation problem",
European Journal of Operational Research (2019). Task, checker, instances and Gurobi references are from the Hugging
Face dataset frontieror/FrontierOR (CC BY 4.0). They are downloaded at run time and not copied here.

MV2, Munim, Inc., mv2@munimtech.com

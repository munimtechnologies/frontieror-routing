# bode2012: capacitated arc routing (CARP) solver for the FrontierOR benchmark

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; text CC BY 4.0.

A standard-library Python solver for FrontierOR task `bode2012` (Bode & Irnich 2012, two-index CARP), written for
the FrontierOR Challenge's Main track (2 vCPU, 4 GB, no network, answer before the time limit).

    python solve.py --problem bode2012 --instance instance.json --output solution.json --time-limit 60
    python -m unittest -v test_bode2012          # CARP_OFFICIAL=<feasibility_check.py> also checks agreement
    python bode_real.py --hf-dir <FrontierOR copy> --out-dir out   # public instances + official checker

- `solve.py`: required edges as two-direction tasks, shortest-path deadheading, SISR ruin-and-recreate with
  simulated annealing, per-route polish, exactly `num_vehicles` routes, `verify()` mirroring the official checker.
  Environment: `MV2_CARP_WORKERS` (2 = a forked second search), `MV2_CARP_SEED`, `MV2_CARP_LOG`.
- `test_bode2012.py`: Dijkstra vs Floyd-Warshall, cache consistency under ruin-and-recreate, exact insertion
  pricing, brute-force optima on small instances, verify() rejections, agreement with the official checker, timing.
- `bode_real.py`: runs the solver the contest way on the public tiny + 5 large instances (Hugging Face
  frontieror/FrontierOR, CC BY 4.0), judges every answer with the official `feasibility_check.py`, records the
  stored Gurobi answers' facts and a fleet-size probe of the checker.
- `PREREG.md`: 12 predictions written before the first run. Results will be graded in a separate score file.

Status: v0.1.0, not yet run on the public instances.

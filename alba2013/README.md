# alba2013: double TSP with multiple stacks (DTSPMS) solver for the FrontierOR benchmark

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; text CC BY 4.0.

A standard-library Python solver for FrontierOR task `alba2013` (Alba Martinez et al. 2013), written for the
FrontierOR Challenge's Main track (2 vCPU, 4 GB, no network, answer before the time limit).

    python solve.py --problem alba2013 --instance instance.json --output solution.json --time-limit 60
    python -m unittest -v test_alba2013          # DTSP_OFFICIAL=<feasibility_check.py> also checks agreement
    python alba_real.py --hf-dir <FrontierOR copy> --out-dir out   # public instances + official checker

- `solve.py`: simulated annealing over loading plans; for each plan, both optimal tours by an exact dynamic program
  over the stacks; answers always listed from the depot; `verify()` mirrors the official checker (strict about the
  depot-first listing). Environment: `MV2_DTSP_WORKERS`, `MV2_DTSP_SEED`, `MV2_DTSP_LOG`.
- `test_alba2013.py`: dynamic program vs every interleaving, solver vs brute force over every pair of tours, plan
  moves stay valid, verify() rejections, the rotation rule, agreement with the official checker, timing.
- `alba_real.py`: the public tiny + 5 large instances (Hugging Face frontieror/FrontierOR, CC BY 4.0) with the
  official checker, instance and Gurobi-answer facts, and a rotation probe of the checker.
- `PREREG.md`: 12 predictions written before the first run.

Status: v0.1.0, not yet run on the public instances.

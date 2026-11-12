# gpshim memory probe and gpshim_objfix 0.1.0

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0 (code),
CC BY 4.0 (text). Not affiliated with or endorsed by Gurobi Optimization, the FrontierOR organisers or Google.

- `memprobe.py`: runs FrontierOR's own reference models (`gurobi_code.py`, Hugging Face frontieror/FrontierOR,
  CC BY 4.0) through gpshim on HiGHS on large_instance_1. It kills any run above 3,900 MB, because the FrontierOR
  Challenge sandbox has 4 GB, and records where the memory went: model building in Python, matrix assembly, or the
  solver. The official checker judges each answer.
- `solve_probe.py`: the contest entry point (`python solve.py --problem --instance --output --time-limit`) with
  memory stage marks and objfix.
- `gpshim_objfix.py`: makes ObjVal the original objective's value at the solution, as Gurobi does, when gpshim
  had to reformulate quadratic objective terms. Use `import gpshim, gpshim_objfix; gpshim_objfix.install(gpshim)`.
- `test_objfix.py`: 6 tests (`python fetch_base.py . && python -m unittest -v test_objfix`).
- `fetch_base.py`: downloads the gpshim 0.2.0 base at a pinned commit.
- [`PREREG.md`](PREREG.md): 8 predictions, published before the run.

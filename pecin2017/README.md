# pecin2017: vehicle routing with time windows (FrontierOR)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0, text CC BY 4.0.

A FrontierOR Main-track solver for task pecin2017: serve every customer once within its time window, respect vehicle
capacity, use any number of vehicles, and minimise total Euclidean distance. The task comes from Pecin, Contardo,
Desaulniers and Uchoa, "New Enhancements for the Exact Solution of the Vehicle Routing Problem with Time Windows",
INFORMS Journal on Computing 29(3) (2017). The benchmark data are from Hugging Face frontieror/FrontierOR (CC BY 4.0)
and are downloaded at run time, not copied here.

| file | what |
|---|---|
| [solve.py](solve.py) | the solver (contest contract: `python solve.py --problem pecin2017 --instance in.json --output out.json --time-limit T`) |
| [frontier_runtime.py](frontier_runtime.py) | shared runtime: clock, atomic best-so-far writer, watchdog (copy of `kit/frontier_runtime.py`) |
| [pecin_check.py](pecin_check.py) | independent checker written from the official rules |
| [test_pecin.py](test_pecin.py) | offline tests, plus agreement with the official checker when it is available |
| [pecin_real.py](pecin_real.py) | runs the solver on the 6 public instances with the official checker |
| [wait_prereg.py](wait_prereg.py) | the job's first step: waits until PREREG.md is public and records it |
| [PREREG.md](PREREG.md) | predictions for the first run, written before it |

Method: insertion, then PyVRP (MIT; Wouda, Lan and Kool) on a conservatively rounded integer copy. Every route is
re-checked on the exact data before it is written. Status: first run queued.

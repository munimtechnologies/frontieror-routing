# borndorfer2007: line planning in public transport

FrontierOR task borndorfer2007 (Borndörfer, Grötschel and Pfetsch, "A Column-Generation Approach to Line Planning in
Public Transport", Transportation Science 41(1), 2007). Choose the lines (simple paths between two terminals of one
mode) and their frequencies, and route every passenger, minimising lambda x (fixed + operating line cost) + (1 - lambda)
x passenger travel time, under edge frequency limits and vehicle capacities.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

| file | what it is |
|---|---|
| [solve.py](solve.py) | the solver (FrontierOR contract: `python solve.py --problem borndorfer2007 --instance in.json --output out.json --time-limit 60`), standard library only, with `verify()` mirroring the official checker plus the model's line rules |
| [test_borndorfer2007.py](test_borndorfer2007.py) | tests: hand-computed optima, grids, mutations both checkers must reject, a line-rule probe, the real tiny instance |
| [born_real.py](born_real.py) | runs the solver on the public FrontierOR instances with the official checker and compares with the stored Gurobi plans |
| [wait_prereg.py](wait_prereg.py) | holds the graded job until its guesses are public |
| [PREREG.md](PREREG.md) | 13 guesses, written before the first run |

Method in short: a valid "anchor" line for every edge, capacity-aware shortest-path routing under a generalised cost,
then a greedy weighted cover that turns the needed frequency on each edge into lines and frequencies, and a search
that re-routes random origins and re-plans the lines. Details in the solve.py docstring and PREREG.md.

The FrontierOR benchmark data (Hugging Face frontieror/FrontierOR, CC BY 4.0) is downloaded at run time and not
copied here.

MV2, Munim, Inc., mv2@munimtech.com

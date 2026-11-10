# scflp/: bodur2017 (two-stage stochastic capacitated facility location), v0.1.0

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0; this text CC BY 4.0.

Pre-registered on 2026-11-10 at about 19:00 UTC, before the calibration job `froc-scflp-v1` ran. The guesses below will be graded exactly as written, failures included.

## The problem

This follows the public FrontierOR problem page (https://frontieror-challenge.com/problems/bodur2017), which is based on Bodur, Dash, Günlük and Luedtke, "Strengthened Benders Cuts for Stochastic Integer Programs with Continuous Recourse", INFORMS Journal on Computing 29(1), 2017.

- **Before demand is known:** choose which facilities to open. Each has an opening cost and a capacity.
- **In each demand scenario:** ship every customer's demand from open facilities at a per-unit cost (the Euclidean distance).
- **Constraints:** no facility ships more than its capacity, and closed facilities ship nothing. The opened capacity must cover the largest total demand of any scenario.
- **Objective:** minimise opening costs plus the probability-weighted transport cost. The time limit is 60 s.

**The official checker is public.** The contest's practice problems come from the FrontierOR benchmark (arXiv 2605.25246), which is published on Hugging Face as `frontieror/FrontierOR` (CC BY 4.0). Each of its 180 tasks comes with its `feasibility_check.py`, instances and Gurobi reference solutions, and the contest's public files for bodur2017 (`tiny_instance`, `large_instance_1`) are among them. What we read in the bodur2017 checker on 2026-11-10:

- missing `y` entries count as 0;
- the feasibility tolerance is 1e-5;
- the stated objective may differ from the recomputed one by up to max(1e-3, 1e-3 x |true objective|);
- `open_facilities` must be non-empty but is otherwise unused.

So our output format (full, open-only or sparse `y`) is accepted as written.

## The solver (bodur2017/solve.py)

Once the open set is fixed, every scenario is an independent transportation problem, so the solver searches over open sets and evaluates each one exactly:

1. **Quick start:** open facilities in order of cost per unit of capacity until the aggregate rule holds. Evaluate that set on every scenario and write it at once.
2. **Small instances:** if the whole extensive form is small (scenarios x facilities x customers <= 40,000), solve it as one MIP (HiGHS through SciPy, with strong linking rows). A proven optimum ends the run.
3. **Sample-average MIPs:**
   - first the mean-demand problem;
   - then up to three stratified samples: the largest-demand scenario plus one random scenario per demand stratum, each weighted by its stratum's probability.
   Every open set they return is evaluated on all scenarios. The aggregate rule always uses the true largest demand, so every candidate is feasible.
4. **Local search for the remaining time:** drop, add and swap moves (swaps go to the 8 facilities with the most similar cost profiles). Moves are screened on a stratified scenario sample sized to the time left, and the best 4 are confirmed on all scenarios. When stuck, the search kicks the best set with random changes.

**How the transportation problems are solved:** as min-cost flows (OR-Tools SimpleMinCostFlow) in integer units of 10^-6:

- demands are rounded up and capacities rounded down, so every flow written is exactly feasible;
- costs are scaled to integers only inside the flow solver;
- the stated objective is recomputed from the quantities written.

**Tools:**
- `scflp_check.py`: an independent checker that shares no code with the solver;
- `scflp_exact.py`: an extensive-form MIP, an LP evaluation of a fixed open set, and a brute force;
- `scflp_gen.py`: the instance generator;
- `scflp_eval.py`: the contest-style calibration through `kit/harness.py`;
- `test_scflp.py`: the tests.

## Calibration data

**Real instances (`scflp_real.py`):** the six bodur2017 instances of the FrontierOR benchmark (`tiny_instance`, `large_instance_1` to `_5`), downloaded at a pinned dataset revision with each file's sha256 recorded. Every solution of ours is checked by our checker and by the official `feasibility_check.py`. The reference is the objective of the Gurobi solution stored with each instance, which we also re-check with both checkers. We expect the contest's frozen references to be these Gurobi values or similar, but we have not confirmed that.

**Synthetic instances (`scflp_eval.py`):** Bodur et al. built their stochastic CAP instances from the classic capacitated facility location instances, so we also generate 20 synthetic instances in the classic way of Cornuéjols, Sridharan and Thizy (1991). Generator settings:

- capacity ratio 1.5-5;
- demand spread "normal" (std 10-20% of mean) or "high" (30-50%);
- the box size sets the balance between opening and transport costs.

The spread values and box sizes are our guesses. They are not the contest's.

| class | cases | facilities | customers | scenarios |
|---|---|---|---|---|
| S | 6 | 10-16 | 20-30 | 10-40 |
| M | 8 | 25-50 | 50-70 | 50-100 |
| L | 6 | 50-100 | 100-200 | 200-500 |

**References:**
- **S and M:** the extensive-form MIP, run by HiGHS for 150 s. Its open set is re-costed with one LP per scenario. It uses strong linking rows when the model has at most 130,000 flow variables, and it counts as proven only where HiGHS says so.
- **L:** the same solver given 180 s, which proves nothing.

**Baseline:** the expected-value solution, i.e. the mean-demand MIP's open set evaluated on every scenario.

**Score:** min(2, reference / objective), as the contest scores minimisation.

## Pre-registered guesses (probability that each holds)

| id | guess | p |
|---|---|---|
| B1 | The test step passes (`python scflp/test_scflp.py -v`) | 0.70 |
| B2 | All 20 runs are feasible under our checker, finish within 60 s, state an objective equal to the recomputed one, and the largest solution file is under 16 MB | 0.80 |
| B3 | At least 5 of the 6 S cases are within 0.01% of the extensive-MIP reference | 0.75 |
| B4 | Mean contest score on S+M >= 0.995 | 0.65 |
| B5 | On at least 4 of the 6 L cases, the 60 s result is within 0.5% of the 180 s result | 0.65 |
| B6 | No worse than the expected-value solution on every case where that solution exists | 0.85 |
| B7 | Mean gap to HiGHS's dual bound on the M cases with strong-linking references <= 1.0% | 0.45 |

On the six public FrontierOR instances (sizes not yet seen when these were written):

| id | guess | p |
|---|---|---|
| R1 | The official checker finds all 6 of our solutions feasible | 0.75 |
| R2 | Mean contest score on the 5 large instances against the Gurobi reference is >= 0.99 | 0.55 |
| R3 | Our checker and the official checker agree on every one of the 12 verdicts (our 6 solutions and Gurobi's 6) | 0.80 |
| R4 | On at least 1 of the 5 large instances we match or beat the Gurobi reference (score >= 1) | 0.40 |

All eleven will be graded in `score-v1.md` with Brier scores. The tallies are computed in `results.json` (synthetic) and `scflp-real/results.json` (real).

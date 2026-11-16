# borndorfer2007 (line planning in public transport) v0.1.0: pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0, text CC BY 4.0.
Written 2026-11-16 at about 16:30 UTC, before the job `froc-borndorfer2007-v1` was filed. That job first waits until
this file is public here (`wait_prereg.py`). Results go in `score-v1.md` next to this file, whether the guesses hold
or not.

## Why this task
FrontierOR task borndorfer2007 (hard-set rank 15, field "Public Transit & Mobility") asks for a line plan: which
bus/tram lines to run, how often, and how all passengers travel, minimising lambda x line cost + (1 - lambda) x
passenger travel time. MV2 had no solver for it. In MV2's reference census ([refgap/score-v1.md](../refgap/score-v1.md)),
it has the highest mean "ceiling" of any transit or logistics task in the hard set without a solver: 1.83. On all 5
large public instances Gurobi stopped at its one-hour limit with MIP gaps of 90%, 73%, 62%, 84% and 14%. The
benchmark's model also limits itself to at most 50,000 lines, enumerated shortest first within 30 s, and to the 10
shortest paths of each passenger pair. Longer lines are never considered, and every line pays a fixed cost.

A ceiling is an upper limit, not a forecast: a large gap can mean a weak bound rather than a weak answer.

## The solver ([solve.py](solve.py), standard library only)
- An "anchor" line for every edge: the shortest valid line through it, found by breadth-first search to two
  different terminals within the length limit. Edges with no valid line are closed to passengers.
- Passengers: capacity-aware all-or-nothing routing (Dijkstra per origin). The arc cost is (1 - lambda) x time +
  lambda x beta x operating cost / vehicle capacity.
- Lines for a routing:
  - each edge needs a frequency of max(flow in either direction) / vehicle capacity;
  - candidates are the anchor lines plus "corridor" lines grown from each busy edge along its busiest neighbours;
  - a lazy greedy picks lines and frequencies by cost per unit of covered need;
  - a reverse pass removes frequency no edge needs.
- Search: four start settings, then repeated re-routing of a random share of origins with costs that make spare line
  capacity free and unserved edges dearer. Lines are re-planned each time, and only improvements are kept. A
  forked second process runs another seed.
- `verify()` mirrors the official checker. In strict mode it also checks the model's line rules: mode edges, two
  different terminals, a simple path, the length limit. The official checker does not check those.

## The job
[born_real.py](born_real.py) runs the solver the contest way on the tiny instance and the 5 large public instances
(Hugging Face `frontieror/FrontierOR`, CC BY 4.0), at 60 s (`v010-60s`) and at 10 s (`v010-10s`). The official
`feasibility_check.py` judges every output. score = min(2, Gurobi's stored objective / ours). The job also records,
for our plans and for Gurobi's stored ones: line count, line lengths, fixed and operating cost, travel time and any
line-rule breaches. Then the tests run ([test_borndorfer2007.py](test_borndorfer2007.py)): hand-computed optima
on small networks, grids, mutations that both checkers must reject, a probe, and the real tiny instance.

## Guesses (probability that each holds, written before any run)
| id | guess | p |
|---|---|---|
| B1 | All unit tests pass (`exit=0` in tests.txt). | 0.70 |
| B2 | v010-60s: the official checker accepts all 6 outputs (none missing, none over time). | 0.60 |
| B3 | v010-60s: mean score on the 5 large instances >= 1.0. | 0.50 |
| B4 | v010-60s: strictly better than Gurobi's stored objective on at least 3 of the 5 large instances. | 0.50 |
| B5 | v010-60s: mean score on the 5 large instances >= 1.3. | 0.25 |
| B6 | v010-60s: large_5 (Gurobi's smallest gap, 14%) scores no higher than the mean of the other four large. | 0.60 |
| B7 | v010-60s: on the tiny instance, our objective is within 2% of Gurobi's (40,885.81, proven optimal for its restricted model). | 0.45 |
| B8 | Our verify (checker tolerances) agrees with the official checker on every output of both variants and on all 6 stored Gurobi solutions. | 0.80 |
| B9 | Gurobi's stored plan has more lines than ours (60 s) on at least 4 of the 5 large instances. | 0.55 |
| B10 | v010-10s mean large score >= 0.9 x v010-60s mean large score. | 0.60 |
| B11 | Probe: the official checker accepts a plan in which one line is split into two at a non-terminal node (line rules not checked). | 0.85 |
| B12 | All 6 stored Gurobi plans obey the line rules (our strict check finds no breach). | 0.80 |
| B13 | The job ends with status ok and peak memory under 1 GB. | 0.85 |

## Grading
From `born/summary.json` (variants: official_feasible, score, large_mean_score, large_strictly_better,
ours_agree_official, gurobi_official_feasible, gurobi_ours_feasible, parts; gurobi: lines, line_rule_breaches,
ours_strict_verdict), `born/tests.txt` (B1, the PROBE line for B11, the TINY line) and the job's summary (B13). A wrong
guess is reported as wrong, with a Brier score. If B11 holds, it joins the other checker findings in one note to the
FrontierOR maintainers. Our solver never relies on it.

## Honest limits
The contest scores private instances against its own frozen best-known values, which may be stronger than these
public Gurobi answers. The instances' sizes and lambda are not known before this run: the instance files cannot be read
outside a job. This is a first version, and its line design is greedy, not optimal.

MV2, Munim, Inc., mv2@munimtech.com

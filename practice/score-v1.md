# Practice solvers on the real FrontierOR instances: score of the pre-registration

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. CC BY 4.0. Graded 2026-11-11
from job `froc-practice-real-v1` (finished 16:39 UTC; repository at 36131580d332b820baed72df5f323b279abbacf3;
FrontierOR benchmark revision ef42a2eac13595453f986d9df0b62e86e75ab596). Predictions: [PREREG.md](PREREG.md), written before
the run. Raw numbers: [results-v1/summary.json](results-v1/summary.json), table: [results-v1/results.md](results-v1/results.md).

Each solver version ran on its task's tiny instance and five large public instances, 60 s each, the contest way. The
official `feasibility_check.py` judged every output. official_score is min(2, Gurobi / ours) for a minimisation task (ours / Gurobi
for a maximisation task) when the official checker accepts the file, otherwise 0.

## Results

| version | task | official accepts | mean official score, 5 large | note |
|---|---|---|---|---|
| darp-v2 (v0.2.0) | cordeau2006 dial-a-ride | 4/6 | 0.6095 | large_2, large_5 rejected: only 3 of 4 vehicles listed |
| **darp-v3 (v0.3.0)** | cordeau2006 | **6/6** | **1.0121** | better than the stored Gurobi solution on large_1 (+4.6%) and large_2 (+1.5%) |
| nagy-v2 | nagy2015 VRP with divisible deliveries and pickups | 3/6 | 0.4214 | large_2-4 rejected: arc backhaul n+i to linehaul i (constraint 15) |
| **nagy-v3** | nagy2015 | **6/6** | **1.1003** | better than the stored Gurobi solution on all 5 large instances (+4.5% to +19.5%) |
| op-v1 | fischetti1998 orienteering (maximise) | 6/6 | 0.8938 | 3.8% to 13.8% below Gurobi |
| spp-v020 / spp-v030 | hoffman1993 set partitioning | 3/6 | 0.2739 | no output on large_1, large_4, large_5 |

The official checkers accepted all 24 stored Gurobi solutions of these four tasks.

## Predictions

| id | prediction | p | outcome | held |
|---|---|---|---|---|
| D1 | darp-v2: official checker rejects >= 1 of 6 | 0.85 | 2 rejected | yes |
| D2 | darp-v3: official checker accepts all 6 | 0.75 | 6/6 | yes |
| D3 | darp-v3: mean official_score (5 large) >= 0.95 | 0.55 | 1.0121 | yes |
| N1 | nagy-v2: official checker rejects >= 1 of 6 | 0.35 | 3 rejected | yes |
| N2 | nagy-v3: official checker accepts all 6 | 0.80 | 6/6 | yes |
| S1 | spp-v020: >= 1 of 6 ends with no output or an official rejection | 0.55 | 3 with no output | yes |
| S2 | spp-v030: accepts all 6 and mean official_score >= 0.999 | 0.70 | 3/6, 0.2739 | **no** |
| O1 | op-v1: official checker accepts all 6 | 0.85 | 6/6 | yes |
| O2 | op-v1: mean official_score (5 large) >= 0.95 | 0.55 | 0.8938 | **no** |
| G1 | official checkers accept all 24 stored Gurobi solutions | 0.90 | 24/24 | yes |

8 of 10 held. Brier score 0.178 (a constant 0.5 guess would score 0.25).

## What the two misses mean

**S2 (set partitioning).** We expected that reading the instances the way the official checker does would be the fix. It was not
the problem: none of the five large instances has extra columns or stale leg indices. The real problem is that the public
instances are dense (100 legs, 15,000 rotations, many legs per rotation), and v0.3.0's search for a first solution failed.
On large_1 (the one case whose solver log was captured), the HiGHS MIP on the 1,000 columns of smallest reduced cost
used its 24 s slice without finding a feasible partition, and so did HiGHS on all 15,000 columns for the rest of the
minute. large_4 and large_5 ended the same way, with no output, which scores 0. Gurobi's stored solutions for the same three instances were found in 0.42 to 0.59 s. The LP bound on large_1 is
11.75 against a best-known 657, so the LP gives almost no guidance on these instances. v0.4.0 (in [spp040/](spp040/), pre-registered
before its run) adds an exact-cover depth-first search that finds partitions combinatorially and can prove optimality.

**O2 (orienteering).** op-v1 is feasible everywhere but collects 3.8% to 13.8% less prize than Gurobi on the 500-node
instances. Its local search needs to be stronger. That is open work.

## What changes

- The output fixes found by reading the official checkers are confirmed. darp v0.3.0 and nagy v3 go from 4/6 and 3/6
  accepted to 6/6, and both now beat the stored Gurobi solutions on average.
- Contest-style folders for these tasks (one folder per task, everything it imports inside it) are assembled from this
  repository's own files in the next job, together with the set-partitioning v0.4.0 test.

MV2, Munim, Inc., mv2@munimtech.com

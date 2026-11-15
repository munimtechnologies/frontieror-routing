# rothenbacher2018: truck-and-trailer routing with time windows (MV2 engine v0.1.0)

An open, standard-library-only solver for FrontierOR task `rothenbacher2018`. The task comes from Rothenbächer, Drexl and Irnich, "Branch-and-Price-and-Cut for the Truck-and-Trailer Routing Problem with Time Windows", Transportation Science 52(5) (2018). FrontierOR's stored one-hour Gurobi runs hit their time limit on all 5 large public instances (hard-list rank 4 of 180).

Made with AI agents working in MV2's name (MV2 of Munim, Inc., mv2@munimtech.com). Code: Apache-2.0. Text: CC BY 4.0. The FrontierOR benchmark (Hugging Face `frontieror/FrontierOR`) is CC BY 4.0.

## The problem in one paragraph

A mixed fleet of trucks, each used alone or with a trailer, collects supply from customers within time windows. Truck customers can only be reached by a truck without its trailer. A truck with a trailer can park the trailer at a trailer customer or a transshipment location, serve a subtour with the truck alone, and come back to couple. Cost = fixed truck costs + distance costs (with a towing surcharge while the trailer is attached) + coupling and decoupling costs.

## Use

```
python solve.py --problem rothenbacher2018 --instance in.json --output out.json --time-limit 60 [--seed 1]
python -m unittest -v test_rothenbacher2018          # MV2_FROC_HF=<benchmark copy> adds the official-checker tests
python rothenbacher_real.py --hf-dir <benchmark copy> --out-dir out   # tiny + 5 large public instances, 60 s and 10 s
```

## What the official checker wants (read in `feasibility_check.py` and `gurobi_code.py`)

- **Format.** Answers use the benchmark's own format, with expanded node ids. The decouple copy of parking location P[i] is n_orig + i, and the couple copy is n_orig + len(P) + i, where P = sorted(trailer customers + transshipment locations).
- **Time windows.** Customer time windows sit in an optional `time_window` field that the published schema does not list. The checker tests them on the service starts the answer reports in `arrival_times`.
- **Loading.** While the trailer is attached, supply goes into the trailer first. While it is parked, everything goes into the truck. At coupling, as much as fits moves into the trailer.
- **Cost.** The objective is recomputed from `route_sequence`. An arc pays the towing surcharge when its tail is the depot, a trailer customer or a couple copy, and its head is the depot, a trailer customer or a decouple copy. That rule also charges the surcharge on a trailer-customer-to-trailer-customer arc inside a subtour, so the solver prices that arc the same way.

## Method

- **Routes.** A route is a vehicle class, a main tour, and at most one parking with its truck-only subtour.
- **Fast insertion checks.** For each route we keep earliest departures, latest feasible arrivals and load prefixes. Any insertion is then checked and priced in O(1) per position: into the main tour, into the subtour, or as a new subtour with its own parking.
- **Search.** Slack induction by string removals (SISR, Christiaens and Vanden Berghe 2020) with simulated annealing, plus route removal, vehicle-class changes and re-parking.
- **Conservative choices.** Every answer is also a feasible point of the benchmark's own MIP:
  - at most one parking per route;
  - no class used more often than its `num_available`;
  - at a decouple or couple copy of a trailer customer, that customer's window and service time apply, as they do in `gurobi_code.py`.
- **Checked before writing.** Every written answer passes `verify()`, our mirror of the official checker.

## Results

The pre-registered guesses for the first run on the real instances are in [PREREG.md](PREREG.md). The graded results will be in `score-v1.md`.

MV2, Munim, Inc., mv2@munimtech.com

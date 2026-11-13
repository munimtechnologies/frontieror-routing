# archetti2007: inventory routing with the order-up-to policy (candidate solver v0.1.0)

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.
Standard library only (Python 3.8+).

A solver for the FrontierOR benchmark task `archetti2007` (Hugging Face `frontieror/FrontierOR`, CC BY 4.0), the
vendor-managed inventory routing problem of Archetti, Bertazzi, Laporte and Speranza (2007): one supplier, n
retailers, H periods, one vehicle, and every visit fills the retailer to its maximum stock.

```
python solve.py --problem archetti2007 --instance instance.json --output solution.json --time-limit 60
```

It stops at min(0.9 T, T - 3) seconds and writes the solution JSON the task's `feasibility_check.py` reads
(`deliveries`, `routes` as [i, j, times] segments, `supplier_inventory`, `retailer_inventory`, `objective_value`).

How it works
- With the order-up-to rule a retailer's plan is fixed by the periods it is visited, so each retailer gets the list
  of its stockout-free visit patterns (at most 2^H) with exact delivery quantities and holding cost.
- Cost = constant + chosen patterns' holding costs + one tour per period.
- Simulated annealing changes one retailer's pattern at a time, pricing all its patterns at once (holding change,
  exact removal or cheapest insertion per period, exact tours for up to 4 retailers, adaptive penalty on vehicle
  capacity and supplier stock), with 2-opt / or-opt tour repair, three cooling cycles and a strict final descent.
- Two workers via fork where available. Only plans that pass `verify()` (the checker's rules) are written.

Files: `solve.py` (solver + `verify()`), `test_archetti2007.py` (brute-force optima on small cases, checker
mirror, CLI timing; `ARCH_OFFICIAL=<feasibility_check.py>` adds an agreement test), `arch_real.py` (runs the public
instances with the official checker), `PREREG.md` (predictions published before the first run).

Status: not yet run on the real instances; see PREREG.md. Results will be added as `score-v1.md`.

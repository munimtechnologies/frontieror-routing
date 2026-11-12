# gpshim A/B: HiGHS vs CP-SAT on FrontierOR's reference models

Benchmark revision ef42a2eac13595453f986d9df0b62e86e75ab596 (Hugging Face frontieror/FrontierOR, CC BY 4.0); kit from munimtechnologies/frontieror-routing at dc12249d66a244daf6bc25d74876c8ac0fd935cd; versions {"highspy": "1.15.1", "ortools": "9.15.6755", "numpy": "2.5.4"}; gpshim base 0bea743ade89ee77bae0058bceaad18b93cc5e77; gpshim_cpsat 0.3.1 (CP-SAT in a worker process). Each task's own gurobi_code.py ran unchanged, the contest way, and the official feasibility_check.py judged every output. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

- Tasks selected: 55; tiny runs on CP-SAT: 55; CP-SAT eligible (all-integer model actually solved by CP-SAT): 54
- large_instance_1 eligible (<= 1500000 bytes): 35; skipped for budget: 0

## tiny_highs_vs_cpsat2

```
{
 "pairs": 54,
 "cpsat2_better": [
  "armbruster2012",
  "furini2017",
  "pettersson2020",
  "sadykov2013",
  "segundo2019",
  "walteros2020"
 ],
 "highs_better": [],
 "ties": 48,
 "mean_highs": 0.890245,
 "mean_cpsat2": 0.947317,
 "accepted_highs": 50,
 "accepted_cpsat2": 51,
 "best_of_both_mean": 0.947317
}
```

## large_highs_vs_cpsat2

```
{
 "pairs": 35,
 "cpsat2_better": [
  "barnhart2000",
  "caprara1999",
  "forrest2006",
  "gualandi2012",
  "hosseinian2020",
  "rahimian2017",
  "rothenbacher2019",
  "sadykov2013"
 ],
 "highs_better": [
  "boland2019",
  "chebil2015",
  "watermeyer2020"
 ],
 "ties": 24,
 "mean_highs": 0.214844,
 "mean_cpsat2": 0.329427,
 "accepted_highs": 10,
 "accepted_cpsat2": 13,
 "best_of_both_mean": 0.371226
}
```

## large_cpsat2_vs_cpsat8

```
{
 "pairs": 15,
 "cpsat8_better": [],
 "cpsat2_better": [
  "rothenbacher2019",
  "savelsbergh1997"
 ],
 "ties": 13,
 "mean_cpsat2": 0.189655,
 "mean_cpsat8": 0.177853,
 "accepted_cpsat2": 3,
 "accepted_cpsat8": 3,
 "best_of_both_mean": 0.189655
}
```

## Why models stayed on HiGHS (tiny)

- 1: `worker died ` (mingozzi1999)

## Large instance, per task

| task | highs | cpsat2 | cpsat8 |
|---|---|---|---|
| alba2013 | 0 (no_solution) | 0 (no_solution) | 0 (no_solution) |
| alfieri2020 | 0 (overtime_no_output) | 0 (no_solution) |  |
| araujo2020 | 0 (no_solution) | 0 (no_solution) | 0 (overtime) |
| barnhart2000 | 0.8916 | 0.9439 |  |
| bode2012 | 0 (no_solution) | 0 (no_solution) | 0 (no_solution) |
| boland2019 | 0.4335 | 0 (no_solution) |  |
| brandao2016 | 0 (overtime_no_output) | 0 (overtime_no_output) | 0 (overtime_no_output) |
| caprara1999 | 0 (rejected) | 0.9302 |  |
| carvalho1999 | 0 (overtime_no_output) | 0 (no_solution) |  |
| chebil2015 | 0.9986 | 0.9681 |  |
| cote2018 | 0 (overtime_no_output) | 0 (overtime_no_output) | 0 (overtime_no_output) |
| delorme2020 | 0 (crash) | 0 (crash) | 0 (crash) |
| fischetti1997 | 0 (no_solution) | 0 (no_solution) |  |
| forrest2006 | 0.0000 | 0.4445 |  |
| furini2016 | 0 (crash) | 0 (crash) | 0 (crash) |
| furini2017 | 1.0000 | 1.0000 |  |
| furini2021 | 0.5455 | 0.5455 |  |
| gschwind2021 | 0 (crash) | 0 (crash) | 0 (crash) |
| gualandi2012 | 0 (overtime_no_output) | 1.1765 |  |
| guo2021 | 0 (crash) | 0 (crash) |  |
| hosseinian2020 | 0 (overtime) | 1.5294 |  |
| kobeaga2024 | 0 (crash) | 0 (crash) |  |
| letelier2022 | 0 (rejected) | 0 (no_solution) | 0 (rejected) |
| mehrotra1996 | 0 (crash) | 0 (crash) |  |
| morrison2016 | 0 (crash) | 0 (crash) |  |
| rahimian2017 | 0 (no_solution) | 0.1026 |  |
| rothenbacher2019 | 0.6625 | 0.8556 | 0.6862 |
| sadykov2013 | 0 (overtime) | 1.0444 |  |
| sansegundo2016 | 0 (crash) | 0 (crash) | 0 (crash) |
| savelsbergh1997 | 0.9889 | 0.9892 | 0.9816 |
| walteros2020 | 0 (crash) | 0 (crash) | 0 (crash) |
| watermeyer2020 | 0.9991 | 0 (no_solution) |  |
| watermeyer2023 | 0 (no_solution) | 0 (no_solution) |  |
| wei2020 | 0 (overtime) | 0 (overtime_no_output) | 0 (overtime_no_output) |
| wei2020b | 1.0000 | 1.0000 | 1.0000 |

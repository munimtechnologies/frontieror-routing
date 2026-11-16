# FrontierOR reference census (refgap v0.1.0)

Benchmark revision `ef42a2eac13595453f986d9df0b62e86e75ab596`. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).
Ceiling = the contest score an answer would get if it reached Gurobi's own bound (bound = objective -/+ MIP gap x |objective|).

Tasks: 180; solution files: 1080 (987 read whole, 93 big ones read by their first and last 64 KB, 0 not read); large cases with a gap: 711 of 900.

## Top 30 tasks by mean ceiling over large instances

| task | hard-set rank | sense | mean ceiling | large cases at 2 | max gap | median gap | field |
|---|---|---|---|---|---|---|---|
| zetina2019 | 16 | min | 2 | 5/5 | 1 | 1 | Telecommunications & Networking |
| armbruster2012 | 7 | min | 2 | 5/5 | 0.9997 | 0.9984 | Foundational / Theoretical |
| kress2019 |  | min | 2 | 2/5 | 0.867 | 0.867 | Transportation & Logistics |
| martin-iradi2024 | 39 | min | 2 | 5/5 | 0.8588 | 0.8448 | Transportation & Logistics |
| rothenbacher2018 | 4 | min | 1.994 | 4/5 | 0.7397 | 0.625 | Transportation & Logistics |
| samarghandi2017 |  | min | 1.986 | 4/5 | 0.6897 | 0.6869 | Manufacturing & Production |
| bayani2024 | 32 | min | 1.971 | 4/5 | 0.788 | 0.7269 | Foundational / Theoretical |
| ropke2009 | 6 | min | 1.931 | 3/5 | 0.758 | 0.5781 | Transportation & Logistics |
| borndorfer2007 | 15 | min | 1.832 | 4/5 | 0.9045 | 0.732 | Public Transit & Mobility |
| kobeaga2024 | 42 | max | 1.8 | 4/5 | 16.4 | 6.875 | Foundational / Theoretical |
| he2020 | 28 | min | 1.76 | 3/5 | 0.8165 | 0.6125 | Transportation & Logistics |
| roshanaei2017 | 12 | min | 1.704 | 1/5 | 72.09 | 0.7342 | Healthcare |
| adulyasak2015 | 13 | min | 1.668 | 2/5 | 1 | 0.3429 | Supply Chain & Inventory |
| bierwirth2017 | 43 | min | 1.647 | 0/5 | 0.4607 | 0.3633 | Manufacturing & Production |
| fleszar2022b |  | max | 1.636 | 1/5 | 4.511 | 0.6722 | Foundational / Theoretical |
| segundo2019b |  | max | 1.602 | 3/5 | 8.611 | 1.141 | Foundational / Theoretical |
| hoffman1993 |  | min | 1.6 | 3/5 | 0.9452 | 0.6329 | Aerospace & Aviation |
| chen1999 |  | min | 1.586 | 2/5 | 0.8147 | 0.4813 | Manufacturing & Production |
| ji2019 |  | min | 1.579 | 1/5 | 0.8302 | 0.311 | Transportation & Logistics |
| spliet2015 | 48 | min | 1.554 | 1/5 | 0.7536 | 0.3121 | Transportation & Logistics |
| yang2013 |  | max | 1.542 | 1/5 | 2.469 | 0.4692 | Foundational / Theoretical |
| hassannayebi2016 |  | min | 1.506 | 0/5 | 0.4265 | 0.389 | Public Transit & Mobility |
| desaulniers2016 | 26 | min | 1.505 | 0/5 | 0.4501 | 0.3144 | Supply Chain & Inventory |
| guo2021 | 3 | min | 1.492 | 2/5 | 6349 | 0.1562 | Healthcare |
| bollapragada2001 |  | min | 1.475 | 2/5 | 0.7713 | 0.2714 | Foundational / Theoretical |
| bard2002 | 45 | min | 1.445 | 2/5 | 0.8571 | 0.15 | Transportation & Logistics |
| letelier2022 | 30 | min | 1.369 | 1/5 | 0.75 | 0.25 | Transportation & Logistics |
| colombi2017 |  | max | 1.351 | 0/5 | 0.7771 | 0.3973 | Transportation & Logistics |
| reihaneh2019 | 37 | min | 1.337 | 0/5 | 0.3541 | 0.2021 | Transportation & Logistics |
| nagy2015 | 5 | min | 1.278 | 0/5 | 0.2837 | 0.1888 | Transportation & Logistics |

Full data: tasks.csv, cases.csv, cases.jsonl, summary.json.

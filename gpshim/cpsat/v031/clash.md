# Solver import-order probe (FrontierOR image)

Versions: `{"python": "3.12.15", "highspy": "1.15.1", "ortools": "9.15.6755", "scipy": "1.18.1", "numpy": "2.5.4"}`, platform linux, 2026-11-12T09:40:03Z. Each row is a fresh Python process that solves a tiny model with each step in order. Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| order | result | error |
|---|---|---|
| highspy | ok |  |
| cpsat | ok |  |
| glop | ok |  |
| routing | ok |  |
| scipy_milp | ok |  |
| highspy then cpsat | FAILS at cpsat | ImportError('/usr/local/lib/python3.12/site-packages/ortools/sat/python/../../../ortools/.libs/libortools.so.9: undefined symbol: _Z19setLocalOptionValueRK15Hig |
| highspy then glop | FAILS at glop | ImportError('/usr/local/lib/python3.12/site-packages/ortools/linear_solver/../../ortools/.libs/libortools.so.9: undefined symbol: _Z19setLocalOptionValueRK15Hig |
| highspy then routing | FAILS at routing | ImportError('/usr/local/lib/python3.12/site-packages/ortools/constraint_solver/../../ortools/.libs/libortools.so.9: undefined symbol: _Z19setLocalOptionValueRK1 |
| highspy then scipy_milp | ok |  |
| cpsat then highspy | FAILS at highspy | ImportError('/usr/local/lib/python3.12/site-packages/highspy/_core.cpython-312-x86_64-linux-gnu.so: undefined symbol: _ZN5Highs13releaseMemoryEv') |
| cpsat then glop | ok |  |
| cpsat then routing | ok |  |
| cpsat then scipy_milp | ok |  |
| glop then highspy | FAILS at highspy | ImportError('/usr/local/lib/python3.12/site-packages/highspy/_core.cpython-312-x86_64-linux-gnu.so: undefined symbol: _ZN5Highs13releaseMemoryEv') |
| glop then cpsat | ok |  |
| glop then routing | ok |  |
| glop then scipy_milp | ok |  |
| routing then highspy | FAILS at highspy | ImportError('/usr/local/lib/python3.12/site-packages/highspy/_core.cpython-312-x86_64-linux-gnu.so: undefined symbol: _ZN5Highs13releaseMemoryEv') |
| routing then cpsat | ok |  |
| routing then glop | ok |  |
| routing then scipy_milp | ok |  |
| scipy_milp then highspy | ok |  |
| scipy_milp then cpsat | ok |  |
| scipy_milp then glop | ok |  |
| scipy_milp then routing | ok |  |

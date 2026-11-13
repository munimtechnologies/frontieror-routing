# FrontierOR checker census: today's checker vs the stored gurobi_feasi_result

Public FrontierOR benchmark (Hugging Face frontieror/FrontierOR, revision ef42a2eac13595453f986d9df0b62e86e75ab596, CC BY 4.0). Each task's official feasibility_check.py was run unchanged on its stored Gurobi solutions; every read of a key that the instance JSON does not contain was recorded (trace_run.py). Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

| task | case | stored feasible | checker now | violated | violations (first 300 chars) |
|---|---|---|---|---|---|

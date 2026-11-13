# FrontierOR checker census: instance keys a checker reads but the instance lacks

Public FrontierOR benchmark (Hugging Face frontieror/FrontierOR, revision ef42a2eac13595453f986d9df0b62e86e75ab596, CC BY 4.0). Each task's official feasibility_check.py was run unchanged on its stored Gurobi solutions; every read of a key that the instance JSON does not contain was recorded (trace_run.py). Made with AI agents working in MV2's name (MV2 of Munim, Inc.).

```
{
 "census_version": "0.2.0",
 "revision": "ef42a2eac13595453f986d9df0b62e86e75ab596",
 "tasks": 7,
 "cases": 42,
 "ran": 28,
 "with_stored_result": 28,
 "reproduced": 28,
 "mismatches": 0,
 "checker_failed": 0,
 "skipped": {
  "too_big": 14
 },
 "tasks_with_instance_default_reads": 0,
 "tasks_with_instance_default_reads_list": [],
 "tasks_with_any_absent_instance_key_read": 0,
 "he2020_instance_keys": [],
 "traced_timeouts": 0
}
```

Kinds: get / setdefault = the checker fell back to the default shown; in = a membership test came back false; getitem = d[key] raised KeyError (the checker may catch it). A default read is not a bug by itself: the triage of what each one changes is done by hand afterwards.

| task | key | kind | default(s) | cases | reads | context (keys of the object read) |
|---|---|---|---|---|---|---|

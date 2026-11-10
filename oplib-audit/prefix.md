# OPLib follow-up: the 2017 EA4OP routes against the instance files before and after 8e9cd01

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Code Apache-2.0, text and numbers CC BY 4.0.

Parent 2b8957e46dae9eb44c244fdfdc965382defdc310, fix 8e9cd01bf2c81607ec2f08b58ec658d66fd127f3, current 823ac3e8c156d45e868c295ee1c95c3fee05bdd2. OPLib's files are not redistributed.

```
{
 "parent": "2b8957e46dae9eb44c244fdfdc965382defdc310",
 "fix": "8e9cd01bf2c81607ec2f08b58ec658d66fd127f3",
 "current": "823ac3e8c156d45e868c295ee1c95c3fee05bdd2",
 "checks": {
  "Q1": "held",
  "Q2": "held",
  "Q3": "held",
  "Q4": "did not hold",
  "Q5": "held",
  "Q6": "held"
 },
 "parent_consistent": [
  "a280",
  "fnl4461",
  "kroA100",
  "nrw1379",
  "pa561",
  "pr76",
  "rat195",
  "rat575",
  "rat783",
  "rat99",
  "tsp225"
 ],
 "current_consistent": [
  "kroA100",
  "pa561",
  "pr76",
  "rat99"
 ],
 "floor_raw_ge_0_9_at_parent": [
  "rat195",
  "rat575",
  "rat783"
 ],
 "fix_equals_current": [
  "a280",
  "fnl4461",
  "nrw1379",
  "rat195",
  "rat575",
  "rat783",
  "rat99",
  "tsp225"
 ]
}
```

| instance | group | stated | re-scored, parent file | parent status | re-scored, current file | current status | node scores changed | route delta | only scores differ | route same at parent |
|---|---|---|---|---|---|---|---|---|---|---|
| a280-gen3-50 | fixed | 8684.0 | 8684.0 | consistent | 7720.0 | inconsistent | 279 | -964.0 | True | True |
| fnl4461-gen3-50 | fixed | 164201.0 | 164201.0 | consistent | 142782.0 | inconsistent | 4282 | -21419.0 | True | True |
| nrw1379-gen3-50 | fixed | 43972.0 | 43972.0 | consistent | 42280.0 | inconsistent | 1176 | -1692.0 | True | True |
| rat195-gen3-50 | fixed | 6139.0 | 6139.0 | consistent | 6141.0 | inconsistent | 30 | 2.0 | True | True |
| rat575-gen3-50 | fixed | 19879.0 | 19879.0 | consistent | 19857.0 | inconsistent | 52 | -22.0 | True | True |
| rat783-gen3-50 | fixed | 26797.0 | 26797.0 | consistent | 26762.0 | inconsistent | 61 | -35.0 | True | True |
| rat99-gen3-50 | fixed | 2886.0 | 2886.0 | consistent | 2886.0 | consistent | 18 | 0.0 | True | True |
| tsp225-gen3-50 | fixed | 7488.0 | 7488.0 | consistent | 7584.0 | inconsistent | 224 | 96.0 | True | True |
| pa561-gen3-50 | control | 14034.0 | 14034.0 | consistent | 14034.0 | consistent | 0 | 0.0 | True | True |
| kroA100-gen3-50 | control | 3180.0 | 3180.0 | consistent | 3180.0 | consistent | 0 | 0.0 | True | True |
| pr76-gen3-50 | control | 2430.0 | 2430.0 | consistent | 2430.0 | consistent | 0 | 0.0 | True | True |

# OPLib census: do the stored EA4OP routes agree with their instance files?

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Code Apache-2.0, text and numbers CC BY 4.0.

OPLib commit 823ac3e8c156d45e868c295ee1c95c3fee05bdd2. Every solutions/**/*.sol file was re-scored with its instance's NODE_SCORE_SECTION and re-costed with the instance's own TSPLIB distance function. OPLib's files are not redistributed.

## Tally

```
{
 "oplib_commit": "823ac3e8c156d45e868c295ee1c95c3fee05bdd2",
 "solution_files": 344,
 "checked": 344,
 "consistent": 337,
 "inconsistent": 7,
 "share_consistent": 0.9797,
 "not_checked": {},
 "by_gen": {
  "1": {
   "checked": 86,
   "consistent": 86,
   "inconsistent": []
  },
  "2": {
   "checked": 86,
   "consistent": 86,
   "inconsistent": []
  },
  "3": {
   "checked": 86,
   "consistent": 79,
   "inconsistent": [
    "a280-gen3-50",
    "fnl4461-gen3-50",
    "nrw1379-gen3-50",
    "rat195-gen3-50",
    "rat575-gen3-50",
    "rat783-gen3-50",
    "tsp225-gen3-50"
   ]
  },
  "4": {
   "checked": 86,
   "consistent": 86,
   "inconsistent": []
  }
 },
 "score_mismatch": [
  "a280-gen3-50",
  "fnl4461-gen3-50",
  "nrw1379-gen3-50",
  "rat195-gen3-50",
  "rat575-gen3-50",
  "rat783-gen3-50",
  "tsp225-gen3-50"
 ],
 "cost_mismatch": [],
 "over_limit": [],
 "with_duplicates": [],
 "not_starting_at_depot": [],
 "nodes_header_mismatch": [],
 "depot_score_counted_in_stated": 337,
 "gen3_checked": 86,
 "gen3_file_reading_counts": {
  "floor_tsplib": 81,
  "floor_raw": 20,
  "none": 5
 },
 "gen3_reproduced_by_reading": {
  "a280-gen3-50": [],
  "fnl4461-gen3-50": [],
  "nrw1379-gen3-50": [],
  "rat195-gen3-50": [],
  "rat575-gen3-50": [],
  "rat783-gen3-50": [],
  "tsp225-gen3-50": []
 },
 "rbc_excluded_gen3": [
  {
   "family": "rat99",
   "rows": [
    {
     "instance": "rat99-gen3-50",
     "status": "consistent",
     "score_diff": 0.0
    }
   ]
  },
  {
   "family": "rat195",
   "rows": [
    {
     "instance": "rat195-gen3-50",
     "status": "inconsistent",
     "score_diff": -2.0
    }
   ]
  },
  {
   "family": "tsp225",
   "rows": [
    {
     "instance": "tsp225-gen3-50",
     "status": "inconsistent",
     "score_diff": -96.0
    }
   ]
  },
  {
   "family": "pa561",
   "rows": [
    {
     "instance": "pa561-gen3-50",
     "status": "consistent",
     "score_diff": 0.0
    }
   ]
  },
  {
   "family": "rat575",
   "rows": [
    {
     "instance": "rat575-gen3-50",
     "status": "inconsistent",
     "score_diff": 22.0
    }
   ]
  },
  {
   "family": "rat783",
   "rows": [
    {
     "instance": "rat783-gen3-50",
     "status": "inconsistent",
     "score_diff": 35.0
    }
   ]
  },
  {
   "family": "nrw1379",
   "rows": [
    {
     "instance": "nrw1379-gen3-50",
     "status": "inconsistent",
     "score_diff": 1692.0
    }
   ]
  },
  {
   "family": "fnl4461",
   "rows": [
    {
     "instance": "fnl4461-gen3-50",
     "status": "inconsistent",
     "score_diff": 21419.0
    }
   ]
  }
 ]
}
```

## Inconsistent pairs

| instance | stated score | re-scored (with depot) | without depot | stated cost | re-costed | limit | Gen3 reading reproducing the stated score |
|---|---|---|---|---|---|---|---|
| a280-gen3-50 | 8684.0 | 7720.0 | 7720.0 | 1290.0 | 1290.0 | 1290.0 | [] |
| fnl4461-gen3-50 | 164201.0 | 142782.0 | 142782.0 | 91281.0 | 91281.0 | 91283.0 | [] |
| nrw1379-gen3-50 | 43972.0 | 42280.0 | 42280.0 | 28317.0 | 28317.0 | 28319.0 | [] |
| rat195-gen3-50 | 6139.0 | 6141.0 | 6141.0 | 1162.0 | 1162.0 | 1162.0 | [] |
| rat575-gen3-50 | 19879.0 | 19857.0 | 19857.0 | 3387.0 | 3387.0 | 3387.0 | [] |
| rat783-gen3-50 | 26797.0 | 26762.0 | 26762.0 | 4403.0 | 4403.0 | 4403.0 | [] |
| tsp225-gen3-50 | 7488.0 | 7584.0 | 7584.0 | 1958.0 | 1958.0 | 1958.0 | [] |

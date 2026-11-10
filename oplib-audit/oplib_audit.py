#!/usr/bin/env python3
"""Census: does every EA4OP solution stored in OPLib agree with its own instance file?

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. License: Apache-2.0.

OPLib (github.com/bcamath-ds/OPLib) is the standard benchmark library for the Orienteering Problem (OP). Next to
the instances it stores one best-found route per instance from the EA4OP algorithm (Kobeaga, Merino and Lozano
2018), with a stated ROUTE_SCORE and ROUTE_COST. While calibrating an OP solver on 39 OPLib instances, MV2's agents
found that 37 stated scores match the route re-scored with the instance's own NODE_SCORE_SECTION (up to the depot's
prize) but two do not: tsp225-gen3-50 (stated 7488, re-scored 7584) and a280-gen3-50 (stated 8684, re-scored 7720).
This script checks every pair in the library at a pinned commit, with code written independently of the solver
harness that found it.

For each solutions/**/*.sol file and its instance it records: route length, duplicates, unknown nodes, whether the
route starts at the depot; the route's cost under the instance's own TSPLIB distance function and whether it fits
COST_LIMIT; the route's score with and without the depot's prize; and whether ROUTE_SCORE / ROUTE_COST / ROUTE_NODES
agree. For Gen3 instances (score grows with distance from the depot, Fischetti, Salazar-Gonzalez and Toth 1998:
p_i = 1 + floor(99 * t_0i / max_j t_0j)) it also re-derives the scores under several readings of that formula and
reports which reading the instance file follows, and which reading (if any) reproduces each stated ROUTE_SCORE that
disagrees with the file. Only derived numbers are written; OPLib's files are not redistributed.

Usage:
    python oplib_audit.py fetch --data-dir /data
    python oplib_audit.py run --data-dir /data --out-dir /out
"""
import argparse
import csv
import json
import math
import os
import re
import sys
import time
import urllib.request

OPLIB_SHA = "823ac3e8c156d45e868c295ee1c95c3fee05bdd2"
RAW = "https://raw.githubusercontent.com/bcamath-ds/OPLib/" + OPLIB_SHA + "/"
API = "https://api.github.com/repos/bcamath-ds/OPLib/git/"
UA = "MV2 of Munim, Inc. OPLib consistency census (mv2@munimtech.com)"

# Gen3 instances that Kobeaga, Merino and Lozano (RB&C, arXiv 2011.02743) left out of their comparison with EA4OP
# and ALNS because of "an issue in the generation of scores of the instances used by those algorithms".
RBC_EXCLUDED_GEN3 = ["rat99", "rat195", "tsp225", "pa561", "rat575", "rat783", "nrw1379", "fnl4461"]


# ---------------------------------------------------------------- download
def _get(url, tries=3):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retried, then reported
            last = e
            time.sleep(2.0 * (k + 1))
    raise last


def local_name(rel):
    return rel.replace("/", "__")


def fetch(data_dir):
    root = os.path.join(data_dir, "oplib-" + OPLIB_SHA[:7])
    os.makedirs(root, exist_ok=True)
    tree_path = os.path.join(root, "tree.json")
    if not os.path.exists(tree_path):
        try:
            tree = json.loads(_get(API + "trees/" + OPLIB_SHA + "?recursive=1"))
        except Exception:  # noqa: BLE001 - fall back to commit -> tree sha
            commit = json.loads(_get(API + "commits/" + OPLIB_SHA))
            tree = json.loads(_get(API + "trees/" + commit["tree"]["sha"] + "?recursive=1"))
        with open(tree_path, "w", encoding="utf-8") as f:
            json.dump(tree, f)
    with open(tree_path, encoding="utf-8") as f:
        tree = json.load(f)
    paths = [e["path"] for e in tree.get("tree", []) if e.get("type") == "blob"]
    sols = sorted(p for p in paths if p.startswith("solutions/") and p.endswith(".sol"))
    insts = {os.path.basename(p)[:-len(".oplib")]: p for p in paths if p.endswith(".oplib")}
    want = []
    for s in sols:
        want.append(s)
        base = os.path.basename(s)[:-len(".sol")]
        if base in insts:
            want.append(insts[base])
    got = missing = 0
    for rel in want:
        dest = os.path.join(root, local_name(rel))
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            got += 1
            continue
        try:
            data = _get(RAW + rel)
            with open(dest, "wb") as f:
                f.write(data)
            got += 1
        except Exception as e:  # noqa: BLE001 - recorded, not fatal
            missing += 1
            print("missing", rel, e, flush=True)
        time.sleep(0.15)
    print("tree truncated:", tree.get("truncated"), "| blobs", len(paths), "| .sol", len(sols),
          "| .oplib", len(insts), "| files present", got, "| missing", missing, flush=True)


# ---------------------------------------------------------------- TSPLIB-style parsing
_SECTION = re.compile(r"^([A-Z_]+_SECTION)\s*:?\s*(.*)$")
_KEY = re.compile(r"^([A-Z][A-Z_0-9]*)\s*:\s*(.*)$")


def parse(text):
    """Return (header dict, sections dict of token lists per line). Works for .oplib and .sol files."""
    head, sec, cur = {}, {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "EOF":
            break
        m = _SECTION.match(line)
        if m:
            cur = m.group(1)
            sec[cur] = []
            rest = m.group(2).strip()
            if rest:
                sec[cur].append(rest.split())
            continue
        m = _KEY.match(line)
        if m:
            head[m.group(1)] = m.group(2).strip()
            cur = None
            continue
        if cur is not None:
            sec[cur].append(line.split())
    return head, sec


def nint(x):
    return int(x + 0.5)


class Instance:
    def __init__(self, text):
        head, sec = parse(text)
        self.head = head
        self.name = head.get("NAME", "")
        self.n = int(float(head.get("DIMENSION", "0")))
        self.limit = float(head["COST_LIMIT"])
        self.ewt = head.get("EDGE_WEIGHT_TYPE", "").upper()
        self.ewf = head.get("EDGE_WEIGHT_FORMAT", "").upper()
        self.coords = {}
        for row in sec.get("NODE_COORD_SECTION", []):
            self.coords[int(row[0])] = (float(row[1]), float(row[2]))
        self.score = {}
        for row in sec.get("NODE_SCORE_SECTION", []):
            self.score[int(row[0])] = float(row[1])
        self.depot = 1
        for row in sec.get("DEPOT_SECTION", []):
            for tok in row:
                v = int(float(tok))
                if v > 0:
                    self.depot = v
                    break
            else:
                continue
            break
        self.matrix = None
        if self.ewt == "EXPLICIT":
            vals = [float(t) for row in sec.get("EDGE_WEIGHT_SECTION", []) for t in row]
            self.matrix = explicit_matrix(vals, self.n, self.ewf)
        if self.ewt == "GEO":
            self._geo = {i: geo_latlon(x, y) for i, (x, y) in self.coords.items()}

    def nodes(self):
        if self.coords:
            return sorted(self.coords)
        return list(range(1, self.n + 1))

    def raw_dist(self, a, b):
        """Unrounded Euclidean distance (coordinate instances only), for the Gen3 formula readings."""
        (xa, ya), (xb, yb) = self.coords[a], self.coords[b]
        return math.sqrt((xa - xb) ** 2 + (ya - yb) ** 2)

    def d(self, a, b):
        """TSPLIB distance of the instance's EDGE_WEIGHT_TYPE."""
        if a == b:
            return 0.0
        t = self.ewt
        if t == "EXPLICIT":
            return self.matrix[a - 1][b - 1]
        if t == "EUC_2D":
            return float(nint(self.raw_dist(a, b)))
        if t == "CEIL_2D":
            return float(math.ceil(self.raw_dist(a, b)))
        if t == "ATT":
            (xa, ya), (xb, yb) = self.coords[a], self.coords[b]
            return float(att(xa - xb, ya - yb))
        if t == "GEO":
            return float(geo_dist(self._geo[a], self._geo[b]))
        raise ValueError("unsupported EDGE_WEIGHT_TYPE " + t)


def att(dx, dy):
    r = math.sqrt((dx * dx + dy * dy) / 10.0)
    t = nint(r)
    return t + 1 if t < r else t


def geo_latlon(x, y):
    pi = 3.141592

    def conv(v):
        deg = int(v)
        mn = v - deg
        return pi * (deg + 5.0 * mn / 3.0) / 180.0
    return conv(x), conv(y)


def geo_dist(p, q):
    rrr = 6378.388
    q1 = math.cos(p[1] - q[1])
    q2 = math.cos(p[0] - q[0])
    q3 = math.cos(p[0] + q[0])
    return int(rrr * math.acos(0.5 * ((1.0 + q1) * q2 - (1.0 - q1) * q3)) + 1.0)


def explicit_matrix(vals, n, fmt):
    M = [[0.0] * n for _ in range(n)]
    it = iter(vals)
    if fmt == "FULL_MATRIX":
        for i in range(n):
            for j in range(n):
                M[i][j] = next(it)
        return M
    pairs = []
    if fmt == "UPPER_ROW":
        pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    elif fmt == "LOWER_ROW":
        pairs = [(i, j) for i in range(n) for j in range(i)]
    elif fmt == "UPPER_DIAG_ROW":
        pairs = [(i, j) for i in range(n) for j in range(i, n)]
    elif fmt == "LOWER_DIAG_ROW":
        pairs = [(i, j) for i in range(n) for j in range(i + 1)]
    elif fmt == "UPPER_COL":
        pairs = [(i, j) for j in range(n) for i in range(j)]
    elif fmt == "LOWER_COL":
        pairs = [(i, j) for j in range(n) for i in range(j + 1, n)]
    else:
        raise ValueError("unsupported EDGE_WEIGHT_FORMAT " + fmt)
    for i, j in pairs:
        v = next(it)
        M[i][j] = M[j][i] = v
    return M


def parse_sol(text):
    head, sec = parse(text)
    seq = []
    for row in sec.get("NODE_SEQUENCE_SECTION", []):
        for tok in row:
            v = int(float(tok))
            if v == -1:
                break
            seq.append(v)
    return head, seq


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- Gen3 score readings
def gen3_variants(inst):
    """Score vectors under several readings of p_i = 1 + floor(99 * t_0i / max_j t_0j); depot gets 0."""
    if inst.ewt not in ("EUC_2D", "CEIL_2D", "ATT", "GEO") or not inst.coords:
        return {}
    o = inst.depot
    ids = [i for i in inst.nodes() if i != o]
    raw = {i: inst.raw_dist(o, i) for i in ids} if inst.ewt in ("EUC_2D", "CEIL_2D") else None
    tsp = {i: inst.d(o, i) for i in ids}
    out = {}
    for label, dd in (("floor_tsplib", tsp), ("floor_raw", raw)):
        if dd is None:
            continue
        mx = max(dd.values()) or 1.0
        out[label] = {i: 1 + math.floor(99.0 * dd[i] / mx + 1e-12) for i in ids}
    for label, dd in (("round_tsplib", tsp), ("round_raw", raw)):
        if dd is None:
            continue
        mx = max(dd.values()) or 1.0
        out[label] = {i: 1 + nint(99.0 * dd[i] / mx) for i in ids}
    if raw is not None:
        mx = max(raw.values()) or 1.0
        out["floor_raw_100"] = {i: math.floor(100.0 * raw[i] / mx + 1e-12) for i in ids}
        out["ceil_raw"] = {i: max(1, math.ceil(99.0 * raw[i] / mx - 1e-12)) for i in ids}
    return out


def match_rate(vec, file_scores, depot):
    ids = [i for i in vec if i != depot]
    if not ids:
        return None
    same = sum(1 for i in ids if abs(vec[i] - file_scores.get(i, -1)) < 1e-9)
    return round(same / len(ids), 6)


# ---------------------------------------------------------------- audit of one pair
def audit_pair(inst, sol_head, seq):
    r = {"n": inst.n, "ewt": inst.ewt, "limit": inst.limit, "depot": inst.depot,
         "stated_score": num(sol_head.get("ROUTE_SCORE")), "stated_cost": num(sol_head.get("ROUTE_COST")),
         "stated_nodes": num(sol_head.get("ROUTE_NODES")), "route_nodes": len(seq),
         "sol_cost_limit": num(sol_head.get("COST_LIMIT"))}
    known = set(inst.nodes())
    r["duplicates"] = len(seq) - len(set(seq))
    r["unknown_nodes"] = sorted(set(v for v in seq if v not in known))[:10]
    r["starts_at_depot"] = bool(seq) and seq[0] == inst.depot
    r["depot_score"] = inst.score.get(inst.depot, 0.0)
    if r["unknown_nodes"] or not seq:
        r["status"] = "bad_route"
        return r
    try:
        route = list(seq) + ([seq[0]] if seq[0] != seq[-1] else [])
        cost = sum(inst.d(a, b) for a, b in zip(route[:-1], route[1:]))
    except ValueError as e:
        r["status"] = "unsupported: %s" % e
        return r
    vis = set(seq)
    s_all = sum(inst.score.get(v, 0.0) for v in vis)
    s_nodep = s_all - (inst.score.get(inst.depot, 0.0) if inst.depot in vis else 0.0)
    r.update({"cost": cost, "fits_limit": cost <= inst.limit + 1e-9, "score_with_depot": s_all,
              "score_without_depot": s_nodep})
    st = r["stated_score"]
    r["score_matches"] = st is not None and (abs(st - s_all) < 1e-6 or abs(st - s_nodep) < 1e-6)
    r["score_matches_with_depot"] = st is not None and abs(st - s_all) < 1e-6
    r["score_diff"] = None if st is None else round(st - s_all, 6)
    r["cost_matches"] = r["stated_cost"] is not None and abs(r["stated_cost"] - cost) < 1e-6
    r["nodes_match"] = r["stated_nodes"] is not None and int(r["stated_nodes"]) == len(seq)
    ok = (r["score_matches"] and r["cost_matches"] and r["fits_limit"] and r["duplicates"] == 0
          and r["starts_at_depot"])
    r["status"] = "consistent" if ok else "inconsistent"
    return r


# ---------------------------------------------------------------- run
def run(data_dir, out_dir):
    root = os.path.join(data_dir, "oplib-" + OPLIB_SHA[:7])
    out = os.path.join(out_dir, "oplib-audit")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(root, "tree.json"), encoding="utf-8") as f:
        tree = json.load(f)
    paths = [e["path"] for e in tree.get("tree", []) if e.get("type") == "blob"]
    sols = sorted(p for p in paths if p.startswith("solutions/") and p.endswith(".sol"))
    insts = {os.path.basename(p)[:-len(".oplib")]: p for p in paths if p.endswith(".oplib")}
    rows = []
    gen3_rows = []
    for s in sols:
        base = os.path.basename(s)[:-len(".sol")]
        m = re.search(r"-gen(\d+)-(\d+)$", base)
        row = {"solution": s, "instance": base, "gen": int(m.group(1)) if m else None,
               "budget": int(m.group(2)) if m else None, "algorithm": s.split("/")[1] if s.count("/") >= 2 else ""}
        row["family"] = re.sub(r"-gen\d+-\d+$", "", base)
        ipath = insts.get(base)
        spath = os.path.join(root, local_name(s))
        if ipath is None or not os.path.exists(os.path.join(root, local_name(ipath))) or not os.path.exists(spath):
            row["status"] = "missing_file"
            rows.append(row)
            continue
        try:
            with open(os.path.join(root, local_name(ipath)), encoding="utf-8", errors="replace") as f:
                inst = Instance(f.read())
            with open(spath, encoding="utf-8", errors="replace") as f:
                sh, seq = parse_sol(f.read())
            row.update(audit_pair(inst, sh, seq))
        except Exception as e:  # noqa: BLE001 - recorded per file
            row["status"] = "error: %s" % repr(e)[:200]
            rows.append(row)
            continue
        if row.get("gen") == 3:
            vs = gen3_variants(inst)
            rates = {k: match_rate(v, inst.score, inst.depot) for k, v in vs.items()}
            row["gen3_file_follows"] = sorted(k for k, x in rates.items() if x == 1.0)
            row["gen3_match_rates"] = rates
            if row.get("status") == "inconsistent" and row.get("stated_score") is not None:
                vis = set(seq)
                repro = []
                for k, v in vs.items():
                    sc = sum(v.get(i, 0) for i in vis if i != inst.depot)
                    if abs(sc - row["stated_score"]) < 1e-6 or abs(sc + 1 - row["stated_score"]) < 1e-6:
                        repro.append(k)
                    row.setdefault("gen3_route_score_by_reading", {})[k] = sc
                row["gen3_reading_reproducing_stated"] = repro
            gen3_rows.append(row)
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("instance", "status", "stated_score", "score_with_depot",
                                                   "score_without_depot", "stated_cost", "cost", "limit")}),
              flush=True)
    done = [r for r in rows if r.get("status") in ("consistent", "inconsistent")]
    inc = [r for r in done if r["status"] == "inconsistent"]
    by_gen = {}
    for r in done:
        g = str(r.get("gen"))
        b = by_gen.setdefault(g, {"checked": 0, "consistent": 0, "inconsistent": []})
        b["checked"] += 1
        if r["status"] == "consistent":
            b["consistent"] += 1
        else:
            b["inconsistent"].append(r["instance"])
    excl = []
    for fam in RBC_EXCLUDED_GEN3:
        hit = [r for r in done if r.get("gen") == 3 and r.get("family") == fam]
        excl.append({"family": fam, "rows": [{"instance": r["instance"], "status": r["status"],
                                              "score_diff": r.get("score_diff")} for r in hit]})
    tally = {
        "oplib_commit": OPLIB_SHA,
        "solution_files": len(sols),
        "checked": len(done),
        "consistent": len(done) - len(inc),
        "inconsistent": len(inc),
        "share_consistent": round((len(done) - len(inc)) / len(done), 4) if done else None,
        "not_checked": {r["instance"]: r.get("status") for r in rows if r not in done},
        "by_gen": by_gen,
        "score_mismatch": sorted(r["instance"] for r in inc if not r.get("score_matches")),
        "cost_mismatch": sorted(r["instance"] for r in inc if not r.get("cost_matches")),
        "over_limit": sorted(r["instance"] for r in inc if not r.get("fits_limit")),
        "with_duplicates": sorted(r["instance"] for r in inc if r.get("duplicates")),
        "not_starting_at_depot": sorted(r["instance"] for r in inc if not r.get("starts_at_depot")),
        "nodes_header_mismatch": sorted(r["instance"] for r in done if not r.get("nodes_match")),
        "depot_score_counted_in_stated": sum(1 for r in done if r.get("score_matches_with_depot")),
        "gen3_checked": len([r for r in gen3_rows if r.get("status") in ("consistent", "inconsistent")]),
        "gen3_file_reading_counts": _count_readings(gen3_rows),
        "gen3_reproduced_by_reading": {r["instance"]: r.get("gen3_reading_reproducing_stated")
                                       for r in gen3_rows if r.get("status") == "inconsistent"},
        "rbc_excluded_gen3": excl,
    }
    with open(os.path.join(out, "audit.json"), "w", encoding="utf-8") as f:
        json.dump({"tally": tally, "rows": rows}, f, indent=1)
    cols = ["instance", "gen", "budget", "algorithm", "status", "n", "ewt", "limit", "stated_cost", "cost",
            "fits_limit", "stated_score", "score_with_depot", "score_without_depot", "depot_score", "score_diff",
            "stated_nodes", "route_nodes", "duplicates", "starts_at_depot"]
    with open(os.path.join(out, "audit.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c) for c in cols])
    lines = ["# OPLib census: do the stored EA4OP routes agree with their instance files?", "",
             "MV2 of Munim, Inc. Made with AI agents working in MV2's name. Code Apache-2.0, text and numbers CC BY 4.0.",
             "", "OPLib commit %s. Every solutions/**/*.sol file was re-scored with its instance's NODE_SCORE_SECTION "
             "and re-costed with the instance's own TSPLIB distance function. OPLib's files are not redistributed." %
             OPLIB_SHA, "", "## Tally", "", "```", json.dumps(tally, indent=1), "```", "",
             "## Inconsistent pairs", "",
             "| instance | stated score | re-scored (with depot) | without depot | stated cost | re-costed | limit | "
             "Gen3 reading reproducing the stated score |", "|---|---|---|---|---|---|---|---|"]
    for r in inc:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["instance"], r.get("stated_score"), r.get("score_with_depot"), r.get("score_without_depot"),
            r.get("stated_cost"), r.get("cost"), r.get("limit"), r.get("gen3_reading_reproducing_stated", "")))
    with open(os.path.join(out, "audit.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("TALLY", json.dumps({k: tally[k] for k in ("solution_files", "checked", "consistent", "inconsistent")}))


def _count_readings(gen3_rows):
    c = {}
    for r in gen3_rows:
        for k in r.get("gen3_file_follows", []) or ["none"]:
            c[k] = c.get(k, 0) + 1
    return c


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "run"])
    ap.add_argument("--data-dir", default="/data")
    ap.add_argument("--out-dir", default="/out")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        fetch(a.data_dir)
    else:
        run(a.data_dir, a.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Paired, case-level comparison of two conditions from results.<cond>.jsonl files.

  python3 analysis/paired_bootstrap.py --run experiments/<run> --a C3 --b C2 [--n-boot 10000] [--seed 1]
      [--source mamo_complex_lp] [--subset well_specified|ill_specified]

--subset filters cases against the frozen under-specification screen
(data/mamo_underspecified_ids.json, rule mamo_underspec_keyword.v1). Main tables use the full
set; the appendix repeats the same metrics with --subset well_specified. The screen is a
heuristic lower bound, so a well_specified subset still contains some ill-specified cases.

Units are cases (repeats of the same case are averaged first, so the resampling unit is the case, never the call).
Reports: accuracy of each condition, paired difference, case-level bootstrap 95% CI, exact McNemar test on the
(repeat-0) win/loss counts, and win/tie/loss counts. Every number in the paper comes from this script, not by hand.
"""
import argparse
import json
import math
import os
import random
from collections import defaultdict


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def per_case(rows):
    acc = defaultdict(list)
    for r in rows:
        acc[r["case_id"]].append(1.0 if r.get("correct") else 0.0)
    return {k: sum(v) / len(v) for k, v in acc.items()}


def load_flagged(path):
    """Case ids hit by the frozen under-specification screen, plus its rule version."""
    if not os.path.exists(path):
        raise SystemExit(f"--subset needs the flag file; not found: {path}")
    doc = json.load(open(path, "r", encoding="utf-8"))
    ids = set()
    for src in doc.get("sources", {}).values():
        for hit in src.get("flagged", []):
            ids.add(hit["case_id"])
    return ids, doc.get("rule_version")


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p-value for discordant counts b (A right, B wrong) and c (A wrong, B right)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--source", default=None, help="restrict to one benchmark source")
    ap.add_argument("--subset", choices=["well_specified", "ill_specified"], default=None,
                    help="filter by the frozen under-specification screen (appendix analysis)")
    ap.add_argument("--flags", default="data/mamo_underspecified_ids.json")
    a = ap.parse_args()
    ra = read_jsonl(os.path.join(a.run, f"results.{a.a}.jsonl"))
    rb = read_jsonl(os.path.join(a.run, f"results.{a.b}.jsonl"))
    if a.source:
        ra = [r for r in ra if r.get("source") == a.source]
        rb = [r for r in rb if r.get("source") == a.source]
    flag_rule = None
    if a.subset:
        flagged, flag_rule = load_flagged(a.flags)
        keep = (lambda r: r["case_id"] not in flagged) if a.subset == "well_specified" \
            else (lambda r: r["case_id"] in flagged)
        ra = [r for r in ra if keep(r)]
        rb = [r for r in rb if keep(r)]
    pa, pb = per_case(ra), per_case(rb)
    cases = sorted(set(pa) & set(pb))
    if not cases:
        raise SystemExit("no common cases")
    da = [pa[c] for c in cases]
    db = [pb[c] for c in cases]
    diff = [x - y for x, y in zip(da, db)]
    n = len(cases)
    mean_a, mean_b = sum(da) / n, sum(db) / n
    rng = random.Random(a.seed)
    boots = []
    for _ in range(a.n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        boots.append(sum(diff[i] for i in idx) / n)
    boots.sort()
    lo, hi = boots[int(0.025 * a.n_boot)], boots[int(0.975 * a.n_boot) - 1]
    # McNemar on repeat-0 outcomes
    r0a = {r["case_id"]: bool(r.get("correct")) for r in ra if r.get("repeat", 0) == 0}
    r0b = {r["case_id"]: bool(r.get("correct")) for r in rb if r.get("repeat", 0) == 0}
    bwin = sum(1 for c in cases if r0a.get(c) and not r0b.get(c))
    closs = sum(1 for c in cases if (not r0a.get(c)) and r0b.get(c))
    ties = n - bwin - closs
    out = {
        "run": os.path.basename(os.path.abspath(a.run)), "A": a.a, "B": a.b, "source": a.source, "subset": a.subset, "subset_rule": flag_rule, "n_cases": n,
        "accuracy_A": round(mean_a, 4), "accuracy_B": round(mean_b, 4), "diff_A_minus_B": round(mean_a - mean_b, 4),
        "bootstrap_95ci": [round(lo, 4), round(hi, 4)], "ci_excludes_zero": (lo > 0) or (hi < 0),
        "win_tie_loss_repeat0": [bwin, ties, closs], "mcnemar_exact_p": round(mcnemar_exact(bwin, closs), 5),
        "n_boot": a.n_boot, "seed": a.seed,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

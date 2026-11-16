#!/usr/bin/env python3
"""Score your own results on MAMO ComplexLP or IndustryOR with the checked references.

    python quickstart/score_with_checked_references.py --benchmark industryor --answers my_answers.csv
    python quickstart/score_with_checked_references.py --write-table

my_answers.csv has a header and two columns: the problem id (the `id` of the source
file, or the id used here such as industryor-0001) and the objective value your
method returned (empty if it returned none). The script prints your accuracy twice:
against the original references, and against the checked references, where a
corrected value replaces the original and a problem judged ambiguous is left out.
The comparison rule is the one of the article (relative and absolute tolerance 1e-4).

--write-table rebuilds references/checked_references.csv from the frozen files.
Standard library only.
"""
import argparse
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = os.path.join(ROOT, "frozen_tree")
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(FROZEN, "runtime"))
from orgene import score as S  # noqa: E402  (frozen scoring code of the evaluation)

BENCHMARKS = ("mamo_complex_lp", "industryor")
TABLE = os.path.join(ROOT, "references", "checked_references.csv")
REPLACING, LEAVES = ("CORRECT_ROUNDED", "INCORRECT"), ("AMBIGUOUS", "UNDERSPECIFIED")


def load(benchmark):
    """{case_id: row} for every problem of the benchmark; unchecked problems have verdict NOT_CHECKED."""
    rows = {}
    with open(os.path.join(FROZEN, "data", "cases", benchmark + ".jsonl"), encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if "case_id" in r:
                rows[r["case_id"]] = {"case_id": r["case_id"], "benchmark": benchmark, "source_id": r["source_id"],
                                      "original_reference": r["reference"]["objective"], "verdict": "NOT_CHECKED",
                                      "checked_reference": r["reference"]["objective"], "method": ""}
    doc = json.load(open(os.path.join(FROZEN, "data", "reference_overrides", benchmark + ".json"), encoding="utf-8"))
    for e in doc["entries"]:
        row = rows[e["case_id"]]
        row["verdict"], row["method"] = e["verdict"], e.get("method") or ""
        if e["verdict"] in REPLACING:
            row["checked_reference"] = e["new_value"]
        elif e["verdict"] in LEAVES:
            row["checked_reference"] = None
    return rows


def write_table():
    cols = ["case_id", "benchmark", "source_id", "original_reference", "verdict", "checked_reference", "method"]
    with open(TABLE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        n = 0
        for b in BENCHMARKS:
            for cid, row in sorted(load(b).items()):
                if row["verdict"] != "NOT_CHECKED":
                    w.writerow({k: ("" if row[k] is None else row[k]) for k in cols})
                    n += 1
    print(f"wrote {n} checked problems to {os.path.relpath(TABLE, ROOT)}")


def number(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def score(benchmark, answers_path):
    rows = load(benchmark)
    by_source = {r["source_id"]: cid for cid, r in rows.items()}
    answers, unknown = {}, []
    with open(answers_path, newline="", encoding="utf-8") as f:
        rd = csv.reader(f)
        next(rd, None)
        for line in rd:
            if not line or not line[0].strip():
                continue
            key = line[0].strip()
            cid = key if key in rows else by_source.get(key.lstrip("0") or "0")
            if cid is None:
                unknown.append(key)
            else:
                answers[cid] = number(line[1].strip()) if len(line) > 1 else None
    if unknown:
        print(f"{len(unknown)} id(s) not in {benchmark}, ignored: {', '.join(unknown[:5])}{' ...' if len(unknown) > 5 else ''}")
    if not answers:
        sys.exit("no answer matched a problem id of this benchmark")
    ok = lambda obj, ref: obj is not None and ref is not None and S.is_correct(obj, ref)[0]  # noqa: E731
    orig = [ok(a, rows[c]["original_reference"]) for c, a in answers.items()]
    kept = [c for c in answers if rows[c]["checked_reference"] is not None]
    chk = [ok(answers[c], rows[c]["checked_reference"]) for c in kept]
    flipped = [c for c in kept if ok(answers[c], rows[c]["checked_reference"]) != ok(answers[c], rows[c]["original_reference"])]
    left = [c for c in answers if rows[c]["checked_reference"] is None]
    print(f"{benchmark}: {len(answers)} problems answered")
    print(f"  original references: {sum(orig)}/{len(orig)} = {100 * sum(orig) / len(orig):.1f}%")
    print(f"  checked references:  {sum(chk)}/{len(chk)} = {100 * sum(chk) / max(1, len(chk)):.1f}%"
          f"   ({len(left)} ambiguous problems left out)")
    if flipped:
        print(f"  verdict on your answer changes on: {', '.join(sorted(flipped))}")
    checked = sum(1 for c in answers if rows[c]["verdict"] != "NOT_CHECKED")
    print(f"  {checked} of your {len(answers)} problems have a verdict in the checked-reference files; the others keep their original reference.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--benchmark", choices=BENCHMARKS)
    ap.add_argument("--answers", help="CSV: problem id, objective value")
    ap.add_argument("--write-table", action="store_true", help="rebuild references/checked_references.csv")
    a = ap.parse_args()
    if a.write_table:
        return write_table()
    if not a.benchmark or not a.answers:
        ap.error("give --benchmark and --answers, or --write-table")
    score(a.benchmark, a.answers)


if __name__ == "__main__":
    main()

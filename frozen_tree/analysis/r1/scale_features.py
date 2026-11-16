#!/usr/bin/env python3
"""Scale features of every case, computed from the problem statement by script only (E14; todo 1A, A1-22).

  $ORGENE_PY analysis/r1/scale_features.py [--out data/features/scale_features.json]
                                           [--token-counter module:function] [--solve-records records.jsonl ...]

Nobody reads the statements: the script reads the frozen cases files named by data/splits/*/SPLIT_LOCK.json and
writes numbers keyed by case id. Nothing it prints or writes contains statement text.

Features per case
  n_chars, n_words                    length of the statement
  n_numeric_literals                  numbers written in the statement ("1,200", "3.5", "40%" count once each;
                                      digits inside identifiers such as x1 do not count)
  n_tokens                            statement tokens with the local tokenizer (E09), passed as --token-counter
                                      module:function (function(text) -> int); null while no counter is given
  n_variables_est, n_constraints_est  from C0 round-0 solve records (E12), passed as --solve-records (jsonl with
                                      case_id, n_variables, n_constraints; first record per case); null = missing
Strata: tertile cut points per benchmark from the frozen dev cases only (statistics.quantiles, n=3, "inclusive"),
applied to every case: 0 (<= q1), 1 (<= q2), 2 (> q2); null where the feature is missing.
"""
import argparse
import datetime
import glob
import hashlib
import importlib
import json
import os
import re
import statistics
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

SCHEMA = "orgene-r1/scale_features/v1"
NUM_RE = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?%?(?![\w])")
FEATURES = ("n_chars", "n_words", "n_numeric_literals", "n_tokens", "n_variables_est", "n_constraints_est")
CUT_RULE = "per benchmark; tertiles of the frozen dev cases (statistics.quantiles n=3 method=inclusive); 0 <= q1 < 1 <= q2 < 2"


def text_features(text, count_tokens=None):
    return {"n_chars": len(text), "n_words": len(text.split()), "n_numeric_literals": len(NUM_RE.findall(text)),
            "n_tokens": int(count_tokens(text)) if count_tokens else None}


def load_counter(spec):
    if not spec:
        return None
    mod, _, fn = spec.partition(":")
    if not fn:
        raise SystemExit("--token-counter must be module:function")
    return getattr(importlib.import_module(mod), fn)


def load_solve_records(paths):
    out = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    out.setdefault(r["case_id"], (r.get("n_variables"), r.get("n_constraints")))
    return out


def cutpoints(values):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    q = statistics.quantiles(vals, n=3, method="inclusive")
    return [round(q[0], 6), round(q[1], 6)]


def stratum(v, cp):
    if v is None or cp is None:
        return None
    return 0 if v <= cp[0] else (1 if v <= cp[1] else 2)


def build(root, token_counter=None, solve_records=()):
    count = load_counter(token_counter)
    solved = load_solve_records(solve_records)
    feats, sources, cps = {}, [], {}
    for lock_path in sorted(glob.glob(os.path.join(root, "data", "splits", "*", "SPLIT_LOCK.json"))):
        d = os.path.dirname(lock_path)
        bench = os.path.basename(d)
        lock = json.load(open(lock_path, encoding="utf-8"))
        side = {c: "dev" for c in json.load(open(os.path.join(d, "dev_ids.json"), encoding="utf-8"))}
        side.update({c: "test" for c in json.load(open(os.path.join(d, "test_ids.json"), encoding="utf-8"))})
        cases_path = os.path.join(root, lock["cases_path"])
        sources.append({"benchmark": bench, "cases_path": lock["cases_path"],
                        "cases_sha256": hashlib.sha256(open(cases_path, "rb").read()).hexdigest()})
        rows = {}
        with open(cases_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("_header") or r["case_id"] not in side:
                    continue
                x = text_features(r["text"], count)
                nv, nc = solved.get(r["case_id"], (None, None))
                x.update({"n_variables_est": nv, "n_constraints_est": nc})
                rows[r["case_id"]] = dict(benchmark=bench, split=side[r["case_id"]], **x)
        cps[bench] = {k: cutpoints([v[k] for v in rows.values() if v["split"] == "dev"]) for k in FEATURES}
        for cid, v in rows.items():
            v["strata"] = {k: stratum(v[k], cps[bench][k]) for k in FEATURES}
        feats.update(rows)
    return {"schema": SCHEMA, "created": datetime.date.today().isoformat(), "sources": sources,
            "tokenizer": token_counter, "solve_records": [os.path.basename(p) for p in solve_records],
            "pending": ([] if token_counter else ["n_tokens: local tokenizer (E09)"]) +
                       ([] if solve_records else ["n_variables_est / n_constraints_est: C0 round-0 solve records (E12)"]),
            "cut_rule": CUT_RULE, "cutpoints": cps, "features": {c: feats[c] for c in sorted(feats)}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    ap.add_argument("--out", default="data/features/scale_features.json")
    ap.add_argument("--token-counter", default=None)
    ap.add_argument("--solve-records", nargs="*", default=[])
    a = ap.parse_args(argv)
    doc = build(a.root, a.token_counter, a.solve_records)
    out = a.out if os.path.isabs(a.out) else os.path.join(a.root, a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(doc, indent=1) + "\n")
    n_by = {}
    for v in doc["features"].values():
        n_by[(v["benchmark"], v["split"])] = n_by.get((v["benchmark"], v["split"]), 0) + 1
    print("cases:", ", ".join(f"{b}/{s} {n}" for (b, s), n in sorted(n_by.items())))
    print("pending:", "; ".join(doc["pending"]) or "(none)")
    print("wrote", os.path.relpath(out, a.root))
    return 0


if __name__ == "__main__":
    sys.exit(main())

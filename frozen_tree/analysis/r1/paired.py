#!/usr/bin/env python3
"""Paired, case-level comparison of two analysis labels (E20a; generalises v5 analysis/paired_bootstrap.py).

  $PY analysis/r1/paired.py --a C3L@2 --b C3E@2 [--registry experiments/run_registry.json]
      [--set main | --set dev_signal55] [--incl-0905] [--outcome correct] [--models qwen3:8b ...]
      [--n-boot N --seed S] [--allow-pending] --out paired.json

For each model, each benchmark of the analysis set, and the pooled set:
  accuracy of A and B, paired difference A - B,
  case bootstrap percentile CI (default 95%; pooled: resampled within each benchmark, so every replicate keeps the
    benchmark sizes; one benchmark: the same draws as v5 paired_bootstrap.py, which it reproduces),
  exact two-sided McNemar test, wins / ties / losses, discordant proportion with its Wilson interval.
Repeats of a case are averaged first, so the case is the unit of resampling and testing; with several repeats the
McNemar test becomes the exact sign test on the per-case mean differences (identical when there is one repeat).
The labels may come from different run directories (one per benchmark, or one per configuration): the registry
(registry.py) assembles them. A case of the analysis set that a label lacks is an error.

Outcome: correct (primary), correct_tol:<tier>, correct_original_ref, correct_tol_original_ref:<tier>,
verified_correct, exec_ok, protocol_ok. A set whose reference kind is "original" (sens_orig_ref) switches correct /
correct_tol to their original-reference forms; a set whose kind is "not_a_signal" (dev_error_type_only30) is refused.
Outputs are labelled DEV / TEST (file name and first line). Standard library only.
"""
import argparse
import math
import random
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import prereg as PR  # noqa: E402
import registry as RG  # noqa: E402
from common import (AnalysisError, csv_text, dumps, labelled_path, md_header, p4, pct1, r4, rel,  # noqa: E402
                    signed_pp, write_text)

SCHEMA = "orgene.r1.paired.v1"
Z95 = 1.959963984540054


# ------------------------------------------------------------------ statistics (standard library)


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p for discordant counts b (A right, B wrong) and c (A wrong, B right)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def wilson(x, n, z=Z95):
    if n == 0:
        return (None, None)
    p = x / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def percentile_ci(boots, level):
    """The v5 convention: sorted replicates, lower = b[int(a/2 * B)], upper = b[int((1 - a/2) * B) - 1]."""
    b = sorted(boots)
    B = len(b)
    a = 1.0 - level
    # the small epsilon keeps float fuzz (1 - 0.95 = 0.050000000000000044) from moving an index by one
    return b[int(math.floor(a / 2 * B + 1e-9))], b[int(math.floor((1 - a / 2) * B + 1e-9)) - 1]


def bootstrap_mean_diff(strata, n_boot, seed):
    """Replicates of the mean of all differences; each stratum (a list of per-case differences, in a fixed order) is
    resampled with replacement to its own size. One stratum reproduces v5 paired_bootstrap.py draw for draw."""
    rng = random.Random(seed)
    N = sum(len(s) for s in strata)
    out = []
    for _ in range(n_boot):
        tot = 0.0
        for s in strata:
            m = len(s)
            idx = [rng.randrange(m) for _ in range(m)]
            tot += sum(s[i] for i in idx)
        out.append(tot / N)
    return out


# ------------------------------------------------------------------ outcomes and per-case values


def outcome_field(outcome, reference_kind="r1"):
    """(field, tier) read from a matrix row for `outcome` under an analysis set's reference kind."""
    if reference_kind == "not_a_signal":
        raise AnalysisError("this analysis set is not a correctness signal (error types only); refusing a paired "
                            "accuracy comparison")
    base, _, tier = outcome.partition(":")
    if base in ("correct_tol", "correct_tol_original_ref") and not tier:
        raise AnalysisError(f"{base} needs a tier, e.g. {base}:0.0001")
    if base not in RG.OUTCOMES + ("correct_tol", "correct_tol_original_ref"):
        raise AnalysisError(f"unknown outcome {outcome!r}")
    if reference_kind == "original":
        base = {"correct": "correct_original_ref", "correct_tol": "correct_tol_original_ref"}.get(base, base)
    return base, (tier or None)


def value_of(row, field, tier):
    v = row.get(field)
    if tier is not None:
        v = (v or {}).get(tier) if isinstance(v, dict) else None
    if v is None:
        raise AnalysisError(f"{row['label']}: case {row['case_id']} has no {field}{':' + tier if tier else ''} "
                            "(older result rows lack it)")
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if v in (0, 1):
        return float(v)
    raise AnalysisError(f"{field} must be boolean, got {v!r}")


def per_case(rows, field, tier):
    """{case_id: mean over repeats}, {case_id: number of repeats}."""
    acc = {}
    for r in rows:
        acc.setdefault(r["case_id"], []).append(value_of(r, field, tier))
    return {c: sum(v) / len(v) for c, v in acc.items()}, {c: len(v) for c, v in acc.items()}


def compare_cases(pa, pb, cases, bench_of, n_boot=10000, seed=1, level=0.95, stratify=True):
    """Paired comparison over `cases` (every case must be in pa and pb)."""
    cases = sorted(cases)
    missing = [c for c in cases if c not in pa or c not in pb]
    if missing:
        raise AnalysisError(f"{len(missing)} case(s) of the analysis set lack a value in one of the two labels "
                            f"(first: {missing[:3]})")
    n = len(cases)
    if n == 0:
        raise AnalysisError("no cases to compare")
    by = {}
    for c in cases:
        by.setdefault(bench_of[c] if stratify else "all", []).append(pa[c] - pb[c])
    strata_names = sorted(by)
    boots = bootstrap_mean_diff([by[s] for s in strata_names], n_boot, seed)
    lo, hi = percentile_ci(boots, level)
    d = [pa[c] - pb[c] for c in cases]
    wins = sum(1 for x in d if x > 0)
    losses = sum(1 for x in d if x < 0)
    binary = all(pa[c] in (0.0, 1.0) and pb[c] in (0.0, 1.0) for c in cases)
    acc_a = sum(pa[c] for c in cases) / n
    acc_b = sum(pb[c] for c in cases) / n
    out = {"n": n, "acc_a": r4(acc_a), "acc_b": r4(acc_b), "diff": r4(acc_a - acc_b),
           "ci": [r4(lo), r4(hi)], "ci_level": level, "ci_excludes_zero": lo > 0 or hi < 0,
           "n_boot": n_boot, "seed": seed, "strata": strata_names if len(strata_names) > 1 else None,
           "wins": wins, "ties": n - wins - losses, "losses": losses,
           "mcnemar_exact_p": mcnemar_exact(wins, losses), "binary": binary}
    if binary:
        both_right = sum(1 for c in cases if pa[c] == 1.0 and pb[c] == 1.0)
        wl = wilson(wins + losses, n)
        out.update({"a_only_right": wins, "b_only_right": losses, "both_right": both_right,
                    "both_wrong": n - wins - losses - both_right, "discordance": r4((wins + losses) / n),
                    "discordance_wilson95": [r4(wl[0]), r4(wl[1])],
                    "n_correct_a": sum(1 for c in cases if pa[c] == 1.0),
                    "n_correct_b": sum(1 for c in cases if pb[c] == 1.0)})
    # exact (unrounded) values for downstream checks
    out["_exact"] = {"acc_a": acc_a, "acc_b": acc_b, "diff": acc_a - acc_b, "ci": [lo, hi]}
    return out


def compare(matrix, a, b, model, outcome="correct", bench_of=None, reference_kind="r1", n_boot=10000, seed=1,
            level=0.95, scopes=None):
    """Per benchmark and pooled comparisons of labels a and b of one model. bench_of: {case_id: benchmark} of the
    analysis set (default: every case of the matrix that both labels hold, benchmark from the rows)."""
    field, tier = outcome_field(outcome, reference_kind)
    ra, rb = matrix.select(model, a), matrix.select(model, b)
    pa, ka = per_case(ra, field, tier)
    pb, kb = per_case(rb, field, tier)
    if bench_of is None:
        bench_of = {r["case_id"]: r["benchmark"] for r in ra + rb}
    benches = sorted(set(bench_of.values()))
    res = []
    for scope in (scopes or benches + (["pooled"] if len(benches) > 1 else [])):
        cases = [c for c, bm in bench_of.items() if scope == "pooled" or bm == scope]
        r = compare_cases(pa, pb, cases, bench_of, n_boot, seed, level, stratify=scope == "pooled")
        r.update({"model": model, "a": a, "b": b, "outcome": outcome, "field": field + (f":{tier}" if tier else ""),
                  "scope": scope, "max_repeats_a": max(ka[c] for c in cases), "max_repeats_b": max(kb[c] for c in cases)})
        res.append(r)
    return res


# ------------------------------------------------------------------ report


def cell(r):
    ci = f"[{signed_pp(r['ci'][0])}, {signed_pp(r['ci'][1])}]"
    return (f"| {r['model']} | {r['a']} vs {r['b']} | {r['scope']} | {r['n']} | {pct1(r['acc_a'])} | {pct1(r['acc_b'])} | "
            f"{signed_pp(r['diff'])} | {ci} | {r['wins']}/{r['ties']}/{r['losses']} | {p4(r['mcnemar_exact_p'])} |")


def render_md(doc):
    lines = [md_header(f"Paired comparison ({doc['outcome']}, set {doc['analysis_set']['name']})", doc["data"]),
             "| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    lines += [cell(r) for r in doc["results"]]
    if doc["prereg"]["pending_used"]:
        lines += ["", "Pending pre-registered items used with their proposals: " +
                  ", ".join(sorted(doc["prereg"]["pending_used"]))]
    return "\n".join(lines) + "\n"


def run(args, matrix=None, aset=None, prereg=None):
    """Library entry used by the CLI and the tests; returns the output document."""
    pr = prereg or PR.load(args.prereg)
    if matrix is None:
        reg = RG.load_registry(args.registry, superseded_path=args.superseded)
        matrix = RG.build_matrix(reg, labels=[args.a, args.b], models=args.models)
    dev = matrix.label == "DEV"
    boot = pr.get("bootstrap", allow_pending=dev)
    n_boot = args.n_boot or boot["n_boot"]
    seed = boot["seed"] if args.seed is None else args.seed
    level = boot.get("ci_level", 0.95)
    if aset is None:
        name = RG.set_name_for(matrix.label, args.set, args.incl_0905)
        aset = RG.resolve_set(name, allow_pending=args.allow_pending and dev)
    if aset["pending"] and not dev:
        raise AnalysisError(f"analysis set {aset['name']} is pending {aset['pending']}; a test analysis cannot use it")
    m = RG.restrict(matrix, aset)
    bench_of = RG.bench_map(aset)
    results = []
    for model in (args.models or m.models()):
        results += compare(m, args.a, args.b, model, args.outcome, bench_of, aset["reference"], n_boot, seed, level)
    for r in results:
        r.pop("_exact", None)
    return {"schema": SCHEMA, "data": m.label, "generated_by": "analysis/r1/paired.py", "outcome": args.outcome,
            "a": args.a, "b": args.b, "analysis_set": m.header["analysis_set"], "prereg": pr.provenance(),
            "inputs": {k: m.header[k] for k in ("registry", "superseded", "runs", "freeze_gate")},
            "results": results}


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--registry", default=RG.DEFAULT_REGISTRY)
    ap.add_argument("--superseded", default=RG.DEFAULT_SUPERSEDED)
    ap.add_argument("--prereg", default=PR.DEFAULT_PATH)
    ap.add_argument("--set", default=None)
    ap.add_argument("--incl-0905", action="store_true", help="sensitivity: add the 2026-09-05-viewed cases back")
    ap.add_argument("--allow-pending", action="store_true", help="dev only: resolve pending set lists as empty")
    ap.add_argument("--outcome", default="correct")
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--n-boot", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default=None, help="output .json (a .md and a .csv are written next to it)")
    return ap


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        doc = run(a)
    except AnalysisError as x:
        print(f"[paired] REFUSED: {x}", file=sys.stderr)
        return 2
    md = render_md(doc)
    if a.out:
        out = labelled_path(a.out, doc["data"])
        write_text(out, dumps(doc))
        write_text(os.path.splitext(out)[0] + ".md", md)
        write_text(os.path.splitext(out)[0] + ".csv", csv_text(doc["results"]))
        print(f"[paired] {doc['data']}: {len(doc['results'])} rows -> {rel(out)}")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Holm step-down correction over the pre-registered comparison families (E20a).

  $PY analysis/r1/holm.py --paired paired.main.json [paired.other.json ...] [--prereg configs/prereg_analysis.json]
                          [--allow-pending] [--out holm.json]

Families come from the pre-registered item holm_families (configs/prereg_analysis.json): each family lists its
comparisons {id, a, b, model, outcome, analysis_set, scope} and its alpha. The p-value of a comparison is the exact
McNemar p of the matching row of a paired.py output. Gated tests (item gated_tests) follow as a fixed sequence: a
gated comparison is tested, at its own alpha, only when its gate comparison was rejected; otherwise its row is
reported as an estimate. The one-sided direction is fixed: a gated test rejects only for a positive difference.
The p-value of a comparison is the exact McNemar p of the matching row of a paired.py output (same labels, model, outcome, set and scope). Every comparison of
a family must be found exactly once, and all of a family's rows must carry the same data label; otherwise the family
is refused (a family is never corrected over a subset of its members).

Holm (1979): order the m p-values p(1) <= ... <= p(m); adjusted p(i) = max over j <= i of min(1, (m - j + 1) p(j));
reject H(i) when its adjusted p <= alpha (equivalently, step down while p(i) <= alpha / (m - i + 1)).
Ties keep the family's listed order. Standard library only.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import prereg as PR  # noqa: E402
from common import AnalysisError, dumps, labelled_path, md_header, p4, rel, write_text  # noqa: E402

SCHEMA = "orgene.r1.holm.v1"


def holm(pvalues, alpha=0.05):
    """pvalues: list of (name, p). Returns [{name, p, rank, p_adj, reject}] in the input order."""
    if not pvalues:
        raise AnalysisError("an empty family")
    for name, p in pvalues:
        if not isinstance(p, (int, float)) or not 0.0 <= p <= 1.0:
            raise AnalysisError(f"{name}: p-value {p!r} outside [0, 1]")
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: (pvalues[i][1], i))
    adj = [None] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i][1]))
        adj[i] = running
    ranks = {i: r + 1 for r, i in enumerate(order)}
    return [{"name": pvalues[i][0], "p": pvalues[i][1], "rank": ranks[i], "p_adj": adj[i], "reject": adj[i] <= alpha}
            for i in range(m)]


def _key(c):
    return (c["a"], c["b"], c["model"], c["outcome"], c["analysis_set"], c["scope"])


def index_paired(docs):
    """{(a, b, model, outcome, set, scope): (row, data label)} from paired.py outputs; duplicates are refused."""
    idx = {}
    for d in docs:
        for r in d["results"]:
            k = (r["a"], r["b"], r["model"], r["outcome"], d["analysis_set"]["name"], r["scope"])
            if k in idx:
                raise AnalysisError(f"comparison {k} appears in two paired outputs")
            idx[k] = (r, d["data"])
    return idx


def correct_families(families, idx):
    out = []
    for f in families:
        rows, labels = [], set()
        missing = [c["id"] for c in f["comparisons"] if _key(c) not in idx]
        if missing:
            raise AnalysisError(f"family {f['id']}: no paired result for {missing}; a family is corrected over all "
                                "of its members or not at all")
        for c in f["comparisons"]:
            r, lab = idx[_key(c)]
            labels.add(lab)
            rows.append((c["id"], r["mcnemar_exact_p"]))
        if len(labels) != 1:
            raise AnalysisError(f"family {f['id']} mixes data labels {sorted(labels)}")
        res = holm(rows, f["alpha"])
        for c, h in zip(f["comparisons"], res):
            r, _ = idx[_key(c)]
            h.update({"a": c["a"], "b": c["b"], "model": c["model"], "scope": c["scope"],
                      "analysis_set": c["analysis_set"], "diff": r.get("diff"), "ci": r.get("ci")})
        out.append({"family": f["id"], "alpha": f["alpha"], "m": len(res), "data": labels.pop(), "results": res})
    return out


def gated_results(gated, families, idx):
    """Fixed-sequence tests: each is read only when its gate comparison was rejected in its (one-member) family.
    Not tested: the row is still reported with its estimate, marked as an estimate only."""
    rej = {h["name"]: h["reject"] for f in families for h in f["results"]}
    out = []
    for g in gated:
        c = g["comparison"]
        if g["gate"] not in rej:
            raise AnalysisError(f"gated test {g['id']}: its gate {g['gate']} has no result")
        if _key(c) not in idx:
            raise AnalysisError(f"gated test {g['id']}: no paired result for {c['id']}")
        r, _ = idx[_key(c)]
        tested = bool(rej[g["gate"]])
        p = r["mcnemar_exact_p"]
        out.append({"id": g["id"], "gate": g["gate"], "gate_rejected": tested, "tested": tested, "alpha": g["alpha"],
                    "comparison": c["id"], "a": c["a"], "b": c["b"], "model": c["model"], "scope": c["scope"],
                    "p": p if tested else None, "reject": bool(tested and p <= g["alpha"] and (r.get("diff") or 0) > 0),
                    "diff": r.get("diff"), "ci": r.get("ci"),
                    "reading": "confirmatory" if tested else "estimate only (gate not rejected)"})
    return out


def render_md(doc):
    lines = [md_header("Holm correction per pre-registered family", doc["data"])]
    for f in doc["families"]:
        lines += ["", f"## {f['family']} (m = {f['m']}, alpha = {f['alpha']})", "",
                  "| comparison | a vs b | p | Holm p | reject |", "|---|---|---|---|---|"]
        lines += [f"| {h['name']} | {h['a']} vs {h['b']} | {p4(h['p'])} | {p4(h['p_adj'])} | {h['reject']} |"
                  for h in f["results"]]
    if doc.get("gated"):
        lines += ["", "## gated tests (fixed sequence)", "", "| test | gate | gate rejected | a vs b | diff | p | reject | reading |",
                  "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {g['id']} | {g['gate']} | {g['gate_rejected']} | {g['a']} vs {g['b']} | {g['diff']} | "
                  f"{p4(g['p']) if g['p'] is not None else 'n/a'} | {g['reject']} | {g['reading']} |" for g in doc["gated"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paired", nargs="+", required=True)
    ap.add_argument("--prereg", default=PR.DEFAULT_PATH)
    ap.add_argument("--allow-pending", action="store_true", help="dev only: use the proposed families")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    try:
        docs = [json.load(open(p, encoding="utf-8")) for p in a.paired]
        labels = {d["data"] for d in docs}
        if len(labels) != 1:
            raise AnalysisError(f"paired outputs of several data labels {sorted(labels)}")
        label = labels.pop()
        pr = PR.load(a.prereg)
        fams = pr.get("holm_families", allow_pending=a.allow_pending and label == "DEV")
        idx = index_paired(docs)
        # dev with --allow-pending only: families without results are skipped (listed as skipped). Any other analysis
        # (test data, or no --allow-pending) corrects every pre-registered family and refuses an incomplete one.
        if a.allow_pending and label == "DEV":
            present = [f for f in fams if all(_key(c) in idx for c in f["comparisons"])]
        else:
            present = fams
        doc = {"schema": SCHEMA, "data": label, "generated_by": "analysis/r1/holm.py", "prereg": pr.provenance(),
               "inputs": [rel(os.path.abspath(p)) for p in a.paired],
               "families": correct_families(present, idx),
               "skipped_families": sorted(f["id"] for f in fams if f not in present)}
        gated = pr.get("gated_tests", allow_pending=a.allow_pending and label == "DEV")
        if a.allow_pending and label == "DEV":  # dev: a gated test without its rows is skipped, like a family
            done = {h["name"] for f in doc["families"] for h in f["results"]}
            gated = [g for g in gated if g["gate"] in done and _key(g["comparison"]) in idx]
        doc["gated"] = gated_results(gated, doc["families"], idx)
    except AnalysisError as x:
        print(f"[holm] REFUSED: {x}", file=sys.stderr)
        return 2
    md = render_md(doc)
    if a.out:
        out = labelled_path(a.out, doc["data"])
        write_text(out, dumps(doc))
        write_text(os.path.splitext(out)[0] + ".md", md)
        print(f"[holm] {doc['data']}: {len(doc['families'])} families -> {rel(out)}")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

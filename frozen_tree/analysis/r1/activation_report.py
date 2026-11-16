#!/usr/bin/env python3
"""Per-gene activation rates, and the dev case ids a gene author needs to check the activation rules (E04).

  /opt/homebrew/bin/python3 analysis/r1/activation_report.py \
      [--cases data/cases/mamo_complex_lp.jsonl data/cases/industryor.jsonl] [--splits data/splits] \
      [--genes genes/genes.r1.jsonl] [--lexicon genes/activation_lexicon.v1.json] \
      [--analysis-sets data/analysis_sets/analysis_sets.json] \
      [--validated experiments/<dev-run>/validated.<COND>.round0.jsonl ...] [--out report.json] [--md report.md]

Dev (default). Every dev case of every split under --splits (only dev ids are loaded). Features come from the
problem statement only (runtime/orgene/features.py). Columns:
  dev_main     dev cases of the primary analysis sets (MAMO cleaned 30 + IndustryOR 25 = 55): the only source of
               right/wrong signals for gene work
  dev_removed  the other dev cases (the 30 MAMO dev cases dropped by the cleaning): error types only
  Without an analysis-sets file there is a single column, dev_all.
Per gene and column: activation rate (rule true), and with --validated
  missed_activation    dev case ids where the gene's predicate failed but its rule is false
  active_never_failed  dev case ids where the rule is true and the predicate was checked but never failed
--validated must come from a dev run in which every in-scope gene was checked (activation mode "all", e.g. C3L-ALL,
or runs made before E04); a gene not checked on a case counts as not evaluated there. A validated file under a
*-test-* run directory, or containing a test case id, is refused.

Test (--split test --after-freeze): per-gene activation rates only (no case ids, no features, no failures), and only
when the freeze manifest exists. Before the freeze gate this mode refuses to run.
No problem text is printed in either mode. Input paths may be given relative to the repository root; --out and --md
are written where given.
"""
import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene import features as F  # noqa: E402
from orgene import genes as G  # noqa: E402
from orgene.paths import rel, resolve  # noqa: E402

DEFAULT_SETS = os.path.join(ROOT, "data", "analysis_sets", "analysis_sets.json")
DEFAULT_FREEZE = os.path.join(ROOT, "FREEZE_MANIFEST.json")


def sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                if not rec.get("_header"):
                    out.append(rec)
    return out


def load_split_ids(splits_dir):
    dev, test = set(), set()
    for name in sorted(os.listdir(splits_dir)):
        d = os.path.join(splits_dir, name)
        if not os.path.isfile(os.path.join(d, "dev_ids.json")):
            continue
        with open(os.path.join(d, "dev_ids.json"), encoding="utf-8") as f:
            dev |= set(json.load(f))
        with open(os.path.join(d, "test_ids.json"), encoding="utf-8") as f:
            test |= set(json.load(f))
    if dev & test:
        raise SystemExit("dev and test ids overlap in " + rel(splits_dir))
    return dev, test


def load_cases(paths, ids):
    cases = {}
    for p in paths:
        for rec in read_jsonl(p):
            if rec["case_id"] in ids:
                cases[rec["case_id"]] = rec
    return cases


def main_dev_ids(sets_path):
    """Union of the dev ids of each benchmark's primary analysis set (schema orgene-eaai-r1/analysis_sets/v2)."""
    with open(sets_path, encoding="utf-8") as f:
        doc = json.load(f)
    ids = set()
    for bench, set_name in sorted(doc["primary_sets"].items()):
        ids |= set(doc["sets"][set_name]["dev"])
    return ids


def load_failures(paths, test_ids):
    """(case_id, geneId) -> {"evaluated": bool, "failed": bool} from validated.*.jsonl records."""
    out = {}
    for p in paths:
        # any directory on the path (not only the parent) named like a test run; checked before the file is opened
        if any("-test-" in part for part in os.path.dirname(os.path.abspath(p)).split(os.sep)):
            raise SystemExit(f"refusing a validated file from a test run: {rel(p)}")
        for rec in read_jsonl(p):
            cid = rec.get("case_id")
            if cid in test_ids:
                raise SystemExit(f"refusing {rel(p)}: it contains a test case id")
            for iss in rec.get("issues") or []:
                d = out.setdefault((cid, iss.get("geneId")), {"evaluated": False, "failed": False})
                if iss.get("ok") is not None:
                    d["evaluated"] = True
                if iss.get("ok") is False:
                    d["failed"] = True
    return out


def _rate(k, n):
    return round(k / n, 4) if n else None


def dev_report(a):
    dev_ids, test_ids = load_split_ids(a.splits)
    cases = load_cases(a.cases, dev_ids)
    lex = F.load_lexicon(a.lexicon)
    store = G.load_store(a.genes, lexicon=lex)
    feats = {cid: F.extract_features(c["text"], lex) for cid, c in sorted(cases.items())}
    sets_path = a.analysis_sets if a.analysis_sets else (DEFAULT_SETS if os.path.exists(DEFAULT_SETS) else None)
    if sets_path:
        main = main_dev_ids(sets_path) & set(cases)
        columns = {"dev_main": sorted(main), "dev_removed": sorted(set(cases) - main)}
    else:
        columns = {"dev_all": sorted(cases)}
    fails = load_failures(a.validated or [], test_ids)
    report = {
        "split": "dev", "genes": rel(a.genes), "genes_file_sha256": sha_file(a.genes),
        "lexicon": lex.path, "lexicon_sha256": lex.sha256, "analysis_sets": rel(sets_path) if sets_path else None,
        "validated": [rel(p) for p in a.validated or []],
        "columns": {k: len(v) for k, v in columns.items()},
        "feature_prevalence": {}, "genes_report": [],
    }
    for col, ids in columns.items():
        prev = {}
        for name, typ in sorted(lex.types.items()):
            vals = [feats[c][name] for c in ids]
            if typ == "bool":
                prev[name] = {"rate": _rate(sum(vals), len(vals))}
            else:
                prev[name] = {"mean": round(sum(vals) / len(vals), 2) if vals else None}
        report["feature_prevalence"][col] = prev
    for g in store:
        rule = F.gene_rule(g)
        row = {"geneId": g["geneId"], "version": g["version"], "lifecycle": g["lifecycle"].get("state"),
               "scope": g.get("scope", {}).get("conditions"), "severity": g["validation"].get("severity"),
               "rule": rule, "features_used": sorted(F.rule_features(rule)), "columns": {}}
        for col, ids in columns.items():
            active = [c for c in ids if F.eval_rule(rule, feats[c])]
            cell = {"n": len(ids), "n_active": len(active), "activation_rate": _rate(len(active), len(ids))}
            if a.validated:
                ev = {c: fails.get((c, g["geneId"]), {"evaluated": False, "failed": False}) for c in ids}
                cell["n_evaluated"] = sum(1 for c in ids if ev[c]["evaluated"])
                cell["n_failed"] = sum(1 for c in ids if ev[c]["failed"])
                cell["missed_activation"] = [c for c in ids if ev[c]["failed"] and c not in active]
                cell["active_never_failed"] = [c for c in active if ev[c]["evaluated"] and not ev[c]["failed"]]
            row["columns"][col] = cell
        report["genes_report"].append(row)
    return report


def test_rates(a):
    if not a.after_freeze or not os.path.exists(a.freeze_manifest):
        raise SystemExit("test mode runs only after the freeze gate (--after-freeze and an existing freeze manifest)")
    if a.validated:
        raise SystemExit("test mode reports activation rates only; --validated is not accepted")
    _, test_ids = load_split_ids(a.splits)
    cases = load_cases(a.cases, test_ids)
    lex = F.load_lexicon(a.lexicon)
    store = G.load_store(a.genes, lexicon=lex)
    n = len(cases)
    rows = []
    for g in store:
        rule = F.gene_rule(g)
        k = sum(1 for c in cases.values() if F.eval_rule(rule, F.extract_features(c["text"], lex)))
        rows.append({"geneId": g["geneId"], "version": g["version"], "activation_rate": _rate(k, n)})
    return {"split": "test", "genes": rel(a.genes), "genes_file_sha256": sha_file(a.genes),
            "lexicon": lex.path, "lexicon_sha256": lex.sha256, "n": n, "genes_report": rows}


def to_markdown(rep):
    lines = [f"# Gene activation report ({rep['split']})", "",
             f"genes `{rep['genes']}` sha256 `{rep['genes_file_sha256'][:16]}`; lexicon `{rep['lexicon']}` "
             f"sha256 `{rep['lexicon_sha256'][:16]}`", ""]
    if rep["split"] == "test":
        lines += [f"n = {rep['n']}", "", "| gene | version | activation rate |", "|---|---|---|"]
        lines += [f"| {r['geneId']} | {r['version']} | {r['activation_rate']} |" for r in rep["genes_report"]]
        return "\n".join(lines) + "\n"
    cols = list(rep["columns"])
    lines.append("columns: " + ", ".join(f"{c} (n={rep['columns'][c]})" for c in cols))
    lines += ["", "| gene | rule features | " + " | ".join(f"{c} rate" for c in cols) + " |",
              "|---|---|" + "---|" * len(cols)]
    for r in rep["genes_report"]:
        rates = " | ".join(str(r["columns"][c]["activation_rate"]) for c in cols)
        lines.append(f"| {r['geneId']} | {', '.join(r['features_used']) or 'always'} | {rates} |")
    if rep["validated"]:
        lines += ["", "## Missed activations and active-but-never-failed cases", ""]
        for r in rep["genes_report"]:
            for c in cols:
                cell = r["columns"][c]
                if cell.get("missed_activation") or cell.get("active_never_failed"):
                    lines.append(f"- {r['geneId']} [{c}] evaluated {cell['n_evaluated']}, failed {cell['n_failed']}; "
                                 f"missed: {', '.join(cell['missed_activation']) or '-'}; "
                                 f"active never failed: {len(cell['active_never_failed'])}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", nargs="+", default=["data/cases/mamo_complex_lp.jsonl", "data/cases/industryor.jsonl"])
    ap.add_argument("--splits", default="data/splits")
    ap.add_argument("--genes", default="genes/genes.r1.jsonl")
    ap.add_argument("--lexicon", default="genes/activation_lexicon.v1.json")
    ap.add_argument("--analysis-sets", default=None,
                    help="analysis_sets.json (default data/analysis_sets/analysis_sets.json when present)")
    ap.add_argument("--validated", nargs="*", default=None)
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--after-freeze", action="store_true")
    ap.add_argument("--freeze-manifest", default=DEFAULT_FREEZE)
    ap.add_argument("--out", default=None)
    ap.add_argument("--md", default=None)
    a = ap.parse_args(argv)
    a.cases = [resolve(p) for p in a.cases]
    a.splits, a.genes, a.lexicon = resolve(a.splits), resolve(a.genes), resolve(a.lexicon)
    a.analysis_sets = resolve(a.analysis_sets) if a.analysis_sets else None
    a.validated = [resolve(p) for p in a.validated] if a.validated else None
    a.freeze_manifest = resolve(a.freeze_manifest)
    rep = test_rates(a) if a.split == "test" else dev_report(a)
    text = json.dumps(rep, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(to_markdown(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())

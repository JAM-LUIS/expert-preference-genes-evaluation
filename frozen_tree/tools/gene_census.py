#!/usr/bin/env python3
"""Gene provenance table (todo 1C / E20; preregistration section 6.2), from the gene library alone.

  /opt/homebrew/bin/python3 tools/gene_census.py [--genes genes/genes.it1.jsonl] [--out configs/gene_provenance.json] [--check]

One row per gene: id, version, lifecycle, source type as recorded (seed_structural / dev_failure_derived), the
provenance class of section 6.2 (seed_unrevised: a seed gene at its first version; seed_dev_revised: a seed gene
whose record supersedes an earlier version; dev_derived: drafted from dev failures), the dev case ids consulted
(dev only; recorded by the library), the predicate and severity, the function class
(configs/gene_function_classes.json), and the activation mode. Counts per class are included. --check rebuilds the
table and compares it byte for byte with the committed file. Prints counts only.
"""
import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SCHEMA = "orgene-r1/gene_provenance/v1"


def load_genes(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(json.loads(line))
    return out


def provenance_class(g):
    src = g["audit"].get("sourceType")
    if src == "dev_failure_derived":
        return "dev_derived"
    if src == "seed_structural":
        return "seed_dev_revised" if g["lifecycle"].get("supersedes") else "seed_unrevised"
    raise ValueError(f"{g['geneId']}: unknown sourceType {src!r}")


def build(genes_path, classes_path):
    genes = load_genes(genes_path)
    classes = json.load(open(classes_path, encoding="utf-8"))
    cmap = classes.get("classes", classes)
    rows = []
    for g in genes:
        v = g.get("validation", {})
        rows.append({
            "geneId": g["geneId"], "version": g["version"], "lifecycle_state": g["lifecycle"].get("state"),
            "supersedes": g["lifecycle"].get("supersedes", []), "createdAt": g["audit"].get("createdAt"),
            "sourceType": g["audit"].get("sourceType"), "provenance_class": provenance_class(g),
            "devCaseIds": sorted(g["audit"].get("devCaseIds") or []),
            "predicateId": v.get("predicateId"), "severity": v.get("severity"), "mode": v.get("mode"),
            "function_class": (cmap.get(g["geneId"]) if isinstance(cmap.get(g["geneId"]), str)
                               else (cmap.get(g["geneId"]) or {}).get("class") if isinstance(cmap.get(g["geneId"]), dict) else None),
            "activation": (g.get("activation") or {}).get("mode", "always"),
        })
    counts = {}
    for r in rows:
        counts[r["provenance_class"]] = counts.get(r["provenance_class"], 0) + 1
    sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()  # noqa: E731
    return {"schema": SCHEMA, "library": {"path": os.path.relpath(genes_path, ROOT), "sha256": sha(genes_path)},
            "function_classes": {"path": os.path.relpath(classes_path, ROOT), "sha256": sha(classes_path)},
            "n_genes": len(rows), "counts_by_class": counts, "genes": rows}


def render(doc):
    return (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--genes", default="genes/genes.it1.jsonl")
    ap.add_argument("--classes", default="configs/gene_function_classes.json")
    ap.add_argument("--out", default="configs/gene_provenance.json")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    body = render(build(os.path.join(ROOT, a.genes), os.path.join(ROOT, a.classes)))
    out = os.path.join(ROOT, a.out)
    if a.check:
        ok = os.path.exists(out) and open(out, "rb").read() == body
        print(f"RESULT: {'PASS' if ok else 'FAIL'} ({a.out} {'equals' if ok else 'differs from'} a fresh census)")
        return 0 if ok else 1
    with open(out, "wb") as f:
        f.write(body)
    doc = json.loads(body)
    print(f"genes {doc['n_genes']}, by class {doc['counts_by_class']}; wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

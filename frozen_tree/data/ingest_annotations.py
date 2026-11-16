#!/usr/bin/env python3
"""Ingest the text-free annotation summaries into R1 (E14): type labels, reference overrides, exclusions.

  $ORGENE_PY data/ingest_annotations.py --type type_final_labels.csv
  $ORGENE_PY data/ingest_annotations.py --ref ref_check.csv --sample reference_check_sample.json
  (both can be given in one call; --strict refuses pending or invalid rows; --dry-run writes nothing)

Inputs are the outputs of the stage-1 collection script (ids, closed-vocabulary labels and numbers only; the filled
sheets with problem statements are never read here). Writes, relative to the repository root:
  data/labels/industryor_type.json
  data/reference_overrides/<source>.json   E13 format, built and validated by runtime/orgene/refs.py; written only
                                           when every sampled case is settled (until then scoring keeps the
                                           original references and the sets that depend on Q3 stay pending)
  data/exclusions_r1.json                  nl_not_linearizable and q3_removed with their status
A part not given in this call keeps its previous content in data/exclusions_r1.json. If an override file cannot be
built, nothing at all is written. Rules: runtime/orgene/annotations.py (Q3, D5). Prints counts and case ids only.
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene import analysis_sets as A  # noqa: E402
from orgene import annotations as N  # noqa: E402
from orgene.paths import resolve  # noqa: E402

TYPE_SET = "industryor_main_rev2026_100"


def cases_paths(root, sources):
    out = {}
    for src in sources:
        lock = json.load(open(resolve(os.path.join(A.SPLITS_DIR, src, "SPLIT_LOCK.json"), root), encoding="utf-8"))
        out[src] = resolve(lock["cases_path"], root)
    return out


def build_override_docs(entries, paths):
    """{source: validated E13 override document}; raises AnnotationError without runtime/orgene/refs.py."""
    try:
        from orgene import refs
    except ImportError:
        raise N.AnnotationError("reference-override files are built by runtime/orgene/refs.py (E13), which is not in "
                                "this tree; nothing written") from None
    return {src: refs.build_overrides_doc(src, paths[src], ents) for src, ents in sorted(entries.items())}, refs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    ap.add_argument("--type", dest="type_csv", default=None, help="type_final_labels.csv")
    ap.add_argument("--ref", dest="ref_csv", default=None, help="ref_check.csv")
    ap.add_argument("--sample", default=None, help="reference_check_sample.json (required with --ref)")
    ap.add_argument("--date", default=None, help="record date YYYY-MM-DD (default: today)")
    ap.add_argument("--strict", action="store_true", help="fail on any pending or invalid row")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not a.type_csv and not a.ref_csv:
        ap.error("give --type and/or --ref")
    if a.ref_csv and not a.sample:
        ap.error("--ref needs --sample")
    root = a.root
    id_sets = A.load_id_sets(None, root)

    labels_doc = ref_res = None
    docs, refs = {}, None
    if a.type_csv:
        s = id_sets["sets"][TYPE_SET]
        expected = {c: side for side in A.SIDES for c in s[side]}
        labels_doc = N.ingest_type_labels(a.type_csv, expected, strict=a.strict)
        print(f"[type] final {labels_doc['n_final']}/{labels_doc['n_expected']}  counts {labels_doc['counts']}")
        print(f"[type] NL_NOT_LINEARIZABLE: {' '.join(labels_doc['nl_not_linearizable']) or '(none)'}")
        print(f"[type] LINEAR_UNRESOLVED: {' '.join(labels_doc['linear_unresolved']) or '(none)'}")
        print(f"[type] pending {len(labels_doc['pending'])}: {' '.join(labels_doc['pending'])}")
        for p in labels_doc["problems"]:
            print("  -", p)
    if a.ref_csv:
        sample = json.load(open(a.sample, encoding="utf-8"))
        paths = cases_paths(root, sorted({r["benchmark"] for r in sample["rows"]}))
        originals = N.originals_from_cases(paths.values())
        ref_res = N.ingest_reference_checks(a.ref_csv, sample, originals, date=a.date, strict=a.strict,
                                            sample_sha256=N.sha256_path(a.sample))
        print(f"[ref] verdicts {ref_res['counts']}")
        print("[ref] entries " + ", ".join(f"{k} {len(v)}" for k, v in ref_res["entries"].items()))
        print(f"[ref] q3_removed {len(ref_res['q3']['ids'])}: {' '.join(ref_res['q3']['ids'])}")
        print(f"[ref] pending {len(ref_res['pending'])}: {' '.join(ref_res['pending'])}")
        for p in ref_res["problems"]:
            print("  -", p)
        if ref_res["final"]:
            docs, refs = build_override_docs(ref_res["entries"], paths)
        else:
            print("[ref] not settled yet: override files are not written, q3_removed stays pending")

    ex_path = resolve(N.EXCLUSIONS_PATH, root)
    ex = N.build_exclusions(labels_doc, ref_res, date=a.date)
    if os.path.exists(ex_path):
        old = json.load(open(ex_path, encoding="utf-8"))
        for part, given in (("nl_not_linearizable", labels_doc), ("q3_removed", ref_res)):
            if given is None and part in old:
                ex[part] = old[part]
                print(f"[exclusions] {part}: kept from the existing file (status {old[part].get('status')})")
    if a.dry_run:
        print("dry run: nothing written")
        return 0
    if labels_doc is not None:
        N.write_json(resolve(N.LABELS_PATH, root), labels_doc)
        print("wrote", N.LABELS_PATH)
    for src, doc in docs.items():
        rel_path = f"{N.OVERRIDES_DIR}/{src}.json"
        sha = refs.write_overrides(doc, resolve(rel_path, root))
        print("wrote", rel_path, sha[:16])
    N.write_json(ex_path, ex)
    print("wrote", N.EXCLUSIONS_PATH, f"(nl_not_linearizable {ex['nl_not_linearizable']['status']}, "
                                      f"q3_removed {ex['q3_removed']['status']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

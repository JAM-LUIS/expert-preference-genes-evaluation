#!/usr/bin/env python3
"""Stratified results: by benchmark, scale tertile (cut points from dev), IndustryOR difficulty and type label (E20a;
todo A1-22).

  $PY analysis/r1/strata.py --a C3L@2 --b C3E@2 --by benchmark scale difficulty type [--registry ...] [--set main]
      [--scale-feature n_tokens (dev only while pending)] [--no-bootstrap] --out strata.json

Stratum of a case:
  benchmark   the case's benchmark
  scale       tertile 0 / 1 / 2 of the pre-registered scale feature, as data/features/scale_features.json records it
              (analysis/r1/scale_features.py: per benchmark, cut points from the frozen dev cases only). A test
              analysis also checks the file's sha256 against the pre-registered item strata_scale_cutpoints.
  difficulty  IndustryOR `extra.difficulty` of the case record (Easy / Medium / Hard); only that field is kept,
              and only for the cases of the analysis set; MAMO cases get "n/a"
  type        adjudicated IndustryOR type label (data/labels/industryor_type.json, effective_type); MAMO "n/a";
              LINEAR_UNRESOLVED cases (linear, class not settled) are left out of the type strata (PREREG_R1)
Per stratum and model: n, accuracy of A and B, difference, wins / ties / losses, exact McNemar p and (unless
--no-bootstrap) the case bootstrap CI, from paired.py. Cases without a stratum value are counted under "missing".
Standard library only.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import paired as PA  # noqa: E402
import prereg as PR  # noqa: E402
import registry as RG  # noqa: E402
from common import (ROOT, AnalysisError, dumps, labelled_path, md_header, p4, pct1, rel, resolve,  # noqa: E402
                    sha256_file, signed_pp, write_text)

SCHEMA = "orgene.r1.strata.v1"
KINDS = ("benchmark", "scale", "difficulty", "type")
SCALE_FILE = "data/features/scale_features.json"
MISSING = "missing"
NA = "n/a"
LINEAR_UNRESOLVED = "LINEAR_UNRESOLVED"


def scale_strata(ids, feature, path=None, root=None, expect_sha256=None):
    p = resolve(path or SCALE_FILE, root or ROOT)
    if not os.path.exists(p):
        raise AnalysisError(f"{rel(p)} not found (analysis/r1/scale_features.py writes it)")
    if expect_sha256 and sha256_file(p) != expect_sha256:
        raise AnalysisError(f"{rel(p)} differs from the pre-registered scale features file")
    doc = json.load(open(p, encoding="utf-8"))
    feats = doc.get("features") or {}
    out = {}
    for c in ids:
        s = ((feats.get(c) or {}).get("strata") or {}).get(feature)
        out[c] = MISSING if s is None else f"T{int(s) + 1}"
    return out, {"file": rel(p), "sha256": sha256_file(p), "feature": feature, "cutpoints": {
        b: (v or {}).get(feature) for b, v in (doc.get("cutpoints") or {}).items()}}


def difficulty_strata(ids, bench_of, cases_path, levels=None):
    """{case: difficulty} for the IndustryOR cases in `ids` (only the difficulty field of those records is kept)."""
    want = {c for c in ids if bench_of.get(c) == "industryor"}
    out = {c: NA for c in ids if c not in want}
    with open(cases_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            cid = r.get("case_id")
            if r.get("_header") or cid not in want:
                continue
            v = (r.get("extra") or {}).get("difficulty")
            out[cid] = v if v and (levels is None or v in levels) else MISSING
    for c in want:
        out.setdefault(c, MISSING)
    return out


def type_strata(ids, bench_of, labels_path, field="effective_type"):
    doc = json.load(open(labels_path, encoding="utf-8")) if os.path.exists(labels_path) else {}
    labels = doc.get("labels") or {}
    out, dropped = {}, 0
    for c in ids:
        if bench_of.get(c) != "industryor":
            out[c] = NA
        elif (labels.get(c) or {}).get("type") == LINEAR_UNRESOLVED:
            dropped += 1                                # registered rule: dropped only from type strata
        else:
            out[c] = (labels.get(c) or {}).get(field) or MISSING
    return out, {"file": rel(labels_path), "status": doc.get("status", "missing"),
                 "sha256": sha256_file(labels_path) if os.path.exists(labels_path) else None,
                 "n_linear_unresolved_dropped": dropped}


def stratified(matrix, a, b, model, stratum_of, outcome="correct", reference_kind="r1", bootstrap=True,
               n_boot=10000, seed=1, level=0.95, bench_of=None):
    """Per stratum paired summaries; stratum_of: {case_id: stratum}."""
    field, tier = PA.outcome_field(outcome, reference_kind)
    pa, _ = PA.per_case(matrix.select(model, a), field, tier)
    pb, _ = PA.per_case(matrix.select(model, b), field, tier)
    groups = {}
    for c, s in stratum_of.items():
        groups.setdefault(s, []).append(c)
    out = []
    for s in sorted(groups):
        cases = groups[s]
        bo = bench_of or {c: "all" for c in cases}
        benches = {bo[c] for c in cases}
        r = PA.compare_cases(pa, pb, cases, bo, n_boot if bootstrap else 1, seed, level, stratify=len(benches) > 1)
        r.pop("_exact", None)
        if not bootstrap:
            r["ci"], r["n_boot"] = None, 0
        r.update({"model": model, "a": a, "b": b, "stratum": s, "n_benchmarks": len(benches)})
        out.append(r)
    return out


def run(args, matrix=None, aset=None, prereg=None, root=None):
    root = root or ROOT
    pr = prereg or PR.load(args.prereg)
    if matrix is None:
        reg = RG.load_registry(args.registry, superseded_path=args.superseded)
        matrix = RG.build_matrix(reg, labels=[args.a, args.b], models=args.models)
    dev = matrix.label == "DEV"
    boot = pr.get("bootstrap", allow_pending=dev)
    if aset is None:
        name = RG.set_name_for(matrix.label, args.set, args.incl_0905)
        aset = RG.resolve_set(name, allow_pending=args.allow_pending and dev)
    m = RG.restrict(matrix, aset)
    bench_of = RG.bench_map(aset)
    ids = sorted(bench_of)
    sources, maps = {}, {}
    for kind in args.by:
        if kind == "benchmark":
            maps[kind] = dict(bench_of)
        elif kind == "scale":
            feat = pr.get("strata_scale_feature", allow_pending=dev, override=args.scale_feature)
            expect = None
            if not dev:
                expect = pr.get("strata_scale_cutpoints")["file_sha256"]
            maps[kind], sources[kind] = scale_strata(ids, feat, args.scale_file, root, expect)
        elif kind == "difficulty":
            cfg = pr.get("strata_industryor_difficulty")
            cases_path = resolve(args.industryor_cases, root)
            maps[kind] = difficulty_strata(ids, bench_of, cases_path, cfg.get("levels"))
            sources[kind] = {"file": rel(cases_path), "field": cfg.get("field"), "levels": cfg.get("levels")}
        elif kind == "type":
            cfg = pr.get("strata_type_labels")
            maps[kind], sources[kind] = type_strata(ids, bench_of, resolve(cfg["file"], root), cfg["field"])
        else:
            raise AnalysisError(f"unknown stratification {kind!r}")
    res = {}
    for kind, smap in maps.items():
        res[kind] = []
        for model in (args.models or m.models()):
            res[kind] += stratified(m, args.a, args.b, model, smap, args.outcome, aset["reference"],
                                    not args.no_bootstrap, args.n_boot or boot["n_boot"],
                                    boot["seed"] if args.seed is None else args.seed, boot.get("ci_level", 0.95),
                                    bench_of)
    return {"schema": SCHEMA, "data": m.label, "generated_by": "analysis/r1/strata.py", "a": args.a, "b": args.b,
            "outcome": args.outcome, "analysis_set": m.header["analysis_set"], "prereg": pr.provenance(),
            "strata_sources": sources, "inputs": {k: m.header[k] for k in ("registry", "runs", "freeze_gate")},
            "results": res}


def render_md(doc):
    lines = [md_header(f"Stratified comparison {doc['a']} vs {doc['b']} ({doc['outcome']})", doc["data"])]
    for kind, rows in doc["results"].items():
        lines += ["", f"## by {kind}", "", "| model | stratum | n | acc A % | acc B % | A−B (pp) | W/T/L | McNemar p |",
                  "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {r['model']} | {r['stratum']} | {r['n']} | {pct1(r['acc_a'])} | {pct1(r['acc_b'])} | "
                  f"{signed_pp(r['diff'])} | {r['wins']}/{r['ties']}/{r['losses']} | {p4(r['mcnemar_exact_p'])} |"
                  for r in rows]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--by", nargs="+", default=["benchmark"], choices=KINDS)
    ap.add_argument("--registry", default=RG.DEFAULT_REGISTRY)
    ap.add_argument("--superseded", default=RG.DEFAULT_SUPERSEDED)
    ap.add_argument("--prereg", default=PR.DEFAULT_PATH)
    ap.add_argument("--set", default=None)
    ap.add_argument("--incl-0905", action="store_true")
    ap.add_argument("--allow-pending", action="store_true")
    ap.add_argument("--outcome", default="correct")
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--scale-feature", default=None, help="dev only while strata_scale_feature is pending")
    ap.add_argument("--scale-file", default=SCALE_FILE)
    ap.add_argument("--industryor-cases", default="data/cases/industryor.jsonl")
    ap.add_argument("--no-bootstrap", action="store_true")
    ap.add_argument("--n-boot", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    try:
        doc = run(a)
    except AnalysisError as x:
        print(f"[strata] REFUSED: {x}", file=sys.stderr)
        return 2
    md = render_md(doc)
    if a.out:
        out = labelled_path(a.out, doc["data"])
        write_text(out, dumps(doc))
        write_text(os.path.splitext(out)[0] + ".md", md)
        print(f"[strata] {doc['data']} -> {rel(out)}")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

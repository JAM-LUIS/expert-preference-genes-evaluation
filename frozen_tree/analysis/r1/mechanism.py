#!/usr/bin/env python3
"""Mechanism analysis of gene-guided repair (D12): round-0 strata, nested decomposition, detection and repair rates,
gains by function class, the conservative bound for the answer-distribution heuristic, per-gene detection.
  $PY analysis/r1/mechanism.py --l C3L@1 --e C3E@1 [--t C3T@1] [--a C3A@1] --round0-label C0 [--registry ...]
      [--set main | dev_signal55] [--allow-pending] [--models qwen3:8b] [--families families.json] --out mechanism.json

Labels: --l gene repair, --e generic repair, --t detection with generic content (C3T), --a forced review (C3A). All must
share round 0 with --round0-label (checked by round-0 content sha256, as shared_round0.py does). The same ladder point
should be used for every label (the gated test H2 reads the 1-round cut).

1. Strata, from the round-0 checks of the --l run only (unit records; nothing that happens after round 0 is used):
     N  no hard failure          P  only genes of the generic-repair scope fail
     X  both kinds fail          M  only other genes fail
2. Paired comparisons L-E (and, with --t, T-E and L-T), pooled and per stratum. With --t the nested decomposition
   d(L-E) = d(T-E) + d(L-T) holds case by case; the three bootstrap intervals use the same resamples.
3. Detection and repair per label, against the round-0 outcome: among cases wrong at round 0, detect = share repaired
   and repair_success = share of those that end correct; among cases correct at round 0, false_alarm = share repaired
   and break = share of those that end wrong. final = p0 + (1 - p0) d s - p0 f b (an accounting identity; the form is
   that of Yang et al. 2025 and, gated, Polat et al. 2026, Proposition 1; not a result of this analysis).
4. Gains of L over E by the function class of the genes applied in the first repair round (configs/
   gene_function_classes.json): a case counts under every class applied to it, and under `single_class` when all its
   applied genes share one class.
5. Conservative bound: for cases whose round-0 hard failures are only genes of class answer_distribution_heuristic,
   the outcome of L is replaced by that of E, and L-E is recomputed.
6. Per-gene detection at round 0: fires (hard or soft failure) on round-0-wrong and round-0-correct answers, with
   Wilson intervals; by gene and by function class.
7. Problem families (--families: {"case_family": {case: family}, "gene_source_families": {geneId: [family]}}): L-E for
   cases whose applied genes come from the case's own family, from other families, or from seeds only. Without the
   file this part is reported as pending.
Everything here is an estimate or a description; the only tests are the pre-registered ones (prereg H1 and gated H2),
whose p-values are those of the pooled rows `L_vs_E` and `L_vs_T`.
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
from common import (ROOT, AnalysisError, dumps, labelled_path, md_header, p4, pct1, r4, rel, resolve,  # noqa: E402
                    sha256_file, signed_pp, write_text)
from orgene.genes import GENERIC_LINE_FOR_PREDICATE  # noqa: E402

SCHEMA = "orgene.r1.mechanism.v1"
CLASSES_FILE = "configs/gene_function_classes.json"
CLASSES = ("protocol_execution", "coding_hygiene", "or_modelling", "answer_distribution_heuristic")
HEURISTIC = "answer_distribution_heuristic"
STRATA = ("N", "P", "X", "M")


def load_classes(path=None, root=None):
    p = resolve(path or CLASSES_FILE, root or ROOT)
    doc = json.load(open(p, encoding="utf-8"))
    cls = doc.get("classes") or {}
    bad = sorted(g for g, c in cls.items() if c not in CLASSES)
    if not cls or bad:
        raise AnalysisError(f"{rel(p)}: no classes, or classes outside {list(CLASSES)} for {bad[:3]}")
    return cls, {"file": rel(p), "sha256": sha256_file(p)}


def round0_records(reg, model, label, root=None):
    """{case_id: {hard, soft, generic, applied, fired}} from the unit records of `label` (repeat 0): the round-0 hard and
    soft failures, which of the hard failures belong to the generic-repair scope, the genes applied in the first repair
    round, and every gene whose check failed (hard or soft)."""
    root = root or ROOT
    out = {}
    for e in reg.runs:
        if e["model"] != model or e["label"] != label:
            continue
        d = RG.units_dir_of(resolve(e["path"], root), e["config"])
        if not d:
            raise AnalysisError(f"{label} / {e['benchmark']}: no unit records (the mechanism analysis needs the unit "
                                "executor's records of the gene-repair run)")
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json"):
                continue
            u = json.load(open(os.path.join(d, name), encoding="utf-8"))
            if u.get("schema_version") != RG.UNIT_SCHEMA or u.get("config_id") != e["config"] or int(u.get("repeat", 0)):
                continue
            r0 = u["rounds"][0]
            v = r0["validated"]
            pred = {i["geneId"]: i.get("predicateId") for i in v["issues"]}
            hard = sorted(v["hard_failed_genes"])
            out[u["case_id"]] = {
                "hard": hard, "soft": sorted(v["soft_failed_genes"]),
                "generic": sorted(g for g in hard if pred.get(g) in GENERIC_LINE_FOR_PREDICATE),
                "applied": sorted(r0.get("repair_applied_genes") or []),
                "fired": sorted(set(hard) | set(v["soft_failed_genes"]))}
    if not out:
        raise AnalysisError(f"no registered run for label {label!r} of model {model!r}")
    return out


def stratum_of(rec):
    if not rec["hard"]:
        return "N"
    other = [g for g in rec["hard"] if g not in rec["generic"]]
    return "P" if not other else ("X" if rec["generic"] else "M")


def _cmp(pa, pb, cases, bench_of, boot, label):
    if not cases:
        return {"comparison": label, "n": 0}
    benches = {bench_of[c] for c in cases}
    r = PA.compare_cases(pa, pb, cases, bench_of, boot["n_boot"], boot["seed"], boot.get("ci_level", 0.95),
                         stratify=len(benches) > 1)
    r.pop("_exact", None)
    r["comparison"] = label
    return r


def rates(p_final, p0, repaired, cases):
    wrong = [c for c in cases if p0[c] == 0.0]
    right = [c for c in cases if p0[c] == 1.0]
    if len(wrong) + len(right) != len(cases):
        raise AnalysisError("detection and repair rates need one repeat per case (binary round-0 outcomes)")
    det = [c for c in wrong if repaired[c]]
    fix = [c for c in det if p_final[c] == 1.0]
    fa = [c for c in right if repaired[c]]
    brk = [c for c in fa if p_final[c] == 0.0]
    # answers that change without a recorded repair would break the identity; they cannot occur with a shared round 0
    drift = [c for c in cases if not repaired[c] and p_final[c] != p0[c]]
    if drift:
        raise AnalysisError(f"{len(drift)} unrepaired case(s) differ from the round-0 outcome (first: {drift[:3]})")
    n = len(cases)
    out = {"n": n, "n_wrong0": len(wrong), "n_correct0": len(right), "detected": len(det), "repaired_ok": len(fix),
           "false_alarms": len(fa), "broken": len(brk),
           "detect": r4(len(det) / len(wrong)) if wrong else None, "detect_wilson95": _w(len(det), len(wrong)),
           "repair_success": r4(len(fix) / len(det)) if det else None, "repair_success_wilson95": _w(len(fix), len(det)),
           "false_alarm": r4(len(fa) / len(right)) if right else None, "false_alarm_wilson95": _w(len(fa), len(right)),
           "break": r4(len(brk) / len(fa)) if fa else None,
           "n_correct_final": sum(1 for c in cases if p_final[c] == 1.0)}
    if out["n_correct_final"] != len(right) + len(fix) - len(brk):
        raise AnalysisError("the accounting identity does not hold")  # cannot happen; guards the definitions
    return out


def _w(x, n):
    if not n:
        return None
    lo, hi = PA.wilson(x, n)
    return [r4(lo), r4(hi)]


def analyse(matrix, reg, model, labels, round0_label, bench_of, classes, boot, reference_kind="r1", outcome="correct",
            families=None, root=None):
    field, tier = PA.outcome_field(outcome, reference_kind)
    cases = sorted(bench_of)
    per, rep = {}, {}
    for key, lab in labels.items():
        rows = matrix.select(model, lab)
        per[key], n_rep = PA.per_case(rows, field, tier)
        if any(n != 1 for n in n_rep.values()):
            raise AnalysisError(f"{lab}: the mechanism analysis reads one repeat per case")
        rep[key] = {r["case_id"]: (r.get("repair_rounds_used") or 0) > 0 for r in rows}
        miss = [c for c in cases if c not in per[key]]
        if miss:
            raise AnalysisError(f"{lab}: {len(miss)} case(s) of the analysis set are missing (first: {miss[:3]})")
    p0, _ = PA.per_case(matrix.select(model, round0_label), field, tier)
    # shared round 0: the content sha256 of every label equals the round-0 label's
    sha = {key: {r["case_id"]: r["round0_content_sha256"] for r in matrix.select(model, lab)} for key, lab in labels.items()}
    sha0 = {r["case_id"]: r["round0_content_sha256"] for r in matrix.select(model, round0_label)}
    for key in labels:
        bad = [c for c in cases if not sha0.get(c) or sha[key].get(c) != sha0[c]]
        if bad:
            raise AnalysisError(f"{labels[key]} does not share round 0 with {round0_label} on {len(bad)} case(s) "
                                f"(first: {bad[:3]}); round-0 content sha256 missing or different")
    r0 = round0_records(reg, model, labels["l"], root)
    miss = [c for c in cases if c not in r0]
    if miss:
        raise AnalysisError(f"{labels['l']}: no unit record for {len(miss)} case(s) (first: {miss[:3]})")
    st = {c: stratum_of(r0[c]) for c in cases}
    pairs = [("L_vs_E", "l", "e")] + ([("T_vs_E", "t", "e"), ("L_vs_T", "l", "t")] if "t" in labels else []) \
        + ([("A_vs_T", "a", "t")] if "a" in labels and "t" in labels else [])
    comps = {}
    for name, x, y in pairs:
        comps[name] = {"pooled": _cmp(per[x], per[y], cases, bench_of, boot, name),
                       "by_stratum": {s: _cmp(per[x], per[y], [c for c in cases if st[c] == s], bench_of, boot, name)
                                      for s in STRATA}}
    out = {"model": model, "labels": dict(labels, round0=round0_label), "n": len(cases),
           "strata_counts": {s: sum(1 for c in cases if st[c] == s) for s in STRATA}, "comparisons": comps}
    if "t" in labels:
        bad = [c for c in cases if abs((per["l"][c] - per["e"][c]) - (per["t"][c] - per["e"][c]) - (per["l"][c] - per["t"][c])) > 1e-12]
        total, det, pres = (comps[k]["pooled"]["diff"] for k in ("L_vs_E", "T_vs_E", "L_vs_T"))
        out["decomposition"] = {"total_L_minus_E": total, "detection_T_minus_E": det, "prescription_L_minus_T": pres,
                                "ci": {k: comps[k]["pooled"]["ci"] for k in ("L_vs_E", "T_vs_E", "L_vs_T")},
                                "additive": not bad and abs(total - det - pres) < 2e-4}
    out["rates"] = {labels[k]: rates(per[k], p0, rep[k], cases) for k in labels}
    # gains by function class of the genes applied in the first repair round of L
    unknown = sorted({g for c in cases for g in r0[c]["fired"] if g not in classes})
    if unknown:
        raise AnalysisError(f"genes without a function class: {unknown}")
    by_class = {k: {"wins": 0, "losses": 0, "single_class_wins": 0, "single_class_losses": 0} for k in CLASSES}
    for c in cases:
        d = per["l"][c] - per["e"][c]
        if d == 0:
            continue
        cl = {classes[g] for g in r0[c]["applied"]}
        for k in cl:
            by_class[k]["wins" if d > 0 else "losses"] += 1
            if len(cl) == 1:
                by_class[k]["single_class_wins" if d > 0 else "single_class_losses"] += 1
    out["gains_by_function_class"] = by_class
    # conservative bound for the answer-distribution heuristic
    heur = [c for c in cases if r0[c]["hard"] and all(classes[g] == HEURISTIC for g in r0[c]["hard"])]
    pl = dict(per["l"])
    for c in heur:
        pl[c] = per["e"][c]
    out["conservative_bound"] = {"n_cases_only_heuristic_at_round0": len(heur),
                                 "n_outcomes_changed": sum(1 for c in heur if per["l"][c] != per["e"][c]),
                                 "L_vs_E": _cmp(pl, per["e"], cases, bench_of, boot, "L_vs_E (heuristic-only cases set to E)")}
    # per-gene detection at round 0
    wrong = [c for c in cases if p0[c] == 0.0]
    right = [c for c in cases if p0[c] == 1.0]
    genes = sorted({g for c in cases for g in r0[c]["fired"]})

    def det_row(sel):
        w = sum(1 for c in wrong if sel(r0[c]["fired"]))
        k = sum(1 for c in right if sel(r0[c]["fired"]))
        return {"fires_on_wrong": w, "fires_on_correct": k, "precision": r4(w / (w + k)) if w + k else None,
                "precision_wilson95": _w(w, w + k), "share_of_wrong": r4(w / len(wrong)) if wrong else None,
                "false_alarm": r4(k / len(right)) if right else None, "false_alarm_wilson95": _w(k, len(right))}

    out["detection_round0"] = {
        "n_wrong0": len(wrong), "n_correct0": len(right),
        "by_gene": {g: dict(det_row(lambda f, g=g: g in f), function_class=classes[g]) for g in genes},
        "by_class": {k: det_row(lambda f, k=k: any(classes[g] == k for g in f)) for k in CLASSES}}
    # problem families
    if families is None:
        out["families"] = {"status": "pending", "note": "no family labels file given"}
    else:
        fam, src = families["case_family"], families["gene_source_families"]
        miss = [c for c in cases if c not in fam]
        if miss:
            raise AnalysisError(f"family labels are missing for {len(miss)} case(s) (first: {miss[:3]})")
        grp = {}
        for c in cases:
            a = r0[c]["applied"]
            if not a:
                g = "no_repair"
            elif all(not src.get(x) for x in a):
                g = "seed_only"
            elif any(fam[c] in (src.get(x) or []) for x in a):
                g = "same_family"
            else:
                g = "other_family"
            grp.setdefault(g, []).append(c)
        out["families"] = {"status": "computed", "groups": {g: _cmp(per["l"], per["e"], cs, bench_of, boot, f"L_vs_E [{g}]")
                                                           for g, cs in sorted(grp.items())}}
    return out


def run(args, matrix=None, aset=None, prereg=None, reg=None, root=None):
    root = root or ROOT
    pr = prereg or PR.load(args.prereg)
    if args.from_prereg:
        if args.l or args.e or args.t or args.a or args.round0_label:
            raise AnalysisError("--from-prereg takes every label from the pre-registered item `mechanism`")
        lab = pr.get("mechanism")["labels"]
        args.l, args.e, args.t, args.a, args.round0_label = (lab[k] for k in ("l", "e", "t", "a", "round0"))
    if not (args.l and args.e and args.round0_label):
        raise AnalysisError("give --l, --e and --round0-label, or --from-prereg")
    labels = {"l": args.l, "e": args.e}
    if args.t:
        labels["t"] = args.t
    if args.a:
        labels["a"] = args.a
    if reg is None:
        reg = RG.load_registry(args.registry, superseded_path=args.superseded)
    if matrix is None:
        matrix = RG.build_matrix(reg, root=root, labels=sorted(set(labels.values()) | {args.round0_label}), models=args.models)
    dev = matrix.label == "DEV"
    boot = dict(pr.get("bootstrap", allow_pending=dev))
    if args.n_boot:
        boot["n_boot"] = args.n_boot
    if aset is None:
        name = RG.set_name_for(matrix.label, args.set, args.incl_0905)
        aset = RG.resolve_set(name, allow_pending=args.allow_pending and dev)
    m = RG.restrict(matrix, aset)
    bench_of = RG.bench_map(aset)
    classes, csrc = load_classes(args.classes, root)
    families, fsrc = None, None
    if args.families:
        fp = resolve(args.families, root)
        families = json.load(open(fp, encoding="utf-8"))
        fsrc = {"file": rel(fp), "sha256": sha256_file(fp)}
    res = [analyse(m, reg, model, labels, args.round0_label, bench_of, classes, boot, aset["reference"], args.outcome,
                   families, root) for model in (args.models or m.models())]
    return {"schema": SCHEMA, "data": m.label, "generated_by": "analysis/r1/mechanism.py", "outcome": args.outcome,
            "analysis_set": m.header["analysis_set"], "prereg": pr.provenance(), "function_classes": csrc,
            "families_file": fsrc, "inputs": {k: m.header[k] for k in ("registry", "runs", "freeze_gate")},
            "results": res}


def _row(r):
    if not r.get("n"):
        return "| 0 | | | | | |"
    return (f"| {r['n']} | {pct1(r['acc_a'])} | {pct1(r['acc_b'])} | {signed_pp(r['diff'])} | "
            f"[{signed_pp(r['ci'][0])}, {signed_pp(r['ci'][1])}] | {r['wins']}/{r['ties']}/{r['losses']} | {p4(r['mcnemar_exact_p'])} |")


def render_md(doc):
    out = [md_header("Mechanism analysis (strata, decomposition, detection and repair)", doc["data"])]
    for res in doc["results"]:
        lab = res["labels"]
        out += ["", f"## {res['model']}: " + ", ".join(f"{k}={v}" for k, v in lab.items()), "",
                "Round-0 strata (from the gene-repair run's round-0 checks): "
                + ", ".join(f"{s} {res['strata_counts'][s]}" for s in STRATA), "",
                "| comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |",
                "|---|---|---|---|---|---|---|---|---|"]
        for name, c in res["comparisons"].items():
            out.append(f"| {name} | pooled " + _row(c["pooled"]))
            out += [f"| {name} | {s} " + _row(c["by_stratum"][s]) for s in STRATA]
        if "decomposition" in res:
            d = res["decomposition"]
            out += ["", f"Nested decomposition (pp): total {signed_pp(d['total_L_minus_E'])} = detection with generic "
                        f"content {signed_pp(d['detection_T_minus_E'])} + gene diagnosis and prescription "
                        f"{signed_pp(d['prescription_L_minus_T'])}; additive case by case: {d['additive']}."]
        out += ["", "| label | wrong at r0 | detected | repaired ok | correct at r0 | false alarms | broken | final correct |",
                "|---|---|---|---|---|---|---|---|"]
        out += [f"| {k} | {v['n_wrong0']} | {v['detected']} | {v['repaired_ok']} | {v['n_correct0']} | {v['false_alarms']} | "
                f"{v['broken']} | {v['n_correct_final']} |" for k, v in res["rates"].items()]
        out += ["", "| function class of applied genes | wins | losses | single-class wins | single-class losses |",
                "|---|---|---|---|---|"]
        out += [f"| {k} | {v['wins']} | {v['losses']} | {v['single_class_wins']} | {v['single_class_losses']} |"
                for k, v in res["gains_by_function_class"].items()]
        cb = res["conservative_bound"]
        out += ["", f"Conservative bound: {cb['n_cases_only_heuristic_at_round0']} case(s) flagged at round 0 only by the "
                    f"answer-distribution heuristic ({cb['n_outcomes_changed']} outcome(s) changed); L−E becomes "
                    f"{signed_pp(cb['L_vs_E']['diff'])} pp, CI [{signed_pp(cb['L_vs_E']['ci'][0])}, "
                    f"{signed_pp(cb['L_vs_E']['ci'][1])}], McNemar p {p4(cb['L_vs_E']['mcnemar_exact_p'])}.",
                "", "| gene | class | fires on wrong | fires on correct | precision | false alarm |", "|---|---|---|---|---|---|"]
        out += [f"| {g} | {v['function_class']} | {v['fires_on_wrong']} | {v['fires_on_correct']} | {v['precision']} | "
                f"{v['false_alarm']} |" for g, v in res["detection_round0"]["by_gene"].items()]
        out += ["", f"Problem families: {res['families']['status']}."]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-prereg", action="store_true", help="labels of the pre-registered item `mechanism`")
    ap.add_argument("--l", default=None)
    ap.add_argument("--e", default=None)
    ap.add_argument("--t", default=None)
    ap.add_argument("--a", default=None)
    ap.add_argument("--round0-label", default=None)
    ap.add_argument("--registry", default=RG.DEFAULT_REGISTRY)
    ap.add_argument("--superseded", default=RG.DEFAULT_SUPERSEDED)
    ap.add_argument("--prereg", default=PR.DEFAULT_PATH)
    ap.add_argument("--classes", default=None)
    ap.add_argument("--families", default=None)
    ap.add_argument("--set", default=None)
    ap.add_argument("--incl-0905", action="store_true")
    ap.add_argument("--allow-pending", action="store_true")
    ap.add_argument("--outcome", default="correct")
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--n-boot", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    try:
        doc = run(a)
    except AnalysisError as x:
        print(f"[mechanism] REFUSED: {x}", file=sys.stderr)
        return 2
    md = render_md(doc)
    if a.out:
        out = labelled_path(a.out, doc["data"])
        write_text(out, dumps(doc))
        write_text(os.path.splitext(out)[0] + ".md", md)
        print(f"[mechanism] {doc['data']} -> {rel(os.path.abspath(out))}")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

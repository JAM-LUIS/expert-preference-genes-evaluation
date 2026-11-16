"""Type labels, reference-override entries and R1 exclusions from the text-free annotation summaries (E14 interface).

Inputs are the outputs of the stage-1 collection script (run by someone who may open the filled sheets), which hold
ids, closed-vocabulary labels and numbers only:
  type_final_labels.csv  case_id, split, final_label, final_type_after_linearization, method, adjudicator, note
  ref_check.csv          case_id, benchmark, split, checker, reference, verdict_A, value_A, ..., verdict_B, ...,
                         final_verdict, final_value, method, adjudicator
plus the reference-check sample (reference_check_sample.json: which cases were drawn and who checks them).
Free-text columns (note, rationale) are never read. Every kept cell is reduced to its closed vocabulary or a number;
anything else is reported without its content. Method values follow the annotation instructions
(independent_agreement, single_check_correct, discussion, third_party); annotator codes are A, B, C (never names).

Outputs (paths relative to the repository root):
  data/labels/industryor_type.json          final type label per IndustryOR case (this module's format)
  data/reference_overrides/<source>.json    one entry per settled reference check, in the E13 format
                                            (runtime/orgene/refs.py, data/reference_overrides/README.md); the
                                            command line (data/ingest_annotations.py) builds and validates them with
                                            refs.build_overrides_doc, writes them with refs.write_overrides, and only
                                            once every sampled case is settled
  data/exclusions_r1.json                   nl_not_linearizable and q3_removed lists with their status (read by
                                            analysis_sets.py)

Rule Q3 (R1-D5), per sampled case with a final verdict (E13 applies it when scoring):
  CORRECT                     entry kept for the record; the original reference is used
  CORRECT_ROUNDED             new_value = the checked exact value; the original is reported alongside
  INCORRECT                   new_value = the corrected value (two checkers agreeing, or adjudicated)
  AMBIGUOUS / UNDERSPECIFIED  original reference; the case goes to q3_removed (out of main, kept in the full-data
                              sensitivity sets)
  not sampled                 no entry; original reference
A case without a final label / verdict (disagreement not yet resolved, or not yet checked) is "pending"; with
strict=True any pending case or invalid row raises AnnotationError.
"""
import csv
import datetime
import hashlib
import json
import math
import os
import re

# linear labels that differ between the two re-derivation batches and that the objective check cannot settle
# (PREREG_R1, comparison rules registered in OSF record 1, count in record 2)
LINEAR_UNRESOLVED = "LINEAR_UNRESOLVED"
TYPE_LABELS = ("LP", "MILP", "IP", "NL_LINEARIZABLE", "NL_NOT_LINEARIZABLE", LINEAR_UNRESOLVED)
POST_LIN = ("LP", "MILP", "IP")
VERDICTS = ("CORRECT", "CORRECT_ROUNDED", "INCORRECT", "AMBIGUOUS", "UNDERSPECIFIED")
REPLACING = ("CORRECT_ROUNDED", "INCORRECT")
REMOVING = ("AMBIGUOUS", "UNDERSPECIFIED")
TYPE_METHODS = ("independent_agreement", "discussion", "third_party")
REF_METHODS = ("independent_agreement", "single_check_correct", "discussion", "third_party", "adjudication")
# annotation-instruction vocabulary -> E13 override vocabulary
OVERRIDE_METHOD = {"third_party": "adjudication"}
SPECIAL_VALUES = ("infeasible", "unbounded")
CODE_RE = re.compile(r"^[A-Z]$")                  # one annotator / adjudicator code (A, B, C); never a name
CHECKER_RE = re.compile(r"^[A-Z](\+[A-Z])*$")    # the sample's checker column (A, B, A+B)
CASE_ID_RE = re.compile(r"^(mamo_complex_lp|industryor)-\d{4}$")

LABELS_SCHEMA = "orgene-r1/labels/industryor_type/v1"
EXCLUSIONS_SCHEMA = "orgene-r1/exclusions/v1"
LABELS_PATH = "data/labels/industryor_type.json"
OVERRIDES_DIR = "data/reference_overrides"
EXCLUSIONS_PATH = "data/exclusions_r1.json"
RULE_Q3 = ("R1-D5 (Q3): CORRECT keep; CORRECT_ROUNDED replace by the exact value, report the original; INCORRECT "
           "(two checkers or adjudicated) replace by the corrected value, report the original; AMBIGUOUS / "
           "UNDERSPECIFIED out of main, kept in the full-data sensitivity sets; not sampled keep")
RULE_NL = ("D5: IndustryOR cases whose final label is NL_NOT_LINEARIZABLE are kept but reported separately: "
           "not in the main table and not in the MDE sample size")
RULE_LU = ("PREREG_R1: linear labels that differ between the two re-derivation batches and that the objective "
           "check cannot settle are LINEAR_UNRESOLVED: counted as linear (not in nl_not_linearizable), dropped only "
           "from type-stratified analyses (no effective_type)")
TOL = 1e-4                                        # primary tolerance: |a - b| <= max(t, t * |b|)


class AnnotationError(ValueError):
    """Invalid or incomplete annotation input under strict ingestion, or no way to write the result."""


def sha256_path(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        return list(rd), list(rd.fieldnames or [])


def _num(s):
    s = (s or "").strip().replace(",", "")
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def _value(s):
    """A value cell -> ("number", float) | ("status", "infeasible"/"unbounded") | (None, None)."""
    s = (s or "").strip()
    if s.lower() in SPECIAL_VALUES:
        return "status", s.lower()
    x = _num(s)
    return ("number", x) if x is not None else (None, None)


def within_tol(a, b):
    return a is not None and b is not None and abs(a - b) <= max(TOL, TOL * abs(b))


def _code(s, pattern=CODE_RE):
    """'' for an empty cell, the code if it is one, None otherwise (content never echoed)."""
    s = (s or "").strip()
    return s if (s == "" or pattern.match(s)) else None


def _require_cols(fields, needed, name):
    missing = [c for c in needed if c not in fields]
    if missing:
        raise AnnotationError(f"{name}: missing column(s) {missing}")


def _row_id(r, i, known, what):
    cid = (r.get("case_id") or "").strip()
    if cid in known:
        return cid, None
    shown = f" ({cid})" if CASE_ID_RE.match(cid) else " (not shown)"
    return None, f"row {i}: case id not {what}{shown}"


def _finish(problems, pending, strict, what):
    if strict and (problems or pending):
        raise AnnotationError(f"{what}: {len(problems)} problem(s), {len(pending)} pending case(s): "
                              + "; ".join(problems[:10]) + (f"; pending {pending[:10]}" if pending else ""))


def _ids_of(problems):
    return {p.split(":")[0] for p in problems if CASE_ID_RE.match(p.split(":")[0])}


# ------------------------------------------------------------------ type labels


def ingest_type_labels(csv_path, expected, strict=False):
    """Final IndustryOR type labels. `expected` = {case_id: split} of the cases that must be labelled.

    Returns the labels document: `pending` = cases without a final label (unresolved disagreement or missing row),
    `invalid` = cases whose row broke a rule (listed in `problems`, content not shown).
    """
    rows, fields = read_csv(csv_path)
    _require_cols(fields, ("case_id", "final_label", "final_type_after_linearization", "method", "adjudicator"),
                  os.path.basename(csv_path))
    labels, problems, seen = {}, [], set()
    for i, r in enumerate(rows, 2):
        cid, err = _row_id(r, i, expected, "among the expected cases")
        if err:
            problems.append(err)
            continue
        if cid in seen:
            problems.append(f"{cid}: more than one row")
            continue
        seen.add(cid)
        lab = (r.get("final_label") or "").strip()
        if lab == "":
            continue                                    # not settled yet -> pending
        after = (r.get("final_type_after_linearization") or "").strip()
        method = (r.get("method") or "").strip()
        adj = _code(r.get("adjudicator"))
        bad = []
        if lab not in TYPE_LABELS:
            bad.append("final_label outside the label list")
        if lab == "NL_LINEARIZABLE" and after not in POST_LIN:
            bad.append("NL_LINEARIZABLE needs final_type_after_linearization LP/MILP/IP")
        if lab != "NL_LINEARIZABLE" and after:
            bad.append("final_type_after_linearization given for a label other than NL_LINEARIZABLE")
        if lab == LINEAR_UNRESOLVED and (method != "independent_agreement" or adj):
            bad.append("LINEAR_UNRESOLVED is set by the batch comparison only (independent_agreement, no adjudicator)")
        if method not in TYPE_METHODS:
            bad.append(f"method must be one of {list(TYPE_METHODS)}")
        if adj is None:
            bad.append("adjudicator is not a single code such as C (value not shown)")
        elif method == "third_party" and not adj:
            bad.append("third_party needs an adjudicator code")
        if bad:
            problems += [f"{cid}: {b}" for b in bad]
            continue
        labels[cid] = {"split": expected[cid], "type": lab,
                       "type_after_linearization": after or None,
                       "effective_type": (after if lab == "NL_LINEARIZABLE"
                                          else None if lab == LINEAR_UNRESOLVED else lab),
                       "method": method, "adjudicator": adj or None}
    invalid = sorted(_ids_of(problems))
    pending = sorted(set(expected) - set(labels) - set(invalid))
    _finish(problems, pending, strict, "type labels")
    return {
        "schema": LABELS_SCHEMA,
        "basis": {"file": os.path.basename(csv_path), "sha256": sha256_path(csv_path)},
        "rule": RULE_NL,
        "rule_linear_unresolved": RULE_LU,
        "status": "final" if not pending and not problems else "pending",
        "n_expected": len(expected),
        "n_final": len(labels),
        "counts": {t: sum(v["type"] == t for v in labels.values()) for t in TYPE_LABELS},
        "labels": {c: labels[c] for c in sorted(labels)},
        "nl_not_linearizable": sorted(c for c, v in labels.items() if v["type"] == "NL_NOT_LINEARIZABLE"),
        "linear_unresolved": sorted(c for c, v in labels.items() if v["type"] == LINEAR_UNRESOLVED),
        "pending": pending,
        "invalid": invalid,
        "problems": problems,
    }


# ------------------------------------------------------------------ reference checks


def _original_value(orig):
    obj, status = orig
    return obj if obj is not None else status


def _checkers(r, fields):
    """Who checked: A / B when their verdict column is filled, else the sample's checker column (A, B, A+B)."""
    got = [x for x in ("A", "B") if f"verdict_{x}" in fields and (r.get(f"verdict_{x}") or "").strip()]
    if got:
        return got
    c = _code(r.get("checker"), CHECKER_RE)
    return c.split("+") if c else None


def ingest_reference_checks(csv_path, sample, originals, date=None, strict=False, sample_sha256=None):
    """Settled reference checks -> E13 override entries per source, plus the q3_removed list.

    sample    = the reference-check sample document ({"rows": [{"case_id", "benchmark", "split", "checker"}, ...]})
    originals = {case_id: (objective float | None, status str | None)} from data/cases/ (the frozen references)
    Returns {"entries": {source: [entry, ...]}, "q3": {...}, "counts", "problems", "pending", "basis"}.
    """
    date = date or datetime.date.today().isoformat()
    rows, fields = read_csv(csv_path)
    _require_cols(fields, ("case_id", "final_verdict", "final_value", "method", "adjudicator", "checker"),
                  os.path.basename(csv_path))
    basis = {"file": os.path.basename(csv_path), "sha256": sha256_path(csv_path)}
    drawn = {r["case_id"]: r for r in sample["rows"]}
    problems, seen, verdicts = [], set(), {}
    entries = {src: [] for src in sorted({r["benchmark"] for r in sample["rows"]})}
    removed = {v: [] for v in REMOVING}
    for i, r in enumerate(rows, 2):
        cid, err = _row_id(r, i, drawn, "in the reference-check sample")
        if err:
            problems.append(err)
            continue
        if cid in seen:
            problems.append(f"{cid}: more than one row")
            continue
        seen.add(cid)
        if cid not in originals:
            problems.append(f"{cid}: not in the frozen cases")
            continue
        orig = originals[cid]
        ref_cell = (r.get("reference") or "").strip()
        if ref_cell and not (orig[0] is not None and _num(ref_cell) is not None
                             and math.isclose(_num(ref_cell), orig[0], rel_tol=1e-12, abs_tol=1e-12)):
            problems.append(f"{cid}: the sheet's reference column is not the frozen reference (checked against another version?)")
            continue
        verdict = (r.get("final_verdict") or "").strip()
        if verdict == "":
            continue                                    # disagreement unresolved / not checked yet -> pending
        method = (r.get("method") or "").strip()
        adj = _code(r.get("adjudicator"))
        checkers = _checkers(r, fields)
        kind, val = _value(r.get("final_value"))
        bad = []
        if verdict not in VERDICTS:
            bad.append("final_verdict outside the verdict list")
        if method not in REF_METHODS:
            bad.append(f"method must be one of {list(REF_METHODS)}")
        elif method == "single_check_correct" and verdict != "CORRECT":
            bad.append("a single check can only settle CORRECT; other verdicts need a second checker or adjudication")
        if adj is None:
            bad.append("adjudicator is not a single code such as C (value not shown)")
        elif method in ("third_party", "adjudication") and not adj:
            bad.append("adjudication needs an adjudicator code")
        if checkers is None:
            bad.append("checker is not a code")
        elif verdict in VERDICTS and verdict != "CORRECT" and len(checkers) < 2:
            bad.append(f"{verdict} needs two checkers (independent agreement or adjudication)")
        if verdict in REPLACING:
            if kind is None:
                bad.append(f"{verdict} needs a numeric final_value (or infeasible / unbounded)")
            elif verdict == "CORRECT_ROUNDED" and (kind != "number" or orig[0] is None):
                bad.append("CORRECT_ROUNDED needs numeric reference and final_value")
            elif kind == "number" and within_tol(val, orig[0]):
                bad.append(f"{verdict} but final_value is within tolerance of the reference (that is CORRECT)")
            elif kind == "status" and orig[1] == val:
                bad.append(f"{verdict} but final_value equals the reference status (that is CORRECT)")
        if verdict == "CORRECT" and kind == "number" and not within_tol(val, orig[0]):
            bad.append("CORRECT but final_value is outside tolerance of the reference")
        if bad:
            problems += [f"{cid}: {b}" for b in bad]
            continue
        verdicts[cid] = verdict
        keep_new = verdict in REPLACING or (verdict == "CORRECT" and kind == "number")
        entries[drawn[cid]["benchmark"]].append({
            "case_id": cid, "original_value": _original_value(orig), "new_value": val if keep_new else None,
            "verdict": verdict, "checkers": checkers, "method": OVERRIDE_METHOD.get(method, method),
            "adjudicator": adj if method in ("third_party", "adjudication") else "",
            "date": date, "evidence_sha256": basis["sha256"]})
        if verdict in REMOVING:
            removed[verdict].append(cid)
    pending = sorted(set(drawn) - set(verdicts) - _ids_of(problems))
    _finish(problems, pending, strict, "reference checks")
    sample_sha = sample_sha256 or hashlib.sha256(json.dumps(sample, sort_keys=True).encode("utf-8")).hexdigest()
    final = not pending and not problems
    return {"entries": {s: sorted(v, key=lambda e: e["case_id"]) for s, v in entries.items()},
            "q3": {"status": "final" if final else "pending",
                   "ids": sorted(removed["AMBIGUOUS"] + removed["UNDERSPECIFIED"]),
                   "by_verdict": {v: sorted(removed[v]) for v in REMOVING},
                   "pending_ids": sorted(set(pending) | _ids_of(problems)),
                   "basis": basis, "sample_sha256": sample_sha},
            "counts": {v: sum(x == v for x in verdicts.values()) for v in VERDICTS},
            "final": final, "problems": problems, "pending": pending, "basis": basis}


# ------------------------------------------------------------------ exclusions


def build_exclusions(labels_doc=None, ref_result=None, date=None):
    """data/exclusions_r1.json from the two ingested inputs (either may be missing -> that list is pending)."""
    date = date or datetime.date.today().isoformat()
    if labels_doc is None:
        nl = {"status": "pending", "ids": [], "pending_ids": [], "basis": None, "reason": "type labels not ingested"}
    else:
        nl = {"status": labels_doc["status"], "ids": labels_doc["nl_not_linearizable"],
              "pending_ids": sorted(set(labels_doc["pending"]) | set(labels_doc["invalid"])), "basis": labels_doc["basis"]}
    if ref_result is None:
        q3 = {"status": "pending", "ids": [], "by_verdict": {v: [] for v in REMOVING}, "pending_ids": [],
              "basis": None, "reason": "reference checks not ingested"}
    else:
        q3 = dict(ref_result["q3"])
    return {"schema": EXCLUSIONS_SCHEMA, "created": date,
            "rules": {"nl_not_linearizable": RULE_NL, "q3_removed": RULE_Q3,
                      "seen_20260905_test": "kept in data/analysis_sets/analysis_sets.v2.json (exclusions)"},
            "nl_not_linearizable": nl, "q3_removed": q3}


def originals_from_cases(paths):
    """{case_id: (objective, status)} of the frozen cases files (reference fields only)."""
    out = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("_header"):
                    continue
                ref = r.get("reference") or {}
                out[r["case_id"]] = (ref.get("objective"), ref.get("status"))
    return out


def write_json(path, doc):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")

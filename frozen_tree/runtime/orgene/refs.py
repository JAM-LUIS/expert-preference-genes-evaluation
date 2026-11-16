"""Reference answers used for scoring: tolerance tiers and reference overrides (E13).

Tolerance tiers (score.py): a printed objective is correct at tier t when |obj - ref| <= max(t, t * |ref|), i.e. the
absolute and the relative tolerance take the same value. Tiers 1e-6, 1e-4, 1e-2; `correct` is the primary tier 1e-4.

Reference overrides: `data/reference_overrides/<source>.json` records the outcome of the reference-answer check
(ids, verdicts and numbers only, no problem text). Scoring rule (R1 DECISIONS R1-D5, written before any test run):

  CORRECT                    keep the original reference
  CORRECT_ROUNDED            score against the exact value found by the check; the original-reference score is
                             reported alongside (`correct_original_ref`)
  INCORRECT                  score against the corrected value (two checkers agree, or adjudicated); the
                             original-reference score is reported alongside
  AMBIGUOUS, UNDERSPECIFIED  keep the original reference; the case leaves the main analysis set
                             (`reference_main_eligible` = false) and stays only in the full-set sensitivity analysis
  not checked                keep the original reference

File format (one JSON object, written by `dumps_overrides`, see data/reference_overrides/README.md):
  {"schema": "orgene.reference_overrides.v1", "source": "<source>", "cases_sha256": "<sha256 of the cases file>",
   "rules_sha256": "<rules_sha256()>",
   "entries": [{"case_id", "original_value", "new_value", "verdict", "checkers", "method"?, "adjudicator"?,
                "date", "evidence_sha256"}, ...]}
  values are a number, "infeasible", "unbounded" or null; checkers/adjudicator are short codes (A, B, C), not names.

Integrity: `load_overrides(path, expected_sha256)` refuses a file whose sha256 differs from the frozen one;
`load_scoring_cases(..., freeze_manifest=...)` takes the expected hash from the freeze manifest and refuses to score when
the file is missing from it, differs from it, or is listed but absent. Error messages never echo cell contents.
"""
import hashlib
import json
import math
import os
import re
from datetime import date

from .paths import ROOT, rel
from .score import PRIMARY_TOL, TOLERANCES, correct_by_tol, is_correct, tol_key
from .score import (MATCHABLE_STATUS_CATEGORIES, STATUS_CATEGORIES, UNDECIDED_STATUS_CATEGORIES,
                    reference_category, status_category)

SCHEMA = "orgene.reference_overrides.v1"
OVERRIDES_DIR = os.path.join(ROOT, "data", "reference_overrides")

VERDICTS = ("CORRECT", "CORRECT_ROUNDED", "INCORRECT", "AMBIGUOUS", "UNDERSPECIFIED")
REPLACING = ("CORRECT_ROUNDED", "INCORRECT")   # the effective reference becomes new_value
LEAVES_MAIN = ("AMBIGUOUS", "UNDERSPECIFIED")  # out of the main analysis set, full-set sensitivity only
NOT_CHECKED = "NOT_CHECKED"
SPECIAL_VALUES = ("infeasible", "unbounded")
METHODS = ("independent_agreement", "single_check_correct", "discussion", "adjudication")

TOP_KEYS = ("schema", "source", "cases_sha256", "rules_sha256", "entries")
ENTRY_KEYS = ("case_id", "original_value", "new_value", "verdict", "checkers", "method", "adjudicator", "date",
              "evidence_sha256")
ENTRY_OPTIONAL = ("method", "adjudicator")

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{0,3}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SOURCE_RE = re.compile(r"^[a-z0-9_]+$")

# The scoring rule as data. Its digest is recorded in every override file and in metrics, and goes into the freeze
# manifest; changing any value here changes rules_sha256() (runtime/tests/test_e13_scoring.py pins it).
SCORING_RULES = {
    "schema": SCHEMA,
    "tolerance": {"form": "abs(obj - ref) <= max(t, t * abs(ref))", "tiers": list(TOLERANCES), "primary": PRIMARY_TOL},
    # E22 engineering cases: reference.kind; a case without a kind is a point reference
    "reference_kind": {
        "cbc_optimal": {"judged": "point"},
        "cbc_attains_published_optimum": {"judged": "point"},
        "cbc_time_limited": {"judged": "interval", "interval": "reference.interval = [CBC bound, CBC best value]",
                             "form": "lo - max(t, t * abs(lo)) <= obj <= hi + max(t, t * abs(hi))"},
    },
    "reference_by_verdict": {
        "CORRECT": {"reference": "original", "main_analysis": True},
        "CORRECT_ROUNDED": {"reference": "new_value", "main_analysis": True, "also_report": "original"},
        "INCORRECT": {"reference": "new_value", "main_analysis": True, "also_report": "original",
                      "requires": "two checkers agree or adjudicated"},
        "AMBIGUOUS": {"reference": "original", "main_analysis": False, "kept_in": "full-set sensitivity"},
        "UNDERSPECIFIED": {"reference": "original", "main_analysis": False, "kept_in": "full-set sensitivity"},
        NOT_CHECKED: {"reference": "original", "main_analysis": True},
    },
    # non-numeric references (score.is_correct / score.status_category; fixed before the freeze, 2026-09-29)
    "non_numeric_reference": {
        "categories": list(STATUS_CATEGORIES),
        "matched_by_the_same_category_only": list(MATCHABLE_STATUS_CATEGORIES),
        "never_matching": list(UNDECIDED_STATUS_CATEGORIES),
    },
}


class OverrideError(ValueError):
    """Malformed or inconsistent reference-override file; scoring must not proceed."""


class OverrideIntegrityError(OverrideError):
    """Override file bytes differ from the frozen hash, or the file is missing from / absent despite the manifest."""


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def rules_sha256():
    return hashlib.sha256(_canon(SCORING_RULES)).hexdigest()


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def default_overrides_path(source):
    return os.path.join(OVERRIDES_DIR, f"{source}.json")


# ------------------------------------------------------------------ validation


def _value(v, where="value"):
    """number -> (float, None); "infeasible"/"unbounded" -> (None, word); null -> (None, None)."""
    if v is None:
        return None, None
    if isinstance(v, bool):
        raise OverrideError(f"{where}: must be a number, 'infeasible', 'unbounded' or null (got a boolean)")
    if isinstance(v, (int, float)):
        if not math.isfinite(v):
            raise OverrideError(f"{where}: must be finite")
        return float(v), None
    if isinstance(v, str) and v in SPECIAL_VALUES:
        return None, v
    raise OverrideError(f"{where}: must be a number, 'infeasible', 'unbounded' or null (value not shown)")


def _same(a, b):
    """Two parsed values agree: both numeric within the primary tolerance of b, or the same status word / both null."""
    if a[0] is not None and b[0] is not None:
        return is_correct(a[0], b[0], tol=PRIMARY_TOL)[0]
    return a == b


def _is_code(c):
    return isinstance(c, str) and bool(_CODE_RE.match(c))


def validate_entry(e, source, where="entry"):
    """Check one entry on its own (format and verdict rules). Returns its case_id."""
    if not isinstance(e, dict):
        raise OverrideError(f"{where}: must be an object")
    missing = [k for k in ENTRY_KEYS if k not in e and k not in ENTRY_OPTIONAL]
    unknown = sorted(k for k in e if k not in ENTRY_KEYS)
    if missing or unknown:
        # key names only; free-text fields (notes, rationale) are not allowed, they could quote a problem statement
        raise OverrideError(f"{where}: missing keys {missing}, unknown keys {[k[:40] for k in unknown]}")
    cid = e["case_id"]
    if not (isinstance(cid, str) and re.fullmatch(re.escape(source) + r"-\d{4,}", cid)):
        raise OverrideError(f"{where}: case_id is not a {source} case id (value not shown)")
    w = f"{where} ({cid})"
    verdict = e["verdict"]
    if verdict not in VERDICTS:
        raise OverrideError(f"{w}: verdict must be one of {list(VERDICTS)} (value not shown)")
    orig = _value(e["original_value"], f"{w} original_value")
    new = _value(e["new_value"], f"{w} new_value")
    checkers = e["checkers"]
    if not (isinstance(checkers, list) and checkers and all(_is_code(c) for c in checkers)
            and len(set(checkers)) == len(checkers)):
        raise OverrideError(f"{w}: checkers must be a non-empty list of distinct short codes such as A, B (value not shown)")
    method, adj = e.get("method"), e.get("adjudicator")
    if method is not None and method not in METHODS:
        raise OverrideError(f"{w}: method must be one of {list(METHODS)} or absent (value not shown)")
    if adj not in (None, "") and not _is_code(adj):
        raise OverrideError(f"{w}: adjudicator must be a short code such as C (value not shown)")
    if method == "adjudication" and not adj:
        raise OverrideError(f"{w}: method adjudication needs an adjudicator code")
    d = e["date"]
    try:
        ok_date = isinstance(d, str) and bool(_DATE_RE.match(d)) and bool(date.fromisoformat(d))
    except ValueError:
        ok_date = False
    if not ok_date:
        raise OverrideError(f"{w}: date must be YYYY-MM-DD (value not shown)")
    ev = e["evidence_sha256"]
    evs = ev if isinstance(ev, list) else [ev]
    if not (evs and all(isinstance(x, str) and _HEX64_RE.match(x) for x in evs)):
        raise OverrideError(f"{w}: evidence_sha256 must be a lowercase sha256 hex digest or a non-empty list of them")
    # verdict rules
    if verdict != "CORRECT":
        if len(checkers) < 2:
            raise OverrideError(f"{w}: verdict {verdict} needs two checkers (independent agreement or adjudication)")
        if method == "single_check_correct":
            raise OverrideError(f"{w}: verdict {verdict} cannot rest on a single check")
    if verdict == "CORRECT":
        if new != (None, None) and not _same(new, orig):
            raise OverrideError(f"{w}: verdict CORRECT but new_value is outside the primary tolerance of original_value")
    elif verdict in REPLACING:
        if new == (None, None):
            raise OverrideError(f"{w}: verdict {verdict} needs new_value")
        if verdict == "CORRECT_ROUNDED" and (new[0] is None or orig[0] is None):
            raise OverrideError(f"{w}: verdict CORRECT_ROUNDED needs numeric original_value and new_value")
        if _same(new, orig):
            raise OverrideError(f"{w}: verdict {verdict} but new_value is within the primary tolerance of original_value "
                                "(that is CORRECT)")
    return cid


def validate_doc(doc, where="override file"):
    """Check a whole override document on its own (no cases file needed)."""
    if not isinstance(doc, dict):
        raise OverrideError(f"{where}: must be a JSON object")
    missing = [k for k in TOP_KEYS if k not in doc]
    unknown = sorted(k for k in doc if k not in TOP_KEYS)
    if missing or unknown:
        raise OverrideError(f"{where}: missing keys {missing}, unknown keys {[k[:40] for k in unknown]}")
    if doc["schema"] != SCHEMA:
        raise OverrideError(f"{where}: schema must be {SCHEMA}")
    source = doc["source"]
    if not (isinstance(source, str) and _SOURCE_RE.match(source)):
        raise OverrideError(f"{where}: source must be a source name such as industryor")
    if not (isinstance(doc["cases_sha256"], str) and _HEX64_RE.match(doc["cases_sha256"])):
        raise OverrideError(f"{where}: cases_sha256 must be a lowercase sha256 hex digest")
    if doc["rules_sha256"] != rules_sha256():
        raise OverrideError(f"{where}: rules_sha256 differs from this code's scoring rules ({rules_sha256()[:16]}...); "
                            "the file was written under other rules")
    if not isinstance(doc["entries"], list):
        raise OverrideError(f"{where}: entries must be a list")
    seen = set()
    for i, e in enumerate(doc["entries"]):
        cid = validate_entry(e, source, f"{where} entry {i}")
        if cid in seen:
            raise OverrideError(f"{where}: case {cid} appears twice")
        seen.add(cid)
    return doc


def check_against_cases(ov, all_refs, source=None, cases_sha256=None):
    """The override file belongs to this cases file: same source and cases hash, known ids, matching original values."""
    if source is not None and ov["source"] != source:
        raise OverrideError(f"{ov['path']}: overrides are for source {ov['source']}, the cases file is {source}")
    if cases_sha256 is not None and ov["cases_sha256"] != cases_sha256:
        raise OverrideError(f"{ov['path']}: written against cases file {ov['cases_sha256'][:16]}..., "
                            f"but the cases file is {cases_sha256[:16]}...")
    for cid, e in ov["entries"].items():
        if cid not in all_refs:
            raise OverrideError(f"{ov['path']}: case {cid} is not in the cases file")
        ref = all_refs[cid] or {}
        if _value(e["original_value"]) != (ref.get("objective"), ref.get("status")):
            raise OverrideError(f"{ov['path']}: case {cid}: original_value does not match the cases file's reference")


# ------------------------------------------------------------------ loading and applying


def load_overrides(path, expected_sha256=None):
    """Read and validate an override file. With expected_sha256, refuse a file whose bytes differ from it."""
    with open(path, "rb") as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and sha != str(expected_sha256).lower():
        raise OverrideIntegrityError(f"{rel(path)}: sha256 {sha[:16]}... differs from the frozen "
                                     f"{str(expected_sha256)[:16]}...; refusing to score")
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OverrideError(f"{rel(path)}: not valid UTF-8 JSON ({type(exc).__name__})") from None
    validate_doc(doc, rel(path))
    return {"path": rel(path), "sha256": sha, "source": doc["source"], "cases_sha256": doc["cases_sha256"],
            "entries": {e["case_id"]: e for e in doc["entries"]},
            "integrity_check": "expected_sha256" if expected_sha256 is not None else None}


def effective_reference(ref, entry=None, file_info=None):
    """The reference a case is scored against, with the original kept next to it (no entry: unchanged values)."""
    out = dict(ref or {})
    out["original_objective"] = out.get("objective")
    out["original_status"] = out.get("status")
    out["verdict"] = entry["verdict"] if entry else None
    out["main_eligible"] = not (entry and entry["verdict"] in LEAVES_MAIN)
    out["version"] = "original"
    out["overrides_file"] = file_info
    if "interval" in out:  # E22 time-limited reference; an override value replaces it by a point reference
        out["original_interval"] = out["interval"]
    if entry and entry["verdict"] in REPLACING:
        out["objective"], out["status"] = _value(entry["new_value"])
        out["version"] = f"override@{file_info['sha256'][:16]}"
        if "interval" in out:
            out["interval"] = None
    return out


def apply_to_cases(rows, overrides, all_refs, source=None, cases_path=None, expected_sha256=None):
    """Annotate case records with their effective reference (called by data.load_cases).

    overrides: "none" (original references), "auto" (default_overrides_path(source) when it exists), a path, or a dict
    from load_overrides(). expected_sha256 pins the file's bytes (with "auto", a pinned file must exist).
    """
    if overrides == "none":
        ov, mode = None, "none"
        if expected_sha256 is not None:
            raise OverrideIntegrityError("an expected override hash was given but overrides are disabled")
    elif overrides == "auto":
        mode, path = "auto", default_overrides_path(source)
        if os.path.exists(path):
            ov = load_overrides(path, expected_sha256)
        elif expected_sha256 is not None:
            raise OverrideIntegrityError(f"{rel(path)} is pinned by hash but does not exist; refusing to score")
        else:
            ov = None
    elif isinstance(overrides, dict):
        ov, mode = overrides, overrides.get("mode", "loaded")
        if expected_sha256 is not None and ov["sha256"] != str(expected_sha256).lower():
            raise OverrideIntegrityError(f"{ov['path']}: sha256 differs from the frozen hash; refusing to score")
    else:
        ov, mode = load_overrides(overrides, expected_sha256), "path"
    if ov is not None:
        check_against_cases(ov, all_refs, source, sha256_file(cases_path) if cases_path else None)
    file_info = {"mode": mode, "path": ov["path"] if ov else None, "sha256": ov["sha256"] if ov else None,
                 "n_entries": len(ov["entries"]) if ov else 0, "integrity_check": ov.get("integrity_check") if ov else None,
                 "rules_sha256": rules_sha256()}
    out = []
    for c in rows:
        entry = ov["entries"].get(c["case_id"]) if ov else None
        c2 = dict(c)
        c2["reference"] = effective_reference(c.get("reference"), entry, file_info)
        out.append(c2)
    return out


def cases_source(cases_path):
    """Source name of a cases file from its header line (or its first record); nothing is printed."""
    with open(cases_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                return r.get("source")
    return None


def manifest_key(path):
    """Key of a file in a freeze manifest: its path relative to the repository root."""
    return rel(path)


def expected_from_manifest(manifest_path, target):
    """sha256 recorded for `target` in a freeze manifest, or None when it is not listed.

    Accepted shapes: {"files": {"<rel path>": "<sha>" | {"sha256": "<sha>"}}}, {"files": [{"path", "sha256"}]},
    or the mapping at top level.
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        m = json.load(f)
    files = m.get("files", m) if isinstance(m, dict) else m
    if isinstance(files, list):
        files = {x.get("path"): x for x in files if isinstance(x, dict)}
    if not isinstance(files, dict):
        raise OverrideError(f"{rel(manifest_path)}: no file table")
    val = files.get(manifest_key(target))
    if val is None:
        return None
    sha = val if isinstance(val, str) else (val.get("sha256") if isinstance(val, dict) else None)
    if not (isinstance(sha, str) and _HEX64_RE.match(sha.lower())):
        raise OverrideError(f"{rel(manifest_path)}: entry for {manifest_key(target)} has no valid sha256")
    return sha.lower()


def load_scoring_cases(cases_path, ids=None, overrides="auto", freeze_manifest=None, expected_sha256=None):
    """Cases with effective references for scoring (the `score` subcommand).

    freeze_manifest: refuse to score unless the override file in use is listed there with the same sha256; a file
    listed there must exist ("auto"). overrides="none" scores against the original references (no file is read).
    """
    from . import data as D

    source = cases_source(cases_path)
    target = None
    if overrides == "auto":
        target = default_overrides_path(source)
    elif overrides not in (None, "none"):
        target = overrides
        if not os.path.exists(target):
            raise OverrideError(f"{rel(target)}: override file not found")
    exists = target is not None and os.path.exists(target)
    check = None
    if freeze_manifest is not None and target is not None:
        listed = expected_from_manifest(freeze_manifest, target)
        if exists and listed is None:
            raise OverrideIntegrityError(f"{manifest_key(target)} is not in the freeze manifest; refusing to score")
        if not exists and listed is not None:
            raise OverrideIntegrityError(f"{manifest_key(target)} is in the freeze manifest but missing; refusing to score")
        if listed is not None:
            if expected_sha256 is not None and str(expected_sha256).lower() != listed:
                raise OverrideIntegrityError("--overrides-sha256 differs from the freeze manifest")
            expected_sha256, check = listed, f"freeze_manifest:{rel(freeze_manifest)}"
    if not exists:
        if expected_sha256 is not None:
            raise OverrideIntegrityError("an expected override hash was given but no override file is in use")
        return D.load_cases(cases_path, ids, overrides="none")
    ov = load_overrides(target, expected_sha256)
    ov["mode"] = "auto" if overrides == "auto" else "path"
    if check:
        ov["integrity_check"] = check
    return D.load_cases(cases_path, ids, overrides=ov)


def main_excluded_ids(ov):
    """Case ids that leave the main analysis set under the rule (AMBIGUOUS, UNDERSPECIFIED)."""
    return sorted(cid for cid, e in ov["entries"].items() if e["verdict"] in LEAVES_MAIN)


# ------------------------------------------------------------------ writing (for the annotation ingest, E14)


def _read_refs(cases_path):
    source, refs = None, {}
    with open(cases_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("_header"):
                source = r.get("source")
                continue
            source = source or r.get("source")
            refs[r["case_id"]] = r.get("reference") or {}
    return source, refs


def build_overrides_doc(source, cases_path, entries):
    """A validated override document for `source`, checked against the cases file it will be applied to."""
    doc = {"schema": SCHEMA, "source": source, "cases_sha256": sha256_file(cases_path), "rules_sha256": rules_sha256(),
           "entries": sorted((dict(e) for e in entries), key=lambda e: str(e.get("case_id")))}
    validate_doc(doc, "new override file")
    src, all_refs = _read_refs(cases_path)
    ov = {"path": "new override file", "source": source, "cases_sha256": doc["cases_sha256"],
          "entries": {e["case_id"]: e for e in doc["entries"]}}
    check_against_cases(ov, all_refs, src, doc["cases_sha256"])
    return doc


def dumps_overrides(doc):
    """Canonical bytes of an override document (stable hash for the freeze manifest)."""
    return (json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def write_overrides(doc, path):
    """Write a document built by build_overrides_doc(); returns the file's sha256."""
    validate_doc(doc, rel(path))
    data = dumps_overrides(doc)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ result rows and metrics


def reference_fields(row, ref, rel_tol=PRIMARY_TOL, abs_tol=PRIMARY_TOL):
    """Per-row fields added by score_condition: tiers against the effective and the original reference."""
    obj, st = row.get("objective"), row.get("status")
    ref = ref or {}
    o_obj = ref.get("original_objective", ref.get("objective"))
    o_st = ref.get("original_status", ref.get("status"))
    iv, o_iv = ref.get("interval"), ref.get("original_interval", ref.get("interval"))  # E22 time-limited references
    return {
        "correct_tol": correct_by_tol(obj, ref.get("objective"), ref.get("status"), status=st, reference_interval=iv),
        "correct_original_ref": is_correct(obj, o_obj, o_st, rel_tol, abs_tol, status=st, reference_interval=o_iv)[0],
        "correct_tol_original_ref": correct_by_tol(obj, o_obj, o_st, status=st, reference_interval=o_iv),
        "reference_original_objective": o_obj,
        "reference_original_status": o_st,
        "reference_kind": ref.get("kind"),
        "reference_interval": iv,
        "reference_verdict": ref.get("verdict"),
        "reference_version": ref.get("version", "original"),
        "reference_main_eligible": ref.get("main_eligible", True),
        # the categories of the printed status and of the effective reference (score.status_category); an undecided
        # printed status (infeasible_or_unbounded, local_*) never matches a non-numeric reference
        "status_category": status_category(st),
        "status_undecided": status_category(st) in UNDECIDED_STATUS_CATEGORIES,
        "reference_category": reference_category(ref.get("objective"), ref.get("status")),
    }


def reference_summary(rows, cases_by_id=None):
    """Metrics over result rows carrying reference_fields(): accuracy per tier, original-reference accuracy, counts."""
    keys = [tol_key(t) for t in TOLERANCES]
    out = {"tolerance_tiers": keys}
    n = len(rows)
    if n == 0:
        return out
    n_tol = {k: sum(1 for r in rows if (r.get("correct_tol") or {}).get(k)) for k in keys}
    n_orig = sum(1 for r in rows if r.get("correct_original_ref"))
    out.update({
        "n_correct_by_tol": n_tol,
        "accuracy_by_tol": {k: round(v / n, 4) for k, v in n_tol.items()},
        "n_correct_original_ref": n_orig,
        "accuracy_original_ref": round(n_orig / n, 4),
        "n_status_undecided": sum(1 for r in rows if r.get("status_undecided")),
    })
    verdicts = {}
    for r in rows:
        v = r.get("reference_verdict") or NOT_CHECKED
        verdicts[v] = verdicts.get(v, 0) + 1
    ref = {"rules_sha256": rules_sha256(),
           "n_overridden": sum(1 for r in rows if r.get("reference_version", "original") != "original"),
           "n_main_excluded": sum(1 for r in rows if r.get("reference_main_eligible") is False),
           "n_interval_reference": sum(1 for r in rows if r.get("reference_interval") is not None),
           "verdict_counts": dict(sorted(verdicts.items()))}
    if cases_by_id is not None:
        files = {}
        for r in rows:
            fi = (cases_by_id[r["case_id"]].get("reference") or {}).get("overrides_file")
            if fi:
                files[json.dumps(fi, sort_keys=True)] = fi
        ref["overrides_files"] = [files[k] for k in sorted(files)]
    out["reference"] = ref
    return out

"""Canonical case records from raw benchmark files (MAMO, IndustryOR, NL4Opt, smoke).

Canonical record (data/cases/<source>.jsonl):
{"case_id": "mamo_complex_lp-0001", "source": "mamo_complex_lp", "source_id": "...", "text": "...",
 "reference": {"objective": 1234.5 | null, "raw": "...", "status": null | "infeasible"},
 "extra": {...original non-text fields...}, "license": "CC-BY-SA-4.0"}
Field names of raw files are auto-detected; the detection is recorded in the output header line.
"""
import hashlib
import json
import os
import re

from .paths import rel

QUESTION_KEYS = ("Question", "question", "en_question", "problem", "problem_description", "text", "prompt", "input")
ANSWER_KEYS = ("Answer", "answer", "en_answer", "objective", "ground_truth", "optimal_value", "solution", "output", "label")
ID_KEYS = ("id", "ID", "index", "idx", "problem_id", "qid")

LICENSES = {
    "mamo_easy_lp": "CC-BY-SA-4.0 (FreedomIntelligence/Mamo)",
    "mamo_complex_lp": "CC-BY-SA-4.0 (FreedomIntelligence/Mamo)",
    # dataset card `license:` field checked 2026-09-05 at HF revision b00811923f167cdf4ae1677c33cd61d4eea78f48 (data/README.md).
    # The frozen cases file keeps the value it was built with (it is locked and hashed); new builds record this one.
    "industryor": "CC-BY-NC-4.0 (CardinalOperations/IndustryOR)",
    "nl4opt": "VERIFY (competition data; use the LLMOPT/ORLM re-annotated release and record its license)",
    "smoke": "author-written, CC0",
}

_NUM_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*(?:[eE][-+]?\d+)?")
UNDECIDED_REFERENCE_STATUS = "infeasible or unbounded"
# non-numeric reference phrases -> stored status word (checked in this order, before any number is read)
_REFERENCE_WORDS = {"infeasible": "infeasible", "unbounded": "unbounded", "no feasible": "infeasible",
                    "no best solution": UNDECIDED_REFERENCE_STATUS, "no optimal solution": UNDECIDED_REFERENCE_STATUS,
                    "no solution": "infeasible"}


def parse_reference(raw):
    """Return (objective float|None, status str|None)."""
    if raw is None:
        return None, None
    if isinstance(raw, (int, float)):
        return float(raw), None
    s = str(raw).strip()
    low = s.lower()
    # A reference that names both outcomes, or states only that there is no optimal solution, is kept undecided:
    # "infeasible or unbounded", which the scorer never counts as matched (score.status_category). "No Best Solution"
    # is what ORLM's evaluation prints for every non-optimal COPT status (ORLM eval/execute.py, ADD_SCRIPT), so it does
    # not say whether the problem is infeasible or unbounded. (Scoring rule fixed before the freeze, 2026-09-29.)
    if "infeasible" in low and "unbounded" in low:
        return None, UNDECIDED_REFERENCE_STATUS
    for word in _REFERENCE_WORDS:
        if word in low:
            return None, _REFERENCE_WORDS[word]
    m = _NUM_RE.findall(s.replace("$", ""))
    if not m:
        return None, None
    # if the answer is a sentence with several numbers, take the last one (common: "... optimal value is 1500")
    try:
        return float(m[-1].replace(",", "")), None
    except ValueError:
        return None, None


def _pick(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return k
    return None


def read_raw(path):
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    txt_s = txt.strip()
    if txt_s.startswith("["):
        data = json.loads(txt_s)
    elif txt_s.startswith("{") and "\n{" not in txt_s:
        obj = json.loads(txt_s)
        data = obj if isinstance(obj, list) else (obj.get("data") or obj.get("examples") or list(obj.values()))
    else:
        data = [json.loads(line) for line in txt.splitlines() if line.strip()]
    return data


def build_cases(source, raw_path, out_path):
    data = read_raw(raw_path)
    if not data or not isinstance(data[0], dict):
        raise ValueError("raw file did not parse into a list of records")
    qk, ak, ik = _pick(data[0], QUESTION_KEYS), _pick(data[0], ANSWER_KEYS), _pick(data[0], ID_KEYS)
    if not qk or not ak:
        raise ValueError(f"could not detect question/answer keys in {list(data[0].keys())}; extend QUESTION_KEYS/ANSWER_KEYS")
    rows, n_numeric = [], 0
    for i, rec in enumerate(data, 1):
        obj, status = parse_reference(rec.get(ak))
        n_numeric += obj is not None
        extra = {k: v for k, v in rec.items() if k not in (qk, ak)}
        rows.append({
            "case_id": f"{source}-{i:04d}",
            "source": source,
            "source_id": str(rec.get(ik, i)) if ik else str(i),
            "text": str(rec.get(qk)).strip(),
            "reference": {"objective": obj, "raw": rec.get(ak) if isinstance(rec.get(ak), (str, int, float)) else json.dumps(rec.get(ak), ensure_ascii=False), "status": status},
            "extra": extra,
            "license": LICENSES.get(source, "VERIFY"),
        })
    header = {"_header": True, "source": source, "raw_path": rel(raw_path), "n": len(rows),
              "n_reference_numeric": n_numeric, "question_key": qk, "answer_key": ak, "id_key": ik}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return header


def case_id_from_line(line):
    """Read top-level identity metadata without deserializing question/reference values.

    Canonical JSONL records are objects. Strings and nested values are skipped lexically;
    only field-name strings and the case_id value are decoded. A reordered record is supported,
    including text containing escaped field names. The full JSON is validated only after gating.
    """
    depth, index, case_id, header = 0, 0, None, False
    if not line.strip():
        return None
    if not line.lstrip().startswith("{"):
        raise ValueError("canonical case metadata must be a JSON object")
    while index < len(line):
        char = line[index]
        if char == '"':
            end = index + 1
            while end < len(line):
                if line[end] == "\\":
                    end += 2
                elif line[end] == '"':
                    break
                else:
                    end += 1
            if end >= len(line):
                raise ValueError("unterminated JSON metadata string")
            after = end + 1
            while after < len(line) and line[after].isspace():
                after += 1
            if depth == 1 and after < len(line) and line[after] == ":":
                key = json.loads(line[index:end + 1])
                value = after + 1
                while value < len(line) and line[value].isspace():
                    value += 1
                if key == "case_id":
                    if value >= len(line) or line[value] != '"':
                        raise ValueError("canonical case_id must be a string")
                    case_id, _ = json.JSONDecoder().raw_decode(line, value)
                elif key == "_header":
                    header = line[value:value + 4] == "true"
            index = end + 1
            continue
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        index += 1
    if header:
        return None
    if case_id is None:
        raise ValueError("canonical record has no top-level case_id")
    return case_id


def load_case_ids(path, ids=None):
    """File-order identities only; never deserialize case text or reference objects."""
    selected = []
    with open(path, "r", encoding="utf-8") as stream:
        for line in stream:
            case_id = case_id_from_line(line)
            if case_id is not None and (ids is None or case_id in ids):
                selected.append(case_id)
    return selected


def load_cases(path, ids=None, overrides=None, overrides_sha256=None, *, metadata_only_filter=False):
    """Case records of a cases file (optionally only `ids`).

    overrides=None returns the records as stored. Otherwise each `reference` becomes the effective reference under the
    reference-override rule (refs.py, E13), keeping the stored value as reference.original_objective / original_status:
    "none" (stored references, annotated), "auto" (data/reference_overrides/<source>.json when present), a path, or a
    dict from refs.load_overrides(). overrides_sha256 pins the override file's bytes.
    """
    rows, all_refs, source = [], {}, None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            if metadata_only_filter and ids is not None:
                case_id = case_id_from_line(line)
                if case_id is not None and case_id not in ids:
                    continue  # excluded records never become question/reference objects
            r = json.loads(line)
            if r.get("_header"):
                source = r.get("source")
                continue
            source = source or r.get("source")
            all_refs[r["case_id"]] = r.get("reference")
            if ids is None or r["case_id"] in ids:
                rows.append(r)
    if overrides is None:
        return rows
    from . import refs
    return refs.apply_to_cases(rows, overrides, all_refs, source=source, cases_path=path, expected_sha256=overrides_sha256)


def neutralize_cases(src_path, out_path, raw_path):
    """Copy a cases file, rewriting only line 1 (`_header.raw_path`) to the relative `raw_path`.

    Lines 2.. are copied byte for byte. The header keeps its key order and serialisation (json.dumps with
    ensure_ascii=False, as build_cases writes it); only the value of raw_path changes. Returns hashes only.
    """
    if os.path.isabs(raw_path):
        raise ValueError("raw_path must be relative to the repository root")
    with open(src_path, "rb") as f:
        data = f.read()
    nl = data.find(b"\n")
    if nl < 0:
        raise ValueError("cases file has no header line")
    head, rest = data[: nl + 1], data[nl + 1:]
    h = json.loads(head)
    if not h.get("_header"):
        raise ValueError("line 1 is not a _header record")
    if (json.dumps(h, ensure_ascii=False) + "\n").encode("utf-8") != head:
        raise ValueError("header line is not in canonical json.dumps form; refusing to re-serialise it")
    before_abs = os.path.isabs(str(h.get("raw_path", "")))
    h["raw_path"] = raw_path
    new_head = (json.dumps(h, ensure_ascii=False) + "\n").encode("utf-8")
    out = new_head + rest
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(out)
    return {
        "src_sha256": hashlib.sha256(data).hexdigest(),
        "out_sha256": hashlib.sha256(out).hexdigest(),
        "lines2plus_sha256": hashlib.sha256(rest).hexdigest(),
        "raw_path_was_absolute": before_abs,
        "raw_path": raw_path,
        "changed": "line 1, _header.raw_path only",
    }

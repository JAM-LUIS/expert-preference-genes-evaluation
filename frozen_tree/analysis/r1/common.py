"""Shared helpers of the R1 analysis scripts (E20a): repository paths, data labels, output writing, small formatters.

Every analysis output carries a data label taken from the splits of the rows it was computed from:
  DEV          only dev cases: development data, never a test result (the outputs say so in their first line)
  TEST         only test cases; the registry passes the freeze gate (tools/freeze.py) before reading such a run
  ENG_HOLDOUT  only engineering hold-out cases (E22); gated like TEST
Mixing splits in one output is refused. No path written into an output is absolute (runtime/orgene/paths.py).

The statistical code of paired.py, holm.py, tost.py, strata.py and shared_round0.py uses the standard library only,
so it runs under the generation interpreter too; length_model.py (statsmodels) and forest.py (matplotlib) need the
analysis environment .venv-tools (configs/venv_tools.json). The runtime never imports anything from here.
"""
import csv
import hashlib
import io
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RUNTIME = os.path.join(ROOT, "runtime")
if RUNTIME not in sys.path:
    sys.path.insert(0, RUNTIME)

from orgene.paths import rel, resolve  # noqa: E402

DATA_LABELS = {"dev": "DEV", "test": "TEST", "eng_holdout": "ENG_HOLDOUT"}
SEALED = ("test", "eng_holdout")
BANNERS = {
    "DEV": "DEV: development data only (dev cases); not a test result.",
    "TEST": "TEST: test cases, read after the freeze gate passed.",
    "ENG_HOLDOUT": "ENG_HOLDOUT: engineering hold-out cases, read after the freeze gate passed.",
}


class AnalysisError(ValueError):
    """An analysis input breaks a rule (mixed splits, missing cases, pending pre-registered value, ...)."""


def data_label(splits):
    """DEV / TEST / ENG_HOLDOUT for a collection of split names; mixing splits is refused."""
    s = {x for x in splits if x is not None}
    if not s:
        raise AnalysisError("no rows: cannot label an empty analysis")
    if len(s) > 1:
        raise AnalysisError(f"rows from several splits {sorted(s)}: an output may hold one split only")
    x = s.pop()
    if x not in DATA_LABELS:
        raise AnalysisError(f"unknown split {x!r}")
    return DATA_LABELS[x]


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def dumps(doc):
    """The JSON text every output uses (stable key order as built, 1-space indent, UTF-8, no NaN)."""
    return json.dumps(doc, indent=1, ensure_ascii=False, allow_nan=False) + "\n"


def write_text(path, text):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def write_json(path, doc):
    return write_text(path, dumps(doc))


def csv_text(rows, fields=None):
    if not rows:
        return ""
    fields = fields or list(rows[0].keys())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in r.items()})
    return buf.getvalue()


def labelled_path(path, label):
    """<stem>.<LABEL><ext> unless the name already carries the label (so a DEV file is never mistaken for TEST)."""
    stem, ext = os.path.splitext(path)
    if stem.endswith("." + label):
        return path
    return f"{stem}.{label}{ext}"


def md_header(title, label):
    return f"# [{label}] {title}\n\n{BANNERS[label]}\n"


def check_relative(p, what="path"):
    """A path recorded in a registry or an output must be relative, posix, and stay inside the repository."""
    if not isinstance(p, str) or not p:
        raise AnalysisError(f"{what} must be a non-empty string")
    if os.path.isabs(p) or p.startswith("~") or "\\" in p:
        raise AnalysisError(f"{what} {p!r} must be relative to the repository root")
    parts = p.split("/")
    if ".." in parts:
        raise AnalysisError(f"{what} {p!r} must not leave the repository root")
    return p


# ------------------------------------------------------------------ number formatting (tables)


def r4(x):
    return None if x is None else round(float(x), 4)


def pct1(x):
    """43.5 for 0.43529; None stays None."""
    return None if x is None else f"{100.0 * x:.1f}"


def signed_pp(x):
    """Signed percentage points with a true minus sign, as the stage-0 tables print them (+15.3, −16.5, +0.0)."""
    v = 100.0 * x
    s = f"{abs(v):.1f}"
    return ("−" if v < 0 and s != "0.0" else "+") + s


def p4(p):
    return "<0.0001" if p < 0.0001 else f"{p:.4f}"


def finite(x):
    return x is not None and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


__all__ = ["ROOT", "RUNTIME", "rel", "resolve", "AnalysisError", "data_label", "sha256_file", "sha256_text",
           "read_jsonl", "dumps", "write_text", "write_json", "csv_text", "labelled_path", "md_header",
           "check_relative", "r4", "pct1", "signed_pp", "p4", "finite", "SEALED", "DATA_LABELS", "BANNERS"]

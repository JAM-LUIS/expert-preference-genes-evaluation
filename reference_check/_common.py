"""Shared helpers for the agent double re-derivation (stage1/annotation_agent/scripts/).

No data lives here: no problem text, no reference answers. The tolerance rule is the E13 primary tier of R1
(`runtime/orgene/score.py`): |a - ref| <= max(t, t * |ref|), t = 1e-4; tiers 1e-6 / 1e-4 / 1e-2 are diagnostics.
"""
import csv
import hashlib
import json
import math
import os
import re
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # stage1/annotation_agent
STAGE1 = os.path.dirname(PKG)
HIDDEN_DEFAULT = os.path.join(STAGE1, "annotation_agent_hidden")
R1_LOCAL = os.path.dirname(STAGE1)                                         # ORgene-EAAI-R1 (local paper workspace)

TOL = 1e-4
TIERS = (1e-6, 1e-4, 1e-2)
VERDICTS = ("CORRECT", "CORRECT_ROUNDED", "INCORRECT", "AMBIGUOUS", "UNDERSPECIFIED")
REPLACING = ("CORRECT_ROUNDED", "INCORRECT")
TYPE_LABELS = ("LP", "MILP", "IP", "NL_LINEARIZABLE", "NL_NOT_LINEARIZABLE")
POST_LIN = ("LP", "MILP", "IP")
STATUSES = ("Optimal", "LocallyOptimal", "Feasible", "Infeasible", "Unbounded", "NotSolved", "TypeOnly")
VALUE_STATUSES = ("Optimal", "LocallyOptimal", "Feasible")                  # statuses that carry an objective value
ISSUES = ("NONE", "AMBIGUOUS", "UNDERSPECIFIED")
CONF = ("HIGH", "MEDIUM", "LOW")
CONF_ALIASES = {"高": "HIGH", "中": "MEDIUM", "低": "LOW", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}
SOLVERS = ("PULP_CBC_CMD", "scipy", "enumeration", "none")
SPECIAL_VALUES = ("infeasible", "unbounded")
CASE_ID_RE = re.compile(r"^(mamo_complex_lp|industryor)-\d{4}$")
BATCHES = ("A", "B")
ADJUDICATOR_CODE = "C"          # Qi Deng; only the code goes into files that R1 ingests

# Pre-registered before any re-derivation result exists (2026-09-29); recorded in groups.json and BUILD_NOTES.md.
GROUP_SEEDS = {"A": "20260929-group-A", "B": "20260929-group-B"}
N_GROUPS = 8
REF_AUDIT_SEED = "20260929-ref-audit"
TYPE_AUDIT_SEED = "20260929-type-audit"
N_AUDIT = 10
# second audit round (main-session rule 2026-09-29): drawn only if round 1 of that audit overturns >= 1 case;
# from the eligible cases not audited in round 1; never a third round
REF_AUDIT_SEED_2 = "20260929-ref-audit-round2"
TYPE_AUDIT_SEED_2 = "20260929-type-audit-round2"
NL_LABELS = ("NL_LINEARIZABLE", "NL_NOT_LINEARIZABLE")
LINEAR_UNRESOLVED = "LINEAR_UNRESOLVED"   # LP/MILP/IP disagreement the objective check cannot settle

MANIFEST = "MANIFEST.sha256"
# files that re-derivation agents create inside their group directory; never listed in a manifest
AGENT_OUTPUTS = ("results.jsonl", "models")
# inside a group directory only these package files are ever listed, hashed or scanned (anything else there was
# written by an agent and is never opened by the package tooling)
GROUP_DIR_RE = re.compile(r"(^|/)batch_[AB]/[AB]\d\d(/|$)")
GROUP_FILE_RE = re.compile(r"^((industryor|mamo_complex_lp)-\d{4}\.txt|REDERIVATION_INSTRUCTIONS\.md|MANIFEST\.sha256)$")


def in_group_dir(path):
    return bool(GROUP_DIR_RE.search(os.path.abspath(path).replace(os.sep, "/") + "/"))


# ------------------------------------------------------------------ hashing, json, manifests

def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def rank_hash(seed, case_id):
    """Order key used for group cuts and audit draws: sha256(f"{seed}|{case_id}") (platform independent)."""
    return hashlib.sha256(f"{seed}|{case_id}".encode("utf-8")).hexdigest()


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    data = (json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)
    return sha256_bytes(data)


def write_csv(path, fields, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="raise")
        w.writeheader()
        w.writerows(rows)


def _skip(rel_parts, name, skip_agent_outputs):
    if name == MANIFEST or name.startswith(".") or name.endswith(".pyc"):
        return True
    if "__pycache__" in rel_parts:
        return True
    if not skip_agent_outputs:
        return False
    # agent outputs inside a group directory: batch_X/Xnn/results.jsonl, batch_X/Xnn/models/...
    return any(p in AGENT_OUTPUTS for p in rel_parts) or name in AGENT_OUTPUTS


def manifest_paths(root, skip_agent_outputs=True):
    out = []
    for dp, dns, fns in os.walk(root):
        grp = skip_agent_outputs and in_group_dir(dp)
        # never descend into an agent's directories (models/ or anything else inside a group directory)
        dns[:] = sorted(d for d in dns if not d.startswith(".") and d != "__pycache__"
                        and not (skip_agent_outputs and d in AGENT_OUTPUTS) and not grp)
        for fn in sorted(fns):
            if grp and not GROUP_FILE_RE.match(fn):
                continue
            rel = os.path.relpath(os.path.join(dp, fn), root)
            parts = rel.split(os.sep)
            if not _skip(parts[:-1], fn, skip_agent_outputs):
                out.append(rel)
    return sorted(out)


def write_manifest(root, skip_agent_outputs=True):
    """MANIFEST.sha256 over every file under root (recursive; skips manifests, dotfiles, caches and, in the package,
    agent outputs). Format of `shasum -a 256`, paths relative to root:
    check with `cd root && shasum -a 256 -c MANIFEST.sha256`."""
    paths = manifest_paths(root, skip_agent_outputs)
    with open(os.path.join(root, MANIFEST), "w", encoding="utf-8") as f:
        for rel in paths:
            f.write(f"{sha256_file(os.path.join(root, rel))}  ./{rel}\n")
    return len(paths)


def verify_manifest(root):
    """-> (n_listed, [problems]) ; problems name files only."""
    mp = os.path.join(root, MANIFEST)
    if not os.path.exists(mp):
        return 0, [f"{os.path.basename(root)}: no {MANIFEST}"]
    probs, n = [], 0
    with open(mp, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            n += 1
            h, rel = line.split("  ", 1)
            rel = rel[2:] if rel.startswith("./") else rel
            p = os.path.join(root, rel)
            if not os.path.exists(p):
                probs.append(f"missing {rel}")
            elif sha256_file(p) != h:
                probs.append(f"changed {rel}")
    return n, probs


# ------------------------------------------------------------------ package metadata

def load_case_set(pkg=PKG):
    return load_json(os.path.join(pkg, "case_set.json"))


def load_groups(pkg=PKG):
    return load_json(os.path.join(pkg, "groups.json"))


def load_references(hidden=HIDDEN_DEFAULT):
    return load_json(os.path.join(hidden, "references.json"))


def group_dir(results_root, batch, group):
    return os.path.join(results_root, f"batch_{batch}", group)


def load_source_texts(hidden=HIDDEN_DEFAULT):
    """{case_id: statement text} from the R1 neutral cases files kept in the hidden directory."""
    out = {}
    for src in ("industryor", "mamo_complex_lp"):
        with open(os.path.join(hidden, "source_cases", f"{src}.jsonl"), encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if not r.get("_header"):
                    out[r["case_id"]] = r["text"]
    return out


# ------------------------------------------------------------------ numbers and tolerance

def num(x):
    """JSON number / numeric string -> finite float, else None (booleans are not numbers)."""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x) if math.isfinite(x) else None
    if isinstance(x, str):
        s = x.strip().replace(",", "").replace(" ", "")
        try:
            v = float(s)
        except ValueError:
            return None
        return v if math.isfinite(v) else None
    return None


def within(a, ref, t=TOL):
    """E13 rule: |a - ref| <= max(t, t * |ref|)."""
    return a is not None and ref is not None and abs(a - ref) <= max(t, t * abs(ref))


def same_value(a, b, t=TOL):
    """Two re-derived values agree (symmetric version of the rule, as in collect_annotations.py)."""
    return within(a, b, t) or within(b, a, t)


def tiers(a, ref):
    return {str(t): within(a, ref, t) for t in TIERS}


def _dec(x):
    try:
        return Decimal(repr(float(x)))
    except (InvalidOperation, ValueError):
        return None


def rounding_relation(x, ref):
    """If `ref` equals `x` rounded / truncated to some precision, name the rule (else None).

    Decimal places k = 8..-6 (half-up, half-even, truncation) and significant figures 1..12. Used only to flag
    CORRECT_ROUNDED candidates (x outside the primary tolerance of ref); the adjudicator decides.
    """
    if x is None or ref is None:
        return None
    dx, dr = _dec(x), _dec(ref)
    if dx is None or dr is None:
        return None
    eps = Decimal("1e-9") * max(Decimal(1), abs(dr))
    for k in range(8, -7, -1):
        q = Decimal(1).scaleb(-k)
        for mode, name in ((ROUND_HALF_UP, "round"), (ROUND_HALF_EVEN, "round_half_even"), (ROUND_DOWN, "truncate")):
            try:
                v = dx.quantize(q, rounding=mode)
            except InvalidOperation:
                continue
            if abs(v - dr) <= eps:
                return f"{name}@{k}dp"
    if dx != 0:
        for s in range(1, 13):
            exp = dx.adjusted() - s + 1
            try:
                v = dx.quantize(Decimal(1).scaleb(exp), rounding=ROUND_HALF_UP)
            except InvalidOperation:
                continue
            if abs(v - dr) <= eps:
                return f"round@{s}sf"
    return None


def kappa(pairs):
    """Cohen's kappa over (a, b) label pairs with both labels present -> (kappa or None, n)."""
    pairs = [(a, b) for a, b in pairs if a and b]
    n = len(pairs)
    if n == 0:
        return None, 0
    cats = sorted({x for p in pairs for x in p})
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in cats)
    return (None if pe == 1 else round((po - pe) / (1 - pe), 4)), n


def conf(x):
    if not isinstance(x, str):
        return None
    x = x.strip()
    x = CONF_ALIASES.get(x, x)
    return x if x in CONF else None


def effective_type(t, after):
    if t == "NL_LINEARIZABLE":
        return after if after in POST_LIN else None
    return t if t in TYPE_LABELS else None

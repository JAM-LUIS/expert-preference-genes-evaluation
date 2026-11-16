"""Problem-text features and activation rules for per-problem gene activation (E04, design choice D3 (1)).

extract_features(text, lexicon) -> {name: bool | int}
    Pure and deterministic. The only inputs are the problem statement and the lexicon: never a spec, a program, a
    model output or the reference answer, so activation cannot depend on anything the model wrote. Values are
    booleans and integers only; keys are sorted.
    Built-in features (always present): numeric_literal_count, word_count.
    Lexicon features: one per entry of the lexicon file (genes/activation_lexicon.v1.json):
        kind "any"   -> bool, true when any pattern matches
        kind "count" -> int, total number of matches over all patterns
    Text normalisation before matching: unicode dashes -> "-", whitespace runs -> one space; patterns are Python
    regular expressions compiled case-insensitively.

Activation rule (gene field `activation.rule`):
    "always"
    {"feature": <name>, "op": "==" | "!=" | ">" | ">=" | "<" | "<=", "value": <bool | number>}
    {"all": [rule, ...]}     {"any": [rule, ...]}     {"not": rule}
    A bool feature takes only == / != with a bool value; a count feature takes any operator with a number.
    Feature names are checked against the lexicon when the gene library is loaded; an unknown name, or a name that
    points at the spec / program / execution / answer, is an error.
The gene field itself: {"rule": <rule>, "rationale": "<why>", "devEvidence": ["<dev case id>", ...]}; only `rule`
is required. A gene without the field is treated as "always", so the v1.0 library and its digests are unchanged.
"""
import hashlib
import json
import operator
import os
import re

from .paths import ROOT, rel

LEXICON_SCHEMA = "orgene.activation_lexicon.v1"
EXAMPLES_SCHEMA = "orgene.activation_examples.v1"
DEFAULT_LEXICON = os.path.join(ROOT, "genes", "activation_lexicon.v1.json")
DEFAULT_EXAMPLES = os.path.join(ROOT, "genes", "activation_examples.r1.json")

ALWAYS = "always"
OPS = {"==": operator.eq, "!=": operator.ne, ">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
BOOL_OPS = ("==", "!=")
KINDS = {"any": "bool", "count": "int"}
BUILTIN_TYPES = {"numeric_literal_count": "int", "word_count": "int"}
ACTIVATION_KEYS = ("rule", "rationale", "devEvidence")
MIN_EXAMPLES = 2  # per gene with a non-trivial rule: at least 2 texts that activate it and 2 that do not

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# A feature named after one of these would make activation depend on something other than the problem text.
_FORBIDDEN_FIRST_TOKENS = ("spec", "code", "program", "exec", "execution", "output", "answer", "reference",
                           "solution", "response", "completion", "status")
_DASHES = {0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-", 0x2212: "-"}
_NUM_LITERAL_RE = re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?(?!\w)")


# ----------------------------------------------------------------------------- lexicon


class Lexicon:
    """A validated, compiled lexicon. `sha256` is the hash of the file bytes (recorded per run)."""

    def __init__(self, features, sha256, path=None, schema=LEXICON_SCHEMA):
        self.features = features  # {name: (kind, [compiled patterns])}, sorted by name
        self.sha256 = sha256
        self.path = path
        self.schema = schema
        self.types = dict(BUILTIN_TYPES)
        self.types.update({n: KINDS[k] for n, (k, _) in features.items()})

    def info(self):
        return {"lexicon_path": self.path, "lexicon_sha256": self.sha256, "features": sorted(self.types)}


def _check_name(name, where):
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ValueError(f"{where}: feature name {name!r} must match {_NAME_RE.pattern}")
    if name.split("_")[0] in _FORBIDDEN_FIRST_TOKENS:
        raise ValueError(f"{where}: feature {name!r} refers to the spec/program/output; activation may depend on "
                         f"problem-text features only")


def compile_lexicon(doc, sha256=None, path=None):
    if not isinstance(doc, dict) or doc.get("schemaVersion") != LEXICON_SCHEMA:
        raise ValueError(f"lexicon: schemaVersion must be {LEXICON_SCHEMA}")
    feats = doc.get("features")
    if not isinstance(feats, dict) or not feats:
        raise ValueError("lexicon: 'features' must be a non-empty object")
    out = {}
    for name in sorted(feats):
        spec = feats[name]
        where = f"lexicon feature {name!r}"
        _check_name(name, "lexicon")
        if name in BUILTIN_TYPES:
            raise ValueError(f"{where}: name collides with a built-in feature")
        if not isinstance(spec, dict):
            raise ValueError(f"{where}: must be an object")
        unknown = set(spec) - {"kind", "patterns", "description"}
        if unknown:
            raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
        kind = spec.get("kind")
        if kind not in KINDS:
            raise ValueError(f"{where}: kind must be one of {sorted(KINDS)}")
        pats = spec.get("patterns")
        if not isinstance(pats, list) or not pats or not all(isinstance(p, str) and p for p in pats):
            raise ValueError(f"{where}: patterns must be a non-empty list of non-empty strings")
        compiled = []
        for p in pats:
            try:
                compiled.append(re.compile(p, re.IGNORECASE))
            except re.error as e:
                raise ValueError(f"{where}: bad pattern {p!r}: {e}") from None
        out[name] = (kind, compiled)
    if sha256 is None:
        canon = json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        sha256 = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    return Lexicon(out, sha256, path=path, schema=doc["schemaVersion"])


def load_lexicon(path=None):
    """Load and validate a lexicon file (default genes/activation_lexicon.v1.json). A Lexicon passes through."""
    if isinstance(path, Lexicon):
        return path
    path = path or DEFAULT_LEXICON
    with open(path, "rb") as f:
        raw = f.read()
    return compile_lexicon(json.loads(raw.decode("utf-8")), sha256=hashlib.sha256(raw).hexdigest(), path=rel(path))


def feature_types(lexicon):
    return dict(load_lexicon(lexicon).types)


# ----------------------------------------------------------------------------- features


def normalize_text(text):
    return " ".join(str(text).translate(_DASHES).split())


def extract_features(text, lexicon):
    """Problem statement -> {feature: bool | int}. Deterministic; sorted keys. `lexicon` is a Lexicon or a path
    (None = default file); pass a loaded Lexicon when extracting for many problems."""
    if not isinstance(text, str):
        raise TypeError("extract_features takes the problem statement (str) only")
    lex = load_lexicon(lexicon)
    t = normalize_text(text)
    out = {"numeric_literal_count": len(_NUM_LITERAL_RE.findall(t)), "word_count": len(t.split())}
    for name, (kind, pats) in lex.features.items():
        if kind == "any":
            out[name] = any(p.search(t) is not None for p in pats)
        else:
            out[name] = sum(len(p.findall(t)) for p in pats)
    return dict(sorted(out.items()))


def features_sha256(features):
    canon = json.dumps(features, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------- rules


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _walk(rule, where, types):
    """Syntax check (and, when `types` is given, name and type check). Returns the set of feature names used."""
    if isinstance(rule, str):
        if rule != ALWAYS:
            raise ValueError(f"{where}: the only string rule is {ALWAYS!r}, got {rule!r}")
        return set()
    if not isinstance(rule, dict):
        raise ValueError(f"{where}: a rule is {ALWAYS!r} or an object, got {type(rule).__name__}")
    keys = set(rule)
    if "feature" in keys:
        if keys != {"feature", "op", "value"}:
            raise ValueError(f"{where}: a feature test has exactly the keys feature, op, value; got {sorted(keys)}")
        name, op, value = rule["feature"], rule["op"], rule["value"]
        _check_name(name, where)
        if op not in OPS:
            raise ValueError(f"{where}: op {op!r} not in {sorted(OPS)}")
        if not (isinstance(value, bool) or _is_number(value)):
            raise ValueError(f"{where}: value must be a bool or a number, got {value!r}")
        if types is not None:
            if name not in types:
                raise ValueError(f"{where}: unknown feature {name!r} (known: {', '.join(sorted(types))})")
            if types[name] == "bool" and (op not in BOOL_OPS or not isinstance(value, bool)):
                raise ValueError(f"{where}: bool feature {name!r} takes == / != with true or false")
            if types[name] == "int" and not _is_number(value):
                raise ValueError(f"{where}: count feature {name!r} takes a number")
        return {name}
    if keys in ({"all"}, {"any"}):
        (k,) = keys
        subs = rule[k]
        if not isinstance(subs, list) or not subs:
            raise ValueError(f"{where}: '{k}' takes a non-empty list of rules")
        used = set()
        for i, sub in enumerate(subs):
            used |= _walk(sub, f"{where}.{k}[{i}]", types)
        return used
    if keys == {"not"}:
        return _walk(rule["not"], f"{where}.not", types)
    raise ValueError(f"{where}: unknown rule form with keys {sorted(keys)} (use feature/op/value, all, any, not)")


def rule_features(rule, where="rule"):
    """Feature names a rule refers to (syntax-checked)."""
    return _walk(rule, where, None)


def check_rule(rule, types, where="rule"):
    """Full check against a feature-type table; returns the sorted feature names used."""
    return sorted(_walk(rule, where, types))


def eval_rule(rule, features):
    """Evaluate a (checked) rule on a feature dict. Every branch is evaluated, so a missing feature always raises."""
    if isinstance(rule, str):
        if rule == ALWAYS:
            return True
        raise ValueError(f"unknown rule {rule!r}")
    if "feature" in rule:
        name, op, value = rule["feature"], rule["op"], rule["value"]
        if name not in features:
            raise ValueError(f"feature {name!r} missing from the problem features")
        got = features[name]
        if isinstance(value, bool):
            if not isinstance(got, bool):
                raise ValueError(f"feature {name!r} is not a bool ({got!r})")
        elif not _is_number(got):
            raise ValueError(f"feature {name!r} is not a number ({got!r})")
        return bool(OPS[op](got, value))
    if "all" in rule:
        vals = [eval_rule(r, features) for r in rule["all"]]
        return all(vals)
    if "any" in rule:
        vals = [eval_rule(r, features) for r in rule["any"]]
        return any(vals)
    if "not" in rule:
        return not eval_rule(rule["not"], features)
    raise ValueError(f"unknown rule form {sorted(rule)}")


def gene_rule(gene):
    """The gene's activation rule; a gene without an `activation` field is always active."""
    act = gene.get("activation")
    if act is None:
        return ALWAYS
    return act["rule"]


def check_activation(act, types, where="activation"):
    """Validate a gene's `activation` field. `types=None` checks syntax only. Returns the sorted feature names used."""
    if not isinstance(act, dict):
        raise ValueError(f"{where}: must be an object")
    unknown = set(act) - set(ACTIVATION_KEYS)
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)} (allowed: {', '.join(ACTIVATION_KEYS)})")
    if "rule" not in act:
        raise ValueError(f"{where}: 'rule' is required")
    if "rationale" in act and not isinstance(act["rationale"], str):
        raise ValueError(f"{where}: rationale must be a string")
    ev = act.get("devEvidence", [])
    if not isinstance(ev, list) or not all(isinstance(x, str) and x for x in ev):
        raise ValueError(f"{where}: devEvidence must be a list of dev case ids")
    return sorted(_walk(act["rule"], f"{where}.rule", types))


# ----------------------------------------------------------------------------- examples (template for gene authors)


def load_examples(path=None):
    path = path or DEFAULT_EXAMPLES
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    if doc.get("schemaVersion") != EXAMPLES_SCHEMA:
        raise ValueError(f"examples: schemaVersion must be {EXAMPLES_SCHEMA}")
    if not isinstance(doc.get("genes"), dict):
        raise ValueError("examples: 'genes' must be an object {geneId: {active: [...], inactive: [...]}}")
    return doc


def check_activation_examples(genes, examples_doc, lexicon):
    """Every gene with a rule other than "always" needs >= MIN_EXAMPLES self-written texts that activate it and
    >= MIN_EXAMPLES that do not, and each text must evaluate as labelled. Returns a list of problems (empty = ok)."""
    lex = load_lexicon(lexicon)
    ex = examples_doc.get("genes", {})
    problems = []
    ruled = {}
    for g in genes:
        if gene_rule(g) != ALWAYS:
            ruled.setdefault(g["geneId"], []).append(g)
    for gid in sorted(set(ex) - set(ruled)):
        problems.append(f"{gid}: examples given but the library has no gene with a non-trivial activation rule")
    for gid in sorted(ruled):
        e = ex.get(gid) or {}
        unknown = set(e) - {"active", "inactive"}
        if unknown:
            problems.append(f"{gid}: unknown keys {sorted(unknown)}")
        pos, neg = e.get("active") or [], e.get("inactive") or []
        if len(pos) < MIN_EXAMPLES or len(neg) < MIN_EXAMPLES:
            problems.append(f"{gid}: needs >= {MIN_EXAMPLES} active and >= {MIN_EXAMPLES} inactive examples "
                            f"(has {len(pos)} / {len(neg)})")
        for g in ruled[gid]:
            rule = gene_rule(g)
            for label, texts, want in (("active", pos, True), ("inactive", neg, False)):
                for i, t in enumerate(texts):
                    got = eval_rule(rule, extract_features(t, lex))
                    if got is not want:
                        problems.append(f"{gid} {g['version']}: {label}[{i}] evaluates to {got}")
    return problems


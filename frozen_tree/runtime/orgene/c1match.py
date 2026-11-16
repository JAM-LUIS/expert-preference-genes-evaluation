"""C1 length matching in tokens and the matching report (E11; design D3; todo A1-07, A0-08, A1-30).

Rule (D3). The C1 system prompt is matched to the C3 system prompt in tokens of the main model: the target is the
mean, over the dev cases of the correctness-signal set (analysis set dev_signal55: MAMO cleaned dev 30 + IndustryOR
dev 25), of the qwen3 token count of each case's own C3 system prompt (per-problem activation, E04). The C1 prompt
is the v5 construction (the header, then a prefix of the pool bullets in file order); of the prefixes within
target*(1+-tol), tol = 0.05, the one closest to the target is taken. (v5 appended bullets until the next one would
overshoot, which lands near the upper edge, +3 to +5 % in tokens; the closest prefix removes that bias and keeps the
API tokenizer's ratio inside the band more often. The character rule keeps v5's greedy choice for the regression.)
No prefix in the band raises C1MatchError: a pool that is too short is an error that 1C fixes by adding generic
entries, never a warning. The report also gives the ratio against the C3 prompt with every C3 gene active and the
per-case ratio distribution.

Only dev cases. Every case id handed to the matching must be a dev id of a frozen split (DevOnlyError otherwise),
and only those lines of the cases files are parsed (load_dev_cases): no test statement is ever read. The C3 dev
prompts are built from the dev cases' problem features only.

Second tokenizer and C1-api (rule written before any API run). The same numbers are computed with the API model's
offline tokenizer (tiktoken, API_ENCODING, provisional until the API model is chosen, D6). When the qwen-matched C1,
counted with the API tokenizer, is outside 1+-tol of the dev mean of the C3 prompts counted with that tokenizer, the
API model gets C1-api, built by the same rule (same header, same pool, same order, closest in-band prefix) with the
API tokenizer as the measure and the API dev mean as the target; otherwise the API model uses the qwen-matched C1
unchanged. See API_RULE.

Rewrites (default 8 of the engineering plan 6.3; todo A1-30). Prompt rewrites live in conditions/variants/<v>/ and
are chosen by the registry field `variant`. The C1 of variant v is matched to the C3 of the same-named variant v
(its own templates, contract frame included). A rewritten C1 pool paraphrases the working pool one to one.

Generic entries only. The C1 pool may only hold generic expert guidance, without gene content (decided 2026-09-29).
A keyword table is drawn from the gene library (code terms, hyphenated technical terms, word trigrams and the rule
names of the geneIds; what the shared base prompt already says is left out). No pool bullet and no header line of
C1, in the working templates or in a rewrite, may hit it; the v5 bullets are not exempt (8 of the 47 hit the table
and are replaced in 1C: conditions/drafts/C1_pool_r1.draft.md). The table screens wording; it does not prove that
an entry carries no gene content (an entry can restate a gene in other words and pass).

Report: `orgene_cli.py c1-match` writes c1_matching_report.json (default conditions/c1_matching_report.json, the
frozen file; 1D regenerates it on the final release). `orgene_cli.py requests` builds C1 only from a report that is
ok and current (gene library, lexicon, templates, C3 configuration, dev set, tolerance, tokenizer, and the dev C3
system prompts themselves, rebuilt from the dev cases and compared by digest), replaying the matching with the
tokenizer and checking that it gives the recorded prompt.
"""
import hashlib
import json
import math
import os
import re
import sys

from . import conditions as C
from . import configs as CF
from . import genes as G
from .conditions import C1MatchError
from .paths import ROOT, rel, resolve

REPORT_SCHEMA = "orgene.r1.c1_matching_report.v1"
DEFAULT_REPORT = os.path.join(ROOT, "conditions", "c1_matching_report.json")
DEFAULT_GENES = os.path.join(ROOT, "genes", "genes.r1.jsonl")
DEFAULT_COND_DIR = os.path.join(ROOT, "conditions")
DEFAULT_SPLITS = os.path.join(ROOT, "data", "splits")
VENV_TOOLS_RECORD = os.path.join(ROOT, "configs", "venv_tools.json")
DEV_SET = "dev_signal55"
TOLERANCE = 0.05
MATCH_MODES = ("tokens", "chars")
QWEN_MODEL = "qwen3:8b"
# The API model is not chosen yet (D6); o200k_base is the current OpenAI encoding. Change it here (and rerun c1-match)
# once the model is chosen; the report records the encoding, its file hash and the tiktoken version.
API_ENCODING = "o200k_base"
TOKENIZERS = ("qwen", "api")
# Test hook: a function (which, **kw) -> counter that replaces the real tokenizers in the two commands.
MAKE_COUNTER = None

MATCH_RULE = ("C1 = C1 header + the prefix of the pool bullets (file order) whose qwen3 token count is closest to the "
              "target among the prefixes within target*(1+-tol); no prefix in the band is an error; target = mean over "
              f"the dev cases of {DEV_SET} of the qwen3 token count of each case's own C3 system prompt (per-problem "
              "activation); tol = 0.05. A rewrite v matches its C1 to its own C3 (same variant name).")
API_RULE = ("C1-api: if the qwen-matched C1, counted with the API tokenizer, is outside 1+-tol of the dev mean of the "
            "C3 system prompts counted with the API tokenizer, the API model gets C1-api = the same rule (same header, "
            "same pool, same order, in-band prefix closest to the target) with the API tokenizer as the measure and "
            "the API dev mean as the target; otherwise the API model uses the qwen-matched C1 unchanged.")

# The 47 bullets of the v5 pool (conditions/C1_generic_expert_pool.md as frozen with release 1.0), first 16 hex digits
# of the sha256 of each '- ' line. Only for reporting (how much of a pool is v5's): every bullet gets the wording check.
V5_POOL_BULLETS = frozenset((
    "ce43a5ab9f3d2c3d", "cfcbc787715b5d4e", "bd9690279c29fb0b", "3bad12ea48768c87", "192a2921a6549079",
    "75ca55b079130306", "4071b02fa96b7342", "3fd2fa9d219134e8", "16ae9e25da9f8b56", "5edd11a6581abacf",
    "374c667327c46e37", "7e1c1268687ca25e", "78c8c8f7ab01a8a7", "822dd6e9df5024df", "f56c17648e3909b9",
    "77559830351d9f85", "e32dd13aa0793b07", "a730a2ce144a90f8", "11a8d9406c3830d7", "b9dc1725e591a13b",
    "420296d76a032a44", "fdbc28ff105a4f9c", "e3c12199a51d2457", "144e03cf442d360f", "92738cce0608511b",
    "b9fb18d7d36dbace", "c74fabbb8f5234c1", "cd4b77c057957958", "2d33dfa4572cc440", "27fbd9bb36b74492",
    "b297a51a000d53f9", "f834eae812a5a874", "99b07ae280e19e4e", "874edd2df957463e", "426227fd18dbf1d8",
    "d215128fb5bbece6", "bacddd6a6c389da2", "5e0e0528103b61c7", "2781b1acd8a02019", "12d6d79e4bbdc030",
    "76f7658a05bf456f", "a989b99ff835f0d6", "3536dad44ffaeed0", "9fd217e597d0cda4", "3575ff41288f8738",
    "fd3ddcc37290d547", "c5a4b321ed4e4c47",
))


class DevOnlyError(C1MatchError):
    """A case handed to the C1 matching is not a dev case of a frozen split."""


def _sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _canon_sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ dev cases only


def split_id_sets(split_root=None):
    """{"dev": set, "sealed": set, "dirs": [...]} over the frozen split directories (data/splits/<benchmark>/).
    Sealed = test ids and, where present, eng_holdout ids. The id files are checked against their locks."""
    from . import split as S
    root = split_root or DEFAULT_SPLITS
    dev, sealed, dirs = set(), set(), []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isfile(os.path.join(d, "SPLIT_LOCK.json")):
            continue
        lock, dev_ids, test_ids = S.read_lock_dir(d)
        dev |= set(dev_ids)
        sealed |= set(test_ids)
        eng = os.path.join(d, "eng_holdout_ids.json")
        if os.path.isfile(eng):
            sealed |= set(json.load(open(eng, encoding="utf-8")))
        dirs.append({"dir": d, "cases_path": lock.get("cases_path")})
    if not dirs:
        raise DevOnlyError(f"no frozen split directory under {rel(root)}")
    return {"dev": dev, "sealed": sealed, "dirs": dirs}


def assert_dev_ids(case_ids, split_root=None):
    """Every id must be a dev id of a frozen split and none a sealed (test / held-out) id. Raises DevOnlyError
    (an explicit check, not an `assert` statement, so that it also runs under python -O). Returns the sorted ids."""
    ids = list(case_ids)
    if not ids:
        raise DevOnlyError("no case ids to match C1 on")
    if len(set(ids)) != len(ids):
        raise DevOnlyError("case ids repeat")
    sets = split_id_sets(split_root)
    not_dev = sorted(set(ids) - sets["dev"])
    sealed = sorted(set(ids) & sets["sealed"])
    if not_dev or sealed:
        bad = sorted(set(not_dev) | set(sealed))
        raise DevOnlyError(f"C1 is matched on dev cases only; {len(bad)} id(s) are not dev ids of a frozen split "
                           f"({len(sealed)} of them test or held-out): {bad[:5]}")
    return sorted(ids)


def dev_set_ids(name=DEV_SET, root=None):
    """(sorted ids, info) of an analysis set that must be a dev set (strict: no pending list)."""
    from . import analysis_sets as AS
    res = AS.analysis_set(name, root=root, strict=True)
    if res["split"] != "dev":
        raise DevOnlyError(f"analysis set {name!r} is a {res['split']} set; C1 is matched on dev only")
    info = {"name": name, "n": res["n"], "sha256": res["sha256"],
            "by_benchmark": {b: len(v) for b, v in sorted(res["by_benchmark"].items())}}
    return list(res["ids"]), info


_CASE_ID_AT_START = re.compile(rb'^\{"case_id":\s*"([^"\\]+)"')


def load_dev_cases(case_ids, cases_paths=None, split_root=None):
    """The case records of `case_ids`, which must all be dev ids (assert_dev_ids first). Each cases file is read
    line by line and only the lines of the wanted ids are parsed: the id is taken from the start of the raw line
    ('{"case_id": "..."'); a line that does not start that way (other than the header) stops the loading rather
    than being parsed. Returns the records sorted by case id."""
    ids = set(assert_dev_ids(case_ids, split_root))
    if cases_paths is None:
        cases_paths = [resolve(d["cases_path"]) for d in split_id_sets(split_root)["dirs"] if d["cases_path"]]
    found = {}
    for path in cases_paths:
        with open(path, "rb") as f:
            for n, raw in enumerate(f, 1):
                if not raw.strip() or raw.startswith(b'{"_header"'):
                    continue
                m = _CASE_ID_AT_START.match(raw)
                if not m:
                    raise ValueError(f"{rel(path)} line {n}: no case id at the start of the line; not parsing it")
                cid = m.group(1).decode("ascii", "replace")
                if cid in ids:
                    rec = json.loads(raw.decode("utf-8"))
                    if rec.get("case_id") != cid:
                        raise ValueError(f"{rel(path)} line {n}: the case id at the start is not the record's")
                    found[cid] = rec
    missing = sorted(ids - set(found))
    if missing:
        raise DevOnlyError(f"{len(missing)} dev case(s) not found in the cases files: {missing[:5]}")
    return [found[c] for c in sorted(found)]


# ------------------------------------------------------------------ tokenizers as measures


class TokenMeasure:
    """text -> token count through a tokcount counter (count(text), and counts(texts) when it has one), memoised.
    `name` goes into the C1 match info ('tokens:<label>')."""

    def __init__(self, counter, label):
        self.counter = counter
        self.label = label
        self.name = f"tokens:{label}"
        self._memo = {}

    def prefetch(self, texts):
        todo = [t for t in dict.fromkeys(texts) if t not in self._memo]
        if not todo:
            return
        if hasattr(self.counter, "counts"):
            got = self.counter.counts(todo)
        else:
            got = [self.counter.count(t) for t in todo]
        self._memo.update(zip(todo, got))

    def __call__(self, text):
        if text not in self._memo:
            self._memo[text] = self.counter.count(text)
        return self._memo[text]

    def identity(self):
        return {"label": self.label, "identity_sha256": getattr(self.counter, "identity_sha256", None),
                "identity": self.counter.identity() if hasattr(self.counter, "identity") else None}


def qwen_counter(model=QWEN_MODEL, **kw):
    """The main model's local counter (E09: llama-tokenize over the Ollama weights blob). Raises TokenizerError."""
    from .tokcount import OllamaCounter
    return OllamaCounter(model, **kw)


def api_counter(encoding=API_ENCODING, record=None, tools_root=None, python=None):
    """tiktoken counter for the API model, over the encoding file registered in configs/venv_tools.json.
    tools_root: where .venv-tools/ and .cache/tiktoken/ are (default the repository root)."""
    from .tokcount import ENV_TOOLS_PY, TiktokenCounter, TokenizerError
    rec = json.load(open(record or VENV_TOOLS_RECORD, encoding="utf-8"))
    encs = (rec.get("tiktoken") or {}).get("encodings") or {}
    if encoding not in encs:
        raise TokenizerError(f"encoding {encoding!r} is not registered in {rel(record or VENV_TOOLS_RECORD)}")
    e = encs[encoding]
    root = tools_root or ROOT
    python = python or os.environ.get(ENV_TOOLS_PY) or os.path.join(root, rec.get("venv", ".venv-tools"), "bin", "python")
    return TiktokenCounter(f"c1match:{encoding}", encoding, os.path.join(root, e["file"]), e["sha256"], python=python)


# ------------------------------------------------------------------ gene wording


_STOP = frozenset((
    "a an the of to in on for and or not no nor is are be been by with as at from that this it its every each any all "
    "one only do does must may should than then when if into over before after same other their they them you your "
    "what which there these those so but never always up out whose make sure use using write keep also both whether "
    "unless can could will would has have how where while such like within without between about more less most "
    "least just very own per").split())
_WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_CODE_PATTERNS = (
    r"`[^`\n]+`",                                       # code spans
    r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+(?:\(\))?",      # dotted names (pulp.value, LpVariable.dicts)
    r"\b[a-z]+[A-Z]\w*\b",                              # lowerCamel (lpSum, maxApplications)
    r"\b[A-Z][a-z]+[A-Z]\w*\b",                         # UpperCamel with an inner capital (LpMinimize, PuLP)
    r"\b[A-Za-z0-9]+_[A-Za-z0-9_]+\b",                  # snake / constant names
    r"\b\w+\(\)",                                       # calls: min(), round()
    r"\b\w+\[[^\]\n]*\](?:\[[^\]\n]*\])?",              # subscripts: d[i, j], d[i][j]
    r"\b\w+=",                                          # keyword arguments: cat=
    r"\b\d+e\d+\b",                                     # 1e6
)
GENE_TEXT_FIELDS = ("preference.statement", "preference.rationale", "contract.required", "contract.forbidden",
                    "contract.checks", "repair.instruction")


def _stem(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _words(text):
    return [_stem(w) for w in _WORD.findall(text.lower())]


def _trigrams(ws):
    return {tuple(ws[i:i + 3]) for i in range(len(ws) - 2)}


def gene_texts(g):
    """The wording of a gene record: statement, rationale, contract lines, repair instruction."""
    p, c, r = g.get("preference") or {}, g.get("contract") or {}, g.get("repair") or {}
    out = [p.get("statement"), p.get("rationale"), r.get("instruction")]
    for k in ("required", "forbidden", "checks"):
        out += list(c.get(k) or [])
    return [t for t in out if isinstance(t, str) and t.strip()]


def _code_terms(text):
    out = set()
    for pat in _CODE_PATTERNS:
        for m in re.findall(pat, text):
            t = m.strip("`").strip()
            if "." in t and not any(len(part) >= 3 for part in re.split(r"[.()]", t)):
                continue  # abbreviations such as e.g / i.e
            if t:
                out.add(t)
    return out


def gene_keyword_table(store, base_texts=()):
    """Keyword table of the gene library's wording (what a generic C1 entry must not contain).

    code:     code-shaped terms (code spans, dotted names, camelCase, snake_case, calls, subscripts, key=, 1e6)
    hyphen:   hyphenated words (big-m, cross-multiply, tuple-keyed, ...), matched as word prefixes
    trigrams: word trigrams (lower case, light plural stemming) with at least two non-function words
    rule_names: the words of each geneId's rule name when it has two or more (tuple key indexing, ...)
    Whatever occurs in `base_texts` (the base prompt every condition shares) is left out.
    """
    base = "\n".join(base_texts)
    base_tri = _trigrams(_words(base))
    code, hyph, tri, names = set(), set(), set(), set()
    for g in store:
        for t in gene_texts(g):
            code |= _code_terms(t)
            ws = _words(t)
            hyph |= {w for w in ws if "-" in w}
            for ng in _trigrams(ws):
                if sum(w not in _STOP for w in ng) >= 2 and ng not in base_tri:
                    tri.add(ng)
        tail = str(g.get("geneId", "")).rsplit(".", 1)[-1].split("_")
        if len(tail) >= 2:
            names.add(" ".join(_words(" ".join(tail))))
    code = {c for c in code if c not in base}
    hyph = {h for h in hyph if h not in set(_words(base))}
    table = {"code": sorted(code), "hyphen": sorted(hyph), "trigrams": sorted(" ".join(t) for t in tri),
             "rule_names": sorted(names)}
    table["sha256"] = _canon_sha({k: table[k] for k in ("code", "hyphen", "trigrams", "rule_names")})
    return table


def wording_hits(text, table):
    """Sorted 'kind:term' hits of the keyword table in one text (a pool bullet, a header line)."""
    hits = set()
    for c in table["code"]:
        if c in text:
            hits.add("code:" + c)
    ws = _words(text)
    tri = {" ".join(t) for t in _trigrams(ws)}
    hits |= {"trigram:" + t for t in tri.intersection(table["trigrams"])}
    for w in ws:
        for h in table["hyphen"]:
            if w.startswith(h):
                hits.add("hyphen:" + h)
    s = " " + " ".join(ws) + " "
    for n in table["rule_names"]:
        if " " + n + " " in s:
            hits.add("rule_name:" + n)
    return sorted(hits)


def bullet_key(bullet):
    return _sha_text(bullet)[:16]


def pool_wording(T, table, base_T=None):
    """Wording check of a C1 template: no pool bullet and no header line may hit the keyword table (the v5 bullets
    included). A rewrite (base_T = the working templates) must also paraphrase the working pool one to one (the same
    number of bullets, in the same order). Returns a dict with the hits and 'errors'."""
    header, bullets = C.c1_parts(T)
    what = "pool" if base_T is None else "rewritten pool"
    out = {"n_bullets": len(bullets), "n_v5_bullets": sum(bullet_key(b) in V5_POOL_BULLETS for b in bullets),
           "header_hits": wording_hits(" ".join(header), table), "bullets_with_hits": [], "errors": []}
    if out["header_hits"]:
        out["errors"].append(f"the C1 header carries gene wording: {out['header_hits']}")
    for i, b in enumerate(bullets, 1):
        h = wording_hits(b, table)
        if h:
            out["bullets_with_hits"].append({"bullet": i, "v5": bullet_key(b) in V5_POOL_BULLETS, "hits": h})
            out["errors"].append(f"{what} bullet {i} carries gene wording: {h}")
    if base_T is not None:
        bb = C.c1_parts(base_T)[1]
        if len(bb) != len(bullets):
            out["errors"].append(f"a rewritten pool paraphrases the working pool one to one: {len(bullets)} bullets, "
                                 f"the working pool has {len(bb)}")
    return out


def candidate_entries(path):
    """The '- ' entries of a candidate file (comment lines and prose ignored)."""
    with open(path, encoding="utf-8") as f:
        return [ln for ln in f.read().splitlines() if ln.startswith("- ")]


def base_texts(cond_dir=None):
    """The base prompt every condition shares (base rules, C0 line, spec schema summary) of conditions/."""
    T = C.load_templates(cond_dir)
    return [T["texts"]["base"], T["texts"]["C0"], T["texts"]["schema_summary"]]


# ------------------------------------------------------------------ matching


def _quantile(sorted_vals, q):
    """Linear interpolation between order statistics (numpy's default 'linear' method)."""
    if not sorted_vals:
        return None
    pos = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def distribution(values, tolerance=None, digits=4):
    v = sorted(values)
    if not v:
        return {"n": 0}
    r = lambda x: round(x, digits)  # noqa: E731
    out = {"n": len(v), "min": r(v[0]), "p10": r(_quantile(v, 0.10)), "q1": r(_quantile(v, 0.25)),
           "median": r(_quantile(v, 0.5)), "q3": r(_quantile(v, 0.75)), "p90": r(_quantile(v, 0.90)),
           "max": r(v[-1]), "mean": r(sum(v) / len(v))}
    if tolerance is not None:
        out["n_within_tolerance"] = sum(1 - tolerance <= x <= 1 + tolerance for x in v)
    return out


def match_c1(T, store, match_mode="tokens", measure=None, dev_cases=None, features_by_case=None, c3_config=None,
             tolerance=TOLERANCE, split_root=None):
    """(C1 text, match info) for templates T.

    match_mode "chars": the v5 rule (characters against the C3 prompt with every C3 gene active), for the release 1.0
    regression. match_mode "tokens": `measure` (a TokenMeasure) against the mean over `dev_cases` (dev ids only,
    checked) of each case's C3 system prompt built from `c3_config`. Raises C1MatchError when C1 cannot be matched.
    """
    if match_mode == "chars":
        if measure not in (None, len):
            raise ValueError("match_mode 'chars' measures characters")
        return C._prompt_c1(T, C.c1_default_target(T, store), tolerance)
    if match_mode != "tokens":
        raise ValueError(f"match_mode must be one of {MATCH_MODES}")
    if measure is None or dev_cases is None:
        raise ValueError("token matching needs a token measure and the dev cases")
    assert_dev_ids([c["case_id"] for c in dev_cases], split_root)
    target = C.c1_default_target(T, store, measure=measure, cases=dev_cases, features_by_case=features_by_case,
                                 c3_config=c3_config)
    return C._prompt_c1(T, target, tolerance, measure=measure)


def _side(T, m, c3, c3_all, prefixes, tolerance):
    """Numbers of one tokenizer for one variant: dev target, C1 match (or its failure), ratios. Returns (dict, text)."""
    counts = {cid: m(text) for cid, text in c3}
    target = sum(counts.values()) / len(counts)
    n_all = m(c3_all)
    full = m(prefixes[-1])
    out = {"c3_dev_tokens": distribution(counts.values(), digits=2), "c3_all_active_tokens": n_all,
           "target": target, "c1_full_pool_tokens": full, "c1_full_pool_ratio": round(full / target, 4)}
    try:
        text, info = C._prompt_c1(T, target, tolerance, measure=m)
    except C1MatchError as e:
        need = math.ceil((1 - tolerance) * target) - full
        out["c1"] = {"ok": False, "error": str(e), "bullets_available": len(prefixes) - 1,
                     "tokens_short_of_band": max(need, 0), "tokens_short_of_target": max(math.ceil(target) - full, 0)}
        return out, None
    out["c1"] = {"ok": True, "bullets_used": info["bullets_used"], "bullets_available": info["bullets_available"],
                 "tokens": info["length"], "chars": len(text), "sha256": _sha_text(text)}
    out.update(_ratios(m, text, counts, n_all, target, tolerance))
    return out, text


def _ratios(m, text, counts, n_all, target, tolerance):
    n = m(text)
    per = {cid: n / k for cid, k in sorted(counts.items())}
    return {"ratio_to_dev_mean": round(n / target, 4), "ratio_all_active": round(n / n_all, 4),
            "per_case_ratio": distribution(per.values(), tolerance),
            "per_case_ratio_by_case": {cid: round(r, 4) for cid, r in per.items()}}


def c3_dev_prompts(T, store, c3_config, dev_cases, features_by_case):
    """[(case id, C3 system prompt)] of the dev cases for templates T (per-problem activation from the features)."""
    out = []
    for case in dev_cases:
        f = None if features_by_case is None else features_by_case[case["case_id"]]
        text, _ = C.build_prompt(c3_config, case, store, features=f, templates=T, variant=T["variant"])
        out.append((case["case_id"], text))
    return out


def c3_dev_digest(pairs):
    """sha256 over the sorted (case id, sha256 of the C3 system prompt) pairs. The matching target is a function of
    these texts and the tokenizer: the same digest and the same tokenizer give the same target, whatever code
    (features, activation, contract compilation, templates) produced the texts."""
    return _canon_sha(sorted([cid, _sha_text(t)] for cid, t in pairs))


def evaluate_variant(T, store, c3_config, dev_cases, features_by_case, measures, tolerance, table, base_T=None):
    """Matching numbers of one prompt family (the working templates, or a rewrite) on the dev cases.
    measures: {"qwen": TokenMeasure, "api": TokenMeasure or None}. Never raises for a failed match: the failure is
    recorded (ok false) so that 1C sees how far the pool is from the band."""
    c3 = c3_dev_prompts(T, store, c3_config, dev_cases, features_by_case)
    c3_all = C.c3_all_active_prompt(T, store, c3_config["gene_scope"])
    prefixes = C.c1_prefix_texts(T)
    header, bullets = C.c1_parts(T)
    distinct = sorted({_sha_text(t) for _, t in c3})
    res = {"variant": T["variant"], "templates": T["files"],
           "c1_pool": {"n_bullets": len(bullets), "n_v5_bullets": sum(bullet_key(b) in V5_POOL_BULLETS for b in bullets)},
           "c3_dev": {"n_cases": len(c3), "n_distinct_prompts": len(distinct), "system_prompt_sha256": distinct,
                      "prompts_sha256": c3_dev_digest(c3)},
           "c3_all_active": {"system_prompt_sha256": _sha_text(c3_all)},
           "tokenizers": {}, "errors": []}
    texts = [t for _, t in c3] + [c3_all] + prefixes
    mq = measures["qwen"]
    mq.prefetch(texts)
    q, q_text = _side(T, mq, c3, c3_all, prefixes, tolerance)
    res["tokenizers"]["qwen"] = q
    if not q["c1"]["ok"]:
        res["errors"].append(f"qwen: {q['c1']['error']}")
    ma = measures.get("api")
    if ma is not None:
        ma.prefetch(texts)
        counts = {cid: ma(t) for cid, t in c3}
        target = sum(counts.values()) / len(counts)
        n_all = ma(c3_all)
        full = ma(prefixes[-1])
        a = {"c3_dev_tokens": distribution(counts.values(), digits=2), "c3_all_active_tokens": n_all, "target": target,
             "c1_full_pool_tokens": full, "c1_full_pool_ratio": round(full / target, 4)}
        if q_text is None:
            a["qwen_c1"] = None
            a["c1_api_needed"] = None
            a["c1_api"] = None
        else:
            a["qwen_c1"] = _ratios(ma, q_text, counts, n_all, target, tolerance)
            a["qwen_c1"]["tokens"] = ma(q_text)
            r = a["qwen_c1"]["ratio_to_dev_mean"]
            a["c1_api_needed"] = not (1 - tolerance <= r <= 1 + tolerance)
            a["c1_api"] = None
            if a["c1_api_needed"]:
                side, api_text = _side(T, ma, c3, c3_all, prefixes, tolerance)
                a["c1_api"] = {k: side[k] for k in side if k not in ("c3_dev_tokens", "c3_all_active_tokens", "target")}
                if api_text is None:
                    res["errors"].append(f"api: {side['c1']['error']}")
                else:
                    a["c1_api"]["qwen_tokens"] = mq(api_text)
        res["tokenizers"]["api"] = a
    w = pool_wording(T, table, base_T)
    res["gene_wording"] = w
    res["errors"] += w["errors"]
    res["ok"] = not res["errors"]
    return res


def variant_names(cond_dir=None):
    """Rewrite names = the directories under <cond_dir>/variants/."""
    vroot = os.path.join(cond_dir or DEFAULT_COND_DIR, "variants")
    if not os.path.isdir(vroot):
        return []
    return sorted(d for d in os.listdir(vroot) if os.path.isdir(os.path.join(vroot, d)) and not d.startswith("."))


def variant_status(cond_dir, variant):
    """'draft' / 'frozen' / None from the 'status:' line of conditions/variants/<v>/README.md."""
    if variant is None:
        return None
    p = os.path.join(cond_dir or DEFAULT_COND_DIR, "variants", variant, "README.md")
    if not os.path.isfile(p):
        return None
    for line in open(p, encoding="utf-8"):
        m = re.match(r"\s*status:\s*([a-z]+)", line.strip().lower())
        if m:
            return m.group(1)
    return None


def vkey(variant):
    return "base" if variant is None else variant


def build_report(store, genes_path, reg, dev_cases, dev_info, lexicon, measures, cond_dir=None, variants=None,
                 tolerance=TOLERANCE, split_root=None):
    """The c1_matching_report dict (also when a variant cannot be matched: ok false, with its errors).

    store/genes_path: the gene library; reg: the configuration registry (its C1 and C3 configurations); dev_cases:
    the dev case records (ids checked here); lexicon: features.Lexicon of the per-problem features; measures:
    {"qwen": TokenMeasure, "api": TokenMeasure or None}.
    """
    from . import features as F
    from .split import ids_sha256
    ids = assert_dev_ids([c["case_id"] for c in dev_cases], split_root)
    if ids_sha256(ids) != dev_info["sha256"] or len(ids) != dev_info["n"]:
        raise C1MatchError(f"the {len(ids)} cases given are not the dev set {dev_info['name']!r} "
                           f"({dev_info['n']} cases, ids sha256 {dev_info['sha256'][:12]}…)")
    c3_config, c1_config = _prompt_config(reg, "C3"), _prompt_config(reg, "C1")
    feats = {c["case_id"]: F.extract_features(c["text"], lexicon) for c in dev_cases}
    table = gene_keyword_table(store, base_texts(cond_dir))
    base_T = C.load_templates(cond_dir)
    out = {"schema": REPORT_SCHEMA, "status": "dev matching record; regenerated on the frozen release in 1D",
           "rule": MATCH_RULE, "api_rule": API_RULE, "tolerance": tolerance, "match_mode": "tokens",
           "dev_set": dict(dev_info, n_loaded=len(dev_cases)),
           "inputs": {"gene_library": {"path": rel(genes_path), "sha256": _sha_file(genes_path),
                                       "n_genes": len(store)},
                      "lexicon": {"path": getattr(lexicon, "path", None), "sha256": lexicon.sha256},
                      "registry": {"path": reg["path"], "sha256": reg["sha256"]},
                      "c3_config": c3_config, "c1_config": c1_config["id"], "cond_dir": rel(cond_dir or DEFAULT_COND_DIR)},
           "tokenizers": {k: (m.identity() if m is not None else None) for k, m in measures.items()},
           "gene_keyword_table": {"sha256": table["sha256"], "n_terms": {k: len(table[k]) for k in
                                                                         ("code", "hyphen", "trigrams", "rule_names")}},
           "variants": {}}
    for v in [None] + list(variants if variants is not None else variant_names(cond_dir)):
        T = base_T if v is None else C.load_templates(cond_dir, v)
        res = evaluate_variant(T, store, c3_config, dev_cases, feats, measures, tolerance, table,
                               base_T=None if v is None else base_T)
        res["status"] = "working" if v is None else (variant_status(cond_dir, v) or "unknown")
        out["variants"][vkey(v)] = res
    out["ok"] = all(r["ok"] for r in out["variants"].values())
    return out


def _prompt_config(reg, prompt):
    """The registry's one standard configuration that uses `prompt` and reuses nothing (the C1 / C3 configuration)."""
    hits = [c for c in reg["configs"].values() if c["prompt"] == prompt and c["round0"] == "own"
            and c.get("pipeline", "standard") == "standard" and c.get("variant") is None]
    if len(hits) != 1:
        raise C1MatchError(f"the registry must have exactly one own-round-0 {prompt} configuration without a variant, "
                           f"found {[c['id'] for c in hits]}")
    return hits[0]


def write_report(report, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")


def load_report(path=None):
    path = path or DEFAULT_REPORT
    if not os.path.isfile(path):
        raise C1MatchError(f"no C1 matching report at {rel(path)}; run `orgene_cli.py c1-match` (dev cases only) first")
    with open(path, encoding="utf-8") as f:
        rep = json.load(f)
    if rep.get("schema") != REPORT_SCHEMA:
        raise C1MatchError(f"{rel(path)} is not a C1 matching report ({REPORT_SCHEMA})")
    rep["_path"], rep["_sha256"] = rel(path), _sha_file(path)
    return rep


# ------------------------------------------------------------------ requests (orgene_cli.py requests)


class RequestsC1:
    """What `orgene_cli.py requests` needs for C1 (and the local token counts of the system prompts).

    match_mode "tokens" (default): C1 comes from the matching report, which must be ok and current; the matching is
    replayed with the tokenizer and must give the recorded prompt. "chars": the v5 rule (release 1.0 regression only).
    tokenizer "qwen" (default) builds the main model's C1; "api" builds the API model's (C1-api when the report says
    it is needed, else the qwen-matched C1). local_tokens "auto": a counter exists only when C1 needs one; "on":
    count the system prompts of every configuration; "off": never (token-matched C1 then refuses).
    """

    def __init__(self, reg, cfgs, store, genes_path, cond_dir, tolerance, lexicon_sha, match_mode="tokens",
                 report_path=None, tokenizer="qwen", local_tokens="auto", qwen_model=QWEN_MODEL, tools_root=None,
                 analysis_root=None, make_counter=None, lexicon=None):
        if match_mode not in MATCH_MODES:
            raise C1MatchError(f"C1 match mode must be one of {MATCH_MODES}")
        if tokenizer not in TOKENIZERS or local_tokens not in ("auto", "on", "off"):
            raise C1MatchError("bad C1 tokenizer or local-tokens setting")
        self.cfgs = [c for c in cfgs if c["prompt"] == "C1"]
        self.mode, self.tokenizer, self.local = match_mode, tokenizer, local_tokens
        self.store, self.genes_path, self.cond_dir, self.tolerance = store, genes_path, cond_dir, tolerance
        self.lexicon = lexicon  # path or features.Lexicon of the problem features (None: the default lexicon)
        self._make = make_counter or self._default_counter
        self._args = {"qwen_model": qwen_model, "tools_root": tools_root}
        self.measures = {}
        self.report = None
        self.by_config = {}
        if self.cfgs and match_mode == "tokens":
            if local_tokens == "off":
                raise C1MatchError("token-matched C1 needs the local tokenizer (drop --local-tokens off, or use "
                                   "--c1-match-mode chars for the v5 regression)")
            self.report = load_report(report_path)
            self._check_report(reg, lexicon_sha, analysis_root)
        if local_tokens == "on" or (self.cfgs and match_mode == "tokens"):
            self.measure(tokenizer)

    @staticmethod
    def _default_counter(which, qwen_model=QWEN_MODEL, tools_root=None):
        return qwen_counter(qwen_model) if which == "qwen" else api_counter(tools_root=tools_root)

    def measure(self, which):
        if which not in self.measures:
            self.measures[which] = TokenMeasure(self._make(which, **self._args), which)
        return self.measures[which]

    def _check_report(self, reg, lexicon_sha, analysis_root):
        rep, stale = self.report, []
        if not rep.get("ok"):
            raise C1MatchError(f"the C1 matching report {rep['_path']} is not ok: C1 is not matched "
                               f"({'; '.join(e for v in rep['variants'].values() for e in v.get('errors', []))[:400]})")
        inp = rep["inputs"]
        if inp["gene_library"]["sha256"] != _sha_file(self.genes_path):
            stale.append("gene library")
        if inp["lexicon"]["sha256"] != lexicon_sha:
            stale.append("activation lexicon")
        if inp["c3_config"] != _prompt_config(reg, "C3"):
            stale.append("C3 configuration")
        if rep["tolerance"] != self.tolerance:
            stale.append("tolerance")
        ids, info = dev_set_ids(rep["dev_set"]["name"], analysis_root)
        if info["sha256"] != rep["dev_set"]["sha256"]:
            stale.append("dev set")
        if not stale:
            stale += self._stale_c3_dev_prompts(reg, ids, inp)
        if stale:
            raise C1MatchError(f"the C1 matching report {rep['_path']} is stale ({', '.join(stale)} changed); "
                               "rerun `orgene_cli.py c1-match`")

    def _stale_c3_dev_prompts(self, reg, ids, inp):
        """Rebuild the dev C3 system prompts (dev ids only) of every variant this call builds C1 for and compare their
        digest with the report's, so that a change in the code that makes them (problem features, activation,
        contract compilation) is caught, not only a change of the recorded input files."""
        from . import features as F
        lex = F.load_lexicon(self.lexicon)
        if lex.sha256 != inp["lexicon"]["sha256"]:
            return ["activation lexicon"]
        cases = load_dev_cases(ids)
        feats = {c["case_id"]: F.extract_features(c["text"], lex) for c in cases}
        c3, out = _prompt_config(reg, "C3"), []
        for v in sorted({vkey(c.get("variant")) for c in self.cfgs}):
            var = self.report["variants"].get(v)
            if var is None:
                continue  # kwargs() names the missing variant
            try:
                T = C.load_templates(self.cond_dir, None if v == "base" else v)
            except ValueError as e:
                raise C1MatchError(str(e)) from None
            if var["c3_dev"].get("prompts_sha256") != c3_dev_digest(c3_dev_prompts(T, self.store, c3, cases, feats)):
                out.append(f"C3 dev system prompts of variant {v!r}")
        return out

    def kwargs(self, config):
        """build_requests keyword arguments for one configuration (empty unless it uses the C1 prompt)."""
        if config["prompt"] != "C1" or self.mode == "chars":
            return {}
        T = C.load_templates(self.cond_dir, config.get("variant"))
        e = self._entry(config, T)
        m = self.measure(e["tokenizer"])
        if m.identity()["identity_sha256"] != e["identity_sha256"]:
            raise C1MatchError(f"the {e['tokenizer']} tokenizer is not the one the C1 matching report was made with; "
                               "rerun `orgene_cli.py c1-match`")
        return {"c1_target": e["target"], "c1_measure": m}

    def _entry(self, config, T):
        rep = self.report
        v = vkey(config.get("variant"))
        if v not in rep["variants"]:
            raise C1MatchError(f"the C1 matching report has no entry for variant {v!r}")
        var = rep["variants"][v]
        if {k: x["sha256"] for k, x in var["templates"].items()} != {k: x["sha256"] for k, x in T["files"].items()}:
            raise C1MatchError(f"the C1 matching report is stale: the templates of variant {v!r} changed; "
                               "rerun `orgene_cli.py c1-match`")
        if not var.get("ok"):
            raise C1MatchError(f"the C1 matching report has no matched C1 for variant {v!r}")
        q = var["tokenizers"]["qwen"]
        if self.tokenizer == "api":
            a = var["tokenizers"].get("api")
            if a is None:
                raise C1MatchError("the C1 matching report has no API tokenizer numbers (it was made with --no-api)")
            if a["c1_api_needed"]:
                return {"tokenizer": "api", "target": a["target"], "sha256": a["c1_api"]["c1"]["sha256"],
                        "identity_sha256": rep["tokenizers"]["api"]["identity_sha256"], "variant": v}
        return {"tokenizer": "qwen", "target": q["target"], "sha256": q["c1"]["sha256"],
                "identity_sha256": rep["tokenizers"]["qwen"]["identity_sha256"], "variant": v}

    def record(self, config, reqs, summ):
        """After build_requests: check the C1 prompt against the report, add local token counts to the summary."""
        if config["prompt"] == "C1" and self.mode == "tokens":
            T = C.load_templates(self.cond_dir, config.get("variant"))
            e = self._entry(config, T)
            shas = {r["meta"]["system_prompt_sha256"] for r in reqs}
            if shas != {e["sha256"]}:
                raise C1MatchError(f"{config['id']}: the replayed C1 prompt is not the one in the matching report")
            self.by_config[config["id"]] = dict(e, report=self.report["_path"], report_sha256=self.report["_sha256"])
        which = self.tokenizer if self.tokenizer in self.measures else next(iter(self.measures), None)
        if which is None:
            summ["system_prompt_tokens_local"] = None
            summ["system_prompt_tokens_note"] = ("not computed: no counter in this call (--local-tokens on counts every "
                                                 "system prompt)" if self.local == "auto" else
                                                 "not computed: --local-tokens off")
            return
        m = self.measures[which]
        texts = {r["meta"]["system_prompt_sha256"]: r["messages"][0]["content"] for r in reqs}
        m.prefetch(texts.values())
        counts = [m(r["messages"][0]["content"]) for r in reqs]
        summ["system_prompt_tokens_local"] = ({"min": min(counts), "mean": round(sum(counts) / len(counts), 2),
                                               "max": max(counts), "tokenizer": which,
                                               "tokenizer_sha256": m.identity()["identity_sha256"]} if counts else None)

    def run_info(self):
        """The run_config record of the C1 matching of this call (None when no C1 was built)."""
        if not self.cfgs:
            return None
        if self.mode == "chars":
            return {"match_mode": "chars", "rule": "v5: characters against the all-active C3 prompt (regression only)"}
        return {"match_mode": "tokens", "tokenizer": self.tokenizer, "report": self.report["_path"],
                "report_sha256": self.report["_sha256"], "by_config": dict(self.by_config)}


_RUN_KEYS = ("match_mode", "tokenizer", "report_sha256")


def same_run_matching(old, new):
    """False when a run directory's recorded C1 matching and this call's differ (mode, tokenizer, report)."""
    if not old or not new:
        return True
    return {k: old.get(k) for k in _RUN_KEYS} == {k: new.get(k) for k in _RUN_KEYS}


def merge_run_matching(old, new):
    out = dict(new)
    if old and old.get("by_config"):
        out["by_config"] = dict(old["by_config"], **(new.get("by_config") or {}))
    return out


# ------------------------------------------------------------------ command line


def add_requests_options(p):
    """Options of `orgene_cli.py requests` for C1 and local token counts."""
    p.add_argument("--c1-match-mode", choices=MATCH_MODES, default="tokens",
                   help="C1 length matching: tokens (dev mean of the C3 prompts, from the matching report; default) or "
                        "chars (the v5 rule, regression only)")
    p.add_argument("--c1-report", default=None, help="C1 matching report (default conditions/c1_matching_report.json)")
    p.add_argument("--c1-tokenizer", choices=TOKENIZERS, default="qwen",
                   help="whose C1: qwen (main model) or api (C1-api when the report says it is needed)")
    p.add_argument("--local-tokens", choices=("auto", "on", "off"), default="auto",
                   help="local token counts of the system prompts: auto (when C1 needs the tokenizer), on, off")
    p.add_argument("--tools-root", default=None, help="where .venv-tools/ and .cache/tiktoken/ are (default: the repository)")


def requests_setup(a, reg, cfgs, store, lexicon_sha, make_counter=None):
    """RequestsC1 from the `requests` arguments; exits with the reason when C1 cannot be built."""
    try:
        return RequestsC1(reg, cfgs, store, a.genes, a.cond_dir, a.tolerance, lexicon_sha, match_mode=a.c1_match_mode,
                          report_path=a.c1_report, tokenizer=a.c1_tokenizer, local_tokens=a.local_tokens,
                          tools_root=a.tools_root, make_counter=make_counter or MAKE_COUNTER,
                          lexicon=getattr(a, "lexicon", None))
    except C1MatchError as e:
        sys.exit(f"[requests] {e}")
    except Exception as e:  # TokenizerError and friends: say what is missing
        sys.exit(f"[requests] local tokenizer unavailable: {type(e).__name__}: {e}")


def add_c1_match_parser(sub):
    p = sub.add_parser("c1-match", help="match C1 to the dev mean of the C3 system prompts in tokens (dev cases only); "
                                        "write c1_matching_report.json")
    p.add_argument("--out", default=DEFAULT_REPORT, help="report path (default conditions/c1_matching_report.json)")
    p.add_argument("--genes", default=DEFAULT_GENES)
    p.add_argument("--cond-dir", default=DEFAULT_COND_DIR)
    p.add_argument("--configs", default=CF.DEFAULT_REGISTRY)
    p.add_argument("--lexicon", default=None, help="activation lexicon of the problem features (default: the features module's)")
    p.add_argument("--dev-set", default=DEV_SET, help="dev analysis set (default dev_signal55)")
    p.add_argument("--variants", nargs="*", default=None, help="rewrites to match (default: every conditions/variants/<v>)")
    p.add_argument("--tolerance", type=float, default=TOLERANCE)
    p.add_argument("--qwen-model", default=QWEN_MODEL)
    p.add_argument("--api-encoding", default=API_ENCODING, help="tiktoken encoding of the API model (provisional, D6)")
    p.add_argument("--no-api", action="store_true", help="skip the API tokenizer (the report then cannot serve API runs)")
    p.add_argument("--tools-root", default=None, help="where .venv-tools/ and .cache/tiktoken/ are (default: the repository)")
    p.set_defaults(fn=cmd_c1_match)
    return p


def cmd_c1_match(a, make_counter=None):
    """orgene_cli.py c1-match: prints only counts, ratios and hashes (never a problem statement)."""
    from . import features as F
    from .tokcount import TokenizerError
    reg = CF.load_registry(a.configs)
    store = G.load_store(a.genes, lexicon=a.lexicon)
    CF.check_registry_against_store(reg, store)
    lex = F.load_lexicon(a.lexicon)
    ids, info = dev_set_ids(a.dev_set)
    cases = load_dev_cases(ids)
    make_counter = make_counter or MAKE_COUNTER
    try:
        if make_counter is not None:
            mq = TokenMeasure(make_counter("qwen"), "qwen")
            ma = None if a.no_api else TokenMeasure(make_counter("api"), "api")
        else:
            mq = TokenMeasure(qwen_counter(a.qwen_model), "qwen")
            ma = None if a.no_api else TokenMeasure(api_counter(a.api_encoding, tools_root=a.tools_root), "api")
    except TokenizerError as e:
        print(f"[c1-match] local tokenizer unavailable: {e}", file=sys.stderr)
        sys.exit(2)
    rep = build_report(store, a.genes, reg, cases, info, lex, {"qwen": mq, "api": ma}, cond_dir=a.cond_dir,
                       variants=a.variants, tolerance=a.tolerance)
    write_report(rep, a.out)
    print(f"[c1-match] dev set {info['name']}: {info['n']} cases; report -> {rel(a.out)}")
    for v, r in rep["variants"].items():
        q = r["tokenizers"]["qwen"]
        line = (f"[c1-match] {v} ({r['status']}): C3 dev mean {q['target']:.1f} qwen tokens; full pool ratio "
                f"{q['c1_full_pool_ratio']}")
        if q["c1"]["ok"]:
            line += (f"; C1 {q['c1']['tokens']} tokens, {q['c1']['bullets_used']}/{q['c1']['bullets_available']} bullets, "
                     f"ratio {q['ratio_to_dev_mean']} (all-active {q['ratio_all_active']})")
        else:
            line += f"; NOT MATCHED ({q['c1']['tokens_short_of_band']} tokens short of the band)"
        a_ = r["tokenizers"].get("api")
        if a_ and a_.get("qwen_c1"):
            line += f"; api ratio {a_['qwen_c1']['ratio_to_dev_mean']} (C1-api {'needed' if a_['c1_api_needed'] else 'not needed'})"
        print(line)
        for e in r["errors"]:
            print(f"[c1-match]   {v}: {e}", file=sys.stderr)
    print(f"[c1-match] {'OK' if rep['ok'] else 'NOT OK'}")
    sys.exit(0 if rep["ok"] else 1)

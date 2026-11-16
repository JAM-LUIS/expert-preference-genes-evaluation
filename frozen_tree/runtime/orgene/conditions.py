"""System prompts and runner requests, built per (configuration, case) from the configuration registry.

Configurations live in configs/r1_configs.json (runtime/orgene/configs.py); nothing here branches on a
configuration name. Each configuration uses one of four system prompts; the user message is the same for all:

  C0  base rules + "return only the program"
  C1  base rules + generic OR guidance, length-matched to C3 (+-tolerance)
  C2  base rules + spec-JSON instruction (no contract)
  C3  base rules + spec-JSON instruction + the contract compiled from the genes active for this case

C1 length matching (E11, design D3): C1 is the header plus a prefix of the pool bullets, and it must lie within
target*(1+-tolerance) or C1MatchError is raised (a pool that cannot reach the target is an error, not a warning).
The measure, the target and the choice of prefix are parameters: the main rule is qwen tokens against the mean
per-case C3 prompt on the dev cases, taking the in-band prefix closest to the target (runtime/orgene/c1match.py
computes it once and writes c1_matching_report.json); without them the v5 rule applies (characters against the C3
prompt with every C3 gene active, bullets appended until the next one would overshoot), kept for the v1.0 regression.

C3L, C3E and C3L-ALL use the C0 prompt, C2E the C2 prompt, byte for byte (their round 0 reuses that output).
With per-problem activation (E04) the C3 contract is compiled per case, so the C3 system prompt can differ between
cases; every request records its own system_prompt_sha256, contract_sha256, activation trace, active genes and
features hash in `meta`. The messages sent to a model are exactly [system, user] and carry no configuration id,
request id or case id (check_messages).

How a configuration validates and repairs is read from the registry too (gene_scope, repair, closing, max_rounds;
E05). C3L's code- and execution-level genes validate the program and drive bounded repair, which isolates
"validate + repair" from "make the model write a spec first". C3E and C2E validate with the C3E gene scope (the
protocol and execution genes) and repair with the fixed generic template (genes.generic_repair_message); C2E closes
on "spec block + program". Repairing configurations run to at most two repair rounds; the ladder points "round 0"
and "at most one round" are cut from that run (ladder.py), not run separately. The prompt-only C3P and the C3
no-repair switch are gone (v5 decision D7).

build_system_prompts_v1() is the v5 builder (one prompt per condition for all cases). It is kept for the v1.0
regression (tools/anchor_hashes.py, runtime/tests/test_v1_regression.py) and as the all-genes-active prompt table of
the tokenizer cross-check (tools/tokcount_crosscheck.py); requests are never built from it.
"""
import hashlib
import inspect
import json
import os
import re

from . import configs as CF
from . import genes as G
from .paths import ROOT, rel

DEFAULT_COND_DIR = os.path.join(ROOT, "conditions")
# conditions of the v5 builder (the prompt-only 'C3P' ablation was dropped by v5 decision D7)
V1_CONDITIONS = ("C0", "C1", "C2", "C3", "C3L", "C3E")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def approx_tokens(text):
    """Tokenizer-neutral proxy (chars/4). Exact Qwen/tiktoken counts, when available, are recorded separately in run config."""
    return round(len(text) / 4.0, 1)


def exact_tokens(text, counter=None):
    """Exact count with a local tokenizer (tokcount counter, E09). Raises TokenizerError; never returns None."""
    if counter is None:
        from .tokcount import TokenizerError
        raise TokenizerError("exact_tokens needs a tokcount counter (the model's own tokenizer)")
    return counter.count(text)


def build_system_prompts_v1(cond_dir, genes_path, tolerance=0.05, token_counter=None):
    """v5 builder: one system prompt per condition, all genes of each scope active. Regression and the tokenizer
    cross-check only (no requests are built from it).

    token_counter (a tokcount counter, E09) adds exact local token counts of the prompts to `info`; without one they
    are recorded as not computed (None)."""
    base = _read(os.path.join(cond_dir, "base_system.md")).rstrip() + "\n"
    schema_summary = _read(os.path.join(cond_dir, "spec_schema_summary.md")).rstrip()
    store = G.load_store(genes_path)
    active, trace = G.activate(store, condition="C3")
    active_c3l, trace_c3l = G.activate(store, condition="C3L")
    active_c3e, trace_c3e = G.activate(store, condition="C3E")
    contract, cinfo = G.compile_contract(active)
    c3_body = _read(os.path.join(cond_dir, "C3_orgene.md")).replace("{SPEC_SCHEMA_SUMMARY}", schema_summary).replace("{CONTRACT}", contract.rstrip())
    c2_body = _read(os.path.join(cond_dir, "C2_schema_only.md")).replace("{SPEC_SCHEMA_SUMMARY}", schema_summary)
    c0_body = _read(os.path.join(cond_dir, "C0_direct.md"))
    sys_c3 = base + "\n" + c3_body.rstrip() + "\n"
    sys_c2 = base + "\n" + c2_body.rstrip() + "\n"
    sys_c0 = base + "\n" + c0_body.rstrip() + "\n"
    # C1: header + bullets until length matches C3
    pool_raw = _read(os.path.join(cond_dir, "C1_generic_expert_pool.md"))
    header, bullets = [], []
    for line in pool_raw.splitlines():
        if line.startswith("<!--"):
            continue
        if line.startswith("- "):
            bullets.append(line)
        elif line.strip():
            header.append(line)
    target = len(sys_c3)
    body = "\n".join(header) + "\n"
    chosen = []
    for b in bullets:
        candidate = base + "\n" + body + "\n".join(chosen + [b]) + "\n"
        if len(candidate) > target * (1 + tolerance):
            break
        chosen.append(b)
    sys_c1 = base + "\n" + body + "\n".join(chosen) + "\n"
    ratio = len(sys_c1) / target
    match_ok = (1 - tolerance) <= ratio <= (1 + tolerance)
    # C3L asks for exactly what C0 asks for: the genes act on the program, not on the prompt.
    prompts = {"C0": sys_c0, "C1": sys_c1, "C2": sys_c2, "C3": sys_c3, "C3L": sys_c0, "C3E": sys_c0}
    info = {
        "gene_store_path": rel(genes_path),
        "gene_store_sha256": G.store_digest(active),
        "active_genes": [{"geneId": g["geneId"], "version": g["version"]} for g in active],
        "activation_trace": trace,
        "contract_sha256": cinfo["contract_sha256"],
        "contract_chars": len(contract),
        "c3e_active_genes": [{"geneId": g["geneId"], "version": g["version"]} for g in active_c3e],
        "c3e_gene_store_digest": G.store_digest(active_c3e),
        "c3l_active_genes": [{"geneId": g["geneId"], "version": g["version"]} for g in active_c3l],
        "c3l_gene_store_digest": G.store_digest(active_c3l),
        "c3l_activation_trace": trace_c3l,
        "c3l_prompt_equals_c0": prompts["C3L"] == prompts["C0"],
        "c1_bullets_used": len(chosen),
        "c1_c3_char_ratio": round(ratio, 4),
        "c1_c3_match_ok": match_ok,
        "tolerance": tolerance,
        "system_prompt_chars": {k: len(v) for k, v in prompts.items()},
        "system_prompt_tokens_proxy": {k: approx_tokens(v) for k, v in prompts.items()},
        # exact counts only with a tokcount counter (E09); without one they are not computed (None), never guessed
        "system_prompt_tokens_local": ({k: exact_tokens(v, token_counter) for k, v in prompts.items()}
                                       if token_counter is not None else None),
        "system_prompt_tokenizer_sha256": getattr(token_counter, "identity_sha256", None),
        "system_prompt_sha256": {k: hashlib.sha256(v.encode("utf-8")).hexdigest() for k, v in prompts.items()},
    }
    return prompts, info


def user_message(case):
    return "Problem:\n" + case["text"].strip() + "\n"


# ----------------------------------------------------------------------------- templates (per variant)

TEMPLATE_FILES = {"base": "base_system.md", "schema_summary": "spec_schema_summary.md", "C0": "C0_direct.md",
                  "C1": "C1_generic_expert_pool.md", "C2": "C2_schema_only.md", "C3": "C3_orgene.md"}
# Optional templates: used (and hashed) only where the file exists. conditions/ has none, so the templates and every
# hash of the main prompts stay as they were; a rewrite may reword the contract's framing lines (E11).
# The D12 templates (C0R prompt, review checklist) are optional in the same sense: a template directory without them
# still loads, and only a configuration that needs one refuses to run without it.
OPTIONAL_TEMPLATE_FILES = {"contract_frame": "C3_contract_frame.json", "C0R": "C0R_rules_in_prompt.md",
                           "review_checklist": "review_checklist.md"}
_VARIANT_EXTRA_FILES = ("README.md",)
_PLACEHOLDERS = ("{SPEC_SCHEMA_SUMMARY}", "{CONTRACT}")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_templates(cond_dir=None, variant=None):
    """Prompt templates of conditions/ or of the rewrite conditions/variants/<variant>/.

    A variant directory holds only the templates it rewrites; the others come from conditions/. Files that are not
    template names are an error (a misspelt file name would otherwise silently fall back to the original).
    """
    cond_dir = cond_dir or DEFAULT_COND_DIR
    vdir = None
    if variant is not None:
        if not isinstance(variant, str) or not CF.VARIANT_RE.match(variant):
            raise ValueError(f"invalid prompt variant name {variant!r}")
        vdir = os.path.join(cond_dir, "variants", variant)
        if not os.path.isdir(vdir):
            raise ValueError(f"prompt variant {variant!r} not found ({rel(vdir)})")
        unknown = sorted(f for f in os.listdir(vdir) if not f.startswith(".")
                         and f not in TEMPLATE_FILES.values() and f not in OPTIONAL_TEMPLATE_FILES.values()
                         and f not in _VARIANT_EXTRA_FILES)
        if unknown:
            raise ValueError(f"prompt variant {variant!r} has files that are not template names: {unknown}")
    texts, files = {}, {}
    for key, name in list(TEMPLATE_FILES.items()) + list(OPTIONAL_TEMPLATE_FILES.items()):
        p = os.path.join(cond_dir, name)
        if vdir and os.path.isfile(os.path.join(vdir, name)):
            p = os.path.join(vdir, name)
        elif key in OPTIONAL_TEMPLATE_FILES and not os.path.isfile(p):
            continue
        texts[key] = _read(p)
        files[key] = {"path": rel(p), "sha256": _sha(texts[key])}
    if "C0R" in texts and "{CONTRACT}" not in texts["C0R"]:
        raise ValueError("C0R template has no {CONTRACT} placeholder; the compiled contract would be dropped")
    if "{CONTRACT}" not in texts["C3"]:
        raise ValueError("C3 template has no {CONTRACT} placeholder; the compiled contract would be dropped")
    for k in ("C2", "C3"):
        if "{SPEC_SCHEMA_SUMMARY}" not in texts[k]:
            raise ValueError(f"{k} template has no {{SPEC_SCHEMA_SUMMARY}} placeholder")
    frame = None
    if "contract_frame" in texts:
        try:
            frame = G.check_contract_frame(json.loads(texts["contract_frame"]))
        except ValueError as e:
            raise ValueError(f"{files['contract_frame']['path']}: {e}") from None
    return {"cond_dir": rel(cond_dir), "variant": variant, "texts": texts, "files": files, "contract_frame": frame}


def template_input_paths(cond_dir=None):
    """Every template file load_templates may read under cond_dir: the required templates of conditions/, the optional
    ones where they exist, and the template files of every rewrite in conditions/variants/. The test gate requires
    them all to be frozen (freeze.unfrozen_inputs; cli._gate_inputs, unit_exec.gate_inputs)."""
    cond_dir = cond_dir or DEFAULT_COND_DIR
    names = set(TEMPLATE_FILES.values()) | set(OPTIONAL_TEMPLATE_FILES.values())
    paths = [os.path.join(cond_dir, n) for n in sorted(names)
             if n in TEMPLATE_FILES.values() or os.path.isfile(os.path.join(cond_dir, n))]
    for d, _, fs in sorted(os.walk(os.path.join(cond_dir, "variants"))):
        paths += [os.path.join(d, f) for f in sorted(fs) if f in names]
    return paths


def _base(T):
    return T["texts"]["base"].rstrip() + "\n"


def _prompt_c0(T):
    return _base(T) + "\n" + T["texts"]["C0"].rstrip() + "\n"


def _prompt_c2(T):
    body = T["texts"]["C2"].replace("{SPEC_SCHEMA_SUMMARY}", T["texts"]["schema_summary"].rstrip())
    return _base(T) + "\n" + body.rstrip() + "\n"


def _prompt_c3(T, contract):
    body = (T["texts"]["C3"].replace("{SPEC_SCHEMA_SUMMARY}", T["texts"]["schema_summary"].rstrip())
            .replace("{CONTRACT}", contract.rstrip()))
    return _base(T) + "\n" + body.rstrip() + "\n"


# C0R (D12): the C0 prompt plus the contract of the genes active for this problem under `contract_scope`. No gene check
# runs on the contract's rules in such a configuration, so the last framing line does not announce automatic checks.
C0R_CONTRACT_FRAME = dict(G.DEFAULT_CONTRACT_FRAME, checks="Before answering, check your program for:")


def _prompt_c0r(T, contract):
    if "C0R" not in T["texts"]:
        raise ValueError(f"no C0R template ({OPTIONAL_TEMPLATE_FILES['C0R']}) in {T['cond_dir']}")
    return _base(T) + "\n" + T["texts"]["C0R"].replace("{CONTRACT}", contract.rstrip()).rstrip() + "\n"


# Review checklist of the checklist repair mode (C3T, C3A; D12): the first CHECKLIST_BULLETS bullets of the C1 pool as it
# stood when the count was fixed (the v5 pool, commit a56f82f), in pool order. The count was fixed once from the it1 dev
# run (the checklist block is within 10% of the median length of the gene text it stands in for) and is not tuned
# afterwards. The file was registered by its sha256 before the comparison with the reference answers (2026-10-04) and is
# pinned here: the R1 C1 pool of 2026-10-05 replaces the pool bullets that restate gene wording, two of the four among
# them, so the checklist is no longer a prefix of the pool and is checked by its digest instead.
CHECKLIST_BULLETS = 4
CHECKLIST_SHA256 = "a595f8c3607f98e81eefe93e9b200f5763c4ba8e1a3ca1d16cc1b4b6656078a9"


def review_checklist(T):
    """The frozen checklist text; refused when the file is not the registered one (CHECKLIST_SHA256)."""
    if "review_checklist" not in T["texts"]:
        raise ValueError(f"no review checklist ({OPTIONAL_TEMPLATE_FILES[review_checklist]}) in {T[cond_dir]}")
    info = T["files"]["review_checklist"]
    if info.get("sha256") != CHECKLIST_SHA256:
        raise ValueError(f"{info[path]} is not the registered review checklist (sha256 {CHECKLIST_SHA256[:12]}...)")
    text = T["texts"]["review_checklist"].strip()
    if len([l for l in text.splitlines() if l.startswith("- ")]) != CHECKLIST_BULLETS:
        raise ValueError(f"{info[path]} does not hold {CHECKLIST_BULLETS} bullets")
    return text


class C1MatchError(ValueError):
    """The C1 prompt cannot be length-matched: the pool is too short for the target, or the header alone is too long."""


def c1_parts(T):
    """(header lines, pool bullets) of the C1 template: HTML comment lines are skipped, '- ' lines are pool bullets."""
    header, bullets = [], []
    for line in T["texts"]["C1"].splitlines():
        if line.startswith("<!--"):
            continue
        if line.startswith("- "):
            bullets.append(line)
        elif line.strip():
            header.append(line)
    return header, bullets


def c1_text(T, n_bullets):
    """The C1 prompt with the first n_bullets pool bullets (the only prompts _prompt_c1 can produce)."""
    header, bullets = c1_parts(T)
    if not 0 <= n_bullets <= len(bullets):
        raise ValueError(f"the C1 pool has {len(bullets)} bullets, not {n_bullets}")
    return _base(T) + "\n" + "\n".join(header) + "\n" + "\n".join(bullets[:n_bullets]) + "\n"


def c1_prefix_texts(T):
    """Every text _prompt_c1 may measure, for 0..all bullets (lets a token counter count them in one batch)."""
    return [c1_text(T, k) for k in range(len(c1_parts(T)[1]) + 1)]


def _measure_name(measure):
    if measure is len:
        return "chars"
    return getattr(measure, "name", None) or getattr(measure, "__name__", None) or "custom"


C1_SELECT = ("greedy", "closest")


def _prompt_c1(T, target, tolerance=0.05, measure=len, select=None):
    """C1 = header + a prefix of the pool bullets (file order), required to lie within target*(1+-tolerance);
    otherwise C1MatchError (the pool is too short, or the header alone overshoots).

    `measure` maps a prompt text to its length: `len` (characters) or a token measure (E11, c1match). `select`:
      "greedy"   v5: append bullets while the prompt stays within target*(1+tolerance), stop at the first bullet
                 that would overshoot (lands near the upper edge of the band); the default for characters, so the
                 v5 C1 is reproduced;
      "closest"  E11: of the prefixes within the band, the one whose length is closest to the target (ties: fewer
                 bullets); the default for token measures.
    """
    header, bullets = c1_parts(T)
    if not (isinstance(target, (int, float)) and target > 0):
        raise ValueError(f"C1 target must be a positive length, got {target!r}")
    select = select or ("greedy" if measure is len else "closest")
    if select not in C1_SELECT:
        raise ValueError(f"C1 selection must be one of {C1_SELECT}")
    chosen = 0
    for k in range(1, len(bullets) + 1):
        if measure(c1_text(T, k)) > target * (1 + tolerance):
            break
        chosen = k
    if select == "closest":
        band = [k for k in range(chosen + 1) if measure(c1_text(T, k)) >= target * (1 - tolerance)]
        if band:
            chosen = min(band, key=lambda k: (abs(measure(c1_text(T, k)) / target - 1), k))
    text = c1_text(T, chosen)
    length = measure(text)
    ratio = length / target
    info = {"measure": _measure_name(measure), "select": select, "target": target, "length": length,
            "ratio": round(ratio, 4), "tolerance": tolerance, "ok": (1 - tolerance) <= ratio <= (1 + tolerance),
            "bullets_used": chosen, "bullets_available": len(bullets)}
    if not info["ok"]:
        if chosen == len(bullets) and ratio < 1 - tolerance:
            why = (f"the pool is too short: all {len(bullets)} bullets reach {length} of the target {round(target, 1)} "
                   f"({info['measure']}), ratio {info['ratio']} < {1 - tolerance}; extend the C1 pool")
        elif ratio < 1 - tolerance:
            why = (f"bullet {chosen + 1} would overshoot while the prompt is still at ratio {info['ratio']} "
                   f"(< {1 - tolerance}); the pool order cannot reach the band")
        else:
            why = f"the C1 header alone is at ratio {info['ratio']} (> {1 + tolerance}) of the target"
        raise C1MatchError(f"C1 cannot be length-matched ({info['measure']}): {why}")
    return text, info


# ----------------------------------------------------------------------------- activation seam (E04)


def _activate_takes_features():
    try:
        return "features" in inspect.signature(G.activate).parameters
    except (TypeError, ValueError):
        return False


def problem_rule_genes(store, scope=None):
    """geneIds (sorted) whose activation rule depends on the problem, i.e. anything but the rule "always", restricted
    to gene scope `scope` when given. A gene without an `activation` field is always active (E04)."""
    out = []
    for g in store:
        act = g.get("activation")
        if act is None or (isinstance(act, dict) and act.get("rule") == "always"):
            continue
        conds = (g.get("scope") or {}).get("conditions") or []
        if scope is not None and conds and scope not in conds:
            continue
        out.append(g["geneId"])
    return sorted(out)


def activate_for(store, scope, mode, features=None):
    """Active genes of `scope` for one case. Returns (active, trace, impl).

    mode 'all': every active-lifecycle gene of the scope; 'per_problem': the scope's genes whose activation rule
    holds on this case's features. Per-problem rules are evaluated by genes.activate once it takes `features`
    (E04: activate(genes, condition, task, features=None, mode=...)). Until then a library without activation
    rules behaves as 'all' (a gene without a rule is always active), and a library with rules is refused rather
    than silently activating every gene.
    """
    if mode not in ("per_problem", "all"):
        raise ValueError(f"activation mode {mode!r} does not activate genes")
    if _activate_takes_features():
        active, trace = G.activate(store, condition=scope, features=features, mode=mode)
        return active, trace, mode
    if mode == "per_problem":
        ruled = problem_rule_genes(store, scope)
        if ruled:
            raise NotImplementedError(f"genes {ruled} carry activation rules, but genes.activate cannot evaluate "
                                      "them yet (E04); refusing to activate every gene instead")
    active, trace = G.activate(store, condition=scope)
    return active, trace, "scope_only"


def features_digest(features):
    """sha256 of the canonical JSON of a feature dict (same canonical form as features.features_sha256, E04)."""
    if features is None:
        return None
    return _sha(json.dumps(features, sort_keys=True, separators=(",", ":")))


def c3_all_active_prompt(T, store, scope="C3"):
    """The C3 system prompt with every gene of `scope` active (the templates' contract frame applies)."""
    active, _, _ = activate_for(store, scope, "all")
    contract, _ = G.compile_contract(active, frame=T.get("contract_frame"))
    return _prompt_c3(T, contract)


def c1_default_target(T, store, measure=len, cases=None, features_by_case=None, c3_config=None):
    """The C1 length target.

    Without cases: the length of the C3 prompt with every gene of scope C3 active (the v5 C1 target; with
    measure=len this is the v5 rule). With cases (the dev cases, c1match): the mean over the cases of the length of
    each case's own C3 system prompt, built from `c3_config` (the registry's C3) with the case's problem features.
    """
    if cases is None:
        return measure(c3_all_active_prompt(T, store))
    if c3_config is None or c3_config.get("prompt") != "C3":
        raise ValueError("the per-case C1 target needs the C3 configuration of the registry")
    if not cases:
        raise ValueError("the per-case C1 target needs at least one case")
    lengths = []
    for case in cases:
        f = None if features_by_case is None else features_by_case[case["case_id"]]
        text, _ = build_prompt(c3_config, case, store, features=f, templates=T, variant=T["variant"])
        lengths.append(measure(text))
    return sum(lengths) / len(lengths)


# ----------------------------------------------------------------------------- per (configuration, case)


def build_prompt(config, case, store, features=None, variant=None, cond_dir=None, templates=None, c1_target=None,
                 tolerance=0.05, c1_measure=None):
    """System prompt for one (configuration, case). Returns (text, meta).

    `features`: problem features of this case (E04), used by per-problem activation; `variant`: defaults to the
    configuration's variant and may not contradict it; `templates`/`c1_target` let callers reuse work across cases.
    `c1_measure` (a token measure, E11) needs its own `c1_target` (the dev mean from c1match); without both the C1
    prompt follows the v5 rule (characters against the all-active C3 prompt).
    """
    if c1_measure is not None and c1_target is None:
        raise ValueError("a C1 measure needs its target (the dev mean of the C3 prompts, runtime/orgene/c1match.py)")
    cid = config["id"]
    if config.get("pipeline", "standard") != "standard":
        raise ValueError(f"config {cid}: pipeline {config['pipeline']!r} builds its own stage prompts; "
                         "it has no single system prompt")
    if variant is not None and config.get("variant") is not None and variant != config["variant"]:
        raise ValueError(f"config {cid} is registered with variant {config['variant']!r}, not {variant!r}")
    variant = variant if variant is not None else config.get("variant")
    T = templates if templates is not None else load_templates(cond_dir, variant)
    if T["variant"] != variant:
        raise ValueError(f"templates were loaded for variant {T['variant']!r}, config {cid} needs {variant!r}")
    CF.check_store_scopes(store)
    scope, mode = config["gene_scope"], config["activation"]
    if scope is not None and mode != "none":
        active, trace, impl = activate_for(store, scope, mode, features)
    else:
        active, trace, impl = [], [], "none"
    p = config["prompt"]
    contract_sha = contract_chars = c1 = None
    contract_genes = None
    if p == "C0":
        text = _prompt_c0(T)
    elif p == "C1":
        text, c1 = _prompt_c1(T, c1_target if c1_target is not None else c1_default_target(T, store), tolerance,
                              measure=c1_measure or len)
    elif p == "C2":
        text = _prompt_c2(T)
    elif p == "C3":
        contract, cinfo = G.compile_contract(active, frame=T.get("contract_frame"))
        text = _prompt_c3(T, contract)
        contract_sha, contract_chars = cinfo["contract_sha256"], len(contract)
        contract_genes = active
    elif p == "C0R":
        contract_genes, _, _ = activate_for(store, config["contract_scope"], "per_problem", features)
        contract, cinfo = G.compile_contract(contract_genes, frame=C0R_CONTRACT_FRAME)
        text = _prompt_c0r(T, contract)
        contract_sha, contract_chars = cinfo["contract_sha256"], len(contract)
    else:
        raise ValueError(f"config {cid}: unknown prompt {p!r}")
    left = [ph for ph in _PLACEHOLDERS if ph in text]
    if left:
        raise ValueError(f"config {cid}: unfilled placeholder(s) {left} in the system prompt")
    meta = {
        "config_id": cid, "prompt": p, "variant": variant,
        "system_prompt_sha256": _sha(text), "system_prompt_chars": len(text),
        "contract_in_prompt": p in ("C3", "C0R"), "contract_sha256": contract_sha, "contract_chars": contract_chars,
        "contract_scope": config.get("contract_scope") if p == "C0R" else (scope if p == "C3" else None),
        "contract_genes": ([{"geneId": g["geneId"], "version": g["version"]} for g in contract_genes]
                           if contract_genes is not None else None),
        "gene_scope": scope, "activation": mode, "activation_impl": impl,
        "features_sha256": features_digest(features),
        "active_genes": [{"geneId": g["geneId"], "version": g["version"]} for g in active],
        "gene_set_digest": G.store_digest(active) if impl != "none" else None,
        "activation_trace": trace,
        "template_sha256": {k: v["sha256"] for k, v in T["files"].items()},
    }
    if c1 is not None:
        meta["c1_match"] = c1
    return text, meta


def _id_pattern(ident):
    return re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(ident) + r"(?![A-Za-z0-9_-])")


def check_messages(messages, ids=(), config_ids=()):
    """Messages sent to a model: exactly [system, user], only role and content, no run metadata.

    `ids` (request id, case id) may not occur anywhere in the messages; configuration ids may not occur as a
    word in the system prompt (the user message is the problem text and may legitimately contain e.g. 'C1').
    Error messages name the identifier, never the text.
    """
    roles = [m.get("role") for m in messages]
    if roles != ["system", "user"]:
        raise ValueError(f"messages must be exactly [system, user], got {roles}")
    for m in messages:
        if set(m) != {"role", "content"} or not isinstance(m["content"], str):
            raise ValueError(f"{m.get('role')} message must carry only role and a string content")
        for s in ids:
            if s and s in m["content"]:
                raise ValueError(f"{m['role']} message contains the identifier {s!r}")
    for cid in config_ids:
        if _id_pattern(cid).search(messages[0]["content"]):
            raise ValueError(f"system prompt contains the configuration id {cid!r}")


def build_request(config, case, store, run_id, features=None, registry_ids=None, **prompt_kw):
    """Round-0 runner request for one (configuration, case)."""
    text, pmeta = build_prompt(config, case, store, features=features, **prompt_kw)
    rid = f"{case['case_id']}.{config['id']}"
    msgs = [{"role": "system", "content": text}, {"role": "user", "content": user_message(case)}]
    check_messages(msgs, ids=(rid, case["case_id"]), config_ids=tuple(registry_ids or ()) + (config["id"],))
    meta = {"run_id": run_id, "source": case.get("source"), "round": 0, "round0": config["round0"]}
    meta.update(pmeta)
    return {"request_id": rid, "case_id": case["case_id"], "condition": config["id"], "config_id": config["id"],
            "messages": msgs, "meta": meta}


def build_requests(cases, config, store, run_id, features_by_case=None, registry_ids=None, cond_dir=None,
                   tolerance=0.05, c1_target=None, c1_measure=None):
    """Round-0 requests of one configuration for a list of cases (templates and the C1 target computed once).
    c1_target/c1_measure: see build_prompt (c1match.RequestsC1 supplies them from the matching report)."""
    kw = {"cond_dir": cond_dir, "tolerance": tolerance}
    if config.get("pipeline", "standard") == "standard":
        T = load_templates(cond_dir, config.get("variant"))
        kw["templates"] = T
        if config["prompt"] == "C1":
            if c1_measure is not None and c1_target is None:
                raise ValueError("a C1 measure needs its target (the dev mean of the C3 prompts, c1match)")
            kw["c1_target"] = c1_target if c1_target is not None else c1_default_target(T, store)
            if c1_measure is not None:
                kw["c1_measure"] = c1_measure
    out = []
    for c in cases:
        if features_by_case is not None and c["case_id"] not in features_by_case:
            raise KeyError(f"no features for case {c['case_id']}")
        f = features_by_case[c["case_id"]] if features_by_case is not None else None
        out.append(build_request(config, c, store, run_id, features=f, registry_ids=registry_ids, **kw))
    return out


def summarize_requests(reqs):
    """Per-configuration summary for run_config: prompt hashes, lengths, contracts, gene activation rates."""
    n = len(reqs)
    metas = [r["meta"] for r in reqs]
    shas = sorted({m["system_prompt_sha256"] for m in metas})
    chars = [m["system_prompt_chars"] for m in metas]
    counts = {}
    for m in metas:
        for g in m["active_genes"]:
            counts[g["geneId"]] = counts.get(g["geneId"], 0) + 1
    m0 = metas[0] if metas else {}
    out = {
        "n_requests": n, "prompt": m0.get("prompt"), "variant": m0.get("variant"),
        "gene_scope": m0.get("gene_scope"), "activation": m0.get("activation"),
        "activation_impl": sorted({m["activation_impl"] for m in metas}),
        "n_distinct_system_prompts": len(shas), "system_prompt_sha256": shas,
        "system_prompt_chars": ({"min": min(chars), "mean": round(sum(chars) / n, 1), "max": max(chars)} if n else None),
        "contract_sha256": sorted({m["contract_sha256"] for m in metas if m["contract_sha256"]}),
        "gene_activation_rate": {g: round(k / n, 4) for g, k in sorted(counts.items())},
    }
    if "c1_match" in m0:
        out["c1_match"] = m0["c1_match"]
    return out


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

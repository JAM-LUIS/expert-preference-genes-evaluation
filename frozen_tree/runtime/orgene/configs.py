"""Configuration registry (E03): configs/r1_configs.json.

The registry lists every experimental configuration that runs through this pipeline, plus the external baselines
that run through their own adapters (metadata only). Code reads the fields below instead of branching on a
configuration name. The gene library keeps naming only the three gene scopes C3, C3L and C3E in
`scope.conditions`; a configuration points at one of them through `gene_scope`, so adding a configuration never
changes the gene library or its digests.

Pipeline configuration fields (required unless marked optional):
  id          name used in request ids and file names: an upper-case letter, then letters and digits, optionally
              joined by '-' or '_' (no '.', which separates case id and configuration id in request ids)
  prompt      system prompt: C0 | C1 | C2 | C3 | C0R (conditions.build_prompt). C0R is the C0 prompt followed by the
              contract compiled from `contract_scope` (rules in the prompt, no spec; D12)
  round0      own | reuse:<config id>. `reuse` takes the round-0 output of that configuration's unit for the same
              case, repeat and model. The source must itself be `own` and have the same prompt, variant,
              num_predict and num_ctx, so its round-0 request is byte-identical.
  validator   none | observe (run the predicates and record, never repair) | gene (predicates drive repair)
  gene_scope  C3 | C3L | C3E | null: which gene scope is activated (for the contract and/or the validator)
  activation  per_problem (activation rules on problem features, E04) | all (every gene of the scope) | none
  repair      none | gene (gene repair instructions) | generic (fixed template without gene wording) |
              gene_generic (gene trigger and bookkeeping, generic checklist instead of the text of genes outside the
              generic-repair scope: genes.checklist_repair_message; D12)
  closing     program | spec_and_program: what a repair turn asks the model to return
  max_rounds  repair rounds after round 0 (0 exactly when repair is none)
  num_predict, num_ctx   generation limits
  variant     null (templates in conditions/) or the name of a rewrite in conditions/variants/<name>/
  label       (optional) descriptive name for tables
  pipeline    (optional, default standard) standard | ora. `ora` is the three-stage agent baseline; its stage
              prompts are built by its own module (E15), not by conditions.build_prompt
  token_cap   (optional) per-case cumulative token cap for the unit executor; null = no cap (set in 1D)
  force_review    (optional, default false) gene_generic only: at round 0 the checklist is also sent to an answer
                  without any hard failure (C3A)
  contract_scope  (optional, default null) prompt C0R only: the gene scope whose per-problem active genes are
                  compiled into the prompt; independent of gene_scope, which the validator uses
  notes       (optional) free text
Adapter entries: id, adapter (alphaopt | orlm | llmopt), label; optional workpackage, solver, model, notes.
"""
import hashlib
import json
import os
import re

from .paths import ROOT, rel

SCHEMA = "orgene.configs.v1"
DEFAULT_REGISTRY = os.path.join(ROOT, "configs", "r1_configs.json")

PROMPTS = ("C0", "C1", "C2", "C3", "C0R")
SPEC_PROMPTS = ("C2", "C3")          # prompts that ask for the JSON spec before the program
GENE_SCOPES = ("C3", "C3L", "C3E")   # the only scope names a gene record may use
VALIDATORS = ("none", "observe", "gene")
ACTIVATIONS = ("per_problem", "all", "none")
REPAIRS = ("none", "gene", "generic", "gene_generic")
CLOSINGS = ("program", "spec_and_program")
PIPELINES = ("standard", "ora")
ADAPTER_KINDS = ("alphaopt", "orlm", "llmopt")
MAX_ROUNDS_LIMIT = 5

REQUIRED = ("id", "prompt", "round0", "validator", "gene_scope", "activation", "repair", "closing",
            "max_rounds", "num_predict", "num_ctx", "variant")
OPTIONAL = {"label": None, "pipeline": "standard", "token_cap": None, "notes": None, "force_review": False,
            "contract_scope": None}
ADAPTER_REQUIRED = ("id", "adapter", "label")
ADAPTER_OPTIONAL = {"workpackage": None, "solver": None, "model": None, "notes": None}
TOP_REQUIRED = ("schema", "configs")
TOP_OPTIONAL = ("note", "adapters")

# \Z, not $: '$' also matches before a trailing newline, which would let e.g. "C0\n" pass as an id
ID_RE = re.compile(r"^[A-Z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)*\Z")
VARIANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*\Z")
REUSE_RE = re.compile(r"^reuse:(.*)\Z")


class RegistryError(ValueError):
    """The registry (or a gene library checked against it) is not usable."""


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _enum(c, key, allowed, where, errors, nullable=False):
    v = c.get(key)
    if v is None and nullable:
        return
    if v not in allowed:
        errors.append(f"{where}: {key}={v!r} is not one of {list(allowed) + ([None] if nullable else [])}")


def _check_config(c, errors):
    if not isinstance(c, dict):
        errors.append(f"config entry {c!r} is not an object")
        return False
    where = f"config {c.get('id')!r}"
    unknown = sorted(set(c) - set(REQUIRED) - set(OPTIONAL))
    if unknown:
        errors.append(f"{where}: unknown field(s) {unknown}")
    missing = [k for k in REQUIRED if k not in c]
    if missing:
        errors.append(f"{where}: missing field(s) {missing}")
        return False
    n0 = len(errors)
    if not isinstance(c["id"], str) or not ID_RE.match(c["id"]):
        errors.append(f"{where}: id must match {ID_RE.pattern}")
    _enum(c, "prompt", PROMPTS, where, errors)
    _enum(c, "validator", VALIDATORS, where, errors)
    _enum(c, "gene_scope", GENE_SCOPES, where, errors, nullable=True)
    _enum(c, "activation", ACTIVATIONS, where, errors)
    _enum(c, "repair", REPAIRS, where, errors)
    _enum(c, "closing", CLOSINGS, where, errors)
    if c.get("pipeline", OPTIONAL["pipeline"]) not in PIPELINES:
        errors.append(f"{where}: pipeline={c['pipeline']!r} is not one of {list(PIPELINES)}")
    if not (isinstance(c["round0"], str) and (c["round0"] == "own" or REUSE_RE.match(c["round0"]))):
        errors.append(f"{where}: round0={c['round0']!r} must be 'own' or 'reuse:<config id>'")
    if not _is_int(c["max_rounds"]) or not 0 <= c["max_rounds"] <= MAX_ROUNDS_LIMIT:
        errors.append(f"{where}: max_rounds must be an integer in 0..{MAX_ROUNDS_LIMIT}")
    for k in ("num_predict", "num_ctx"):
        if not _is_int(c[k]) or c[k] < 1:
            errors.append(f"{where}: {k} must be a positive integer")
    if c["variant"] is not None and not (isinstance(c["variant"], str) and VARIANT_RE.match(c["variant"])):
        errors.append(f"{where}: variant must be null or match {VARIANT_RE.pattern}")
    tc = c.get("token_cap")
    if tc is not None and (not _is_int(tc) or tc < 1):
        errors.append(f"{where}: token_cap must be null or a positive integer")
    for k in ("label", "notes"):
        if c.get(k) is not None and not isinstance(c[k], str):
            errors.append(f"{where}: {k} must be a string")
    if not isinstance(c.get("force_review", False), bool):
        errors.append(f"{where}: force_review must be true or false")
    _enum(c, "contract_scope", GENE_SCOPES, where, errors, nullable=True)
    if len(errors) > n0:
        return False
    # ---- consistency between fields
    if _is_int(c["num_ctx"]) and _is_int(c["num_predict"]) and c["num_ctx"] <= c["num_predict"]:
        errors.append(f"{where}: num_ctx ({c['num_ctx']}) must exceed num_predict ({c['num_predict']})")
    needs_genes = c["validator"] != "none" or c["prompt"] == "C3"
    has_genes = c["gene_scope"] is not None and c["activation"] != "none"
    if needs_genes and not has_genes:
        errors.append(f"{where}: validator {c['validator']!r} / prompt {c['prompt']!r} need a gene_scope and an "
                      "activation other than 'none'")
    if not needs_genes and (c["gene_scope"] is not None or c["activation"] != "none"):
        errors.append(f"{where}: no validator and no contract, so gene_scope must be null and activation 'none'")
    if c["prompt"] == "C3" and c["gene_scope"] not in (None, "C3"):
        errors.append(f"{where}: the C3 prompt compiles its contract from gene scope C3, not {c['gene_scope']!r}")
    if c["validator"] == "gene" and c["gene_scope"] == "C3" and c["prompt"] not in SPEC_PROMPTS:
        errors.append(f"{where}: gene scope C3 includes the spec predicates, so repairing with it needs a prompt that "
                      f"asks for the spec ({list(SPEC_PROMPTS)}), not {c['prompt']!r}; use scope C3L or C3E")
    if c["repair"] != "none" and c["validator"] != "gene":
        errors.append(f"{where}: repair {c['repair']!r} needs validator 'gene'")
    if c["validator"] == "gene" and c["repair"] == "none":
        errors.append(f"{where}: validator 'gene' without repair; use validator 'observe' to record predicates only")
    if c["repair"] == "generic" and c["gene_scope"] != "C3E":
        errors.append(f"{where}: the generic repair template is triggered by the C3E protocol and execution genes; "
                      f"gene_scope must be 'C3E', not {c['gene_scope']!r}")
    if c["repair"] == "gene_generic" and (c["gene_scope"] != "C3L" or c["closing"] != "program"):
        errors.append(f"{where}: checklist repair (gene_generic) validates with gene scope C3L and returns a program "
                      f"(gene_scope={c['gene_scope']!r}, closing={c['closing']!r})")
    if c.get("force_review", False) and c["repair"] != "gene_generic":
        errors.append(f"{where}: force_review belongs to repair 'gene_generic', not {c['repair']!r}")
    if (c["prompt"] == "C0R") != (c.get("contract_scope") is not None):
        errors.append(f"{where}: contract_scope is set exactly when the prompt is C0R "
                      f"(prompt={c['prompt']!r}, contract_scope={c.get('contract_scope')!r})")
    if c.get("contract_scope") == "C3":
        errors.append(f"{where}: contract_scope C3 includes the spec genes; the C0R prompt asks for no spec")
    if (c["repair"] == "none") != (c["max_rounds"] == 0):
        errors.append(f"{where}: max_rounds must be 0 exactly when repair is 'none' "
                      f"(repair={c['repair']!r}, max_rounds={c['max_rounds']})")
    wants_spec = c["closing"] == "spec_and_program"
    if wants_spec != (c["prompt"] in SPEC_PROMPTS):
        errors.append(f"{where}: closing {c['closing']!r} does not match prompt {c['prompt']!r} "
                      f"(only {list(SPEC_PROMPTS)} ask for a spec, and a repair turn may only ask for what round 0 asked for)")
    if c.get("pipeline", "standard") == "ora" and c["round0"] != "own":
        errors.append(f"{where}: the ora pipeline generates its own round 0")
    return True


def _check_adapter(a, errors):
    if not isinstance(a, dict):
        errors.append(f"adapter entry {a!r} is not an object")
        return False
    where = f"adapter {a.get('id')!r}"
    unknown = sorted(set(a) - set(ADAPTER_REQUIRED) - set(ADAPTER_OPTIONAL))
    if unknown:
        errors.append(f"{where}: unknown field(s) {unknown}")
    missing = [k for k in ADAPTER_REQUIRED if k not in a]
    if missing:
        errors.append(f"{where}: missing field(s) {missing}")
        return False
    ok = True
    if not isinstance(a["id"], str) or not ID_RE.match(a["id"]):
        errors.append(f"{where}: id must match {ID_RE.pattern}")
        ok = False
    if a["adapter"] not in ADAPTER_KINDS:
        errors.append(f"{where}: adapter={a['adapter']!r} is not one of {list(ADAPTER_KINDS)}")
        ok = False
    for k in ("label", "workpackage", "solver", "model", "notes"):
        if a.get(k) is not None and not isinstance(a[k], str):
            errors.append(f"{where}: {k} must be a string")
            ok = False
    return ok


def parse_registry(obj, path=None, sha256=None):
    """Validate a registry object and return {"path", "sha256", "schema", "configs": {id: cfg}, "adapters": {...}}.

    Optional fields are filled with their defaults. Raises RegistryError listing every problem found.
    """
    errors = []
    if not isinstance(obj, dict):
        raise RegistryError("registry must be a JSON object")
    unknown = sorted(set(obj) - set(TOP_REQUIRED) - set(TOP_OPTIONAL))
    if unknown:
        errors.append(f"registry: unknown top-level field(s) {unknown}")
    missing = [k for k in TOP_REQUIRED if k not in obj]
    if missing:
        raise RegistryError(f"registry: missing top-level field(s) {missing}")
    if obj["schema"] != SCHEMA:
        errors.append(f"registry: schema must be {SCHEMA!r}, got {obj['schema']!r}")
    cfg_list, ad_list = obj["configs"], obj.get("adapters", [])
    if not isinstance(cfg_list, list) or not isinstance(ad_list, list):
        raise RegistryError("registry: configs and adapters must be lists")
    good_cfgs = [c for c in cfg_list if _check_config(c, errors)]
    good_ads = [a for a in ad_list if _check_adapter(a, errors)]
    seen = {}
    for kind, entries in (("config", good_cfgs), ("adapter", good_ads)):
        for e in entries:
            if e["id"] in seen:
                errors.append(f"duplicate id {e['id']!r} ({seen[e['id']]} and {kind})")
            seen.setdefault(e["id"], kind)
    configs = {c["id"]: dict(OPTIONAL, **c) for c in good_cfgs}
    adapters = {a["id"]: dict(ADAPTER_OPTIONAL, **a) for a in good_ads}
    # ---- round-0 reuse: the source must exist, generate its own round 0, and send a byte-identical request
    for c in configs.values():
        m = REUSE_RE.match(c["round0"])
        if not m:
            continue
        src_id = m.group(1)
        where = f"config {c['id']!r}"
        if src_id == c["id"]:
            errors.append(f"{where}: round0 reuses itself")
            continue
        if src_id in adapters:
            errors.append(f"{where}: round0 reuses adapter {src_id!r}; only pipeline configurations can be reused")
            continue
        src = configs.get(src_id)
        if src is None:
            errors.append(f"{where}: round0 reuses {src_id!r}, which is not a registered configuration")
            continue
        if src["round0"] != "own":
            errors.append(f"{where}: round0 reuses {src_id!r}, which itself reuses {src['round0'][6:]!r} (no chains)")
            continue
        if src.get("pipeline", "standard") != "standard":
            errors.append(f"{where}: round0 reuses {src_id!r}, whose pipeline is {src['pipeline']!r}")
        for k in ("prompt", "variant", "num_predict", "num_ctx"):
            if c[k] != src[k]:
                errors.append(f"{where}: round0 reuses {src_id!r} but {k} differs ({c[k]!r} vs {src[k]!r}), "
                              "so the reused round-0 request would not be identical")
    if errors:
        raise RegistryError("invalid configuration registry" + (f" {path}" if path else "") + ":\n  - "
                            + "\n  - ".join(errors))
    return {"path": path, "sha256": sha256, "schema": obj["schema"], "configs": configs, "adapters": adapters}


def load_registry(path=None):
    path = path or DEFAULT_REGISTRY
    with open(path, "rb") as f:
        raw = f.read()
    try:
        obj = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        raise RegistryError(f"registry {rel(path)} is not valid JSON: {e}") from None
    return parse_registry(obj, path=rel(path), sha256=hashlib.sha256(raw).hexdigest())


def all_ids(reg):
    """Every registered id (configurations and adapters)."""
    return tuple(reg["configs"]) + tuple(reg["adapters"])


def get_config(reg, config_id):
    if config_id in reg["configs"]:
        return reg["configs"][config_id]
    if config_id in reg["adapters"]:
        raise RegistryError(f"{config_id!r} is an adapter baseline ({reg['adapters'][config_id]['adapter']}); "
                            "it runs through its own adapter, not through this pipeline")
    raise RegistryError(f"unknown configuration {config_id!r}; registered: {sorted(reg['configs'])}")


def reuse_source(cfg):
    """Configuration id whose round-0 output this configuration reuses, or None."""
    m = REUSE_RE.match(cfg["round0"])
    return m.group(1) if m else None


def asks_for_spec(cfg):
    """True when round 0 asks for the JSON spec (spec predicates are not applicable otherwise)."""
    return cfg["prompt"] in SPEC_PROMPTS


def specless_scopes(reg):
    """Gene scopes that repairing configurations without a spec validate with (C3L, C3E): every gene of such a scope
    checks the program or its run, never the spec. Read from the registry, not from configuration names."""
    return sorted({c["gene_scope"] for c in reg["configs"].values()
                   if c["validator"] == "gene" and c["gene_scope"] and not asks_for_spec(c)})


def inapplicable_genes(cfg, reg, active):
    """geneIds among `active` that cannot apply to this configuration's answers (E06, observe mode of C0/C1): when
    round 0 asks for no spec, the genes outside every specless scope check the spec, which such an answer never has.
    They are recorded as not applicable instead of failing by construction. Empty when round 0 asks for a spec."""
    if asks_for_spec(cfg):
        return []
    free = set(specless_scopes(reg))
    return sorted(g["geneId"] for g in active
                  if (g.get("scope") or {}).get("conditions") and not set(g["scope"]["conditions"]) & free)


def check_store_scopes(store):
    """Gene records may only be scoped to C3, C3L, C3E; configurations reach them through gene_scope."""
    bad = []
    for g in store:
        conds = (g.get("scope") or {}).get("conditions") or []
        extra = [c for c in conds if c not in GENE_SCOPES]
        if extra:
            bad.append(f"{g.get('geneId')}: {extra}")
    if bad:
        raise RegistryError(f"gene scope names must be among {list(GENE_SCOPES)} (a configuration points at a scope "
                            "through gene_scope): " + "; ".join(bad))


def check_registry_against_store(reg, store):
    """Scope names are valid, and every scope a configuration uses has at least one active gene."""
    check_store_scopes(store)
    for c in reg["configs"].values():
        s = c["gene_scope"]
        if s is None:
            continue
        n = sum(1 for g in store if g["lifecycle"].get("state") == "active"
                and (not (g.get("scope") or {}).get("conditions") or s in g["scope"]["conditions"]))
        if n == 0:
            raise RegistryError(f"config {c['id']!r}: gene scope {s!r} has no active gene in this library")

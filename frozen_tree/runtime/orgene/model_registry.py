"""Model and decoding-parameter registry (E19): load, validate, entry hashes, and checks against what a runner
sends and against what a read-only snapshot of the host observes.

The registry is `configs/model_registry.json`:

  entries     one entry per (model, decoding setting) that a runner may send. The runners take
              `--registry configs/model_registry.json --registry-entry <id>` (E08): they refuse a call whose settings
              differ from the entry and record the entry's sha256 in the run's config.json. The entry format is the
              one the runners read: {"backend", "model", "digest", "opts": {every key sent}, "seed_rule"}, plus
              "purpose", "basis" and an "identity" block (observed facts: blobs, quantization, Ollama version, the
              server's flash attention / KV cache settings). The identity block is part of the entry, so the entry
              hash a run records covers it.
  models      other Ollama models the project may use (the long-context alias)
  api_models  API models: requested id, returned ids and fingerprints, call dates, seed support (pending, D6)
  anchors     ORLM / LLMOPT checkpoints: HF revision, safetensors and GGUF sha256, Ollama identity, llama.cpp build
  server      the Ollama server settings that change results (flash attention, KV cache type, parallel slots)
  execution   interpreter, PuLP, CBC and the execution timeouts
  baselines   baseline environment: coptpy, Pyomo, glpk, COPT license mode, llama.cpp build
  tokenizers  local tokenizers (E09 uses llama-tokenize; the API tokenizer is pending)

Decisions (opts, seed rules, purposes, timeouts, anchor provenance) are edited by hand and reviewed. Observed facts
are written only by `apply_snapshot` (tools/model_registry.py update) from a snapshot taken by
orgene.model_snapshot, and `compare_snapshot` (tools/model_registry.py check) reports every difference.

Standard library only. Nothing here contacts a server; the snapshot module does the (read-only) reading.
"""
import copy
import hashlib
import json
import os
import re

from .paths import ROOT, find_absolute_paths, rel

SCHEMA_VERSION = "orgene.r1.model_registry.v1"
DEFAULT_PATH = os.path.join(ROOT, "configs", "model_registry.json")

TOP_KEYS = ("schema_version", "about", "generated", "entries", "models", "api_models", "anchors", "server",
            "execution", "baselines", "tokenizers")
TOP_REQUIRED = ("schema_version", "entries", "server", "execution")
ENTRY_REQUIRED = ("backend", "model", "opts", "seed_rule", "purpose")
ENTRY_OPTIONAL = ("digest", "basis", "identity", "notes", "status")
# An entry whose settings are not final carries "status": "pending" (the anchors, until the preregistration fixes them);
# an entry without the key is final. Drivers refuse a pending entry for sealed (test) cases (entry_pending).
ENTRY_STATUSES = ("pending",)
SEED_RULES = ("base+k", "fixed")
ENTRY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
DURATION_RE = re.compile(r"^(\d+(\.\d+)?(ns|us|ms|s|m|h))+$")
# an API model id counts as a dated snapshot when it carries a date (2024-08-06 or 20240806)
DATED_ID_RE = re.compile(r"(?<!\d)(20\d{2}-\d{2}-\d{2}|20\d{6})(?!\d)")

# What each backend sends (the flat keys of `sent_opts`). Kept in step with REQUIRED_OPTS of orgene.backends.* (E08);
# runtime/tests/test_model_registry.py compares the two when the backends are present.
BACKENDS = {
    "ollama": {
        "required": ("temperature", "top_k", "top_p", "seed", "num_ctx", "num_predict", "think", "keep_alive"),
        "int": ("top_k", "seed", "num_ctx", "num_predict", "num_keep", "repeat_last_n"),
        "float": ("temperature", "top_p", "min_p", "typical_p", "repeat_penalty", "presence_penalty", "frequency_penalty"),
        "bool": ("think",),
        "other": ("stop", "keep_alive"),
        "nullable": (),
        "must_be_null": (),
    },
    "openai_compat": {
        "required": ("temperature", "top_p", "seed", "max_tokens"),
        "int": ("seed", "max_tokens"), "float": ("temperature", "top_p"), "bool": (), "other": (),
        "nullable": ("temperature", "top_p", "seed"), "must_be_null": (),
    },
    "anthropic": {
        # the Messages API has no seed; the backend reports seed None, so the entry must say so explicitly
        "required": ("temperature", "max_tokens", "seed"),
        "int": ("max_tokens",), "float": ("temperature",), "bool": (), "other": ("seed",),
        "nullable": ("temperature", "seed"), "must_be_null": ("seed",),
    },
    "llamacpp": {
        "required": ("temperature", "top_k", "top_p", "seed", "max_tokens"),
        "int": ("top_k", "seed", "max_tokens"), "float": ("temperature", "top_p", "min_p", "repeat_penalty"),
        "bool": (), "other": (), "nullable": (), "must_be_null": (),
    },
    # llama-server's native /completion (E17, the ORLM anchor): the raw prompt, every arg-max-relevant sampler sent
    "llamacpp_completion": {
        "required": ("temperature", "top_k", "top_p", "min_p", "typical_p", "repeat_penalty", "presence_penalty",
                     "frequency_penalty", "dry_multiplier", "xtc_probability", "mirostat", "seed", "n_predict",
                     "cache_prompt", "stop"),
        "int": ("top_k", "seed", "n_predict", "mirostat"),
        "float": ("temperature", "top_p", "min_p", "typical_p", "repeat_penalty", "presence_penalty",
                  "frequency_penalty", "dry_multiplier", "xtc_probability"),
        "bool": ("cache_prompt",), "other": ("stop",), "nullable": (), "must_be_null": (),
    },
}
API_BACKENDS = ("openai_compat", "anthropic")

# identity block of an Ollama entry (observed; written by apply_snapshot)
OLLAMA_IDENTITY_KEYS = ("ollama_version", "weights_blob_sha256", "template_blob_sha256", "params_blob_sha256",
                        "license_blob_sha256", "quantization_level", "parameter_size", "family", "modelfile_params",
                        "inherited_by_calls", "server")
SERVER_IDENTITY_KEYS = ("flash_attention", "kv_cache_type", "num_parallel")
# server settings that change results or scheduling, as named in the server's own start-up line. Path-valued
# settings (models directory, host, origins) are never read.
SERVER_SETTING_KEYS = ("OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE", "OLLAMA_NUM_PARALLEL", "OLLAMA_CONTEXT_LENGTH",
                       "OLLAMA_KEEP_ALIVE", "OLLAMA_MAX_LOADED_MODELS", "OLLAMA_SCHED_SPREAD", "OLLAMA_GPU_OVERHEAD",
                       "OLLAMA_LOAD_TIMEOUT", "OLLAMA_NOPRUNE", "OLLAMA_NEW_ENGINE", "OLLAMA_MULTIUSER_CACHE")
# fields that record when something happened; `check` reports their changes as notes, not as mismatches
PROVENANCE_FIELDS = ("server.ollama.process_started_at", "server.ollama.startup_logged_at")

_MISSING = object()


class RegistryError(ValueError):
    """The registry file is malformed or inconsistent."""


class RegistryMismatch(RuntimeError):
    """Settings about to be sent (or recorded by a run) differ from the registry entry."""


class IdentityChange(RuntimeError):
    """A snapshot would change a model identity already in the registry (digest or weights)."""


# ---------------------------------------------------------------------------------------------------- hashing


def canonical_json(obj):
    """Deterministic bytes for hashing: sorted keys, no whitespace, UTF-8, NaN refused (same as the runners, E08)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_hex(b):
    return hashlib.sha256(b).hexdigest()


def entry_sha256(entry):
    """The hash a run records for the entry it used: sha256 of the canonical JSON of the entry as loaded."""
    return sha256_hex(canonical_json(entry))


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------------- loading


def read(path=None):
    """Parse the registry JSON without validating it."""
    with open(path or DEFAULT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load(path=None, require_observed=True):
    """Parse and validate. Raises RegistryError listing every problem."""
    reg = read(path)
    problems = validate(reg, require_observed=require_observed)
    if problems:
        raise RegistryError("registry %s is not valid:\n  - %s" % (rel(path or DEFAULT_PATH), "\n  - ".join(problems)))
    return reg


def dump(reg, path=None):
    """Write the registry (2-space indent, UTF-8, trailing newline)."""
    text = json.dumps(reg, ensure_ascii=False, indent=2) + "\n"
    with open(path or DEFAULT_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def get_entry(reg, entry_id):
    e = (reg.get("entries") or {}).get(entry_id)
    if not isinstance(e, dict):
        raise RegistryError(f"no registry entry {entry_id!r}; known: {sorted(reg.get('entries') or {})}")
    return e


def entry_record(path, entry_id):
    """The block a run writes into its config.json (same shape as the runners' `registry` block, E08)."""
    reg = read(path)
    return {"path": rel(path or DEFAULT_PATH), "entry_id": entry_id, "entry_sha256": entry_sha256(get_entry(reg, entry_id))}


def registered_ollama_models(reg):
    """Ollama model tags the registry names (entries, models, anchors) — the only ones a snapshot records."""
    tags = []
    for e in (reg.get("entries") or {}).values():
        if e.get("backend") == "ollama" and e.get("model") not in tags:
            tags.append(e["model"])
    for tag in (reg.get("models") or {}):
        if tag not in tags:
            tags.append(tag)
    for a in (reg.get("anchors") or {}).values():
        o = a.get("ollama") or {}
        if o.get("model") and o["model"] not in tags:
            tags.append(o["model"])
    return tags


# ---------------------------------------------------------------------------------------------------- validation


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# E23: an Ollama entry's think is true / false or a reasoning level (gpt-oss cannot switch its reasoning off). Kept
# equal to orgene.backends.ollama.THINK_LEVELS (runtime/tests/test_gptoss_e23.py compares the two).
OLLAMA_THINK_LEVELS = ("low", "medium", "high")


def _check_opts(eid, backend, opts, problems):
    spec = BACKENDS[backend]
    known = set(spec["int"]) | set(spec["float"]) | set(spec["bool"]) | set(spec["other"])
    for k in sorted(set(opts) - known):
        problems.append(f"entries.{eid}.opts: unknown key {k!r} for backend {backend}")
    for k in spec["required"]:
        if k not in opts:
            problems.append(f"entries.{eid}.opts: {k!r} must be set explicitly")
    for k, v in opts.items():
        if k not in known:
            continue
        if v is None:
            if k not in spec["nullable"]:
                problems.append(f"entries.{eid}.opts.{k}: None is not allowed")
            continue
        if k in spec["must_be_null"]:
            problems.append(f"entries.{eid}.opts.{k}: must be null for backend {backend}")
        elif k in spec["bool"] and not isinstance(v, bool) and not (k == "think" and v in OLLAMA_THINK_LEVELS):
            levels = f" or one of {OLLAMA_THINK_LEVELS}" if k == "think" else ""
            problems.append(f"entries.{eid}.opts.{k}: must be true/false{levels}, got {v!r}")
        elif k in spec["int"] and not _is_int(v):
            problems.append(f"entries.{eid}.opts.{k}: must be an integer, got {v!r}")
        elif k in spec["float"] and not _is_num(v):
            problems.append(f"entries.{eid}.opts.{k}: must be a number, got {v!r}")
        elif k == "keep_alive" and not ((_is_int(v) and v >= 0) or (isinstance(v, str) and DURATION_RE.match(v))):
            problems.append(f"entries.{eid}.opts.keep_alive: seconds (int >= 0) or a duration such as 30m, got {v!r}")
        elif k == "stop" and not (isinstance(v, list) and all(isinstance(s, str) for s in v)):
            problems.append(f"entries.{eid}.opts.stop: must be a list of strings")
    for k in ("temperature", "top_p"):
        v = opts.get(k)
        if _is_num(v) and v < 0:
            problems.append(f"entries.{eid}.opts.{k}: must be >= 0")


def _check_hex(where, v, problems, rx=HEX64_RE, required=True):
    if v is None:
        if required:
            problems.append(f"{where}: not yet observed (run tools/model_registry.py update)")
        return
    if not isinstance(v, str) or not rx.match(v):
        problems.append(f"{where}: not a lowercase hex digest: {v!r}")


def entry_pending(entry):
    """True when a registry entry is marked "status": "pending" (its settings are not final)."""
    return isinstance(entry, dict) and entry.get("status") == "pending"


def api_model_allowed(reg, model_id):
    """E10's rule: an API model id must be a dated snapshot, or be listed in api_models.allowlist."""
    if isinstance(model_id, str) and DATED_ID_RE.search(model_id):
        return True
    allow = ((reg.get("api_models") or {}).get("allowlist")) or []
    return model_id in allow


def validate(reg, require_observed=True):
    """Static checks. Returns a list of problems (empty = valid)."""
    p = []
    if not isinstance(reg, dict):
        return ["registry must be a JSON object"]
    for k in sorted(set(reg) - set(TOP_KEYS)):
        p.append(f"unknown top-level key {k!r}")
    for k in TOP_REQUIRED:
        if k not in reg:
            p.append(f"missing top-level key {k!r}")
    if reg.get("schema_version") != SCHEMA_VERSION:
        p.append(f"schema_version must be {SCHEMA_VERSION!r}")
    entries = reg.get("entries")
    if not isinstance(entries, dict) or not entries:
        p.append("entries must be a non-empty object")
        entries = {}
    by_model = {}
    for eid, e in entries.items():
        where = f"entries.{eid}"
        if not ENTRY_ID_RE.match(eid):
            p.append(f"{where}: entry id must match {ENTRY_ID_RE.pattern}")
        if not isinstance(e, dict):
            p.append(f"{where}: must be an object")
            continue
        for k in sorted(set(e) - set(ENTRY_REQUIRED) - set(ENTRY_OPTIONAL)):
            p.append(f"{where}: unknown key {k!r}")
        for k in ENTRY_REQUIRED:
            if k not in e:
                p.append(f"{where}: missing {k!r}")
        backend = e.get("backend")
        if backend not in BACKENDS:
            p.append(f"{where}.backend: unknown backend {backend!r}; known: {sorted(BACKENDS)}")
            continue
        if not isinstance(e.get("model"), str) or not e.get("model"):
            p.append(f"{where}.model: must be a non-empty string")
        if e.get("seed_rule") not in SEED_RULES:
            p.append(f"{where}.seed_rule: must be one of {SEED_RULES}")
        if not isinstance(e.get("purpose"), str) or not e.get("purpose", "").strip():
            p.append(f"{where}.purpose: must be a non-empty string")
        if "status" in e and e["status"] not in ENTRY_STATUSES:
            p.append(f"{where}.status: must be one of {ENTRY_STATUSES} (a final entry has no status key)")
        opts = e.get("opts")
        if not isinstance(opts, dict):
            p.append(f"{where}.opts: must be an object")
        else:
            _check_opts(eid, backend, opts, p)
            if e.get("seed_rule") == "base+k" and opts.get("seed") is None and "seed" in BACKENDS[backend]["int"]:
                p.append(f"{where}: seed_rule base+k needs an integer seed")
        if backend == "ollama":
            _check_hex(f"{where}.digest", e.get("digest"), p, required=require_observed)
            ident = e.get("identity")
            if not isinstance(ident, dict):
                p.append(f"{where}.identity: required for an Ollama entry")
            else:
                for k in sorted(set(ident) - set(OLLAMA_IDENTITY_KEYS)):
                    p.append(f"{where}.identity: unknown key {k!r}")
                for k in ("weights_blob_sha256", "template_blob_sha256", "params_blob_sha256"):
                    _check_hex(f"{where}.identity.{k}", ident.get(k), p, required=require_observed)
                if require_observed:
                    for k in ("ollama_version", "quantization_level", "modelfile_params"):
                        if ident.get(k) in (None, ""):
                            p.append(f"{where}.identity.{k}: not yet observed (run tools/model_registry.py update)")
                srv = ident.get("server")
                if not isinstance(srv, dict):
                    p.append(f"{where}.identity.server: required (flash attention, KV cache type)")
                else:
                    for k in sorted(set(srv) - set(SERVER_IDENTITY_KEYS)):
                        p.append(f"{where}.identity.server: unknown key {k!r}")
                    if require_observed and not isinstance(srv.get("flash_attention"), bool):
                        p.append(f"{where}.identity.server.flash_attention: must be observed as true/false")
                    if require_observed and not isinstance(srv.get("kv_cache_type"), str):
                        p.append(f"{where}.identity.server.kv_cache_type: must be observed")
                mp = ident.get("modelfile_params")
                if isinstance(mp, dict) and isinstance(opts, dict):
                    want = {k: v for k, v in sorted(mp.items()) if k not in opts}
                    if ident.get("inherited_by_calls") != want:
                        p.append(f"{where}.identity.inherited_by_calls: must list the Modelfile parameters the entry "
                                 f"does not send: {want}")
            by_model.setdefault(e.get("model"), []).append(eid)
        if backend in API_BACKENDS and not api_model_allowed(reg, e.get("model")):
            p.append(f"{where}.model: API model id {e.get('model')!r} is neither a dated snapshot nor in api_models.allowlist")
    # entries of one model share its identity
    for model, eids in by_model.items():
        base = entries[eids[0]]
        for eid in eids[1:]:
            e = entries[eid]
            if e.get("digest") != base.get("digest"):
                p.append(f"entries.{eid}.digest differs from entries.{eids[0]}.digest (same model {model})")
            a = {k: v for k, v in (e.get("identity") or {}).items() if k != "inherited_by_calls"}
            b = {k: v for k, v in (base.get("identity") or {}).items() if k != "inherited_by_calls"}
            if a != b:
                p.append(f"entries.{eid}.identity differs from entries.{eids[0]}.identity (same model {model})")
    _validate_models(reg, entries, p, require_observed)
    _validate_server(reg, entries, p, require_observed)
    _validate_execution(reg, p)
    _validate_anchors(reg, p, require_observed)
    _validate_api(reg, p)
    # neutral writing: no home-directory paths anywhere in the file
    text = json.dumps(reg, ensure_ascii=False)
    for hit in find_absolute_paths(text):
        p.append(f"registry contains a home-directory path: {hit[:12]}...")
    home = os.path.expanduser("~")
    if home and home not in ("/", "~") and home in text:
        p.append("registry contains this host's home directory")
    return p


def _validate_models(reg, entries, p, require_observed):
    models = reg.get("models") or {}
    if not isinstance(models, dict):
        p.append("models must be an object")
        return
    allowed = ("role", "digest", "weights_blob_sha256", "template_blob_sha256", "params_blob_sha256",
               "license_blob_sha256", "params_blob_text", "params", "quantization_level", "show_template_sha256", "same_weights_as",
               "modelfile_directives", "modelfile_sha256", "caution")
    for tag, m in models.items():
        where = f"models.{tag}"
        if not isinstance(m, dict):
            p.append(f"{where}: must be an object")
            continue
        for k in sorted(set(m) - set(allowed)):
            p.append(f"{where}: unknown key {k!r}")
        if not m.get("role"):
            p.append(f"{where}.role: required")
        for k in ("digest", "weights_blob_sha256", "template_blob_sha256", "params_blob_sha256"):
            _check_hex(f"{where}.{k}", m.get(k), p, required=require_observed)
        if require_observed and m.get("params_blob_text") is not None:
            try:
                if json.loads(m["params_blob_text"]) != m.get("params"):
                    p.append(f"{where}.params: must be the parsed params_blob_text")
            except (TypeError, ValueError):
                p.append(f"{where}.params_blob_text: not JSON")
        base = m.get("same_weights_as")
        if base:
            ents = [e for e in entries.values() if e.get("model") == base]
            if not ents:
                p.append(f"{where}.same_weights_as: no entry for model {base!r}")
            else:
                w = (ents[0].get("identity") or {}).get("weights_blob_sha256")
                if m.get("weights_blob_sha256") != w:
                    p.append(f"{where}.weights_blob_sha256 must equal the weights of {base} ({str(w)[:12]}...)")


def _validate_server(reg, entries, p, require_observed):
    srv = ((reg.get("server") or {}).get("ollama"))
    if not isinstance(srv, dict):
        p.append("server.ollama: required")
        return
    if require_observed:
        if not isinstance(srv.get("flash_attention"), bool):
            p.append("server.ollama.flash_attention: must be observed as true/false")
        if not isinstance(srv.get("kv_cache_type"), str):
            p.append("server.ollama.kv_cache_type: must be observed")
        if srv.get("sources_agree") is not True:
            p.append("server.ollama.sources_agree: the sources of the server settings must agree")
    for k in sorted(set(srv.get("settings") or {}) - set(SERVER_SETTING_KEYS)):
        p.append(f"server.ollama.settings: key {k!r} is not in the allowlist")
    for eid, e in entries.items():
        if e.get("backend") != "ollama":
            continue
        ident = e.get("identity") or {}
        es = ident.get("server") or {}
        for k, sk in (("flash_attention", "flash_attention"), ("kv_cache_type", "kv_cache_type")):
            if es.get(k) != srv.get(sk):
                p.append(f"entries.{eid}.identity.server.{k} differs from server.ollama.{sk}")
        if ident.get("ollama_version") != srv.get("version"):
            p.append(f"entries.{eid}.identity.ollama_version differs from server.ollama.version")


def _validate_execution(reg, p):
    ex = reg.get("execution")
    if not isinstance(ex, dict):
        p.append("execution must be an object")
        return
    for k in ("timeout_s", "timeout_s_engineering_cases"):
        if not (_is_int(ex.get(k)) and ex.get(k) > 0):
            p.append(f"execution.{k}: must be a positive integer")


def _validate_anchors(reg, p, require_observed):
    anchors = reg.get("anchors") or {}
    for name, a in anchors.items():
        where = f"anchors.{name}"
        if not isinstance(a, dict):
            p.append(f"{where}: must be an object")
            continue
        if not a.get("hf_repo"):
            p.append(f"{where}.hf_repo: required")
        _check_hex(f"{where}.hf_revision", a.get("hf_revision"), p, rx=HEX40_RE)
        st = a.get("safetensors_sha256")
        if not isinstance(st, dict) or not st:
            p.append(f"{where}.safetensors_sha256: required (file -> sha256)")
        else:
            for fn, h in st.items():
                _check_hex(f"{where}.safetensors_sha256[{fn}]", h, p)
        g = a.get("gguf") or {}
        _check_hex(f"{where}.gguf.sha256", g.get("sha256"), p)
        o = a.get("ollama")
        if isinstance(o, dict):
            for k in ("digest", "weights_blob_sha256", "template_blob_sha256", "params_blob_sha256"):
                _check_hex(f"{where}.ollama.{k}", o.get(k), p, required=require_observed)


def _validate_api(reg, p):
    api = reg.get("api_models")
    if api is None:
        return
    if not isinstance(api, dict):
        p.append("api_models must be an object")
        return
    for k in sorted(set(api) - {"status", "record_per_model", "allowlist", "models"}):
        p.append(f"api_models: unknown key {k!r}")
    allowed = ("requested_id", "dated_snapshot", "seed_supported", "tokenizer", "observed", "observed_by_run", "notes")
    for mid, m in (api.get("models") or {}).items():
        if not isinstance(m, dict):
            p.append(f"api_models.models.{mid}: must be an object")
            continue
        for k in sorted(set(m) - set(allowed)):
            p.append(f"api_models.models.{mid}: unknown key {k!r}")
        if m.get("requested_id") != mid:
            p.append(f"api_models.models.{mid}.requested_id must equal the key")
        if m.get("seed_supported") not in (True, False, None):
            p.append(f"api_models.models.{mid}.seed_supported: true, false or null")
        runs = m.get("observed_by_run")
        if m.get("observed") is not None and not isinstance(runs, dict):
            p.append(f"api_models.models.{mid}.observed: must come from observed_by_run (tools/model_registry.py "
                     f"api-observed --update)")
        elif isinstance(runs, dict):
            for src in runs:
                if os.path.isabs(src) or src.startswith("<"):
                    p.append(f"api_models.models.{mid}.observed_by_run: {src[:12]}... is not a run directory "
                             f"relative to the repository")
            if m.get("observed") != combine_api_observed(runs.values()):
                p.append(f"api_models.models.{mid}.observed: must equal the combination of observed_by_run")


# ---------------------------------------------------------------------------------------------------- sent settings


def same_value(a, b):
    """Numbers compare by value (0 == 0.0); booleans only with booleans (false != 0) — same rule as the runners."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_num(a) and _is_num(b):
        return float(a) == float(b)
    return a == b


def expected_opts(entry, repeat_index=0):
    """The flat settings a call with this repeat index must send: seed = base + k under seed_rule base+k."""
    rule = entry.get("seed_rule", "base+k")
    if rule not in SEED_RULES:
        raise RegistryMismatch(f"unknown seed_rule {rule!r}")
    exp = dict(entry.get("opts") or {})
    if rule == "base+k" and _is_int(exp.get("seed")):
        exp["seed"] = exp["seed"] + int(repeat_index)
    return exp


def compare_sent(entry, sent, *, backend_kind=None, model=None, digest=None, repeat_index=0):
    """Differences between the settings about to be sent (flat `sent_opts`) and the entry. Empty list = identical.

    The entry must cover every key sent and every key it lists must be sent; values compare with same_value.
    backend_kind / model / digest are compared when given (the digest only when the entry has one).
    """
    problems = []
    if backend_kind is not None and entry.get("backend") != backend_kind:
        problems.append(f"backend: registry {entry.get('backend')!r} != {backend_kind!r}")
    if model is not None and entry.get("model") != model:
        problems.append(f"model: registry {entry.get('model')!r} != {model!r}")
    if digest is not None and entry.get("digest") and entry["digest"] != digest:
        problems.append(f"digest: registry {entry['digest']!r} != {digest!r}")
    exp = expected_opts(entry, repeat_index)
    for key in sorted(set(exp) | set(sent)):
        a, b = exp.get(key, _MISSING), sent.get(key, _MISSING)
        if a is _MISSING:
            problems.append(f"{key}: sent {b!r} but not in the registry entry")
        elif b is _MISSING:
            problems.append(f"{key}: registry {a!r} but not sent")
        elif not same_value(a, b):
            problems.append(f"{key}: registry {a!r} != sent {b!r}")
    return problems


def require_sent(entry, sent, **kw):
    """compare_sent that raises RegistryMismatch (for executors that call a backend without orgene.runner)."""
    problems = compare_sent(entry, sent, **kw)
    if problems:
        raise RegistryMismatch("; ".join(problems))


# ---------------------------------------------------------------------------------------------------- snapshot -> registry


def _layer(m, kind):
    return ((m or {}).get("layers") or {}).get(kind)


def _ollama_identity(snap, model, opts, old=None):
    o = snap["ollama"]
    m = o["models"][model]
    params = m.get("params") or {}
    srv = o.get("server") or {}
    old_srv = (old or {}).get("server") or {}
    # a server setting the snapshot did not observe keeps its registered value
    server = {
        "flash_attention": srv.get("flash_attention") if srv.get("flash_attention") is not None else old_srv.get("flash_attention"),
        "kv_cache_type": srv.get("kv_cache_type") if srv.get("kv_cache_type") is not None else old_srv.get("kv_cache_type"),
        "num_parallel": ((srv.get("settings") or {}).get("OLLAMA_NUM_PARALLEL") if srv.get("settings_from") == "startup_log"
                         else old_srv.get("num_parallel")),
    }
    return {
        "ollama_version": o.get("version"),
        "weights_blob_sha256": _layer(m, "model"),
        "template_blob_sha256": _layer(m, "template"),
        "params_blob_sha256": _layer(m, "params"),
        "license_blob_sha256": _layer(m, "license"),
        "quantization_level": (m.get("details") or {}).get("quantization_level"),
        "parameter_size": (m.get("details") or {}).get("parameter_size"),
        "family": (m.get("details") or {}).get("family"),
        "modelfile_params": params,
        "inherited_by_calls": {k: v for k, v in sorted(params.items()) if k not in (opts or {})},
        "server": server,
    }


def _guard_identity(where, old, new, accept, changes):
    if old not in (None, "") and new is not None and old != new:
        changes.append(f"{where}: {str(old)[:16]} -> {str(new)[:16]}")
        return old if not accept else new
    return new if new is not None else old


def apply_snapshot(reg, snap, *, snapshot_path=None, accept_identity_change=False):
    """Return (new registry, notes). Writes the observed facts of `snap` into a copy of `reg`; decisions are untouched.

    A snapshot that would change an existing model digest or weights blob raises IdentityChange unless
    accept_identity_change. Parts the snapshot did not observe are left as they are and listed in notes.
    """
    new = copy.deepcopy(reg)
    notes, changes = [], []
    ol = snap.get("ollama") or {}
    om = ol.get("models") or {}
    for eid, e in (new.get("entries") or {}).items():
        if e.get("backend") != "ollama":
            continue
        if e.get("model") not in om:
            notes.append(f"entries.{eid}: model {e.get('model')} not observed")
            continue
        m = om[e["model"]]
        e["digest"] = _guard_identity(f"entries.{eid}.digest", e.get("digest"), m.get("digest"), accept_identity_change, changes)
        ident = _ollama_identity(snap, e["model"], e.get("opts"), e.get("identity"))
        old_w = (e.get("identity") or {}).get("weights_blob_sha256")
        ident["weights_blob_sha256"] = _guard_identity(f"entries.{eid}.identity.weights_blob_sha256", old_w,
                                                       ident["weights_blob_sha256"], accept_identity_change, changes)
        e["identity"] = ident
    for tag, mm in (new.get("models") or {}).items():
        if tag not in om:
            notes.append(f"models.{tag}: not observed")
            continue
        m = om[tag]
        mm["digest"] = _guard_identity(f"models.{tag}.digest", mm.get("digest"), m.get("digest"), accept_identity_change, changes)
        for k, kind in (("weights_blob_sha256", "model"), ("template_blob_sha256", "template"),
                        ("params_blob_sha256", "params"), ("license_blob_sha256", "license")):
            mm[k] = _layer(m, kind)
        mm["params_blob_text"] = m.get("params_blob_text")
        mm["params"] = m.get("params")
        mm["quantization_level"] = (m.get("details") or {}).get("quantization_level")
        mm["show_template_sha256"] = m.get("template_sha256")
    for name, a in (new.get("anchors") or {}).items():
        o = a.get("ollama")
        if not isinstance(o, dict) or not o.get("model"):
            continue
        if o["model"] not in om:
            notes.append(f"anchors.{name}.ollama: model {o['model']} not observed")
            continue
        m = om[o["model"]]
        o["digest"] = _guard_identity(f"anchors.{name}.ollama.digest", o.get("digest"), m.get("digest"), accept_identity_change, changes)
        for k, kind in (("weights_blob_sha256", "model"), ("template_blob_sha256", "template"), ("params_blob_sha256", "params")):
            o[k] = _layer(m, kind)
        o["quantization_level"] = (m.get("details") or {}).get("quantization_level")
        o["modelfile_params"] = m.get("params")
        # what /api/show reports as the template (for a GGUF with its own chat template this can differ from the
        # Modelfile TEMPLATE blob; recorded so that a change is seen)
        o["show_template_sha256"] = m.get("template_sha256")
    srv_snap = ol.get("server")
    if srv_snap and srv_snap.get("settings_from"):
        s = new.setdefault("server", {}).setdefault("ollama", {})
        s["version"] = ol.get("version")
        s["flash_attention"] = srv_snap.get("flash_attention")
        s["kv_cache_type"] = srv_snap.get("kv_cache_type")
        if srv_snap.get("settings_from") == "startup_log":
            # the full allowlisted settings come from the server's own start-up line only
            s["settings"] = {k: v for k, v in (srv_snap.get("settings") or {}).items() if k in SERVER_SETTING_KEYS}
        else:
            notes.append("server: start-up log not read; only flash attention and the KV cache type were compared")
        if srv_snap.get("agree") is not None:
            s["sources_agree"] = srv_snap.get("agree")
        srcs = dict(s.get("sources") or {})
        srcs.update(srv_snap.get("sources_seen") or {})
        s["sources"] = {k: srcs[k] for k in sorted(srcs)}
        for k in ("process_started_at", "startup_logged_at"):
            if srv_snap.get(k):
                s[k] = srv_snap[k]
        loads = srv_snap.get("model_loads") or {}
        ev = dict(s.get("model_load_evidence") or {})
        for blob, info in loads.items():
            # what every logged load of a registered weight blob ran with (counts and dates stay in the snapshot)
            ev[blob] = {"flash_attn_seen": info.get("flash_attn_seen"), "kv_cache_seen": info.get("kv_cache_seen")}
        if ev:
            s["model_load_evidence"] = {k: ev[k] for k in sorted(ev)}
    elif ol.get("models") is not None:
        notes.append("server settings not observed")
    ex = snap.get("execution")
    if ex and ex.get("ok"):
        e = new.setdefault("execution", {})
        for k in ("python_version", "machine", "pulp_version", "cbc_version"):
            e[k] = ex.get(k)
    elif ex is not None:
        notes.append(f"execution check failed: {ex.get('error')}")
    bl = snap.get("baselines")
    if bl and bl.get("observed"):
        b = new.setdefault("baselines", {})
        b["python_version"] = bl.get("python_version")
        b["packages"] = bl.get("packages")
        lic = b.setdefault("copt_license", {})
        lic["license_file_found"] = bl.get("copt_license_file_found")
    tools = snap.get("tools") or {}
    if tools.get("glpsol"):
        new.setdefault("baselines", {})["glpk_version"] = tools["glpsol"].get("version")
    if tools.get("llama_server"):
        new.setdefault("baselines", {})["llama_cpp"] = {k: tools["llama_server"].get(k) for k in ("version", "build", "commit")}
    if tools.get("llama_tokenize"):
        t = new.setdefault("tokenizers", {}).setdefault("llama_tokenize", {})
        for k in ("version", "build", "commit"):
            t[k] = tools["llama_tokenize"].get(k)
    if changes and not accept_identity_change:
        raise IdentityChange("the snapshot would change model identities already in the registry: " + "; ".join(changes))
    gen = {"by": "tools/model_registry.py update", "snapshot_taken_at": snap.get("taken_at")}
    if snapshot_path:
        gen["snapshot"] = rel(snapshot_path)
        gen["snapshot_sha256"] = file_sha256(snapshot_path)
    new["generated"] = gen
    return new, notes + [f"identity changed (accepted): {c}" for c in changes]


def _leaves(obj, prefix=""):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out.update(_leaves(v, f"{prefix}.{k}" if prefix else str(k)))
        if not obj and prefix:
            out[prefix] = {}
        return out
    return {prefix: obj}


def compare_snapshot(reg, snap):
    """Differences between the registry's observed facts and a snapshot.

    Returns (mismatches, notes): mismatches are real differences (a model, blob, version or server setting is not
    what the registry says, or the snapshot itself is inconsistent); notes are unobserved parts and provenance
    fields that moved (a server restart time).
    """
    mismatches, notes = [], []
    try:
        applied, notes = apply_snapshot(reg, snap, accept_identity_change=True)
    except Exception as e:  # noqa: BLE001
        return [f"snapshot cannot be applied: {type(e).__name__}: {e}"], []
    notes = [n for n in notes if not n.startswith("identity changed (accepted)")]
    a = _leaves({k: v for k, v in reg.items() if k != "generated"})
    b = _leaves({k: v for k, v in applied.items() if k != "generated"})
    for path in sorted(set(a) | set(b)):
        va, vb = a.get(path, _MISSING), b.get(path, _MISSING)
        if va is _MISSING and vb is _MISSING:
            continue
        if va == vb and type(va) is type(vb):
            continue
        # a new model-load record for an already registered blob, or a moved start time, is a note
        if path in PROVENANCE_FIELDS or (va is _MISSING and path.startswith("server.ollama.model_load_evidence.")):
            notes.append(f"{path}: registry {_short(va)} / observed {_short(vb)}")
            continue
        mismatches.append(f"{path}: registry {_short(va)} / observed {_short(vb)}")
    # the snapshot's own consistency; a registered model that is missing is a mismatch, never a silent pass
    entry_models = {e.get("model") for e in (reg.get("entries") or {}).values() if e.get("backend") == "ollama"}
    ol = snap.get("ollama")
    if ol is not None:
        if ol.get("error"):
            mismatches.append(f"snapshot: Ollama: {ol['error']}")
        observed = ol.get("models")
        for tag in registered_ollama_models(reg):
            m = (observed or {}).get(tag)
            if m is None:
                if observed is not None:
                    mismatches.append(f"snapshot: model {tag}: not observed")
                continue
            if m.get("error"):
                mismatches.append(f"snapshot: model {tag}: {m['error']}")
            if m.get("show_error"):
                # without /api/show the template the server chats with is not checked; never a silent pass
                mismatches.append(f"snapshot: model {tag}: /api/show failed ({m['show_error']})")
            if m.get("digest_matches_manifest") is False:
                mismatches.append(f"snapshot: model {tag}: /api/tags digest differs from the manifest file's sha256")
            if m.get("template_matches_blob") is False and tag in entry_models:
                # a runner entry's model must chat with exactly its template blob (the LLMOPT anchor, whose GGUF
                # carries its own chat template, renders its prompt itself on llama-server: no Ollama entry)
                mismatches.append(f"snapshot: model {tag}: /api/show template differs from the template blob")
            for kind, ok in (m.get("layer_hashes_verified") or {}).items():
                if ok is False:
                    mismatches.append(f"snapshot: model {tag}: {kind} blob content does not match its name")
    srv = (snap.get("ollama") or {}).get("server") or {}
    if srv and srv.get("agree") is False:
        mismatches.append("snapshot: the sources of the server settings disagree: " + "; ".join(srv.get("disagreements") or []))
    for blob, info in (srv.get("model_loads") or {}).items():
        exp_fa = (reg.get("server") or {}).get("ollama", {}).get("flash_attention")
        exp_kv = (reg.get("server") or {}).get("ollama", {}).get("kv_cache_type")
        fa_ok = {"enabled": True, "disabled": False}
        for fa in info.get("flash_attn_seen") or []:
            if exp_fa is not None and fa_ok.get(fa, None) is not exp_fa:
                mismatches.append(f"snapshot: a load of blob {blob[:12]} ran with flash_attn={fa}")
        for kv in info.get("kv_cache_seen") or []:
            if exp_kv and kv != f"{exp_kv}/{exp_kv}":
                mismatches.append(f"snapshot: a load of blob {blob[:12]} ran with KV cache {kv}")
    ex = snap.get("execution")
    if ex is not None and not ex.get("ok"):
        mismatches.append(f"snapshot: the generation interpreter failed its check: {ex.get('error')}")
    for part in ("ollama", "execution", "baselines", "tools"):
        if not snap.get(part):
            notes.append(f"snapshot: {part} not observed")
    return mismatches, notes


def _short(v):
    if v is _MISSING:
        return "<absent>"
    s = json.dumps(v, ensure_ascii=False, sort_keys=True)
    return s if len(s) <= 80 else s[:77] + "..."


# ---------------------------------------------------------------------------------------------------- runs


def verify_run_config(reg, cfg):
    """Check one runner config.json (E08 layout) against the registry. Returns a list of problems.

    The run must name a registry entry; the entry's hash must still be the one the run recorded; the settings the
    run recorded (opts + seed_base) must equal the entry; the model identity the run saw must equal the entry's.
    """
    rec = cfg.get("registry")
    if not isinstance(rec, dict) or not rec.get("entry_id"):
        return ["the run names no registry entry (started without --registry)"]
    try:
        entry = get_entry(reg, rec["entry_id"])
    except RegistryError as e:
        return [str(e)]
    problems = []
    now = entry_sha256(entry)
    if rec.get("entry_sha256") != now:
        problems.append(f"entry {rec['entry_id']} changed since the run: recorded {str(rec.get('entry_sha256'))[:16]}, "
                        f"now {now[:16]}")
    ident = cfg.get("identity") or {}
    sent = dict(cfg.get("opts") or {})
    if cfg.get("seed_base") is not None or "seed" in (entry.get("opts") or {}):
        sent["seed"] = cfg.get("seed_base")
    problems += compare_sent(entry, sent, backend_kind=cfg.get("backend"), model=ident.get("model"),
                             digest=ident.get("digest"), repeat_index=0)
    ei = entry.get("identity") or {}
    if ident.get("ollama_version") and ei.get("ollama_version") and ident["ollama_version"] != ei["ollama_version"]:
        problems.append(f"ollama_version: run {ident['ollama_version']} != registry {ei['ollama_version']}")
    if ident.get("template_sha256") and ei.get("template_blob_sha256") and ident["template_sha256"] != ei["template_blob_sha256"]:
        problems.append("template: the run's template differs from the registry's template blob")
    return problems


def api_observed(records, requested_model=None):
    """Aggregate API call records (E08/E10 layout) into what the registry keeps per requested model id.

    Returns {requested model: {returned_models, system_fingerprints, n_without_fingerprint, call_dates_utc,
    n_calls, n_ok, seed_sent, n_model_mismatch}}.
    """
    out = {}
    for r in records:
        m = r.get("model")
        if requested_model and m != requested_model:
            continue
        if r.get("backend") not in API_BACKENDS:
            continue
        d = out.setdefault(m, {"returned_models": set(), "system_fingerprints": set(), "n_without_fingerprint": 0,
                               "call_dates_utc": set(), "n_calls": 0, "n_ok": 0, "seed_sent": False, "n_model_mismatch": 0})
        d["n_calls"] += 1
        if r.get("ok"):
            d["n_ok"] += 1
            if r.get("response_model"):
                d["returned_models"].add(r["response_model"])
                if r["response_model"] != m:
                    d["n_model_mismatch"] += 1
            if r.get("system_fingerprint"):
                d["system_fingerprints"].add(r["system_fingerprint"])
            else:
                d["n_without_fingerprint"] += 1
        ts = r.get("finished_at") or r.get("started_at")
        if isinstance(ts, str) and len(ts) >= 10:
            d["call_dates_utc"].add(ts[:10])
        if r.get("seed") is not None or (r.get("sent_opts") or {}).get("seed") is not None:
            d["seed_sent"] = True
    return {m: {k: (sorted(v) if isinstance(v, set) else v) for k, v in d.items()} for m, d in sorted(out.items())}


def combine_api_observed(observations):
    """Combine per-run api_observed() blocks of one model: sets are unioned, counts added, flags or-ed."""
    out = {}
    for obs in observations:
        for k, v in obs.items():
            if isinstance(v, list):
                out[k] = sorted(set(out.get(k) or []) | set(v))
            elif isinstance(v, bool):
                out[k] = bool(out.get(k)) or v
            else:
                out[k] = (out.get(k) or 0) + v
    return {k: out[k] for k in sorted(out)}


def merge_api_observed(reg, observed, *, source):
    """Merge api_observed() output of ONE run directory into api_models.models[<id>].

    The observation is kept under observed_by_run[source] (source = the run directory relative to the repository),
    replacing an earlier observation of the same run, and `observed` is recomputed from all runs. Merging a run
    again, or a resumed run, therefore never counts its calls twice.
    """
    if not isinstance(source, str) or not source or os.path.isabs(source) or source.startswith("<"):
        raise RegistryError(f"merge_api_observed: source must be a run directory relative to the repository, got {source!r}")
    new = copy.deepcopy(reg)
    api = new.setdefault("api_models", {})
    models = api.setdefault("models", {})
    for mid, obs in observed.items():
        m = models.setdefault(mid, {"requested_id": mid, "dated_snapshot": bool(DATED_ID_RE.search(mid)),
                                    "seed_supported": None, "tokenizer": None})
        runs = dict(m.get("observed_by_run") or {})
        runs[source] = obs
        m["observed_by_run"] = {k: runs[k] for k in sorted(runs)}
        m["observed"] = combine_api_observed(m["observed_by_run"].values())
    return new

"""Batch runner shared by runtime/ollama_runner.py and runtime/api_runner.py (E08).

INPUT: a JSONL of requests, one per line:
  {"request_id": ..., "case_id": ..., "condition": ..., "messages": [...] | "system"/"user": ...,
   "format": optional, "meta": {...}}

OUTPUT (the v5 layout, so `orgene_cli.py validate` reads it unchanged):
  config.json                      backend identity, the settings sent (seed = seed_base + repeat index), code hashes,
                                   registry entry hash, local token counter, server defaults that still apply
  outputs/<request_id>.r<k>.json   one call record per call (fields: orgene.backends.base.REQUIRED_CALL_FIELDS)
  receipts.jsonl                   one line per finished call, append-only; resume skips what is listed there
  metrics.json                     counts, truncation (done_reason=length), tokens, model load time, identity drift,
                                   answered calls without local token counts (n_calls_missing_local_tokens; see
                                   local_token_gaps, which the dev rehearsal's record-field check reads)

Refusals happen before any model call: bad opts, a registry entry that differs from what would be sent, a missing
local token counter when one is required, a batch that touches sealed cases without a registered freeze (the E21 test
gate, stage "generate"), or a resume whose settings differ from the existing config.json.

TEST GATE: the run directory is the parent of the output directory (experiments/<run>/gen.<cond>.r0 -> the run). When
the requests carry a sealed case id (data/splits*/**/test_ids.json, eng_holdout_ids.json) or the run's run_config.json
records split test / eng_holdout, generation needs a complete, verified, OSF-registered FREEZE_MANIFEST.json
(orgene/freeze.py); the pass is appended to <run>/freeze_gate.jsonl and recorded as `freeze_gate` in config.json
(not a resume key: the manifest file changes when the registration is recorded). Dev and smoke batches are not gated.
"""
import hashlib
import importlib
import json
import os
import sys
import time

from .backends.base import (BackendError, OptionsError, RegistryMismatch, canonical_json, now_iso,
                            registry_guard, sha256_hex)
from .paths import rel, sanitize_argv

OUTPUT_SCHEMA = "orgene.r1.runner.output.v1"
CONFIG_SCHEMA = "orgene.r1.runner.config.v1"
METRICS_SCHEMA = "orgene.r1.runner.metrics.v1"
RECEIPT_KEYS = ("request_id", "case_id", "condition", "repeat", "ok", "done_reason", "prompt_eval_count", "eval_count",
                "eval_duration_ns", "seconds", "content_sha256", "request_sha256", "seed", "started_at", "finished_at")
# a resumed directory must match on all of these
RESUME_KEYS = ("backend", "identity", "opts", "seed_base", "format", "schema_sha256", "requests_sha256", "registry",
               "local_tokens_counter", "local_tokenizer")
_PROBE_MESSAGES = [{"role": "user", "content": "probe"}]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_requests(path, prefix="[runner]"):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if "messages" not in r:
                msgs = []
                if r.get("system"):
                    msgs.append({"role": "system", "content": r["system"]})
                if r.get("user"):
                    msgs.append({"role": "user", "content": r["user"]})
                r["messages"] = msgs
            if not r["messages"]:
                raise SystemExit(f"{prefix} request on line {i} has no messages")
            r.setdefault("request_id", f"req-{i:05d}")
            r.setdefault("case_id", None)
            r.setdefault("condition", None)
            out.append(r)
    ids = [r["request_id"] for r in out]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"{prefix} duplicate request_id values in requests file")
    return out


def load_token_counter(spec, prefix="[runner]"):
    """'module:attr' -> a token counter: a function called with keyword arguments (messages, completion, backend,
    model, think, thinking) or an object with local_tokens()/identity() (see Backend.count_local; E09)."""
    if not spec:
        return None
    mod, _, fn = spec.partition(":")
    if not mod or not fn:
        raise SystemExit(f"{prefix} --token-counter must look like module:function")
    try:
        f = getattr(importlib.import_module(mod), fn)
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"{prefix} cannot load token counter {spec}: {type(e).__name__}: {e}")
    if not (callable(f) or hasattr(f, "local_tokens")):
        raise SystemExit(f"{prefix} token counter {spec} is neither a function nor a counter object")
    return f


def load_registry_entry(path, entry_id, prefix="[runner]"):
    """Registry file {"entries": {<id>: entry}} (E19 owns the file). Returns (entry, record for config.json)."""
    if not path and not entry_id:
        return None, None
    if not (path and entry_id):
        raise SystemExit(f"{prefix} --registry and --registry-entry go together")
    with open(path, "r", encoding="utf-8") as f:
        reg = json.load(f)
    entry = (reg.get("entries") or {}).get(entry_id)
    if not isinstance(entry, dict) or not isinstance(entry.get("opts"), dict):
        raise SystemExit(f"{prefix} registry entry {entry_id!r} not found (or has no opts) in {rel(path)}")
    # only the entry's hash is kept: adding other entries to the file must not block a resume
    return entry, {"path": rel(path), "entry_id": entry_id, "entry_sha256": sha256_hex(canonical_json(entry))}


def _run_split(run_dir):
    """The split recorded in <run>/run_config.json by `orgene_cli.py requests`, or None (no file, unreadable)."""
    p = os.path.join(run_dir, "run_config.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("split")
    except (OSError, ValueError, AttributeError):
        return None


def _batch_case_ids(requests):
    """Case ids a batch touches: each request's case_id and, for a request written without one (a hand-made or
    v5-style file), the part of its request_id before the first "." (request ids are "<case_id>.<config>...")."""
    ids = set()
    for r in requests:
        if r.get("case_id") is not None:
            ids.add(str(r["case_id"]))
        if r.get("request_id") is not None:
            ids.add(str(r["request_id"]).split(".", 1)[0])
    return sorted(ids)


def generate_gate(requests, out_dir, prefix="[runner]"):
    """E21 test gate for model calls (stage "generate"): None when the batch touches no sealed case, else the gate
    record (also appended to <run>/freeze_gate.jsonl). Exits before anything is written when the freeze does not
    allow it."""
    from . import freeze as FZ
    run_dir = os.path.dirname(os.path.abspath(out_dir))
    ids = _batch_case_ids(requests)
    try:
        return FZ.gate_stage("generate", run_dir=run_dir, case_ids=ids, split=_run_split(run_dir))
    except FZ.GateRefused as e:
        raise SystemExit(f"{prefix} refused by the test gate: {e}")


def _server_state(backend):
    """Whether other models are loaded when the run starts (counts only: other projects' model names stay out)."""
    if not hasattr(backend, "loaded_models"):
        return None
    try:
        ms = backend.loaded_models()
    except Exception as e:  # noqa: BLE001
        return {"error": type(e).__name__}
    mine = [m for m in ms if m.get("name") == backend.model]
    return {"n_loaded": len(ms), "this_model_loaded": bool(mine), "n_other_models_loaded": len(ms) - len(mine)}


MISSING_LISTED = 100  # at most this many "<request_id>.r<k>" names are listed in metrics.json


def _missing_reason(rec):
    if rec.get("local_tokens_counter") is None:
        return "no counter"
    err = str(rec.get("local_tokens_error") or "").strip()
    return err.split(":", 1)[0].strip() or "counter returned nothing"


def _local_token_summary(recs, counter_id):
    """Answered calls (ok) whose record has no local_tokens: the count, the first MISSING_LISTED call names and the
    reasons ('no counter', or the counter's exception type from local_tokens_error). Failed calls are not counted
    here (they have no answer to count; n_calls - n_ok reports them)."""
    missing, reasons = [], {}
    n_answered = 0
    for name, rec in recs:
        if not rec.get("ok"):
            continue
        n_answered += 1
        if rec.get("local_tokens") is None:
            missing.append(name)
            r = _missing_reason(rec)
            reasons[r] = reasons.get(r, 0) + 1
    return {"local_tokens_counter": counter_id, "n_answered_calls": n_answered,
            "n_calls_missing_local_tokens": len(missing),
            "local_tokens_missing": {"calls": missing[:MISSING_LISTED], "n_listed": min(len(missing), MISSING_LISTED),
                                     "reasons": dict(sorted(reasons.items()))}}


def local_token_gaps(gen_dir):
    """Local-count coverage of one runner output directory, for the dev rehearsal (engineering plan 5.2, item 5:
    every call carries local_tokens). Reads metrics.json when it has the fields; otherwise (a directory written
    before they existed) recomputes them from receipts.jsonl and the call records. Returns the same keys as
    metrics.json: local_tokens_counter, n_answered_calls, n_calls_missing_local_tokens, local_tokens_missing, plus
    "source" ("metrics.json" or "outputs")."""
    mp = os.path.join(gen_dir, "metrics.json")
    if os.path.isfile(mp):
        with open(mp, "r", encoding="utf-8") as f:
            m = json.load(f)
        if "n_calls_missing_local_tokens" in m:
            out = {k: m.get(k) for k in ("local_tokens_counter", "n_answered_calls", "n_calls_missing_local_tokens",
                                         "local_tokens_missing")}
            out["source"] = "metrics.json"
            return out
    recs, counter = [], None
    for name, rec in _call_records(gen_dir):
        recs.append((name, rec))
        counter = counter or rec.get("local_tokens_counter")
    out = _local_token_summary(recs, counter)
    out["source"] = "outputs"
    return out


def _call_records(out_dir):
    """(name "<request_id>.r<k>", call record) for every receipt whose record file exists, in receipt order."""
    rp = os.path.join(out_dir, "receipts.jsonl")
    if not os.path.isfile(rp):
        return
    with open(rp, "r", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    for row in rows:
        name = f"{row['request_id']}.r{row['repeat']}"
        p = os.path.join(out_dir, "outputs", f"{name}.json")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                yield name, json.load(f)


def _drift(start, end):
    keys = ("digest", "parameters_from_modelfile", "template_sha256", "ollama_version", "build_info", "chat_template_sha256")
    return {k: {"start": start.get(k), "end": end.get(k)} for k in keys if start.get(k) != end.get(k)}


def run_batch(backend, requests, out_dir, opts, *, repeat=1, fmt=None, schema_path=None, schema_sha256=None,
              requests_path=None, resume=True, argv=None, code_files=(), note="", registry=None, sleep=0.0,
              require_local_tokens=False, prefix="[runner]"):
    """Run every request `repeat` times through `backend`. Returns the exit status (0 ok, 3 identity drift).

    `opts` carries the base seed; the call with repeat index k sends seed + k. `registry` is the
    (entry, config record) pair from load_registry_entry, or None.
    """
    entry, reg_rec = registry if registry else (None, None)
    tokenizer_identity = None
    try:
        ident = backend.identity()
    except BackendError as e:
        raise SystemExit(f"{prefix} {e}")
    try:
        sent0 = backend.sent_opts(backend.build_body(_PROBE_MESSAGES, opts, fmt))
    except OptionsError as e:
        raise SystemExit(f"{prefix} options refused: {e}")
    seed_base = sent0.get("seed")
    if entry is not None:
        # every repeat index is checked up front (a "fixed" seed rule with --repeat > 1 must fail before any call)
        for k in range(max(1, repeat)):
            sent_k = sent0 if k == 0 or seed_base is None else \
                backend.sent_opts(backend.build_body(_PROBE_MESSAGES, dict(opts, seed=seed_base + k), fmt))
            try:
                registry_guard(entry, backend=backend, repeat_index=k)(sent_k)
            except RegistryMismatch as e:
                raise SystemExit(f"{prefix} refused: the settings for repeat {k} differ from registry entry "
                                 f"{reg_rec['entry_id']}: {e}")
    if backend.token_counter is not None:
        try:
            backend.count_local(_PROBE_MESSAGES, "probe", think=sent0.get("think"))
            tokenizer_identity = backend.token_counter_identity()
        except Exception as e:  # noqa: BLE001
            raise SystemExit(f"{prefix} token counter failed its start-up probe: {type(e).__name__}: {e}")
    elif require_local_tokens:
        raise SystemExit(f"{prefix} refused: local token counts are required but no --token-counter is set")
    gate = generate_gate(requests, out_dir, prefix)

    os.makedirs(os.path.join(out_dir, "outputs"), exist_ok=True)
    config = {
        "schema_version": CONFIG_SCHEMA,
        "started_at": now_iso(),
        "argv": sanitize_argv(argv if argv is not None else sys.argv),
        "runner_sha256": sha256_file(code_files[0]) if code_files else None,
        "code_sha256": {rel(p): sha256_file(p) for p in code_files},
        "backend": backend.kind,
        "identity": ident,
        "opts": {k: v for k, v in sent0.items() if k != "seed"},
        "seed_base": seed_base,
        "seed_rule": "seed = seed_base + repeat index" if seed_base is not None else "no seed sent",
        "repeat": repeat,
        "format": ("schema" if isinstance(fmt, dict) else fmt),
        "schema_path": (schema_path if schema_path in (None, "json") else rel(schema_path)),
        "schema_sha256": schema_sha256,
        "requests_path": rel(requests_path) if requests_path else None,
        "requests_sha256": sha256_file(requests_path) if requests_path else None,
        "n_requests": len(requests),
        "registry": reg_rec,
        "local_tokens_counter": backend.token_counter_id,
        "local_tokenizer": tokenizer_identity,
        "inherited_server_defaults": backend.inherited_defaults(sent0),
        "server_state_at_start": _server_state(backend),
        "freeze_gate": gate,
        "note": note,
    }
    cfg_path = os.path.join(out_dir, "config.json")
    if os.path.exists(cfg_path) and resume:
        with open(cfg_path, "r", encoding="utf-8") as f:
            prev = json.load(f)
        differ = [k for k in RESUME_KEYS if prev.get(k) != config.get(k)]
        if differ:
            raise SystemExit(f"{prefix} resume refused: {', '.join(repr(k) for k in differ)} "
                             f"{'differs' if len(differ) == 1 else 'differ'} from the existing config.json in the "
                             f"output directory. Use a new --out directory.")
        config["resumed_at"] = now_iso()
        config["started_at"] = prev.get("started_at")
        history = list(prev.get("code_history") or [])
        if prev.get("code_sha256") != config["code_sha256"]:
            history.append({"until": config["resumed_at"], "code_sha256": prev.get("code_sha256")})
        if history:
            config["code_history"] = history
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    receipts_path = os.path.join(out_dir, "receipts.jsonl")
    done = set()
    if os.path.exists(receipts_path) and resume:
        with open(receipts_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    done.add((r["request_id"], r["repeat"]))

    t_start = time.time()
    total = len(requests) * repeat
    n_done = len(done)
    print(f"{prefix} backend={backend.kind} model={backend.model} digest={(ident.get('digest') or '-')[:12]} "
          f"requests={len(requests)} repeat={repeat} already_done={n_done}", flush=True)
    for r in requests:
        for k in range(repeat):
            if (r["request_id"], k) in done:
                continue
            opts_k = dict(opts)
            if seed_base is not None:
                opts_k["seed"] = seed_base + k
            guard = registry_guard(entry, backend=backend, repeat_index=k) if entry is not None else None
            try:
                rec = backend.call(r["messages"], opts_k, fmt=r.get("format", fmt), guard=guard)
            except (OptionsError, RegistryMismatch) as e:
                raise SystemExit(f"{prefix} refused before sending {r['request_id']} r{k}: {e}")
            record = {"schema_version": OUTPUT_SCHEMA, "request_id": r["request_id"], "case_id": r.get("case_id"),
                      "condition": r.get("condition"), "meta": r.get("meta"), "repeat": k}
            record.update(rec)
            with open(os.path.join(out_dir, "outputs", f"{r['request_id']}.r{k}.json"), "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=1)
            with open(receipts_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({k2: record.get(k2) for k2 in RECEIPT_KEYS}, ensure_ascii=False) + "\n")
            n_done += 1
            tps = (record.get("eval_count") or 0) / (record["eval_duration_ns"] / 1e9) if record.get("eval_duration_ns") else 0.0
            print(f"{prefix} {n_done}/{total} {r['request_id']} r{k} ok={record['ok']} done={record.get('done_reason')} "
                  f"out_tok={record.get('eval_count')} {tps:.1f} tok/s wall={record['wall_seconds']:.1f}s "
                  f"elapsed={(time.time() - t_start) / 60:.1f} min", flush=True)
            if sleep:
                time.sleep(sleep)

    drift, drift_error = {}, None
    try:
        drift = _drift(ident, backend.identity(refresh=True))
    except BackendError as e:
        drift_error = str(e)
    rows = []
    with open(receipts_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    load_ns = 0
    recs = list(_call_records(out_dir))
    for _, rec in recs:
        load_ns += rec.get("load_duration_ns") or 0
    local_summary = _local_token_summary(recs, backend.token_counter_id)
    by_cond = {}
    for row in rows:
        d = by_cond.setdefault(row.get("condition") or "_", {"n": 0, "ok": 0, "truncated": 0, "out_tokens": 0})
        d["n"] += 1
        d["ok"] += 1 if row.get("ok") else 0
        d["truncated"] += 1 if row.get("done_reason") == "length" else 0
        d["out_tokens"] += row.get("eval_count") or 0
    gen_tok = sum((x.get("eval_count") or 0) for x in rows)
    gen_ns = sum((x.get("eval_duration_ns") or 0) for x in rows)
    metrics = {
        "schema_version": METRICS_SCHEMA,
        "finished_at": now_iso(),
        "backend": backend.kind,
        "model": backend.model,
        "digest": ident.get("digest"),
        "n_calls": len(rows),
        "n_ok": sum(1 for x in rows if x.get("ok")),
        "n_truncated": sum(1 for x in rows if x.get("done_reason") == "length"),
        "total_generated_tokens": gen_tok,
        "total_prompt_tokens": sum((x.get("prompt_eval_count") or 0) for x in rows),
        "mean_gen_tokens_per_s": (gen_tok / (gen_ns / 1e9)) if gen_ns else None,
        "total_model_load_seconds": round(load_ns / 1e9, 3),
        "wall_seconds_this_session": round(time.time() - t_start, 1),
        "by_condition": by_cond,
        **local_summary,
        "identity_changed": bool(drift),
        "identity_drift": drift,
        "identity_check_error": drift_error,
    }
    with open(os.path.join(out_dir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"{prefix} done. calls={metrics['n_calls']} ok={metrics['n_ok']} truncated={metrics['n_truncated']} "
          f"gen_tokens={gen_tok} tok/s={metrics['mean_gen_tokens_per_s']} "
          f"missing_local_tokens={metrics['n_calls_missing_local_tokens']}", flush=True)
    if backend.token_counter is not None and metrics["n_calls_missing_local_tokens"]:
        print(f"{prefix} WARNING: {metrics['n_calls_missing_local_tokens']} answered call(s) have no local token count "
              f"({metrics['local_tokens_missing']['reasons']}); see local_tokens_error in their records",
              file=sys.stderr, flush=True)
    if drift:
        print(f"{prefix} ERROR: the server's model identity changed during the run: {sorted(drift)}", file=sys.stderr, flush=True)
        return 3
    return 0

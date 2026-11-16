"""One interface for every model backend: `backend.call(messages, opts) -> record` (E08).

A backend turns (messages, opts) into exactly one HTTP request body, sends it (with retries), and returns one call
record. The record carries every field the run needs to be audited without the server:

  started_at / finished_at   UTC ISO timestamps around all attempts of this call (per attempt as well)
  seed, digest               the seed actually sent; the model digest from the identity lookup (None for APIs)
  sent_opts                  the decoding settings exactly as sent (flat dict, reconstructed from the body)
  request_sha256             sha256 of the canonical JSON of the body sent, without transport-only fields
                             (`stream`, `keep_alive`): model + messages + options (+ think / format)
  done_reason, prompt_eval_count, eval_count, ...   the server's own report
  local_tokens               local tokenizer counts from the configured counter (E09); None when none is set

opts are validated before anything is sent: an unknown key, a missing required key or a wrong type raises
OptionsError, and an optional `guard(sent_opts)` (the registry check, E19) can refuse the call. In both cases no
request reaches the server.
"""
import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from ..paths import find_absolute_paths, rel

CALL_SCHEMA = "orgene.r1.call.v1"
TRANSPORT_FIELDS = frozenset({"stream", "keep_alive"})

# Fields every call record must carry (dev rehearsal check 5, ENGINEERING_PLAN 5.2).
REQUIRED_CALL_FIELDS = (
    "call_schema", "backend", "model", "digest", "seed", "sent_opts", "request_sha256",
    "started_at", "finished_at", "wall_seconds", "attempts", "ok",
    "done_reason", "prompt_eval_count", "eval_count", "content", "content_sha256",
    "local_tokens", "local_tokens_counter",
)
# Fields that must never appear in a call record (v5 carried a parse flag that was always false).
FORBIDDEN_CALL_FIELDS = ("parse_ok", "parsed")

_MISSING = object()


class OptionsError(ValueError):
    """opts (or the backend configuration) rejected before any request was sent."""


class RegistryMismatch(RuntimeError):
    """The settings about to be sent differ from the registry entry the run was started with."""


class BackendError(RuntimeError):
    """The server could not be identified (unreachable, model not installed)."""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def canonical_json(obj):
    """Deterministic bytes for hashing: sorted keys, no whitespace, UTF-8, NaN refused."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_hex(b):
    return hashlib.sha256(b).hexdigest()


def request_sha256(body):
    """sha256 of the request body without transport-only fields (`stream`, `keep_alive`)."""
    return sha256_hex(canonical_json({k: v for k, v in body.items() if k not in TRANSPORT_FIELDS}))


def content_sha256(text):
    return sha256_hex(text.encode("utf-8")) if text else None


def scrub_paths(text):
    """Free text that goes into a record (server or tokenizer error messages): home-directory paths, which carry the
    user name, become root-relative or `<outside-root>/<basename>` (the rule of orgene.paths)."""
    if not text:
        return text
    for p in sorted(set(find_absolute_paths(text)), key=len, reverse=True):
        text = text.replace(p, rel(p))
    return text


def http_json(url, payload=None, headers=None, timeout=60):
    """GET (payload None) or POST JSON; returns the decoded JSON body. HTTP errors raise urllib.error.HTTPError."""
    data = None
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_messages(messages):
    if not isinstance(messages, list) or not messages:
        raise OptionsError("messages must be a non-empty list")
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant") or not isinstance(m.get("content"), str):
            raise OptionsError(f"bad message: {str(m)[:80]}")


def coerce_opts(opts, *, required, int_keys=(), float_keys=(), bool_keys=(), other_keys=(), nullable=()):
    """Validate and type-normalize a flat opts dict.

    - every key must be known (typos such as `num_predic` are refused);
    - every key in `required` must be present (None only for keys in `nullable`);
    - ints stay ints, floats become floats (so 0 and 0.0 hash the same); booleans are never accepted as numbers.
    """
    if not isinstance(opts, dict):
        raise OptionsError("opts must be a dict")
    known = set(int_keys) | set(float_keys) | set(bool_keys) | set(other_keys)
    unknown = sorted(set(opts) - known)
    if unknown:
        raise OptionsError(f"unknown option(s): {unknown}")
    missing = [k for k in required if k not in opts or (opts[k] is None and k not in nullable)]
    if missing:
        raise OptionsError(f"option(s) must be set explicitly: {missing}")
    out = {}
    for k, v in opts.items():
        if v is None:
            if k not in nullable:
                raise OptionsError(f"option {k} is None")
            out[k] = None
        elif k in bool_keys:
            if not isinstance(v, bool):
                raise OptionsError(f"option {k} must be true/false, got {v!r}")
            out[k] = v
        elif k in int_keys:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or \
                    (isinstance(v, float) and (not math.isfinite(v) or v != int(v))):
                raise OptionsError(f"option {k} must be an integer, got {v!r}")
            out[k] = int(v)
        elif k in float_keys:
            # NaN / inf would be sent as bare NaN / Infinity tokens and then break the canonical hash after the call
            if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)):
                raise OptionsError(f"option {k} must be a finite number, got {v!r}")
            out[k] = float(v)
        else:
            out[k] = v
    return out


def same_value(a, b):
    """Registry comparison: numbers compare by value (0 == 0.0), booleans only with booleans."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    return a == b


def registry_guard(entry, *, backend, repeat_index=0):
    """A guard for Backend.call: refuse unless what is about to be sent equals the registry entry.

    Entry format (the registry file itself is E19's): {"backend": ..., "model": ..., "digest": optional,
    "opts": {every key the backend sends}, "seed_rule": "base+k" (default) | "fixed"}. With "base+k" the entry's
    seed is the base and the call with repeat index k must send base + k.
    """
    exp_raw = dict(entry.get("opts") or {})
    rule = entry.get("seed_rule", "base+k")
    if rule not in ("base+k", "fixed"):
        raise RegistryMismatch(f"unknown seed_rule {rule!r}")
    if rule == "base+k" and exp_raw.get("seed") is not None:
        exp_raw["seed"] = exp_raw["seed"] + repeat_index

    def guard(sent):
        problems = []
        if entry.get("backend") is not None and entry["backend"] != backend.kind:
            problems.append(f"backend: registry {entry['backend']!r} != {backend.kind!r}")
        if entry.get("model") is not None and entry["model"] != backend.model:
            problems.append(f"model: registry {entry['model']!r} != {backend.model!r}")
        if entry.get("digest"):
            dig = backend.digest()
            if dig != entry["digest"]:
                problems.append(f"digest: registry {entry['digest']!r} != server {dig!r}")
        for key in sorted(set(exp_raw) | set(sent)):
            a, b = exp_raw.get(key, _MISSING), sent.get(key, _MISSING)
            if a is _MISSING:
                problems.append(f"{key}: sent {b!r} but not in the registry entry")
            elif b is _MISSING:
                problems.append(f"{key}: registry {a!r} but not sent")
            elif not same_value(a, b):
                problems.append(f"{key}: registry {a!r} != sent {b!r}")
        if problems:
            raise RegistryMismatch("; ".join(problems))
    return guard


def missing_call_fields(rec):
    """Fields from REQUIRED_CALL_FIELDS absent from a record, plus forbidden ones present (prefixed '!')."""
    out = [k for k in REQUIRED_CALL_FIELDS if k not in rec]
    out += ["!" + k for k in FORBIDDEN_CALL_FIELDS if k in rec]
    if rec.get("ok"):
        for k in ("started_at", "finished_at", "request_sha256", "sent_opts"):
            if not rec.get(k):
                out.append(k)
    return out


class Backend:
    """Base class. Subclasses set `kind`, `REQUIRED_OPTS` and implement normalize_opts, build_body, sent_opts,
    _send_once and _parse. `identity()` is cached; `digest()` reads it."""

    kind = "base"
    NON_RETRYABLE_HTTP = ()
    RETRY_SLEEP_CAP = 30.0

    def __init__(self, model, *, timeout=900, max_attempts=2, retry_sleep=5.0, token_counter=None, token_counter_id=None):
        if not model:
            raise OptionsError("model is required")
        self.model = model
        self.timeout = timeout
        self.max_attempts = max(1, int(max_attempts))
        self.retry_sleep = float(retry_sleep)
        self.token_counter = token_counter
        if token_counter is not None and not token_counter_id:
            token_counter_id = type(token_counter).__name__ if hasattr(token_counter, "local_tokens") else \
                getattr(token_counter, "__name__", type(token_counter).__name__)
        self.token_counter_id = token_counter_id if token_counter is not None else None
        self._identity = None
        self._active_guard = None

    # -- identity ---------------------------------------------------------------------------------------------
    def _lookup_identity(self):
        return {"backend": self.kind, "model": self.model, "digest": None}

    def identity(self, refresh=False):
        if self._identity is None or refresh:
            self._identity = self._lookup_identity()
        return self._identity

    def digest(self):
        return self.identity().get("digest")

    def inherited_defaults(self, sent):
        """Server-side defaults that apply because they were not sent (Ollama: Modelfile parameters)."""
        return {}

    # -- request construction (pure) ---------------------------------------------------------------------------
    def normalize_opts(self, opts):
        raise NotImplementedError

    def build_body(self, messages, opts, fmt=None):
        raise NotImplementedError

    def sent_opts(self, body):
        raise NotImplementedError

    # -- transport ------------------------------------------------------------------------------------------------
    def _send_once(self, body):
        """One HTTP exchange. Returns (response_json, final_body); final_body differs from body only when the
        backend had to adjust the request (recorded in `adjustments`)."""
        raise NotImplementedError

    def _parse(self, resp):
        raise NotImplementedError

    def _error_text(self, e):
        if isinstance(e, urllib.error.HTTPError):
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                body = ""
            return scrub_paths(f"HTTP {e.code}: {e.reason}: {body[:400]}")
        return scrub_paths(repr(e)[:500])

    # -- local token counts (E09) ----------------------------------------------------------------------------------
    def count_local(self, messages, completion, think=None, thinking=None):
        """Local tokenizer counts for one call; raises when the counter fails.

        The counter is either an object with `local_tokens(messages, completion, think=, thinking=)` (and optionally
        `identity()`), the shape of orgene.tokcount's counters, or a plain function called with keyword arguments
        messages, completion, backend, model, think, thinking. Returns None when no counter is configured."""
        c = self.token_counter
        if c is None:
            return None
        if hasattr(c, "local_tokens"):
            out = c.local_tokens(messages, completion, think=think, thinking=thinking)
        else:
            out = c(messages=messages, completion=completion, backend=self.kind, model=self.model, think=think, thinking=thinking)
        if not isinstance(out, dict):
            raise TypeError(f"token counter returned {type(out).__name__}, expected a dict")
        return out

    def token_counter_identity(self):
        c = self.token_counter
        return c.identity() if c is not None and hasattr(c, "identity") else None

    def _count_local(self, messages, content, think=None, thinking=None):
        if self.token_counter is None:
            return None, None
        try:
            return self.count_local(messages, content, think=think, thinking=thinking), None
        except Exception as e:  # noqa: BLE001
            return None, scrub_paths(f"{type(e).__name__}: {e}")[:300]

    def call(self, messages, opts, *, fmt=None, guard=None):
        """Send one request (with retries) and return its call record. Raises OptionsError / RegistryMismatch
        before sending anything when opts or the guard refuse."""
        check_messages(messages)
        body = self.build_body(messages, opts, fmt)
        sent = self.sent_opts(body)
        if guard is not None:
            guard(sent)
        ident = self.identity()
        attempts, resp = [], None
        started_at, t0 = now_iso(), time.monotonic()
        final_body = body
        self._active_guard = guard  # a backend that must adjust a request re-checks the adjusted body with it
        try:
            for attempt in range(1, self.max_attempts + 1):
                a_start, ta = now_iso(), time.monotonic()
                try:
                    resp, final_body = self._send_once(body)
                    if isinstance(resp, dict) and resp.get("error"):
                        raise RuntimeError(f"server error: {str(resp.get('error'))[:300]}")
                    attempts.append({"attempt": attempt, "ok": True, "started_at": a_start, "finished_at": now_iso(),
                                     "seconds": round(time.monotonic() - ta, 3)})
                    break
                except (RegistryMismatch, OptionsError):
                    raise
                except Exception as e:  # noqa: BLE001
                    resp, final_body = None, body
                    attempts.append({"attempt": attempt, "ok": False, "started_at": a_start, "finished_at": now_iso(),
                                     "seconds": round(time.monotonic() - ta, 3), "error": self._error_text(e)})
                    if isinstance(e, urllib.error.HTTPError) and e.code in self.NON_RETRYABLE_HTTP:
                        break
                    if attempt < self.max_attempts:
                        time.sleep(min(self.RETRY_SLEEP_CAP, self.retry_sleep * attempt))
        finally:
            self._active_guard = None
        finished_at, wall = now_iso(), round(time.monotonic() - t0, 3)
        adjustments = sorted(k for k in set(body) | set(final_body) if body.get(k, _MISSING) != final_body.get(k, _MISSING))
        if adjustments:
            sent = self.sent_opts(final_body)
        parsed = self._parse(resp) if resp is not None else {}
        content = parsed.pop("content", "") or ""
        local, local_err = (self._count_local(messages, content, think=sent.get("think"), thinking=parsed.get("thinking"))
                            if resp is not None else (None, None))
        rec = {
            "call_schema": CALL_SCHEMA,
            "backend": self.kind,
            "model": self.model,
            "digest": ident.get("digest"),
            "seed": sent.get("seed"),
            "sent_opts": sent,
            "format": ("schema" if isinstance(final_body.get("format"), dict) else final_body.get("format")),
            "request_sha256": request_sha256(final_body),
            "messages_sha256": sha256_hex(canonical_json(messages)),
            "n_messages": len(messages),
            "request_adjustments": adjustments,
            "started_at": started_at,
            "finished_at": finished_at,
            "wall_seconds": wall,
            "seconds": round(sum(a["seconds"] for a in attempts), 3),
            "attempts": attempts,
            "ok": resp is not None,
            "done_reason": None,
            "prompt_eval_count": None,
            "eval_count": None,
            "content": content,
            "content_sha256": content_sha256(content),
            "local_tokens": local,
            "local_tokens_counter": self.token_counter_id,
            "local_tokens_error": local_err,
        }
        rec.update(parsed)
        return rec

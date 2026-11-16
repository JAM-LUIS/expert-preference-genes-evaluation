"""OpenAI-compatible Chat Completions backend (OpenAI, DeepSeek, any official compatible endpoint) (E08).

Carries the v5 api_runner behaviour into the common backend interface: the key is read from an environment variable
and never recorded; relay / proxy gateways are refused; the two v5 request fallbacks (max_completion_tokens ->
max_tokens, dropping temperature for models that reject it) are kept but are now recorded as
`request_adjustments`, change `request_sha256` and `sent_opts` accordingly, and are re-checked by the registry
guard before the adjusted request is sent.

E10 extends this module (dated snapshots only, 429/5xx back-off, cached/reasoning token details, x-request-id,
response-model mismatch flag).
"""
import os
import urllib.error

from .base import Backend, BackendError, OptionsError, coerce_opts, http_json

PRESETS = {
    "openai": {"base": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY"},
    "deepseek": {"base": "https://api.deepseek.com", "key_env": "DEEPSEEK_API_KEY"},
    "compat": {"base": None, "key_env": None},
}
RELAY_MARKERS = ("zjapi", "relay", "proxy")
REQUIRED_OPTS = ("temperature", "top_p", "seed", "max_tokens")  # None = deliberately not sent (explicit)


def refuse_relay(base_url):
    low = (base_url or "").lower()
    if any(m in low for m in RELAY_MARKERS):
        raise OptionsError("refusing a relay/proxy endpoint; official APIs only (project policy)")


class OpenAICompatBackend(Backend):
    kind = "openai_compat"
    NON_RETRYABLE_HTTP = (400, 401, 403, 404)
    RETRY_SLEEP_CAP = 60.0

    def __init__(self, model, *, preset="compat", base_url=None, key_env=None, **kw):
        kw.setdefault("timeout", 300)
        kw.setdefault("max_attempts", 3)
        super().__init__(model, **kw)
        if preset not in PRESETS:
            raise OptionsError(f"unknown preset {preset!r}")
        self.preset = preset
        self.base_url = (base_url or PRESETS[preset]["base"] or "").rstrip("/")
        self.key_env = key_env or PRESETS[preset]["key_env"]
        if not self.base_url or not self.key_env:
            raise OptionsError("the compat preset needs base_url and key_env")
        refuse_relay(self.base_url)
        self._key = os.environ.get(self.key_env)
        if not self._key:
            raise BackendError(f"environment variable {self.key_env} is not set")

    def _lookup_identity(self):
        # no network call: an API has no digest; E10 records the returned model / fingerprint per call
        return {"backend": self.kind, "preset": self.preset, "base_url": self.base_url, "model": self.model,
                "key_env": self.key_env, "digest": None}

    def normalize_opts(self, opts):
        return coerce_opts(opts, required=REQUIRED_OPTS, int_keys=("seed", "max_tokens"), float_keys=("temperature", "top_p"),
                           nullable=("temperature", "top_p", "seed"))

    def build_body(self, messages, opts, fmt=None):
        if fmt:
            raise OptionsError("structured output formats are not supported by this backend")
        o = self.normalize_opts(opts)
        body = {"model": self.model, "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
                "max_completion_tokens": o["max_tokens"]}
        for k in ("temperature", "top_p", "seed"):
            if o[k] is not None:
                body[k] = o[k]
        return body

    def sent_opts(self, body):
        return {"max_tokens": body.get("max_completion_tokens", body.get("max_tokens")),
                "temperature": body.get("temperature"), "top_p": body.get("top_p"), "seed": body.get("seed")}

    def _post(self, body):
        return http_json(f"{self.base_url}/chat/completions", body, headers={"Authorization": f"Bearer {self._key}"},
                         timeout=self.timeout)

    def _send_once(self, body):
        try:
            return self._post(body), body
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            low = text.lower()
            adj = None
            if e.code == 400 and "max_completion_tokens" in low and "max_completion_tokens" in body:
                adj = {k: v for k, v in body.items() if k != "max_completion_tokens"}
                adj["max_tokens"] = body["max_completion_tokens"]
            elif e.code == 400 and "temperature" in low and "temperature" in body:
                adj = {k: v for k, v in body.items() if k != "temperature"}
            if adj is None:
                raise urllib.error.HTTPError(e.url, e.code, f"{e.reason}: {text[:400]}", e.headers, None)
            if self._active_guard is not None:
                self._active_guard(self.sent_opts(adj))
            return self._post(adj), adj

    def _parse(self, resp):
        choice = (resp.get("choices") or [{}])[0]
        usage = resp.get("usage") or {}
        return {
            "content": ((choice.get("message") or {}).get("content")) or "",
            "done_reason": choice.get("finish_reason"),
            "prompt_eval_count": usage.get("prompt_tokens"),
            "eval_count": usage.get("completion_tokens"),
            "response_model": resp.get("model"),
            "system_fingerprint": resp.get("system_fingerprint"),
            "response_id": resp.get("id"),
            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        }

    def call(self, messages, opts, *, fmt=None, guard=None):
        rec = super().call(messages, opts, fmt=fmt, guard=guard)
        rec["temperature_sent"] = rec["sent_opts"].get("temperature") is not None
        # v5 kept the client wall time here; the pipeline reads it as generation seconds
        rec["total_duration_ns"] = int(rec["seconds"] * 1e9)
        rec["total_duration_source"] = "client_wall"
        return rec

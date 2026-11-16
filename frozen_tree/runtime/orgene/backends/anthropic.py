"""Anthropic Messages API backend (the v5 api_runner's `anthropic` path, moved behind the common interface) (E08).

The Messages API has no seed parameter, so `seed` is recorded as None. System messages are joined into the
top-level `system` field, as in v5.
"""
import os

from .base import Backend, BackendError, OptionsError, coerce_opts, http_json
from .openai_compat import refuse_relay

DEFAULT_BASE = "https://api.anthropic.com"
REQUIRED_OPTS = ("temperature", "max_tokens")


class AnthropicBackend(Backend):
    kind = "anthropic"
    NON_RETRYABLE_HTTP = (400, 401, 403, 404)
    RETRY_SLEEP_CAP = 60.0

    def __init__(self, model, *, base_url=None, key_env="ANTHROPIC_API_KEY", **kw):
        kw.setdefault("timeout", 300)
        kw.setdefault("max_attempts", 3)
        super().__init__(model, **kw)
        self.base_url = (base_url or DEFAULT_BASE).rstrip("/")
        self.key_env = key_env
        refuse_relay(self.base_url)
        self._key = os.environ.get(self.key_env)
        if not self._key:
            raise BackendError(f"environment variable {self.key_env} is not set")

    def _lookup_identity(self):
        return {"backend": self.kind, "base_url": self.base_url, "model": self.model, "key_env": self.key_env, "digest": None}

    def normalize_opts(self, opts):
        return coerce_opts(opts, required=REQUIRED_OPTS, int_keys=("max_tokens",), float_keys=("temperature",),
                           nullable=("temperature",))

    def build_body(self, messages, opts, fmt=None):
        if fmt:
            raise OptionsError("structured output formats are not supported by this backend")
        o = self.normalize_opts(opts)
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system") or None
        body = {"model": self.model, "max_tokens": o["max_tokens"],
                "messages": [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]}
        if system:
            body["system"] = system
        if o["temperature"] is not None:
            body["temperature"] = o["temperature"]
        return body

    def sent_opts(self, body):
        return {"max_tokens": body.get("max_tokens"), "temperature": body.get("temperature"), "seed": None}

    def _send_once(self, body):
        headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01"}
        return http_json(f"{self.base_url}/v1/messages", body, headers=headers, timeout=self.timeout), body

    def _parse(self, resp):
        usage = resp.get("usage") or {}
        return {
            "content": "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text"),
            "done_reason": resp.get("stop_reason"),
            "prompt_eval_count": usage.get("input_tokens"),
            "eval_count": usage.get("output_tokens"),
            "response_model": resp.get("model"),
            "system_fingerprint": None,
            "response_id": resp.get("id"),
            "reasoning_tokens": None,
        }

    def call(self, messages, opts, *, fmt=None, guard=None):
        rec = super().call(messages, opts, fmt=fmt, guard=guard)
        rec["temperature_sent"] = rec["sent_opts"].get("temperature") is not None
        rec["total_duration_ns"] = int(rec["seconds"] * 1e9)
        rec["total_duration_source"] = "client_wall"
        return rec

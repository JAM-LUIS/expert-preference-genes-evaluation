"""llama.cpp `llama-server` backend (for the ORLM / LLMOPT anchors; E17 builds on it) (E08).

Uses the server's OpenAI-compatible /v1/chat/completions, which applies the GGUF's own chat template and accepts
the llama.cpp sampling fields; every sampling option is sent on every call, as for Ollama. Identity comes from
`/props` (build, context size, chat-template hash). The model file is recorded by its base name only, never by its
path. The GGUF sha256 is not available from the server; E17 records it in the model registry, and a registry entry
with a `digest` is compared against `digest` given to the constructor.
"""
import os

from .base import Backend, BackendError, OptionsError, coerce_opts, http_json, sha256_hex

REQUIRED_OPTS = ("temperature", "top_k", "top_p", "seed", "max_tokens")
INT_OPTS = ("top_k", "seed", "max_tokens")
FLOAT_OPTS = ("temperature", "top_p", "min_p", "repeat_penalty")


class LlamaCppBackend(Backend):
    kind = "llamacpp"
    NON_RETRYABLE_HTTP = (400, 404)
    RETRY_SLEEP_CAP = 30.0

    def __init__(self, model, *, host="http://127.0.0.1:8080", digest=None, **kw):
        super().__init__(model, **kw)
        self.host = host.rstrip("/")
        self._digest = digest

    def _lookup_identity(self):
        try:
            props = http_json(f"{self.host}/props", timeout=60)
        except Exception as e:  # noqa: BLE001
            raise BackendError(f"llama-server at {self.host} not reachable: {type(e).__name__}") from e
        gen = props.get("default_generation_settings") or {}
        tmpl = props.get("chat_template")
        mpath = props.get("model_path")
        return {
            "backend": self.kind,
            "host": self.host,
            "model": self.model,
            "digest": self._digest,
            "model_file": os.path.basename(mpath) if isinstance(mpath, str) else None,
            "build_info": props.get("build_info"),
            "n_ctx": gen.get("n_ctx", props.get("n_ctx")),
            "chat_template_sha256": sha256_hex(tmpl.encode("utf-8")) if isinstance(tmpl, str) else None,
        }

    def normalize_opts(self, opts):
        return coerce_opts(opts, required=REQUIRED_OPTS, int_keys=INT_OPTS, float_keys=FLOAT_OPTS)

    def build_body(self, messages, opts, fmt=None):
        if fmt:
            raise OptionsError("structured output formats are not supported by this backend")
        o = self.normalize_opts(opts)
        body = {"model": self.model, "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
                "stream": False}
        body.update({k: o[k] for k in sorted(o)})
        return body

    def sent_opts(self, body):
        return {k: body[k] for k in sorted(body) if k not in ("model", "messages", "stream")}

    def _send_once(self, body):
        return http_json(f"{self.host}/v1/chat/completions", body, timeout=self.timeout), body

    def _parse(self, resp):
        choice = (resp.get("choices") or [{}])[0]
        usage = resp.get("usage") or {}
        timings = resp.get("timings") or {}

        def ns(ms):
            return int(ms * 1e6) if isinstance(ms, (int, float)) else None
        p_ns, e_ns = ns(timings.get("prompt_ms")), ns(timings.get("predicted_ms"))
        return {
            "content": ((choice.get("message") or {}).get("content")) or "",
            "done_reason": choice.get("finish_reason"),
            "prompt_eval_count": usage.get("prompt_tokens"),
            "eval_count": usage.get("completion_tokens"),
            "response_model": resp.get("model"),
            "system_fingerprint": resp.get("system_fingerprint"),
            "prompt_eval_duration_ns": p_ns,
            "eval_duration_ns": e_ns,
            "total_duration_ns": (p_ns or 0) + (e_ns or 0) if (p_ns is not None or e_ns is not None) else None,
            "total_duration_source": "server",
        }


# ---------------------------------------------------------------------------------------------------------------------
# E17: raw completion through llama-server's native /completion (the ORLM anchor: a completion model, no chat template)
# ---------------------------------------------------------------------------------------------------------------------

from .base import scrub_paths  # noqa: E402  (kept next to the class it serves, so the E08 part above is unchanged)

COMPLETION_REQUIRED_OPTS = ("temperature", "top_k", "top_p", "min_p", "typical_p", "repeat_penalty", "presence_penalty",
                            "frequency_penalty", "dry_multiplier", "xtc_probability", "mirostat", "seed", "n_predict",
                            "cache_prompt", "stop")
COMPLETION_INT_OPTS = ("top_k", "seed", "n_predict", "mirostat")
COMPLETION_FLOAT_OPTS = ("temperature", "top_p", "min_p", "typical_p", "repeat_penalty", "presence_penalty",
                         "frequency_penalty", "dry_multiplier", "xtc_probability")
COMPLETION_BOOL_OPTS = ("cache_prompt",)
COMPLETION_OTHER_OPTS = ("stop",)
# llama-server's stop_type -> the done_reason vocabulary of the other backends ("length" = the output budget ran out)
STOP_TYPE_TO_DONE_REASON = {"eos": "stop", "word": "stop", "limit": "length", "none": None}
# settings the server echoes in `generation_settings`; compared with what was sent (catches an ignored or renamed field)
ECHO_KEYS = ("temperature", "top_k", "top_p", "min_p", "typical_p", "repeat_penalty", "presence_penalty",
             "frequency_penalty", "dry_multiplier", "xtc_probability", "mirostat", "seed", "n_predict", "stop")


def _echo_differs(sent, echoed):
    if isinstance(sent, bool) or isinstance(echoed, bool):
        return sent != echoed
    if isinstance(sent, (int, float)) and isinstance(echoed, (int, float)):
        # the server keeps float settings as 32-bit floats (0.95 comes back as 0.949999988...)
        return abs(float(sent) - float(echoed)) > 1e-6 * max(1.0, abs(float(sent)))
    return sent != echoed


class LlamaCppCompletionBackend(LlamaCppBackend):
    """llama-server's native `/completion`: the prompt is sent verbatim, no chat template is applied (E17).

    `messages` must be exactly one user message; its content is the whole prompt (for ORLM: the official completion
    template filled with the problem text). Every sampling option that can change the arg-max token is required and
    sent on every call, together with `cache_prompt` (false: the whole prompt is evaluated for every request, so the
    output does not depend on the previous request's KV cache) and `stop`. The record adds the server's stop_type,
    stopping word, prompt truncation flag, the echoed generation settings, and any difference between the echoed and
    the sent settings (`settings_echo_mismatch`; an adapter treats a non-empty list as a failed run).
    """

    kind = "llamacpp_completion"

    def _lookup_identity(self):
        ident = super()._lookup_identity()
        ident["backend"] = self.kind
        try:
            props = http_json(f"{self.host}/props", timeout=60)
        except Exception:  # noqa: BLE001  (super() just read it; a second failure only drops the extra fields)
            props = {}
        ident["total_slots"] = props.get("total_slots")
        return ident

    def normalize_opts(self, opts):
        o = coerce_opts(opts, required=COMPLETION_REQUIRED_OPTS, int_keys=COMPLETION_INT_OPTS,
                        float_keys=COMPLETION_FLOAT_OPTS, bool_keys=COMPLETION_BOOL_OPTS,
                        other_keys=COMPLETION_OTHER_OPTS)
        stop = o["stop"]
        if not isinstance(stop, list) or not all(isinstance(s, str) for s in stop):
            raise OptionsError("option stop must be a list of strings")
        o["stop"] = list(stop)
        return o

    def build_body(self, messages, opts, fmt=None):
        if fmt:
            raise OptionsError("structured output formats are not supported by this backend")
        if len(messages) != 1 or messages[0].get("role") != "user":
            raise OptionsError("the completion endpoint takes exactly one user message (its content is the prompt)")
        o = self.normalize_opts(opts)
        body = {"model": self.model, "prompt": messages[0]["content"], "stream": False}
        body.update({k: o[k] for k in sorted(o)})
        return body

    def sent_opts(self, body):
        return {k: body[k] for k in sorted(body) if k not in ("model", "prompt", "stream")}

    def _send_once(self, body):
        return http_json(f"{self.host}/completion", body, timeout=self.timeout), body

    def _parse(self, resp):
        timings = resp.get("timings") or {}

        def ns(ms):
            return int(ms * 1e6) if isinstance(ms, (int, float)) else None
        p_ns, e_ns = ns(timings.get("prompt_ms")), ns(timings.get("predicted_ms"))
        stop_type = resp.get("stop_type")
        if stop_type is None:  # older servers report three booleans instead
            stop_type = ("eos" if resp.get("stopped_eos") else "word" if resp.get("stopped_word")
                         else "limit" if resp.get("stopped_limit") else None)
        gen = resp.get("generation_settings") or {}
        echoed = {k: gen[k] for k in ECHO_KEYS if k in gen}
        model = resp.get("model")
        return {
            "content": resp.get("content") or "",
            "done_reason": STOP_TYPE_TO_DONE_REASON.get(stop_type, stop_type),
            "stop_type": stop_type,
            "stopping_word": resp.get("stopping_word") or None,
            "prompt_truncated": resp.get("truncated"),
            "prompt_eval_count": resp.get("tokens_evaluated"),
            "eval_count": resp.get("tokens_predicted"),
            "tokens_cached": resp.get("tokens_cached"),
            "response_model": scrub_paths(model) if isinstance(model, str) else model,
            "generation_settings": echoed,
            "prompt_eval_duration_ns": p_ns,
            "eval_duration_ns": e_ns,
            "total_duration_ns": (p_ns or 0) + (e_ns or 0) if (p_ns is not None or e_ns is not None) else None,
            "total_duration_source": "server",
        }

    def call(self, messages, opts, *, fmt=None, guard=None):
        rec = super().call(messages, opts, fmt=fmt, guard=guard)
        sent, echoed = rec.get("sent_opts") or {}, rec.get("generation_settings")
        if rec.get("ok") and isinstance(echoed, dict):
            rec["settings_echo_mismatch"] = sorted(k for k in ECHO_KEYS if k in sent and k in echoed
                                                   and _echo_differs(sent[k], echoed[k]))
            rec["settings_echo_missing"] = sorted(k for k in ECHO_KEYS if k in sent and k not in echoed)
        else:
            rec["settings_echo_mismatch"], rec["settings_echo_missing"] = None, None
        return rec

"""Ollama backend: native /api/chat, every decoding option sent on every call (E08).

v5 sent only temperature, num_ctx and num_predict, so a call with temperature > 0 silently inherited top_k and top_p
from the model's Modelfile. Here the six decoding options are required and sent explicitly on every call, `think` is
sent explicitly, and `keep_alive` defaults to 0 (the model is unloaded after each call; a warm KV cache can change
greedy output, and the main experiments load the model cold for every call).

`think` is true / false, or a reasoning level "low" / "medium" / "high" (E23: gpt-oss cannot switch its reasoning off;
Ollama 0.33 writes the level into gpt-oss's system message, and false only drops that line). The server returns the
reasoning as message.thinking; the record keeps it apart from `content` (`thinking`, `thinking_sha256`), so it never
reaches code extraction or scoring.

Identity (`/api/version`, `/api/tags`, `/api/show`) never loads the model. `loaded_models()` reads `/api/ps` so a
scheduler can yield to other users of the server (E07).
"""
import math
import re

from .base import Backend, BackendError, OptionsError, coerce_opts, content_sha256, http_json, sha256_hex

REQUIRED_OPTS = ("temperature", "top_k", "top_p", "seed", "num_ctx", "num_predict")
INT_OPTS = ("top_k", "seed", "num_ctx", "num_predict", "num_keep", "repeat_last_n")
FLOAT_OPTS = ("temperature", "top_p", "min_p", "typical_p", "repeat_penalty", "presence_penalty", "frequency_penalty")
OTHER_OPTS = ("stop",)
CONTROL_OPTS = ("think", "keep_alive")
DEFAULT_KEEP_ALIVE = 0
# E23: reasoning levels accepted for `think` besides true / false (gpt-oss's levels; the server also accepts "max",
# which is not a gpt-oss level and is refused here)
THINK_LEVELS = ("low", "medium", "high")

_INT_RE = re.compile(r"^-?\d+$")


def parse_keep_alive(v):
    """'0' / 0 -> 0 (seconds, int); '30m' stays a duration string; None -> the default (0)."""
    if v is None:
        return DEFAULT_KEEP_ALIVE
    if isinstance(v, bool):
        raise OptionsError("keep_alive must be seconds or a duration string")
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (not math.isfinite(v) or v != int(v)):
            raise OptionsError("keep_alive in seconds must be an integer")
        return int(v)
    v = str(v).strip()
    if _INT_RE.match(v):
        return int(v)
    if not re.match(r"^(\d+(\.\d+)?(ns|us|ms|s|m|h))+$", v):
        raise OptionsError(f"keep_alive {v!r} is neither seconds nor a duration such as 30m")
    return v


def check_think(v):
    """`think` as sent: true / false, or one of THINK_LEVELS (E23). Anything else (None, 0, "none", "LOW") is refused
    before sending; the server would answer 400."""
    if isinstance(v, bool) or (isinstance(v, str) and v in THINK_LEVELS):
        return v
    raise OptionsError(f"option think must be true, false or one of {list(THINK_LEVELS)}, got {v!r}")


def parse_think(v):
    """A command-line think value: true / false (also as the words), or one of THINK_LEVELS (E23)."""
    if isinstance(v, str) and v in ("true", "false"):
        return v == "true"
    return check_think(v)


def parse_modelfile_parameters(text):
    """`/api/show` parameters text ("key value" per line, `stop` repeated) -> dict with typed values."""
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        key = parts[0]
        val = parts[1].strip() if len(parts) > 1 else ""
        if len(val) >= 2 and val[0] == val[-1] == '"':
            val = val[1:-1]
        else:
            try:
                val = int(val) if _INT_RE.match(val) else float(val)
            except ValueError:
                pass
        if key == "stop":
            out.setdefault("stop", []).append(val)
        else:
            out[key] = val
    return out


class OllamaBackend(Backend):
    kind = "ollama"
    NON_RETRYABLE_HTTP = ()  # v5 retried every failure; kept
    RETRY_SLEEP_CAP = 30.0

    def __init__(self, model, *, host="http://127.0.0.1:11434", **kw):
        super().__init__(model, **kw)
        self.host = host.rstrip("/")

    # -- identity -------------------------------------------------------------------------------------------------
    def _lookup_identity(self):
        try:
            version = http_json(f"{self.host}/api/version", timeout=60).get("version")
            tags = http_json(f"{self.host}/api/tags", timeout=60).get("models", [])
        except Exception as e:  # noqa: BLE001
            raise BackendError(f"Ollama server at {self.host} not reachable: {type(e).__name__}") from e
        entry = next((m for m in tags if m.get("name") == self.model or m.get("model") == self.model), None)
        if entry is None:
            raise BackendError(f"model '{self.model}' is not installed on {self.host}")
        try:
            show = http_json(f"{self.host}/api/show", {"model": self.model}, timeout=60)
        except Exception as e:  # noqa: BLE001
            show = {"error": type(e).__name__}
        tmpl = show.get("template")
        return {
            "backend": self.kind,
            "host": self.host,
            "ollama_version": version,
            "model": self.model,
            "digest": entry.get("digest"),
            "size_bytes": entry.get("size"),
            "modified_at": entry.get("modified_at"),
            "details": entry.get("details"),
            "capabilities": show.get("capabilities"),
            "parameters_from_modelfile": show.get("parameters"),
            "template_sha256": sha256_hex(tmpl.encode("utf-8")) if isinstance(tmpl, str) else None,
        }

    def inherited_defaults(self, sent):
        """Modelfile parameters that still apply because the call does not set them (e.g. repeat_penalty, stop)."""
        params = parse_modelfile_parameters(self.identity().get("parameters_from_modelfile"))
        return {k: v for k, v in sorted(params.items()) if k not in sent}

    def loaded_models(self):
        """Models the server currently holds in memory (`/api/ps`): [{name, digest, expires_at}]."""
        ps = http_json(f"{self.host}/api/ps", timeout=30).get("models", [])
        return [{"name": m.get("name") or m.get("model"), "digest": m.get("digest"), "expires_at": m.get("expires_at")}
                for m in ps]

    # -- request construction ---------------------------------------------------------------------------------------
    def normalize_opts(self, opts):
        if not isinstance(opts, dict):
            raise OptionsError("opts must be a dict")
        o = dict(opts)
        ka = parse_keep_alive(o.pop("keep_alive", None))
        if "think" not in o:
            raise OptionsError("option(s) must be set explicitly: ['think']")
        think = check_think(o.pop("think"))
        out = coerce_opts(o, required=REQUIRED_OPTS, int_keys=INT_OPTS, float_keys=FLOAT_OPTS, other_keys=OTHER_OPTS)
        out["think"] = think
        out["keep_alive"] = ka
        return out

    def build_body(self, messages, opts, fmt=None):
        o = self.normalize_opts(opts)
        think, keep_alive = o.pop("think"), o.pop("keep_alive")
        body = {
            "model": self.model,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
            "stream": False,
            "options": {k: o[k] for k in sorted(o)},
            "think": think,
            "keep_alive": keep_alive,
        }
        if fmt:
            body["format"] = fmt
        return body

    def sent_opts(self, body):
        return dict(body["options"], think=body["think"], keep_alive=body["keep_alive"])

    # -- transport ------------------------------------------------------------------------------------------------
    def _send_once(self, body):
        return http_json(f"{self.host}/api/chat", body, timeout=self.timeout), body

    def _parse(self, resp):
        msg = resp.get("message") or {}
        thinking = msg.get("thinking")
        return {
            "content": msg.get("content") or "",
            "thinking": thinking,
            "thinking_sha256": content_sha256(thinking) if isinstance(thinking, str) else None,
            "response_model": resp.get("model"),
            "server_created_at": resp.get("created_at"),
            "done_reason": resp.get("done_reason"),
            "prompt_eval_count": resp.get("prompt_eval_count"),
            "eval_count": resp.get("eval_count"),
            "load_duration_ns": resp.get("load_duration"),
            "prompt_eval_duration_ns": resp.get("prompt_eval_duration"),
            "eval_duration_ns": resp.get("eval_duration"),
            "total_duration_ns": resp.get("total_duration"),
            "total_duration_source": "server",
        }

"""Model backends with one interface: `backend.call(messages, opts) -> call record` (E08).

  ollama.OllamaBackend               local Ollama, native /api/chat, every decoding option sent per call
  openai_compat.OpenAICompatBackend  OpenAI / DeepSeek / official OpenAI-compatible endpoints (E10 extends it)
  anthropic.AnthropicBackend         Anthropic Messages API
  llamacpp.LlamaCppBackend           llama.cpp llama-server (anchors, E17)
  llamacpp.LlamaCppCompletionBackend llama-server native /completion, raw prompt, no chat template (ORLM anchor, E17)

The batch runner (orgene.runner) and the unit executor (E06) both call backends through this interface.
"""
from .base import (CALL_SCHEMA, REQUIRED_CALL_FIELDS, Backend, BackendError, OptionsError, RegistryMismatch,  # noqa: F401
                   canonical_json, missing_call_fields, registry_guard, request_sha256)

KINDS = ("ollama", "openai_compat", "anthropic", "llamacpp", "llamacpp_completion")


def make_backend(kind, model, **kw):
    """Construct a backend by kind. Imports lazily so a missing optional piece never breaks the others."""
    if kind == "ollama":
        from .ollama import OllamaBackend
        return OllamaBackend(model, **kw)
    if kind == "openai_compat":
        from .openai_compat import OpenAICompatBackend
        return OpenAICompatBackend(model, **kw)
    if kind == "anthropic":
        from .anthropic import AnthropicBackend
        return AnthropicBackend(model, **kw)
    if kind == "llamacpp":
        from .llamacpp import LlamaCppBackend
        return LlamaCppBackend(model, **kw)
    if kind == "llamacpp_completion":
        from .llamacpp import LlamaCppCompletionBackend
        return LlamaCppCompletionBackend(model, **kw)
    raise OptionsError(f"unknown backend kind {kind!r}; known: {KINDS}")

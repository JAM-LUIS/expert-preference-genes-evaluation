"""Chat template of the LLMOPT anchor, rendered locally, and its local token counter (E18; llama-server since wave2).

The anchor runs on llama-server's native /completion (orgene.backends.llamacpp.LlamaCppCompletionBackend, as the ORLM
anchor): each prompt is rendered here with a Python port of the chat template stored in the GGUF (the Qwen2.5 Jinja
template, sha256 cd8e9439...) and sent verbatim, so no template layer of a server is involved. Every request is exactly
one user message (the official inference script sends one user message per step; require_single_user_message
enforces it), rendered as

    <|im_start|>system\\n<Qwen's default system text><|im_end|>\\n<|im_start|>user\\n<text><|im_end|>\\n
    <|im_start|>assistant\\n

render_gguf follows the Jinja template as HF / llama.cpp apply it (add_generation_prompt=True, no tools, messages not
merged); runtime/tests/test_llmopt_anchor.py checks it against jinja2 renderings byte for byte. render_modelfile is the
port of the TEMPLATE of the model's Ollama Modelfile (Go text/template, blob 5d00c7c5..., after Ollama's collate
step), kept for the conversion record: on one user message the two give the same prompt (checked against Go
text/template). Neither port handles tool definitions, tool calls or images; they refuse them.

GgufCounter counts with llama.cpp's llama-tokenize over the GGUF the server loads (the E09 counter interface): the
rendered prompt with special tokens parsed and the model's own BOS rule, as llama-server tokenizes a /completion
prompt. The driver compares that count with the server's tokens_evaluated on every call.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if os.path.join(_ROOT, "runtime") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "runtime"))

from orgene import tokcount as TC  # noqa: E402

SERVER_ALIAS = "llmopt-qwen25-14b-q8"  # llama-server --alias: the registry entry's model
MODELFILE_TEMPLATE_SHA256 = "5d00c7c57b65651906a5696cf5fac099016152eaa49d682bcfd2cc4533464ead"
GGUF_TEMPLATE_SHA256 = "cd8e9439f0570856fd70470bf8889ebd8b5d1107207f67a5efb46e342330527f"
DEFAULT_SYSTEM = "You are Qwen, created by Alibaba Cloud. You are a helpful assistant."
ROLES = ("system", "user", "assistant", "tool")
RENDERER_ID = "llmopt-gguf-chat-template.v1"
_PROMPT_HEAD = "<|im_start|>system\n" + DEFAULT_SYSTEM + "<|im_end|>\n<|im_start|>user\n"
_PROMPT_TAIL = "<|im_end|>\n<|im_start|>assistant\n"
CONTROL_TOKENS = ("<|im_start|>", "<|im_end|>", "<|endoftext|>")


class TemplateError(ValueError):
    """Messages the ports do not reproduce, or a request shape the adapter must not send."""


def _check(messages):
    if not isinstance(messages, (list, tuple)) or not messages:
        raise TemplateError("messages must be a non-empty list")
    out = []
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            raise TemplateError(f"message {i} is not an object")
        if m.get("role") not in ROLES:
            raise TemplateError(f"message {i} has role {m.get('role')!r}; the ports know {ROLES}")
        for k in ("tool_calls", "images", "tools"):
            if m.get(k):
                raise TemplateError(f"message {i} carries {k}; the ports do not reproduce them")
        if not isinstance(m.get("content"), str):
            raise TemplateError(f"message {i} content must be a string")
        out.append({"role": m["role"], "content": m["content"]})
    return out


def require_single_user_message(messages):
    """The adapter's request shape: exactly one user message, no system message. Raises TemplateError otherwise."""
    if not (isinstance(messages, (list, tuple)) and len(messages) == 1 and isinstance(messages[0], dict)
            and messages[0].get("role") == "user" and isinstance(messages[0].get("content"), str)
            and set(messages[0]) == {"role", "content"}):
        raise TemplateError("an LLMOPT request must be exactly one user message (role and content only), as the "
                            "upstream inference script sends")
    return messages


def collate(messages):
    """Ollama's template.collate: consecutive messages of one role merged with a blank line, tool messages kept apart."""
    out = []
    for m in _check(messages):
        if out and out[-1]["role"] == m["role"] and m["role"] != "tool":
            out[-1] = {"role": m["role"], "content": out[-1]["content"] + "\n\n" + m["content"]}
        else:
            out.append(dict(m))
    return out


def render_modelfile(messages):
    """Prompt from the Modelfile TEMPLATE (blob 5d00c7c5...) as Ollama's Go renderer builds it (conversion record)."""
    msgs = collate(messages)
    out = []
    if not msgs or msgs[0]["role"] != "system":
        out.append("<|im_start|>system\n" + DEFAULT_SYSTEM + "<|im_end|>\n")
    for m in msgs:
        out.append("<|im_start|>" + m["role"] + "\n" + m["content"] + "<|im_end|>\n")
    out.append("<|im_start|>assistant\n")
    return "".join(out)


def render_gguf(messages, add_generation_prompt=True):
    """Prompt from the GGUF's Qwen2.5 Jinja chat template (cd8e9439...), no tools, messages not merged."""
    msgs = _check(messages)
    out = []
    if msgs[0]["role"] == "system":
        out.append("<|im_start|>system\n" + msgs[0]["content"] + "<|im_end|>\n")
    else:
        out.append("<|im_start|>system\n" + DEFAULT_SYSTEM + "<|im_end|>\n")
    last = len(msgs) - 1
    for i, m in enumerate(msgs):
        role = m["role"]
        if role == "user" or (role == "system" and i > 0) or role == "assistant":
            out.append("<|im_start|>" + role + "\n" + m["content"] + "<|im_end|>\n")
        elif role == "tool":
            if i == 0 or msgs[i - 1]["role"] != "tool":
                out.append("<|im_start|>user")
            out.append("\n<tool_response>\n" + m["content"] + "\n</tool_response>")
            if i == last or msgs[i + 1]["role"] != "tool":
                out.append("<|im_end|>\n")
    if add_generation_prompt:
        out.append("<|im_start|>assistant\n")
    return "".join(out)


RENDERERS = {"modelfile": render_modelfile, "gguf": render_gguf}


def render_prompt(messages):
    """The /completion prompt of one LLMOPT request: exactly one user message, rendered with the GGUF template.
    A user text that itself carries a chat control token is refused: the server parses special tokens in the prompt,
    so such a text would change the turn structure."""
    text = require_single_user_message(messages)[0]["content"]
    bad = [t for t in CONTROL_TOKENS if t in text]
    if bad:
        raise TemplateError(f"the user text carries chat control token(s) {bad}; it cannot be sent as one turn")
    return render_gguf(messages)


def user_text_of(prompt):
    """The user text of a prompt render_prompt made, or None when `prompt` is not such a prompt."""
    if not (isinstance(prompt, str) and prompt.startswith(_PROMPT_HEAD) and prompt.endswith(_PROMPT_TAIL)
            and len(prompt) >= len(_PROMPT_HEAD) + len(_PROMPT_TAIL)):
        return None
    text = prompt[len(_PROMPT_HEAD):len(prompt) - len(_PROMPT_TAIL)]
    if any(t in text for t in CONTROL_TOKENS):
        return None
    return text if render_prompt([{"role": "user", "content": text}]) == prompt else None


class GgufCounter:
    """Local token counts for LLMOPT calls through llama-server /completion (the E09 counter interface: local_tokens,
    identity). llama.cpp's llama-tokenize reads the vocabulary of the GGUF the server loads (its sha256 is checked).
    The request's one user message is the rendered prompt; it is counted with special tokens parsed and the model's
    BOS rule (rendered_prompt), which is what llama-server evaluates for a /completion request."""

    backend = "llamacpp_completion"

    def __init__(self, gguf_path, gguf_sha256, binary=None, verify="full"):
        self.tok = TC.LlamaCppTokenizer(gguf_path, gguf_sha256, binary=binary, verify=verify)
        self._identity = {"backend": self.backend, "gguf_file": os.path.basename(gguf_path), "gguf_sha256": gguf_sha256,
                          "prompt_template_sha256": GGUF_TEMPLATE_SHA256, "renderer": RENDERER_ID,
                          "tokenizer": self.tok.identity()}
        self.identity_sha256 = TC.identity_sha256(self._identity)

    def identity(self):
        return dict(self._identity)

    def count(self, text):
        return self.tok.count(text, parse_special=False, model_bos=False)

    def count_prompt(self, prompt):
        return self.tok.count(prompt, parse_special=True, model_bos=True)

    def local_tokens(self, messages, completion, think=None, thinking=None):
        prompt = messages[0]["content"] if messages else ""
        user = user_text_of(prompt)
        content = self.count(user if user is not None else prompt)
        return {"schema": TC.SCHEMA, "tokenizer_sha256": self.identity_sha256,
                "content_by_message": [content], "content_total": content,
                "rendered_prompt": self.count_prompt(prompt), "think": think, "history_think_stripped": 0,
                "prompt_is_rendered": user is not None,
                "completion": self.count(completion or ""), "completion_thinking": self.count(thinking or "")}

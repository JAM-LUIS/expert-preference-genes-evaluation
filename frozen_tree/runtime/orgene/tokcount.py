"""Local tokenizer counts for every model call (E09, B0-02).

The servers report token counts (Ollama: prompt_eval_count / eval_count; APIs: usage.prompt_tokens /
completion_tokens) but nothing checks them: a server-side template, a hidden prefix or a truncated conversation
changes the reported count and nobody notices. Every call therefore also gets counts from a local tokenizer over
exactly the messages that were sent, and the difference is analysed (token_audit, E20).

qwen3 served by Ollama
  llama.cpp's `llama-tokenize` reads the vocabulary of the very GGUF blob Ollama serves
  (<model store>/blobs/sha256-<weights>; with a tokenizer-only load, no weights are read), so the local count uses
  the same vocabulary and merges as the server. Counts per call (`local_tokens`):
    content_by_message  each message body; special-token text is not parsed, no BOS
    rendered_prompt     the whole prompt as Ollama renders it (render_qwen3, a Python port of the template blob that is
                        tested against Go text/template output), special tokens parsed, BOS as the model says (qwen3:
                        none). This is the number prompt_eval_count should equal.
    completion          the returned content, counted like a message body (completion_thinking: the `thinking` field)
  llama-tokenize is always called with --no-escape: by default it turns the two characters backslash-n into a newline,
  which would miscount any program that prints "\\n".

OpenAI models (the model is not chosen yet: D6 / Q4)
  tiktoken with a local encoding file whose sha256 comes from the model registry (E19), run in a separate interpreter
  (default <root>/.venv-tools/bin/python, or $ORGENE_TOOLS_PY) through a subprocess, so this runtime needs no
  third-party package and tiktoken never downloads anything. The provider's chat framing is not public, so
  rendered_prompt is not computed for API calls; the reported prompt tokens are compared with content_total instead.

Nothing here returns None for a count. A missing binary, model file, encoding file or interpreter, a hash mismatch,
a chat template this module has no port of, or a tokenizer failure raises TokenizerError.
"""
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys

from .paths import ROOT, rel

SCHEMA = "orgene.r1.local_tokens.v1"

# qwen3:8b as pulled into Ollama (v5 DECISIONS; the model registry E19 keeps the same values)
QWEN3_MANIFEST_SHA256 = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"  # Ollama "digest"
QWEN3_WEIGHTS_SHA256 = "a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f"
QWEN3_TEMPLATE_SHA256 = "ae370d884f108d16e7cc8fd5259ebc5773a0afa6e078b11f4ed7e39a27e0dfc4"

DEFAULT_LLAMA_TOKENIZE = "/opt/homebrew/bin/llama-tokenize"
ENV_LLAMA_TOKENIZE = "ORGENE_LLAMA_TOKENIZE"
ENV_OLLAMA_MODELS = "OLLAMA_MODELS"  # Ollama's own variable for its model store
ENV_TOOLS_PY = "ORGENE_TOOLS_PY"
DEFAULT_TOOLS_PY = os.path.join(ROOT, ".venv-tools", "bin", "python")

_HEX64 = re.compile(r"[0-9a-f]{64}")
_IDS_LINE = re.compile(r"\[\s*(?:-?\d+\s*(?:,\s*-?\d+\s*)*)?\]")
_NAME_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class TokenizerError(RuntimeError):
    """A local token count cannot be produced. Never swallowed into a None count."""


# ---------------------------------------------------------------- helpers

def _scrub(s):
    """Error text without the home directory in it."""
    s = s if isinstance(s, str) else str(s)
    home = os.path.expanduser("~")
    return s.replace(home, "~") if home and home != "/" else s


def _utf8(text, what="text"):
    if not isinstance(text, str):
        raise TokenizerError(f"{what} must be a str, got {type(text).__name__}")
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as e:
        raise TokenizerError(f"{what} cannot be encoded as UTF-8 ({e.reason} at offset {e.start})") from None


def sha256_text(text):
    return hashlib.sha256(_utf8(text)).hexdigest()


_FILE_HASHES = {}


def sha256_file(path):
    """sha256 of a file, cached per process by (real path, size, mtime)."""
    st = os.stat(path)
    key = (os.path.realpath(path), st.st_size, st.st_mtime_ns)
    if key not in _FILE_HASHES:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        _FILE_HASHES[key] = h.hexdigest()
    return _FILE_HASHES[key]


def identity_sha256(identity):
    """Short, stable id of a tokenizer identity dict (recorded in every local_tokens entry)."""
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _tail(b, n=300):
    return _scrub((b or b"").decode("utf-8", "replace").strip()[-n:])


# ---------------------------------------------------------------- llama.cpp tokenizer

class LlamaCppTokenizer:
    """Token ids from llama.cpp's `llama-tokenize` over one GGUF file (tokenizer-only load).

    sha256 is required and checked: verify="full" hashes the file (a 5 GB blob takes a few seconds, once per process);
    verify="name" only checks that the file is the Ollama blob named after that hash (Ollama's store is content
    addressed). The text goes through stdin, never through a shell.
    """

    kind = "llama.cpp/llama-tokenize"

    def __init__(self, gguf_path, sha256, binary=None, verify="full", timeout=300):
        self.binary = binary or os.environ.get(ENV_LLAMA_TOKENIZE) or DEFAULT_LLAMA_TOKENIZE
        if not (os.path.isfile(self.binary) and os.access(self.binary, os.X_OK)):
            raise TokenizerError(f"llama-tokenize not found or not executable: {rel(self.binary)} "
                                 f"(install llama.cpp or set {ENV_LLAMA_TOKENIZE})")
        if not isinstance(sha256, str) or not _HEX64.fullmatch(sha256):
            raise TokenizerError("the GGUF file's sha256 (64 lowercase hex digits) is required")
        if not os.path.isfile(gguf_path):
            raise TokenizerError(f"GGUF file not found: {rel(gguf_path)}")
        if verify == "full":
            got = sha256_file(gguf_path)
            if got != sha256:
                raise TokenizerError(f"GGUF file sha256 {got[:12]}… is not the expected {sha256[:12]}…")
        elif verify == "name":
            if os.path.basename(gguf_path) != "sha256-" + sha256:
                raise TokenizerError(f"{rel(gguf_path)} is not the blob sha256-{sha256[:12]}…")
        else:
            raise ValueError("verify must be 'full' or 'name'")
        self.gguf_path, self.sha256, self.verify, self.timeout = gguf_path, sha256, verify, timeout
        self.version = self._version()
        self._cache = {}
        self.ids("x")  # fail now, with the reason, if the file has no usable vocabulary

    def _version(self):
        try:
            p = subprocess.run([self.binary, "--version"], capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            raise TokenizerError(f"cannot run llama-tokenize --version: {type(e).__name__}") from None
        for line in (p.stdout + b"\n" + p.stderr).decode("utf-8", "replace").splitlines():
            if line.strip().lower().startswith("version:"):
                return line.split(":", 1)[1].strip()
        raise TokenizerError(f"llama-tokenize --version printed no version line (rc={p.returncode})")

    def ids(self, text, parse_special=False, model_bos=False):
        """Token ids of `text`. parse_special: read <|im_start|>-style control tokens as such (a rendered prompt);
        model_bos: add BOS if the model adds one (False passes --no-bos)."""
        data = _utf8(text)
        args = [self.binary, "-m", self.gguf_path, "--stdin", "--ids", "--no-escape", "--log-disable"]
        if not parse_special:
            args.append("--no-parse-special")
        if not model_bos:
            args.append("--no-bos")
        try:
            p = subprocess.run(args, input=data, capture_output=True, timeout=self.timeout)
        except (OSError, subprocess.SubprocessError) as e:
            raise TokenizerError(f"llama-tokenize failed to run: {type(e).__name__}") from None
        if p.returncode != 0:
            raise TokenizerError(f"llama-tokenize exited with {p.returncode}: {_tail(p.stderr)}")
        lines = [ln.strip() for ln in p.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
        if not lines or not _IDS_LINE.fullmatch(lines[-1]):
            raise TokenizerError(f"unexpected llama-tokenize output: {_tail(p.stdout, 120)!r}")
        return json.loads(lines[-1])

    def count(self, text, parse_special=False, model_bos=False):
        """Number of tokens, cached by (sha256 of the text, mode)."""
        if text == "" and not model_bos:
            return 0
        key = (sha256_text(text), bool(parse_special), bool(model_bos))
        if key not in self._cache:
            self._cache[key] = len(self.ids(text, parse_special, model_bos))
        return self._cache[key]

    def identity(self):
        return {"kind": self.kind, "version": self.version, "gguf_sha256": self.sha256, "verify": self.verify,
                "flags": ["--no-escape", "content: --no-parse-special --no-bos", "prompt: parse special, model BOS"]}


# ---------------------------------------------------------------- Ollama model store

def ollama_models_dir():
    return os.environ.get(ENV_OLLAMA_MODELS) or os.path.join(os.path.expanduser("~"), ".ollama", "models")


def _parse_tag(tag):
    """'qwen3:8b' -> (registry.ollama.ai, library, qwen3, 8b); '[host/][namespace/]model[:tag]'."""
    if not isinstance(tag, str) or not tag:
        raise TokenizerError("model tag must be a non-empty string")
    name, ver = tag, "latest"
    last = tag.rsplit("/", 1)[-1]
    if ":" in last:
        name, ver = tag.rsplit(":", 1)
    parts = name.split("/")
    if len(parts) == 1:
        parts = ["registry.ollama.ai", "library"] + parts
    elif len(parts) == 2:
        parts = ["registry.ollama.ai"] + parts
    if len(parts) != 3 or not all(_NAME_PART.fullmatch(p) for p in parts + [ver]) or ".." in tag:
        raise TokenizerError(f"cannot parse Ollama model tag {tag!r}")
    return parts[0], parts[1], parts[2], ver


def _blob(models_dir, digest, what, tag):
    if not isinstance(digest, str) or not digest.startswith("sha256:") or not _HEX64.fullmatch(digest[7:]):
        raise TokenizerError(f"{what} layer of {tag} has no sha256 digest")
    path = os.path.join(models_dir, "blobs", "sha256-" + digest[7:])
    if not os.path.isfile(path):
        raise TokenizerError(f"{what} blob of {tag} is missing from the model store")
    return digest[7:], path


# Manifest layers the local count accounts for (license does not reach the prompt). Any other layer changes what
# Ollama sends to the model: a Modelfile SYSTEM is prepended when the request does not start with a system message,
# MESSAGE lines are prepended to every chat, a projector or adapter changes the model. Such models are refused.
_KNOWN_LAYERS = ("model", "template", "params", "license")


def _json_blob(b, what, tag):
    try:
        return json.loads(b)
    except ValueError:
        raise TokenizerError(f"{what} blob of {tag} is not JSON") from None


def resolve_ollama_model(tag, models_dir=None):
    """Read an Ollama manifest (read only): weights, template, params and config blobs of `tag`.

    manifest_sha256 is what /api/tags reports as the model's digest. The small blobs (template, params, config) are
    hashed and must match their names; the weights blob is hashed by LlamaCppTokenizer. A manifest with a layer
    other than model / template / params / license, or a config that names one of Ollama's built-in renderers
    (which replace the template), is refused: the local rendering would not be what the server sends.
    """
    d = models_dir or ollama_models_dir()
    host, ns, model, ver = _parse_tag(tag)
    mpath = os.path.join(d, "manifests", host, ns, model, ver)
    if not os.path.isfile(mpath):
        raise TokenizerError(f"no Ollama manifest for {tag!r} in the model store")
    with open(mpath, "rb") as f:
        raw = f.read()
    try:
        man = json.loads(raw)
    except ValueError:
        raise TokenizerError(f"manifest of {tag!r} is not JSON") from None
    layers = {}
    for layer in man.get("layers") or []:
        kind = str(layer.get("mediaType", "")).rsplit(".", 1)[-1]
        layers.setdefault(kind, []).append(layer.get("digest"))
    if len(layers.get("model") or []) != 1:
        raise TokenizerError(f"manifest of {tag!r} does not have exactly one model layer")
    other = sorted(k for k in layers if k not in _KNOWN_LAYERS)
    if other:
        raise TokenizerError(f"manifest of {tag!r} has {', '.join(other)} layer(s), which change the prompt or the "
                             "model; the local count does not reproduce them")
    out = {"tag": tag, "manifest_sha256": hashlib.sha256(raw).hexdigest()}
    out["weights_sha256"], out["weights_path"] = _blob(d, layers["model"][0], "model", tag)

    def small(digest, what):
        sha, path = _blob(d, digest, what, tag)
        with open(path, "rb") as f:
            b = f.read()
        if hashlib.sha256(b).hexdigest() != sha:
            raise TokenizerError(f"{what} blob of {tag} does not match its digest")
        return sha, b

    for kind in ("template", "params"):
        ds = layers.get(kind) or []
        if len(ds) > 1:
            raise TokenizerError(f"manifest of {tag!r} has {len(ds)} {kind} layers")
        out[kind + "_sha256"], b = small(ds[0], kind) if ds else (None, None)
        if kind == "template":
            out["template_text"] = b.decode("utf-8") if b is not None else None
        else:
            out["params"] = _json_blob(b, "params", tag) if b is not None else None
    cfg = (man.get("config") or {}).get("digest")
    out["config_sha256"], b = small(cfg, "config") if cfg else (None, None)
    config = _json_blob(b, "config", tag) if b is not None else {}
    if not isinstance(config, dict):
        raise TokenizerError(f"config blob of {tag} is not a JSON object")
    if config.get("renderer"):
        raise TokenizerError(f"{tag} is rendered by Ollama's built-in renderer {str(config['renderer'])!r}, not by "
                             "its template; there is no local port")
    out["model_family"] = config.get("model_family")
    return out


# ---------------------------------------------------------------- qwen3 chat template (Ollama)

RENDERER_QWEN3 = "qwen3-ollama-template.v1"
_ROLES = ("system", "user", "assistant", "tool")
# Go's unicode.IsSpace (the White_Space property); differs from str.isspace on U+001C..U+001F
_GO_SPACE = set("\t\n\v\f\r \x85\xa0\u1680\u2028\u2029\u202f\u205f\u3000") | {chr(c) for c in range(0x2000, 0x200B)}


def _go_lstrip(s):
    i = 0
    while i < len(s) and s[i] in _GO_SPACE:
        i += 1
    return s[i:]


def _drop_leading_think(content, open_tag="<think>", close_tag="</think>"):
    """What Ollama's thinking parser leaves as content when a finished message is fed to it: a leading
    <think>…</think> block and the whitespace after it are removed; text that is only whitespace or only the start
    of an opening tag, or a block that is never closed, leaves nothing; anything else is kept unchanged."""
    t = _go_lstrip(content)
    if t.startswith(open_tag):
        after = t[len(open_tag):]
        if close_tag not in after:
            return ""
        return _go_lstrip(after.split(close_tag, 1)[1])
    if open_tag.startswith(t):
        return ""
    return content


def _check_messages(messages):
    if not isinstance(messages, (list, tuple)):
        raise TokenizerError("messages must be a list")
    out = []
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            raise TokenizerError(f"message {i} is not an object")
        role = m.get("role")
        if role not in _ROLES:
            raise TokenizerError(f"message {i} has role {role!r}; the local renderer knows {_ROLES}")
        for k in ("images", "tool_calls", "tools"):
            if m.get(k):
                raise TokenizerError(f"message {i} carries {k}; the local renderer does not reproduce them")
        content = m.get("content")
        content = "" if content is None else content
        thinking = m.get("thinking") or ""
        _utf8(content, f"message {i} content")
        _utf8(thinking, f"message {i} thinking")
        out.append({"role": role, "content": content, "thinking": thinking})
    return out


def render_qwen3(messages, think=None, strip_history_think=True):
    """The prompt Ollama builds for /api/chat with the qwen3 template blob (sha256 ae370d88…), no tools, no images.

    think: None = the request has no "think" field; True / False = sent explicitly (the runners always send it).
    strip_history_think: Ollama's server first removes a leading <think>…</think> block from assistant messages that
    come before the last user message (filterThinkTags, qwen3 family); the number of changed messages is reported.
    Then, as Ollama's template.Execute does: system messages are joined into .System with a blank line, consecutive
    messages of one role are merged with a blank line (tool messages excepted), and the template is applied.
    Returns (prompt, info).
    """
    msgs = _check_messages(messages)
    n_stripped = 0
    if strip_history_think:
        last_user = max((i for i, m in enumerate(msgs) if m["role"] == "user"), default=-1)
        for i, m in enumerate(msgs):
            if m["role"] == "assistant" and i < last_user:
                c = _drop_leading_think(m["content"])
                if c != m["content"]:
                    m["content"] = c
                    n_stripped += 1
    system = "\n\n".join(m["content"] for m in msgs if m["role"] == "system")
    coll = []
    for m in msgs:  # collate: the merged message keeps the first message's thinking
        if coll and coll[-1]["role"] == m["role"] and m["role"] != "tool":
            coll[-1]["content"] += "\n\n" + m["content"]
        else:
            coll.append(dict(m))
    is_set, think_on = think is not None, bool(think)
    last_user = max((i for i, m in enumerate(coll) if m["role"] == "user"), default=-1)
    out = []
    if system:
        out.append("<|im_start|>system\n\n" + system + "<|im_end|>\n")
    for i, m in enumerate(coll):
        last = i == len(coll) - 1
        role = m["role"]
        if role == "user":
            s = "<|im_start|>user\n" + m["content"]
            if is_set and i == last_user:
                s += " /think" if think_on else " /no_think"
            out.append(s + "<|im_end|>\n")
        elif role == "assistant":
            s = "<|im_start|>assistant\n"
            if is_set and m["thinking"] and (last or i > last_user):
                s += "<think>" + m["thinking"] + "</think>\n"
            s += m["content"]
            out.append(s if last else s + "<|im_end|>\n")
        elif role == "tool":
            out.append("<|im_start|>user\n<tool_response>\n" + m["content"] + "\n</tool_response><|im_end|>\n")
        if role != "assistant" and last:
            out.append("<|im_start|>assistant\n" + ("<think>\n\n</think>\n\n" if is_set and not think_on else ""))
    info = {"renderer": RENDERER_QWEN3, "template_sha256": QWEN3_TEMPLATE_SHA256, "think": think,
            "history_think_stripped": n_stripped}
    return "".join(out), info


# chat templates this module has a port of: template blob sha256 -> (renderer id, function)
TEMPLATE_RENDERERS = {QWEN3_TEMPLATE_SHA256: (RENDERER_QWEN3, render_qwen3)}
# E23: template blob sha256 -> factory(resolved model, binary=) for models whose weights blob llama-tokenize cannot
# read itself (gpt-oss; orgene.tokcount_harmony fills both tables). Other models are counted over their weights blob.
TEMPLATE_TOKENIZERS = {}


# ---------------------------------------------------------------- counters (one per model)

class OllamaCounter:
    """Local counts for one Ollama model: llama-tokenize over its own weights blob and the ported chat template.

    expect_digest: the digest the server reports for the model (/api/tags); it must be the local manifest's sha256,
    i.e. the server and this counter read the same blobs. expect_weights_sha256: optional pin (e.g. qwen3:8b's).
    """

    backend = "ollama"

    def __init__(self, tag, models_dir=None, binary=None, verify="full", expect_digest=None,
                 expect_weights_sha256=None):
        m = resolve_ollama_model(tag, models_dir)
        if expect_digest is not None and expect_digest != m["manifest_sha256"]:
            raise TokenizerError(f"server digest {str(expect_digest)[:12]}… of {tag} is not the local manifest "
                                 f"{m['manifest_sha256'][:12]}…; the local tokenizer would read other blobs")
        if expect_weights_sha256 is not None and expect_weights_sha256 != m["weights_sha256"]:
            raise TokenizerError(f"weights blob of {tag} is {m['weights_sha256'][:12]}…, "
                                 f"expected {expect_weights_sha256[:12]}…")
        if m["template_sha256"] not in TEMPLATE_RENDERERS:
            raise TokenizerError(f"no local port of the chat template {str(m['template_sha256'])[:12]}… of {tag}; "
                                 "the rendered prompt cannot be counted")
        self.model = m
        self.renderer_id, self._render = TEMPLATE_RENDERERS[m["template_sha256"]]
        self.strip_history_think = m.get("model_family") == "qwen3"
        make_tok = TEMPLATE_TOKENIZERS.get(m["template_sha256"])  # E23: gpt-oss reads a derived tokenizer file
        self.tok = make_tok(m, binary=binary) if make_tok else \
            LlamaCppTokenizer(m["weights_path"], m["weights_sha256"], binary=binary, verify=verify)
        self._identity = {
            "backend": self.backend, "model": tag, "manifest_sha256": m["manifest_sha256"],
            "weights_sha256": m["weights_sha256"], "template_sha256": m["template_sha256"],
            "model_family": m.get("model_family"), "renderer": self.renderer_id,
            "strip_history_think": self.strip_history_think, "tokenizer": self.tok.identity()}
        self.identity_sha256 = identity_sha256(self._identity)

    def identity(self):
        return dict(self._identity)

    def count(self, text):
        """A message body or a completion: special-token text is not parsed, no BOS."""
        return self.tok.count(text, parse_special=False, model_bos=False)

    def render(self, messages, think):
        return self._render(messages, think=think, strip_history_think=self.strip_history_think)

    def count_prompt(self, messages, think):
        """(tokens of the rendered prompt, render info): what prompt_eval_count should be."""
        prompt, info = self.render(messages, think)
        return self.tok.count(prompt, parse_special=True, model_bos=True), info

    def local_tokens(self, messages, completion, think, thinking=None):
        """The per-call record: local counts for what was sent and what came back."""
        n_prompt, info = self.count_prompt(messages, think)
        by_msg = [self.count(m.get("content") or "") for m in messages]
        out = {"schema": SCHEMA, "tokenizer_sha256": self.identity_sha256,
               "content_by_message": by_msg, "content_total": sum(by_msg),
               "rendered_prompt": n_prompt, "think": think,
               "history_think_stripped": info["history_think_stripped"],
               "completion": self.count(completion or ""), "completion_thinking": self.count(thinking or "")}
        if "current_date" in info:  # E23: the date the gpt-oss template wrote into the prompt
            out["current_date"] = info["current_date"]
        return out


_TIKTOKEN_HELPER = r'''
import base64, hashlib, json, os, sys
os.environ["TIKTOKEN_CACHE_DIR"] = ""  # tiktoken must neither read nor write its download cache
req = json.loads(sys.stdin.read())
out = {"ok": False}
try:
    import tiktoken
    import tiktoken.load as tl
    import tiktoken_ext.openai_public as op
except Exception as e:
    out["error"] = "import tiktoken failed: %s: %s" % (type(e).__name__, e)
    print(json.dumps(out)); sys.exit(0)
out["tiktoken_version"] = getattr(tiktoken, "__version__", None)
try:
    def _no_network(*a, **k):
        raise RuntimeError("tiktoken tried to fetch a file; only the registered local encoding file may be used")
    for name in ("read_file", "read_file_cached"):
        if hasattr(tl, name):
            setattr(tl, name, _no_network)
    op.data_gym_to_mergeable_bpe_ranks = _no_network
    with open(req["encoding_file"], "rb") as f:
        data = f.read()
    got = hashlib.sha256(data).hexdigest()
    if got != req["sha256"]:
        raise ValueError("encoding file sha256 %s is not the registered %s" % (got[:12], req["sha256"][:12]))
    ranks = {}
    for line in data.splitlines():
        if line.strip():
            tok, rank = line.split()
            ranks[base64.b64decode(tok)] = int(rank)
    used = []
    def _local(blobpath, expected_hash=None):
        if expected_hash is not None and expected_hash != got:
            raise ValueError("the local encoding file is not the file tiktoken expects for this encoding")
        used.append(1)
        return ranks
    op.load_tiktoken_bpe = _local
    ctors = getattr(op, "ENCODING_CONSTRUCTORS", {})
    if req["encoding"] not in ctors:
        raise ValueError("unknown encoding %r" % req["encoding"])
    enc = tiktoken.Encoding(**ctors[req["encoding"]]())
    if not used:
        raise ValueError("encoding %r was not built from the local file" % req["encoding"])
    out["encoding"] = enc.name
    out["n_vocab"] = enc.n_vocab
    out["counts"] = [len(enc.encode(t, disallowed_special=())) for t in req["texts"]]
    out["ok"] = True
except Exception as e:
    out["error"] = "%s: %s" % (type(e).__name__, e)
print(json.dumps(out))
'''


class TiktokenCounter:
    """Local counts for an OpenAI model: tiktoken over a registered local encoding file, in a separate interpreter.

    model: the dated snapshot id (recorded only). encoding: e.g. 'o200k_base'. encoding_file / sha256: the local
    .tiktoken file and its registered hash (E19). python: interpreter with tiktoken (default .venv-tools, or
    $ORGENE_TOOLS_PY). Special-token text in a message is counted as ordinary text (disallowed_special=()).
    """

    backend = "openai"

    def __init__(self, model, encoding, encoding_file, sha256, python=None, timeout=300):
        self.python = python or os.environ.get(ENV_TOOLS_PY) or DEFAULT_TOOLS_PY
        if not (os.path.isfile(self.python) and os.access(self.python, os.X_OK)):
            raise TokenizerError(f"interpreter with tiktoken not found: {rel(self.python)} "
                                 f"(create .venv-tools or set {ENV_TOOLS_PY})")
        if not isinstance(sha256, str) or not _HEX64.fullmatch(sha256):
            raise TokenizerError("the encoding file's registered sha256 (64 lowercase hex digits) is required")
        if not os.path.isfile(encoding_file):
            raise TokenizerError(f"tiktoken encoding file not found: {rel(encoding_file)}")
        if not isinstance(encoding, str) or not re.fullmatch(r"[a-z0-9_]+", encoding):
            raise TokenizerError(f"bad encoding name {encoding!r}")
        self.model, self.encoding, self.encoding_file, self.sha256 = model, encoding, encoding_file, sha256
        self.timeout = timeout
        self._cache = {}
        probe = self._run([])
        self._identity = {"backend": self.backend, "model": model, "tokenizer": {
            "kind": "tiktoken", "version": probe.get("tiktoken_version"), "encoding": probe.get("encoding"),
            "n_vocab": probe.get("n_vocab"), "encoding_sha256": sha256}}
        self.identity_sha256 = identity_sha256(self._identity)

    def _run(self, texts):
        payload = json.dumps({"encoding": self.encoding, "encoding_file": os.path.abspath(self.encoding_file),
                              "sha256": self.sha256, "texts": texts}, ensure_ascii=True)
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "TIKTOKEN_CACHE_DIR": ""}
        try:
            p = subprocess.run([self.python, "-I", "-c", _TIKTOKEN_HELPER], input=payload.encode("utf-8"),
                               capture_output=True, timeout=self.timeout, env=env)
        except (OSError, subprocess.SubprocessError) as e:
            raise TokenizerError(f"tiktoken helper failed to run: {type(e).__name__}") from None
        lines = [ln for ln in p.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
        try:
            res = json.loads(lines[-1])
        except (IndexError, ValueError):
            raise TokenizerError(f"tiktoken helper gave no result (rc={p.returncode}): {_tail(p.stderr)}") from None
        if not res.get("ok"):
            raise TokenizerError(f"tiktoken: {_scrub(res.get('error'))}")
        if len(res.get("counts") or []) != len(texts):
            raise TokenizerError("tiktoken helper returned the wrong number of counts")
        return res

    def identity(self):
        return json.loads(json.dumps(self._identity))

    def counts(self, texts):
        """Counts for many texts with one helper process (uncached texts only)."""
        keys = [sha256_text(t) for t in texts]
        todo = sorted({k: t for k, t in zip(keys, texts) if k not in self._cache}.items())
        if todo:
            got = self._run([t for _, t in todo])["counts"]
            self._cache.update({k: n for (k, _), n in zip(todo, got)})
        return [self._cache[k] for k in keys]

    def count(self, text):
        return self.counts([text])[0]

    def count_prompt(self, messages, think=None):
        raise TokenizerError("the provider's chat framing is not public; compare reported prompt tokens with "
                             "content_total instead")

    def local_tokens(self, messages, completion, think=None, thinking=None):
        texts = [(m.get("content") or "") for m in messages]
        n = self.counts(texts + [completion or "", thinking or ""])
        return {"schema": SCHEMA, "tokenizer_sha256": self.identity_sha256,
                "content_by_message": n[:-2], "content_total": sum(n[:-2]),
                "rendered_prompt": None, "rendered_prompt_note": "provider chat framing not public",
                "think": think, "history_think_stripped": 0, "completion": n[-2], "completion_thinking": n[-1]}


def counter_for(backend, model, **kw):
    """The local counter for a (backend, model). Raises TokenizerError when there is no offline tokenizer."""
    if backend == "ollama":
        return OllamaCounter(model, **kw)
    if backend == "openai":
        return TiktokenCounter(model, **kw)
    raise TokenizerError(f"no offline tokenizer for backend {backend!r} (Q4: choose a model whose tokenizer is public)")


# ---------------------------------------------------------------- command line

def main(argv=None):
    """python3 -m orgene.tokcount {identity|count|prompt} --model qwen3:8b  (run with runtime/ on sys.path)

    identity  print the counter identity (hashes, llama-tokenize version)
    count     count stdin as one message body
    prompt    stdin is a JSON list of messages; print the rendered-prompt count (--think / --no-think /
              --think-level low|medium|high (gpt-oss) / none of them)
    """
    import argparse
    ap = argparse.ArgumentParser(prog="orgene.tokcount", description=main.__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["identity", "count", "prompt"])
    ap.add_argument("--model", default="qwen3:8b")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--think", dest="think", action="store_true", default=None)
    g.add_argument("--no-think", dest="think", action="store_false", default=None)
    g.add_argument("--think-level", dest="think", choices=("low", "medium", "high"), default=None)  # E23: gpt-oss
    a = ap.parse_args(argv)
    # the imported module, not a `python -m` copy of it: the gpt-oss port registers itself there (E23)
    T = importlib.import_module(f"{__package__}.tokcount") if __package__ else sys.modules[__name__]
    try:
        c = T.OllamaCounter(a.model)
        if a.what == "identity":
            print(json.dumps(c.identity(), indent=2))
        elif a.what == "count":
            print(c.count(sys.stdin.read()))
        else:
            n, info = c.count_prompt(json.loads(sys.stdin.read()), a.think)
            print(json.dumps(dict(info, rendered_prompt=n)))
    except T.TokenizerError as e:
        print(f"[tokcount] {e}", file=sys.stderr)
        return 2
    return 0


# E23: the gpt-oss port (harmony template, tokenizer file derived from the weights blob) registers itself in
# TEMPLATE_RENDERERS / TEMPLATE_TOKENIZERS; imported last because it builds on the classes above.
from . import tokcount_harmony  # noqa: E402,F401

if __name__ == "__main__":
    sys.exit(main())

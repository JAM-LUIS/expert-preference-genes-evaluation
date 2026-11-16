"""Local token counts for gpt-oss served by Ollama (E23): the harmony prompt as Ollama renders it, counted with the
model's vocabulary. Registers itself with orgene.tokcount, so `tokcount.OllamaCounter(<gpt-oss tag>)` works wherever
the qwen3 counter does (runners, the unit executor, the repair budget check).

How the server handles a /api/chat request for gpt-oss (observed on the host, Ollama 0.33.0):
  1. Ollama renders the chat with the model's Go template: a harmony system message with a fixed preamble, a date
     ("Current date: YYYY-MM-DD") and a "Reasoning: <level>" line; our system prompt becomes the developer message
     ("# Instructions"); then the user / assistant turns.
  2. The prompt text goes to Ollama's bundled llama-server (llama.cpp build 10488), which on load logs
     "handle_gptoss: detected Ollama-format gpt-oss GGUF; applying compatibility fixes" and then runs with
     general.architecture = gpt-oss and tokenizer.ggml.pre = gpt-4o over the blob's own vocabulary; special tokens in
     the prompt are parsed.
  3. The model answers in harmony channels; Ollama returns the analysis channel as message.thinking and the final
     channel as message.content. eval_count counts both plus 10 tokens of channel markup (<|channel|>analysis
     <|message|> ... <|end|><|start|>assistant<|channel|>final<|message|> ... <|return|>) for a finished answer.

Templates (both ported by render_gptoss, tested against Go text/template output, tools/gptoss_template_ref):
  gpt-oss:20b                    blob fa6710a9...: the date is the server's local date ({{ currentDate }}), so the prompt
                                 text changes at midnight (the count does not: every YYYY-MM-DD is the same tokens).
  gpt-oss-20b-date20260929       blob 5dc90082...: the same template with the date fixed to 2026-09-29
                                 (configs/ollama/gpt-oss-20b-date20260929.Modelfile). The study's entry uses it, so the
                                 prompt is the same on every day of the dev and test runs.

Tokenizers (ORGENE_GPTOSS_TOKENIZER selects; the choice is part of the counter identity):
  tiktoken        (default) o200k_harmony from the pinned tiktoken in .venv-tools, built from the registered
                  o200k_base file (configs/venv_tools.json; $ORGENE_TIKTOKEN_DIR names another directory with the same
                  file, $ORGENE_TOOLS_PY another interpreter), in one helper process per counter; it never downloads.
                  Checked for this weights blob (tools/gptoss_tokenizer_check.py): the blob's vocabulary is
                  o200k_harmony id for id, and the server's own token ids (/api/generate context) equal it on our
                  prompts.
  llama-tokenize  E09's wrapper over a tokenizer-only GGUF derived from the weights blob with the server's two fixes
                  (orgene.gguf_vocab; sha256 pinned per blob, cached in .cache/gguf-vocab/ or $ORGENE_GGUF_VOCAB_DIR).
                  llama-tokenize cannot read the blob itself ("unknown model architecture: 'gptoss'"; --override-kv
                  does not reach the architecture key).
Content counts (message bodies, completion, thinking) treat special-token text as text; the rendered prompt parses
special tokens, as the server does.

think (request field; Ollama 0.33 accepts true, false, "low", "medium", "high", "max" and answers 400 to anything
else). With this template: a level writes "Reasoning: <level>"; true or no field writes "Reasoning: medium"; false
removes the line. false does not switch reasoning off: the model still writes an analysis channel (returned as
thinking), with the effort left unspecified. The study sends "low" (registry entry gptoss-20b.main).
"""
import atexit
import json
import os
import re
import subprocess
import weakref
from datetime import datetime

from . import gguf_vocab as GV
from . import tokcount as T
from .paths import ROOT, rel

# gpt-oss:20b as pulled into Ollama (the model registry keeps the same values)
GPTOSS_MANIFEST_SHA256 = "17052f91a42e97930aa6e28a6c6c06a983e6a58dbb00434885a0cf5313e376f7"  # Ollama "digest"
GPTOSS_WEIGHTS_SHA256 = "e7b273f9636059a689e3ddcab3716e4f65abe0143ac978e46673ad0e52d09efb"
GPTOSS_TEMPLATE_SHA256 = "fa6710a93d78da62641e192361344be7a8c0a1c3737f139cf89f20ce1626b99c"
# the fixed-date alias (same weights blob; template = the one above with {{ currentDate }} -> FIXED_DATE)
ALIAS_TAG = "gpt-oss-20b-date20260929:latest"
FIXED_DATE = "2026-09-29"
ALIAS_TEMPLATE_SHA256 = "5dc90082f15d02604c27bdcf974d45f68d003c46cee76249d9cb4f607825c64c"
# template blob sha256 -> the date it writes (None: the server's local date)
GPTOSS_TEMPLATES = {GPTOSS_TEMPLATE_SHA256: None, ALIAS_TEMPLATE_SHA256: FIXED_DATE}
RENDERER_GPTOSS = "gptoss-ollama-template.v1"
THINK_LEVELS = ("low", "medium", "high")

ENV_TOKENIZER = "ORGENE_GPTOSS_TOKENIZER"
TOKENIZERS = ("tiktoken", "llama-tokenize")
DEFAULT_TOKENIZER = "tiktoken"

# tiktoken: the weights blobs whose vocabulary was compared with o200k_harmony id for id (tools/gptoss_tokenizer_check)
TIKTOKEN_ENCODING = "o200k_harmony"
TIKTOKEN_FILE_ENCODING = "o200k_base"  # o200k_harmony = o200k_base's ranks and pattern + the harmony special tokens
TIKTOKEN_N_VOCAB = 201088
TIKTOKEN_VERIFIED_BLOBS = (GPTOSS_WEIGHTS_SHA256,)
ENV_TIKTOKEN_DIR = "ORGENE_TIKTOKEN_DIR"
VENV_TOOLS_RECORD = os.path.join(ROOT, "configs", "venv_tools.json")

# llama-tokenize: the fix Ollama's llama-server applies to its gpt-oss blob, as a recipe for gguf_vocab
VOCAB_RECIPE = {"id": "ollama-gptoss-compat.v1", "architecture": "gpt-oss",
                "overrides": {"tokenizer.ggml.pre": "gpt-4o"}}
# weights blob sha256 -> sha256 of the tokenizer-only GGUF derived with VOCAB_RECIPE (a blob not listed has no
# verified derivation and is refused)
DERIVED_VOCAB_SHA256 = {
    GPTOSS_WEIGHTS_SHA256: "e200fbaa17b087d350b08a3fae9e166e31c6c04b4fe5cbb57e26b82e7901fcbb",
}
ENV_VOCAB_DIR = "ORGENE_GGUF_VOCAB_DIR"
DEFAULT_VOCAB_DIR = os.path.join(ROOT, ".cache", "gguf-vocab")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HEAD = ("<|start|>system<|message|>You are ChatGPT, a large language model trained by OpenAI.\n"
         "Knowledge cutoff: 2024-06\nCurrent date: ")
_CHANNELS = "\n\n# Valid channels: analysis, commentary, final. Channel must be included for every message.<|end|>"
# channel markup the model writes around a finished answer, counted in eval_count (see the module docstring)
COMPLETION_MARKUP_TOKENS = 10


def local_date():
    """This host's local date, YYYY-MM-DD (what the template's currentDate gives on a server running here)."""
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def think_vars(think):
    """The request's think field -> the template's (IsThinkSet, Think, ThinkLevel)."""
    if think is None:
        return False, False, ""
    if isinstance(think, bool):
        return True, think, ""
    if isinstance(think, str) and think in THINK_LEVELS:
        return True, True, think
    raise T.TokenizerError(f"think must be absent, true, false or one of {THINK_LEVELS}, got {think!r}")


def reasoning_line(think):
    """The level the system message states ('low' / 'medium' / 'high'), or None when think is false (no line)."""
    is_set, on, level = think_vars(think)
    if is_set and on and level:
        return level
    if not is_set or on:
        return "medium"
    return None


def render_gptoss(messages, think=None, strip_history_think=False, current_date=None):
    """The prompt Ollama builds for /api/chat with the gpt-oss template (blob fa6710a9...), no tools, no images.

    think: None = the request has no "think" field; True / False / a level = sent explicitly.
    current_date: the date the template writes (YYYY-MM-DD); default this host's local date.
    As Ollama's template.Execute does: system messages are joined into .System with a blank line (they become the
    developer message), consecutive messages of one role are merged with a blank line, and the template is applied:
    an assistant message's thinking is written only after the last user message; a conversation that ends with an
    assistant message is continued (prefill) instead of opening a new assistant turn.
    strip_history_think is accepted for the OllamaCounter interface; this template needs no think-tag filter.
    Returns (prompt, info).
    """
    msgs = T._check_messages(messages)
    for i, m in enumerate(msgs):
        if m["role"] == "tool":
            raise T.TokenizerError(f"message {i} is a tool message; the gpt-oss port does not render tool turns")
    date = current_date if current_date is not None else local_date()
    if not isinstance(date, str) or not _DATE_RE.match(date):
        raise T.TokenizerError(f"current_date must be YYYY-MM-DD, got {date!r}")
    level = reasoning_line(think)
    system = "\n\n".join(m["content"] for m in msgs if m["role"] == "system")
    coll = []
    for m in msgs:  # collate: the merged message keeps the first message's thinking
        if coll and coll[-1]["role"] == m["role"]:
            coll[-1]["content"] += "\n\n" + m["content"]
        else:
            coll.append(dict(m))
    out = [_HEAD, date]
    if level is not None:
        out.append("\n\nReasoning: " + level)
    out.append(_CHANNELS)
    if system:
        out.append("<|start|>developer<|message|>\n\n# Instructions\n\n" + system + "<|end|>")
    last_user = max((i for i, m in enumerate(coll) if m["role"] == "user"), default=-1)
    tail = coll[-1] if coll else None
    prefill_content = bool(tail and tail["role"] == "assistant" and tail["content"])
    prefill_thinking = bool(tail and tail["role"] == "assistant" and not prefill_content and tail["thinking"])
    for i, m in enumerate(coll):
        if m["role"] == "assistant":
            if m["thinking"] and i > last_user:
                out.append("<|start|>assistant<|channel|>analysis<|message|>" + m["thinking"]
                           + ("" if prefill_thinking else "<|end|>"))
            if m["content"]:
                out.append("<|start|>assistant<|channel|>final<|message|>" + m["content"]
                           + ("" if prefill_content else "<|end|>"))
        elif m["role"] == "user":
            out.append("<|start|>user<|message|>" + m["content"] + "<|end|>")
    if not (prefill_content or prefill_thinking):
        out.append("<|start|>assistant")
    info = {"renderer": RENDERER_GPTOSS, "template_sha256": GPTOSS_TEMPLATE_SHA256, "think": think,
            "history_think_stripped": 0, "current_date": date, "reasoning_line": level}
    return "".join(out), info


def fixed_date_renderer(template_sha256, date):
    """render_gptoss for a template whose date is a constant (the alias): the date cannot be chosen by the caller."""
    def render(messages, think=None, strip_history_think=False, current_date=None):
        if current_date not in (None, date):
            raise T.TokenizerError(f"template {template_sha256[:12]}… writes the date {date}, not {current_date}")
        prompt, info = render_gptoss(messages, think=think, strip_history_think=strip_history_think, current_date=date)
        info["template_sha256"] = template_sha256
        return prompt, info
    render.fixed_date = date
    return render


# ---------------------------------------------------------------- tokenizer: tiktoken (default)

_HELPER = r'''
import base64, hashlib, json, os, sys
os.environ["TIKTOKEN_CACHE_DIR"] = ""  # tiktoken must neither read nor write its download cache
def reply(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()
init = json.loads(sys.stdin.readline())
out = {"ok": False}
try:
    import tiktoken
    import tiktoken.load as tl
    import tiktoken_ext.openai_public as op
except Exception as e:
    out["error"] = "import tiktoken failed: %s: %s" % (type(e).__name__, e); reply(out); sys.exit(0)
out["tiktoken_version"] = getattr(tiktoken, "__version__", None)
try:
    def _no_network(*a, **k):
        raise RuntimeError("tiktoken tried to fetch a file; only the registered local encoding file may be used")
    for name in ("read_file", "read_file_cached"):
        if hasattr(tl, name):
            setattr(tl, name, _no_network)
    op.data_gym_to_mergeable_bpe_ranks = _no_network
    with open(init["encoding_file"], "rb") as f:
        data = f.read()
    got = hashlib.sha256(data).hexdigest()
    if got != init["sha256"]:
        raise ValueError("encoding file sha256 %s is not the registered %s" % (got[:12], init["sha256"][:12]))
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
    if init["encoding"] not in ctors:
        raise ValueError("unknown encoding %r" % init["encoding"])
    enc = tiktoken.Encoding(**ctors[init["encoding"]]())
    if not used:
        raise ValueError("encoding %r was not built from the local file" % init["encoding"])
    out.update({"ok": True, "encoding": enc.name, "n_vocab": enc.n_vocab})
except Exception as e:
    out["error"] = "%s: %s" % (type(e).__name__, e)
reply(out)
if not out["ok"]:
    sys.exit(0)
for line in sys.stdin:
    try:
        req = json.loads(line)
        res = []
        for text, special in req["items"]:
            ids = enc.encode(text, allowed_special="all") if special else enc.encode(text, disallowed_special=())
            res.append(ids if req.get("ids") else len(ids))
        reply({"ok": True, "results": res})
    except Exception as e:
        reply({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})
'''


# The only vocabulary entries whose text differs between the blob and o200k_harmony: the unused reserved ids from
# 200019 on are '[PADk]' in the blob (user-defined: llama.cpp reads that text as one token anywhere) and
# '<|reserved_N|>' in tiktoken, and tiktoken also reads '<|reserved_200018|>' as id 200018, which the blob only names
# '<|endofprompt|>' (tools/gptoss_tokenizer_check.py vocab). A prompt with such text would be counted differently
# from the server, so the tiktoken counter refuses it instead of returning a wrong number.
_DIVERGENT = re.compile(r"\[PAD\d+\]|<\|reserved_(\d+)\|>")


def server_divergent_text(text):
    """The first text in `text` that the server and o200k_harmony tokenize differently, or None."""
    for m in _DIVERGENT.finditer(text):
        if m.group(1) is None or int(m.group(1)) >= 200018:
            return m.group(0)
    return None


def registered_encoding(name=TIKTOKEN_FILE_ENCODING, record=None):
    """(path, sha256) of a tiktoken encoding file registered in configs/venv_tools.json. $ORGENE_TIKTOKEN_DIR names a
    directory that holds the same file (a worktree has no .cache/ of its own)."""
    try:
        with open(record or VENV_TOOLS_RECORD, "r", encoding="utf-8") as f:
            rec = json.load(f)
        e = rec["tiktoken"]["encodings"][name]
        path, sha = e["file"], e["sha256"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise T.TokenizerError(f"encoding {name} is not registered in {rel(record or VENV_TOOLS_RECORD)}: "
                               f"{type(e).__name__}") from None
    d = os.environ.get(ENV_TIKTOKEN_DIR)
    return (os.path.join(d, os.path.basename(path)) if d else os.path.join(ROOT, path)), sha


def _stop(proc):
    try:
        if proc.poll() is None:
            proc.stdin.close()
            proc.wait(timeout=10)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


class HarmonyTiktokenTokenizer:
    """o200k_harmony token ids and counts through tiktoken in a separate interpreter (one helper process per instance).

    count(text, parse_special=False, model_bos=False): the E09 tokenizer interface. parse_special=False counts
    special-token text as text; True parses the harmony special tokens (a rendered prompt). gpt-oss adds no BOS, so
    model_bos changes nothing. Counts are cached by (sha256 of the text, mode)."""

    kind = "tiktoken"

    def __init__(self, encoding_file=None, sha256=None, python=None, encoding=TIKTOKEN_ENCODING):
        self.python = python or os.environ.get(T.ENV_TOOLS_PY) or T.DEFAULT_TOOLS_PY
        if not (os.path.isfile(self.python) and os.access(self.python, os.X_OK)):
            raise T.TokenizerError(f"interpreter with tiktoken not found: {rel(self.python)} "
                                   f"(create .venv-tools or set {T.ENV_TOOLS_PY})")
        if encoding_file is None:
            encoding_file, reg_sha = registered_encoding()
            sha256 = sha256 or reg_sha
        if not isinstance(sha256, str) or not T._HEX64.fullmatch(sha256):
            raise T.TokenizerError("the encoding file's registered sha256 (64 lowercase hex digits) is required")
        if not os.path.isfile(encoding_file):
            raise T.TokenizerError(f"tiktoken encoding file not found: {rel(encoding_file)} (set {ENV_TIKTOKEN_DIR} "
                                   "to a directory with the registered file)")
        self.encoding, self.encoding_file, self.sha256 = encoding, encoding_file, sha256
        self._cache = {}
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "TIKTOKEN_CACHE_DIR": "",
               "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            self._proc = subprocess.Popen([self.python, "-I", "-c", _HELPER], stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                          text=True, encoding="utf-8")
        except OSError as e:
            raise T.TokenizerError(f"tiktoken helper failed to start: {type(e).__name__}") from None
        weakref.finalize(self, _stop, self._proc)
        atexit.register(_stop, self._proc)
        init = self._ask({"encoding": encoding, "encoding_file": os.path.abspath(encoding_file), "sha256": sha256})
        if init.get("n_vocab") != TIKTOKEN_N_VOCAB and encoding == TIKTOKEN_ENCODING:
            raise T.TokenizerError(f"{encoding} has {init.get('n_vocab')} tokens, expected {TIKTOKEN_N_VOCAB}")
        self.version, self.n_vocab = init.get("tiktoken_version"), init.get("n_vocab")

    def _ask(self, obj):
        try:
            self._proc.stdin.write(json.dumps(obj, ensure_ascii=True) + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
        except (OSError, ValueError):
            line = ""
        if not line:
            err = ""
            try:
                err = self._proc.stderr.read()[-300:] if self._proc.poll() is not None else ""
            except Exception:  # noqa: BLE001
                pass
            raise T.TokenizerError(f"tiktoken helper stopped: {T._scrub(err.strip())}")
        try:
            res = json.loads(line)
        except ValueError:
            raise T.TokenizerError("tiktoken helper gave no result") from None
        if not res.get("ok"):
            raise T.TokenizerError(f"tiktoken: {T._scrub(str(res.get('error')))}")
        return res

    def _items(self, items, ids=False):
        payload = []
        for text, special in items:
            T._utf8(text)
            if special:
                hit = server_divergent_text(text)
                if hit:
                    raise T.TokenizerError(f"the prompt contains {hit!r}, which the server tokenizes differently "
                                           "(unused reserved token names differ between the blob and o200k_harmony)")
            payload.append([text, bool(special)])
        res = self._ask({"items": payload, "ids": ids})["results"]
        if len(res) != len(payload):
            raise T.TokenizerError("tiktoken helper returned the wrong number of results")
        return res

    def ids(self, text, parse_special=False, model_bos=False):
        return self._items([(text, parse_special)], ids=True)[0]

    def counts(self, items):
        """Counts for many (text, parse_special) pairs with one round trip (uncached ones only)."""
        keys = [(T.sha256_text(t), bool(s)) for t, s in items]
        todo = {}
        for k, (t, s) in zip(keys, items):
            if k not in self._cache:
                todo[k] = (t, s)
        if todo:
            got = self._items(list(todo.values()))
            self._cache.update(zip(todo.keys(), got))
        return [self._cache[k] for k in keys]

    def count(self, text, parse_special=False, model_bos=False):
        if text == "":
            return 0
        return self.counts([(text, parse_special)])[0]

    def identity(self):
        return {"kind": self.kind, "version": self.version, "encoding": self.encoding, "n_vocab": self.n_vocab,
                "encoding_file": TIKTOKEN_FILE_ENCODING, "encoding_sha256": self.sha256,
                "modes": {"content": "special-token text as text", "prompt": "special tokens parsed"},
                "verified_against": getattr(self, "verified_against", None)}

    def close(self):
        _stop(self._proc)


# ---------------------------------------------------------------- tokenizer: llama-tokenize over a derived file

def vocab_dir():
    return os.environ.get(ENV_VOCAB_DIR) or DEFAULT_VOCAB_DIR


def derived_vocab(weights_path, weights_sha256, cache_dir=None):
    """(path, sha256) of the tokenizer-only GGUF for this weights blob, derived with VOCAB_RECIPE.

    The blob must be one whose derivation is pinned (DERIVED_VOCAB_SHA256) and must be the store's file of that name.
    An existing cached file is used only if its sha256 is the pinned one; otherwise the file is derived again from the
    blob's header and must hash to the pinned value before it is written."""
    expected = DERIVED_VOCAB_SHA256.get(weights_sha256)
    if expected is None:
        raise T.TokenizerError(f"no verified tokenizer derivation for the weights blob {str(weights_sha256)[:12]}…; "
                               "check it first (tools/gptoss_tokenizer_check.py) and pin it in DERIVED_VOCAB_SHA256")
    if os.path.basename(weights_path) != "sha256-" + weights_sha256:
        raise T.TokenizerError(f"{rel(weights_path)} is not the blob sha256-{weights_sha256[:12]}…")
    d = cache_dir or vocab_dir()
    path = os.path.join(d, f"gpt-oss.{weights_sha256[:16]}.{VOCAB_RECIPE['id']}.gguf")
    if os.path.isfile(path) and T.sha256_file(path) == expected:
        return path, expected
    try:
        header = GV.read_kv(weights_path)
        data = GV.vocab_only_bytes(header, VOCAB_RECIPE["architecture"], VOCAB_RECIPE["overrides"])
    except (OSError, GV.GGUFError) as e:
        raise T.TokenizerError(f"cannot derive the tokenizer file from {rel(weights_path)}: {type(e).__name__}: {e}") from None
    got = GV.sha256_bytes(data)
    if got != expected:
        raise T.TokenizerError(f"derived tokenizer file sha256 {got[:12]}… is not the pinned {expected[:12]}…")
    try:
        GV.write_atomic(path, data)
    except OSError as e:
        raise T.TokenizerError(f"cannot write the derived tokenizer file under {rel(d)}: {type(e).__name__}") from None
    return path, expected


class DerivedVocabTokenizer(T.LlamaCppTokenizer):
    """llama-tokenize over the tokenizer-only GGUF derived from an Ollama gpt-oss weights blob."""

    kind = "llama.cpp/llama-tokenize (tokenizer-only GGUF derived from the weights blob)"

    def __init__(self, weights_path, weights_sha256, binary=None, cache_dir=None, timeout=300):
        path, sha = derived_vocab(weights_path, weights_sha256, cache_dir)
        super().__init__(path, sha, binary=binary, verify="full", timeout=timeout)
        self.derived_from = {"weights_sha256": weights_sha256, "recipe": VOCAB_RECIPE}

    def identity(self):
        d = super().identity()
        d["derived_from"] = self.derived_from
        return d


# ---------------------------------------------------------------- registration with orgene.tokcount

def tokenizer_choice():
    v = os.environ.get(ENV_TOKENIZER) or DEFAULT_TOKENIZER
    if v not in TOKENIZERS:
        raise T.TokenizerError(f"{ENV_TOKENIZER} must be one of {TOKENIZERS}, got {v!r}")
    return v


def gptoss_tokenizer(model_info, binary=None):
    """TEMPLATE_TOKENIZERS factory: the tokenizer for a resolved gpt-oss model (tokcount.resolve_ollama_model)."""
    if model_info.get("model_family") not in ("gptoss", "gpt-oss"):
        raise T.TokenizerError(f"{model_info.get('tag')} uses a gpt-oss template but its family is "
                               f"{model_info.get('model_family')!r}")
    choice = tokenizer_choice()
    if choice == "llama-tokenize":
        return DerivedVocabTokenizer(model_info["weights_path"], model_info["weights_sha256"], binary=binary)
    if model_info["weights_sha256"] not in TIKTOKEN_VERIFIED_BLOBS:
        raise T.TokenizerError(f"the weights blob {model_info['weights_sha256'][:12]}… of {model_info.get('tag')} was "
                               f"not checked against {TIKTOKEN_ENCODING} (tools/gptoss_tokenizer_check.py vocab)")
    tok = HarmonyTiktokenTokenizer()
    tok.verified_against = {"weights_sha256": model_info["weights_sha256"], "check": "vocab: every id equal"}
    return tok


for _sha, _date in GPTOSS_TEMPLATES.items():
    T.TEMPLATE_RENDERERS[_sha] = (RENDERER_GPTOSS,
                                  render_gptoss if _date is None else fixed_date_renderer(_sha, _date))
    T.TEMPLATE_TOKENIZERS[_sha] = gptoss_tokenizer

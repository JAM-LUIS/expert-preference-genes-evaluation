"""E09 local tokenizer counts (runtime/orgene/tokcount.py) and where they are used.

Most tests use a fake llama-tokenize, a fake Ollama model store and a fake tiktoken built in tmp_path. The tests
marked "real" need llama-tokenize and the qwen3:8b blob in the local Ollama store and are skipped without them; the
Ollama integration test calls the model once and runs only with ORGENE_OLLAMA_TESTS=1 (dev rehearsal). Only
synthetic text and data/smoke are used.
"""
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import conditions as C  # noqa: E402
from orgene import tokcount as T  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
TEMPLATE_FIXTURE = os.path.join(FIX, "qwen3_ollama_template.gotmpl")
GO_REF = json.load(open(os.path.join(FIX, "qwen3_template_go_reference.json"), encoding="utf-8"))
SMOKE = [json.loads(ln) for ln in open(os.path.join(ROOT, "data", "smoke", "smoke_raw.jsonl"), encoding="utf-8")
         if ln.strip()]


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- fakes

FAKE_TOKENIZE = r'''#!{python}
import json, os, sys
SPECIAL = {"<|im_start|>": 151644, "<|im_end|>": 151645}
USER_DEFINED = {"<think>": 151667, "</think>": 151668}
args = sys.argv[1:]
if os.environ.get("FAKE_TOK_LOG"):
    with open(os.environ["FAKE_TOK_LOG"], "a") as f:
        f.write(json.dumps(args) + "\n")
if "--version" in args:
    print("version: 0.0.0 (build 0, commit fake)", file=sys.stderr)
    sys.exit(0)
mode = os.environ.get("FAKE_TOK_MODE", "")
if mode == "fail":
    print("tokenizer exploded", file=sys.stderr)
    sys.exit(3)
if mode == "garbage":
    print("not a list of ids")
    sys.exit(0)
for need in ("-m", "--stdin", "--ids", "--no-escape"):
    if need not in args:
        print("missing " + need, file=sys.stderr)
        sys.exit(9)
if not os.path.isfile(args[args.index("-m") + 1]):
    sys.exit(1)
text = sys.stdin.buffer.read().decode("utf-8")
table = dict(USER_DEFINED)
if "--no-parse-special" not in args:
    table.update(SPECIAL)
ids, i = [], 0
while i < len(text):
    for tok, tid in table.items():
        if text.startswith(tok, i):
            ids.append(tid)
            i += len(tok)
            break
    else:
        ids.extend(text[i].encode("utf-8"))
        i += 1
print(json.dumps(ids))
'''


def fake_count(text, parse_special=False):
    """What the fake tokenizer returns: one id per UTF-8 byte, tag text as one id."""
    table = ["<think>", "</think>"] + (["<|im_start|>", "<|im_end|>"] if parse_special else [])
    n, i = 0, 0
    while i < len(text):
        tok = next((t for t in table if text.startswith(t, i)), None)
        if tok:
            n, i = n + 1, i + len(tok)
        else:
            n, i = n + len(text[i].encode("utf-8")), i + 1
    return n


def write_exe(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def make_store(root, tag="fakeqwen:8b", weights=b"GGUF fake weights", template=None, family="qwen3",
               extra_layers=(), config_extra=None):
    blobs = root / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)

    def put(b):
        h = sha(b)
        (blobs / f"sha256-{h}").write_bytes(b)
        return "sha256:" + h

    template = open(TEMPLATE_FIXTURE, "rb").read() if template is None else template
    layers = [{"mediaType": "application/vnd.ollama.image.model", "digest": put(weights), "size": len(weights)},
              {"mediaType": "application/vnd.ollama.image.template", "digest": put(template)},
              {"mediaType": "application/vnd.ollama.image.params", "digest": put(b'{"temperature":0.6}')},
              {"mediaType": "application/vnd.ollama.image.license", "digest": put(b"license text")}]
    layers += [{"mediaType": f"application/vnd.ollama.image.{kind}", "digest": put(b)} for kind, b in extra_layers]
    config = dict({"model_family": family}, **(config_extra or {}))
    man = json.dumps({"schemaVersion": 2, "config": {"digest": put(json.dumps(config).encode())},
                      "layers": layers}).encode()
    name, ver = tag.split(":")
    mdir = root / "manifests" / "registry.ollama.ai" / "library" / name
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / ver).write_bytes(man)
    return {"manifest_sha256": sha(man), "weights_sha256": sha(weights),
            "weights_path": str(blobs / ("sha256-" + sha(weights)))}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    tok = write_exe(tmp_path / "llama-tokenize", FAKE_TOKENIZE.replace("{python}", sys.executable))
    store = make_store(tmp_path / "models")
    log = tmp_path / "tok.log"
    monkeypatch.setenv(T.ENV_LLAMA_TOKENIZE, tok)
    monkeypatch.setenv(T.ENV_OLLAMA_MODELS, str(tmp_path / "models"))
    monkeypatch.setenv("FAKE_TOK_LOG", str(log))
    monkeypatch.delenv("FAKE_TOK_MODE", raising=False)
    return dict(store, tokenizer=tok, log=log, models=str(tmp_path / "models"), tmp=tmp_path)


def log_lines(fake):
    return [json.loads(ln) for ln in fake["log"].read_text().splitlines()] if fake["log"].exists() else []


# ---------------------------------------------------------------- qwen3 template port

def test_template_fixture_is_the_ollama_blob():
    assert sha(open(TEMPLATE_FIXTURE, "rb").read()) == T.QWEN3_TEMPLATE_SHA256
    assert GO_REF["template_sha256"] == T.QWEN3_TEMPLATE_SHA256


@pytest.mark.parametrize("case", GO_REF["cases"], ids=[c["name"] for c in GO_REF["cases"]])
def test_render_matches_go_text_template(case):
    """The Python port gives byte-identical prompts to Go's text/template on the Ollama template blob."""
    prompt, info = T.render_qwen3(case["messages"], think=case["think"])
    assert prompt == case["prompt"]
    assert info["template_sha256"] == T.QWEN3_TEMPLATE_SHA256 and info["history_think_stripped"] == 0


def test_render_strips_think_block_only_before_last_user():
    msgs = [{"role": "user", "content": "U1"}, {"role": "assistant", "content": "<think>r</think>\n\nA1"},
            {"role": "user", "content": "U2"}, {"role": "assistant", "content": "<think>s</think>A2"}]
    prompt, info = T.render_qwen3(msgs, think=False)
    assert "<|im_start|>assistant\nA1<|im_end|>" in prompt and "<think>s</think>A2" in prompt
    assert info["history_think_stripped"] == 1
    prompt2, info2 = T.render_qwen3(msgs, think=False, strip_history_think=False)
    assert "<think>r</think>" in prompt2 and info2["history_think_stripped"] == 0


@pytest.mark.parametrize("content,expected", [
    ("  <think>a</think>  b", "b"), ("<think>never closed", ""), ("   \n", ""), ("<thi", ""), ("", ""),
    ("plain answer", "plain answer"), ("x <think>y</think>", "x <think>y</think>"),
    ("\x1c<think>a</think>b", "\x1c<think>a</think>b"),  # Go's IsSpace does not include U+001C
])
def test_drop_leading_think(content, expected):
    assert T._drop_leading_think(content) == expected


@pytest.mark.parametrize("msgs", [
    [{"role": "user", "content": "u", "images": ["x"]}],
    [{"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "f"}}]}],
    [{"role": "developer", "content": "d"}],
    [{"role": "user", "content": 3}],
    [{"role": "user", "content": "bad \ud800 surrogate"}],
    "not a list",
])
def test_render_refuses_what_it_cannot_reproduce(msgs):
    with pytest.raises(T.TokenizerError):
        T.render_qwen3(msgs, think=False)


# ---------------------------------------------------------------- llama-tokenize wrapper (fake binary)

def test_flags_content_and_prompt_mode(fake):
    tok = T.LlamaCppTokenizer(fake["weights_path"], fake["weights_sha256"])
    assert tok.version == "0.0.0 (build 0, commit fake)"
    assert tok.count("a\\nb") == 4  # the backslash stays a character: --no-escape is always passed
    assert tok.count("<|im_start|>x", parse_special=True, model_bos=True) == 2
    calls = [a for a in log_lines(fake) if "--version" not in a]
    content, prompt = calls[-2], calls[-1]
    assert "--no-escape" in content and "--no-parse-special" in content and "--no-bos" in content
    assert "--no-escape" in prompt and "--no-parse-special" not in prompt and "--no-bos" not in prompt


def test_counts_are_cached_by_text_hash(fake):
    tok = T.LlamaCppTokenizer(fake["weights_path"], fake["weights_sha256"])
    n0 = len(log_lines(fake))
    assert tok.count("same text") == tok.count("same text") == 9
    assert tok.count("") == 0
    assert len(log_lines(fake)) == n0 + 1


def test_missing_tokenizer_binary_raises(fake, monkeypatch):
    monkeypatch.setenv(T.ENV_LLAMA_TOKENIZE, str(fake["tmp"] / "no-such-binary"))
    with pytest.raises(T.TokenizerError, match="llama-tokenize not found"):
        T.LlamaCppTokenizer(fake["weights_path"], fake["weights_sha256"])


def test_missing_model_file_raises(fake):
    with pytest.raises(T.TokenizerError, match="GGUF file not found"):
        T.LlamaCppTokenizer(str(fake["tmp"] / "missing.gguf"), fake["weights_sha256"])


@pytest.mark.parametrize("verify", ["full", "name"])
def test_model_hash_mismatch_raises(fake, verify):
    with pytest.raises(T.TokenizerError):
        T.LlamaCppTokenizer(fake["weights_path"], "0" * 64, verify=verify)


def test_model_hash_required(fake):
    with pytest.raises(T.TokenizerError, match="sha256"):
        T.LlamaCppTokenizer(fake["weights_path"], None)


@pytest.mark.parametrize("mode", ["fail", "garbage"])
def test_tokenizer_failure_raises_not_none(fake, monkeypatch, mode):
    tok = T.LlamaCppTokenizer(fake["weights_path"], fake["weights_sha256"])
    monkeypatch.setenv("FAKE_TOK_MODE", mode)
    with pytest.raises(T.TokenizerError):
        tok.count("fresh text")


def test_text_that_is_not_utf8_raises(fake):
    tok = T.LlamaCppTokenizer(fake["weights_path"], fake["weights_sha256"])
    with pytest.raises(T.TokenizerError, match="UTF-8"):
        tok.count("lone \ud800")


# ---------------------------------------------------------------- Ollama store and per-call record

def test_counter_reads_the_store_and_builds_the_record(fake):
    c = T.OllamaCounter("fakeqwen:8b", expect_digest=fake["manifest_sha256"])
    ident = c.identity()
    assert ident["manifest_sha256"] == fake["manifest_sha256"] and ident["weights_sha256"] == fake["weights_sha256"]
    assert ident["template_sha256"] == T.QWEN3_TEMPLATE_SHA256 and ident["strip_history_think"] is True
    assert str(fake["tmp"]) not in json.dumps(ident), "no local path in the identity"
    msgs = [{"role": "system", "content": "You are a helper."}, {"role": "user", "content": "Problem:\nMaximize x.\n"}]
    completion = "```python\nprint(1)\n```"
    rec = c.local_tokens(msgs, completion, think=False, thinking="<think>ok")
    rendered = next(x["prompt"] for x in GO_REF["cases"] if x["name"] == "sys_user_nothink")
    assert rec["schema"] == T.SCHEMA and rec["tokenizer_sha256"] == c.identity_sha256
    assert rec["content_by_message"] == [17, 21] and rec["content_total"] == 38
    assert rec["rendered_prompt"] == fake_count(rendered, parse_special=True)
    assert rec["completion"] == len(completion) and rec["completion_thinking"] == 3 and rec["think"] is False


def test_parse_tag():
    assert T._parse_tag("qwen3:8b") == ("registry.ollama.ai", "library", "qwen3", "8b")
    assert T._parse_tag("qwen3-8b-ctx32k") == ("registry.ollama.ai", "library", "qwen3-8b-ctx32k", "latest")
    assert T._parse_tag("user/m:q4") == ("registry.ollama.ai", "user", "m", "q4")
    for bad in ("", "../x:1", "a/b/c/d:1", "a:b:c", None):
        with pytest.raises(T.TokenizerError):
            T._parse_tag(bad)


def test_counter_refusals(fake, tmp_path):
    with pytest.raises(T.TokenizerError, match="no Ollama manifest"):
        T.OllamaCounter("nosuch:1")
    with pytest.raises(T.TokenizerError, match="server digest"):
        T.OllamaCounter("fakeqwen:8b", expect_digest="f" * 64)
    with pytest.raises(T.TokenizerError, match="weights blob"):
        T.OllamaCounter("fakeqwen:8b", expect_weights_sha256="e" * 64)
    other = make_store(tmp_path / "models", tag="other:1", weights=b"w2", template=b"{{ .Prompt }}")
    assert other
    with pytest.raises(T.TokenizerError, match="no local port of the chat template"):
        T.OllamaCounter("other:1")
    os.remove(fake["weights_path"])
    with pytest.raises(T.TokenizerError, match="missing"):
        T.OllamaCounter("fakeqwen:8b")


@pytest.mark.parametrize("kind,blob", [
    ("system", b"You are a helpful assistant."),  # Modelfile SYSTEM: prepended when a request has no system first
    ("messages", b'[{"role":"user","content":"hi"}]'),  # Modelfile MESSAGE lines: prepended to every chat
    ("projector", b"mmproj"), ("adapter", b"lora"),
])
def test_counter_refuses_layers_it_does_not_reproduce(fake, tmp_path, kind, blob):
    make_store(tmp_path / "models", tag="withlayer:1", weights=b"w3", extra_layers=[(kind, blob)])
    with pytest.raises(T.TokenizerError, match=kind):
        T.OllamaCounter("withlayer:1")


def test_counter_refuses_a_builtin_renderer(fake, tmp_path):
    make_store(tmp_path / "models", tag="rendered:1", weights=b"w4", config_extra={"renderer": "qwen3-coder"})
    with pytest.raises(T.TokenizerError, match="built-in renderer"):
        T.OllamaCounter("rendered:1")
    make_store(tmp_path / "models", tag="noren:1", weights=b"w5", config_extra={"renderer": ""})
    assert T.OllamaCounter("noren:1").identity()["model_family"] == "qwen3"


def test_tampered_template_blob_is_refused(fake):
    path = os.path.join(fake["models"], "blobs", "sha256-" + T.QWEN3_TEMPLATE_SHA256)
    with open(path, "ab") as f:
        f.write(b" ")
    with pytest.raises(T.TokenizerError, match="does not match its digest"):
        T.OllamaCounter("fakeqwen:8b")


def test_counter_for_unknown_backend():
    with pytest.raises(T.TokenizerError, match="no offline tokenizer"):
        T.counter_for("anthropic", "some-model")


# ---------------------------------------------------------------- tiktoken (OpenAI) through a separate interpreter

FAKE_TIKTOKEN = '''
import re
__version__ = "0.0-fake"
class Encoding:
    def __init__(self, name, pat_str, mergeable_ranks, special_tokens, explicit_n_vocab=None):
        self.name, self.n_vocab = name, len(mergeable_ranks) + len(special_tokens)
    def encode(self, text, disallowed_special="all"):
        assert disallowed_special == ()
        return re.findall(r"\\w+|[^\\w\\s]", text)
'''
FAKE_TIKTOKEN_LOAD = '''
def read_file(blobpath):
    raise AssertionError("network")
def load_tiktoken_bpe(blobpath, expected_hash=None):
    raise AssertionError("must be replaced by the helper")
'''
FAKE_OPENAI_PUBLIC = '''
from tiktoken.load import load_tiktoken_bpe
EXPECTED = "{expected}"
def cl100k_base():
    ranks = load_tiktoken_bpe("https://example.invalid/cl100k_base.tiktoken", expected_hash=EXPECTED)
    return {{"name": "cl100k_base", "pat_str": "x", "mergeable_ranks": ranks, "special_tokens": {{"<|endoftext|>": 9}}}}
ENCODING_CONSTRUCTORS = {{"cl100k_base": cl100k_base}}
'''


@pytest.fixture
def fake_tiktoken(tmp_path):
    enc = tmp_path / "cl100k_base.tiktoken"
    enc.write_bytes(b"YQ== 0\nYg== 1\nYWI= 2\n")
    pkgs = tmp_path / "site"
    (pkgs / "tiktoken").mkdir(parents=True)
    (pkgs / "tiktoken_ext").mkdir()
    (pkgs / "tiktoken" / "__init__.py").write_text(FAKE_TIKTOKEN)
    (pkgs / "tiktoken" / "load.py").write_text(FAKE_TIKTOKEN_LOAD)
    (pkgs / "tiktoken_ext" / "openai_public.py").write_text(FAKE_OPENAI_PUBLIC.format(expected=sha(enc.read_bytes())))
    # the helper runs "python -I -c ..."; this test interpreter drops -I so that the fake packages are importable
    py = write_exe(tmp_path / "toolspy", f'#!/bin/sh\n[ "$1" = "-I" ] && shift\n'
                                         f'PYTHONPATH="{pkgs}" exec "{sys.executable}" "$@"\n')
    return {"python": py, "file": str(enc), "sha256": sha(enc.read_bytes()), "pkgs": pkgs, "tmp": tmp_path}


def test_tiktoken_counter_with_fake_tiktoken(fake_tiktoken):
    c = T.TiktokenCounter("gpt-x-2026-01-01", "cl100k_base", fake_tiktoken["file"], fake_tiktoken["sha256"],
                          python=fake_tiktoken["python"])
    ident = c.identity()
    assert ident["tokenizer"] == {"kind": "tiktoken", "version": "0.0-fake", "encoding": "cl100k_base", "n_vocab": 4,
                                  "encoding_sha256": fake_tiktoken["sha256"]}
    assert c.count("Hello, world!") == 4 and c.counts(["a b", "", "c"]) == [2, 0, 1]
    rec = c.local_tokens([{"role": "system", "content": "s t"}, {"role": "user", "content": "u"}], "x = 1")
    assert rec["content_by_message"] == [2, 1] and rec["completion"] == 3 and rec["rendered_prompt"] is None
    with pytest.raises(T.TokenizerError, match="not public"):
        c.count_prompt([{"role": "user", "content": "u"}])


def test_tiktoken_refusals(fake_tiktoken, tmp_path):
    ft = fake_tiktoken
    with pytest.raises(T.TokenizerError, match="interpreter with tiktoken not found"):
        T.TiktokenCounter("m", "cl100k_base", ft["file"], ft["sha256"], python=str(tmp_path / "nopython"))
    with pytest.raises(T.TokenizerError, match="encoding file not found"):
        T.TiktokenCounter("m", "cl100k_base", str(tmp_path / "none.tiktoken"), ft["sha256"], python=ft["python"])
    with pytest.raises(T.TokenizerError, match="sha256"):
        T.TiktokenCounter("m", "cl100k_base", ft["file"], None, python=ft["python"])
    with pytest.raises(T.TokenizerError, match="not the registered"):
        T.TiktokenCounter("m", "cl100k_base", ft["file"], "a" * 64, python=ft["python"])
    with pytest.raises(T.TokenizerError, match="unknown encoding"):
        T.TiktokenCounter("m", "o200k_base", ft["file"], ft["sha256"], python=ft["python"])
    other = tmp_path / "other.tiktoken"
    other.write_bytes(b"YQ== 0\n")
    with pytest.raises(T.TokenizerError, match="not the file tiktoken expects"):
        T.TiktokenCounter("m", "cl100k_base", str(other), sha(other.read_bytes()), python=ft["python"])


@pytest.mark.skipif(importlib.util.find_spec("tiktoken") is not None, reason="this interpreter has tiktoken")
def test_tiktoken_missing_in_interpreter_raises(fake_tiktoken):
    with pytest.raises(T.TokenizerError, match="import tiktoken failed"):
        T.TiktokenCounter("m", "cl100k_base", fake_tiktoken["file"], fake_tiktoken["sha256"], python=sys.executable)


# ---------------------------------------------------------------- conditions.exact_tokens

class _StubCounter:
    identity_sha256 = "stub"

    def count(self, text):
        return len(text.split())


def test_exact_tokens_never_returns_none():
    with pytest.raises(T.TokenizerError):
        C.exact_tokens("some prompt")
    assert C.exact_tokens("a b c", _StubCounter()) == 3


def test_system_prompt_counts_only_with_a_counter():
    cond, genes = os.path.join(ROOT, "conditions"), os.path.join(ROOT, "genes", "genes.r1.jsonl")
    prompts, info = C.build_system_prompts_v1(cond, genes, token_counter=_StubCounter())
    assert info["system_prompt_tokens_local"] == {k: len(v.split()) for k, v in prompts.items()}
    assert info["system_prompt_tokenizer_sha256"] == "stub"
    _, info0 = C.build_system_prompts_v1(cond, genes)
    assert info0["system_prompt_tokens_local"] is None and "system_prompt_tokens_cl100k" not in info0


# ---------------------------------------------------------------- ollama_runner with a mock server

class _MockOllama(BaseHTTPRequestHandler):
    digest = None
    chat_calls = 0

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/version":
            return self._send({"version": "0.0.0-mock"})
        if self.path == "/api/tags":
            return self._send({"models": [{"name": "fakeqwen:8b", "model": "fakeqwen:8b",
                                           "digest": type(self).digest, "size": 1}]})
        self.send_error(404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        if self.path == "/api/show":
            return self._send({"parameters": "", "capabilities": ["completion"]})
        if self.path == "/api/chat":
            type(self).chat_calls += 1
            assert body["think"] is False
            return self._send({"message": {"role": "assistant", "content": "```python\nprint(1)\n```"},
                               "done_reason": "stop", "prompt_eval_count": 42, "eval_count": 7,
                               "total_duration": 1000, "eval_duration": 500, "prompt_eval_duration": 100})
        self.send_error(404)

    def log_message(self, *a):
        pass


def _run_runner(tmp_path, digest, env, extra=(), messages=None):
    handler = type("H", (_MockOllama,), {"digest": digest, "chat_calls": 0})
    srv = HTTPServer(("127.0.0.1", 0), handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    reqs = tmp_path / "requests.jsonl"
    messages = messages or [{"role": "system", "content": "You are a helper."},
                            {"role": "user", "content": "Problem:\nMaximize x.\n"}]
    reqs.write_text(json.dumps({"request_id": "smoke-001.C0", "case_id": "smoke-001", "condition": "C0", "meta": {},
                                "messages": messages}) + "\n")
    out = tmp_path / "gen"
    p = subprocess.run([sys.executable, os.path.join(RUNTIME, "ollama_runner.py"), "--host",
                        f"http://127.0.0.1:{srv.server_address[1]}", "--model", "fakeqwen:8b", "--requests", str(reqs),
                        "--out", str(out), *extra], capture_output=True, text=True, env=env, timeout=120)
    srv.shutdown()
    return p, out, handler.chat_calls


def test_ollama_runner_records_local_tokens(fake, tmp_path):
    env = dict(os.environ)
    p, out, n_chat = _run_runner(tmp_path, fake["manifest_sha256"], env)
    assert p.returncode == 0, p.stderr
    rec = json.load(open(out / "outputs" / "smoke-001.C0.r0.json"))
    lt = rec["local_tokens"]
    rendered = next(x["prompt"] for x in GO_REF["cases"] if x["name"] == "sys_user_nothink")
    assert lt["content_by_message"] == [17, 21] and lt["rendered_prompt"] == fake_count(rendered, True)
    assert lt["completion"] == len("```python\nprint(1)\n```") and rec["prompt_eval_count"] == 42 and n_chat == 1
    cfg = json.load(open(out / "config.json"))
    assert cfg["local_tokenizer"]["manifest_sha256"] == fake["manifest_sha256"]
    assert lt["tokenizer_sha256"] == T.identity_sha256(cfg["local_tokenizer"])
    # merged with the E08 runner: the built-in counter is on by default, named, and its code is hashed with the run
    assert rec["local_tokens_counter"] == cfg["local_tokens_counter"] == "orgene.tokcount:OllamaCounter"
    assert rec["local_tokens_error"] is None and "runtime/orgene/tokcount.py" in cfg["code_sha256"]
    # resuming the same output directory without local counts is refused
    p2, _, n_chat2 = _run_runner(tmp_path, fake["manifest_sha256"], env, extra=("--local-tokens", "off"))
    assert p2.returncode != 0 and "local_tokenizer" in p2.stderr and n_chat2 == 0


def test_ollama_runner_stops_before_first_call_without_tokenizer(fake, tmp_path):
    env = dict(os.environ, **{T.ENV_LLAMA_TOKENIZE: str(tmp_path / "missing-llama-tokenize")})
    p, out, n_chat = _run_runner(tmp_path, fake["manifest_sha256"], env)
    assert p.returncode != 0 and "local token counts unavailable" in p.stderr and n_chat == 0
    assert not (out / "outputs" / "smoke-001.C0.r0.json").exists()


def test_ollama_runner_refuses_a_server_serving_other_blobs(fake, tmp_path):
    p, _, n_chat = _run_runner(tmp_path, "d" * 64, dict(os.environ))
    assert p.returncode != 0 and "server digest" in p.stderr and n_chat == 0


def test_ollama_runner_refuses_a_server_without_digest(fake, tmp_path):
    p, _, n_chat = _run_runner(tmp_path, None, dict(os.environ))
    assert p.returncode != 0 and "no digest" in p.stderr and n_chat == 0


def test_ollama_runner_stops_before_first_call_on_an_unrenderable_request(fake, tmp_path):
    msgs = [{"role": "user", "content": "Problem:\nMaximize x.\n", "images": ["aW1n"]}]
    p, out, n_chat = _run_runner(tmp_path, fake["manifest_sha256"], dict(os.environ), messages=msgs)
    assert p.returncode != 0 and "smoke-001.C0" in p.stderr and "images" in p.stderr and n_chat == 0
    assert not (out / "outputs" / "smoke-001.C0.r0.json").exists()


# ---------------------------------------------------------------- repair_prompt_budget

def _budget(tmp_path, env, *args):
    reqs = tmp_path / "requests.C3.repair1.jsonl"
    rows = [{"request_id": "smoke-001.C3.rep0.repair1", "messages": [
        {"role": "system", "content": "S"}, {"role": "user", "content": "P"},
        {"role": "assistant", "content": "x" * 400}, {"role": "user", "content": "Fix it."}]},
        {"request_id": "smoke-002.C3.rep0.repair1", "messages": [{"role": "user", "content": "short"}]}]
    reqs.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return subprocess.run([sys.executable, os.path.join(ROOT, "analysis", "repair_prompt_budget.py"), "--requests",
                           str(reqs), "--model", "fakeqwen:8b", *args], capture_output=True, text=True, env=env,
                          timeout=120)


def test_repair_budget_uses_local_counts(fake, tmp_path):
    out = tmp_path / "budget.json"
    p = _budget(tmp_path, dict(os.environ), "--num-ctx", "300", "--num-predict", "100", "--json-out", str(out))
    # one request over budget: reported, and the exit status stops run_condition.sh before the round is generated
    assert p.returncode == 1, p.stderr
    assert "over budget: 1" in p.stdout and "OVER smoke-001.C3.rep0.repair1" in p.stdout and "not continuing" in p.stderr
    rows = json.load(open(out))["rows"]
    long_msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "P"},
                 {"role": "assistant", "content": "x" * 400}, {"role": "user", "content": "Fix it."}]
    assert rows[0]["prompt_tokens"] == fake_count(T.render_qwen3(long_msgs, think=False)[0], True)


def test_repair_budget_passes_when_every_prompt_fits(fake, tmp_path):
    out = tmp_path / "budget.json"
    p = _budget(tmp_path, dict(os.environ), "--num-ctx", "32768", "--num-predict", "6000", "--json-out", str(out))
    assert p.returncode == 0, p.stderr
    assert "over budget: 0" in p.stdout and not [r for r in json.load(open(out))["rows"] if r["over"]]


def test_repair_budget_counts_with_think_as_sent(fake, tmp_path):
    rows = {}
    for flag in ((), ("--think",)):
        out = tmp_path / f"budget{len(flag)}.json"
        p = _budget(tmp_path, dict(os.environ), "--num-ctx", "32768", "--num-predict", "6000", "--json-out", str(out), *flag)
        assert p.returncode == 0, p.stderr
        rep = json.load(open(out))
        assert rep["think"] is bool(flag)
        rows[bool(flag)] = [r["prompt_tokens"] for r in rep["rows"]]
    long_msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "P"},
                 {"role": "assistant", "content": "x" * 400}, {"role": "user", "content": "Fix it."}]
    assert rows[True][0] == fake_count(T.render_qwen3(long_msgs, think=True)[0], True)
    assert rows[False][0] == fake_count(T.render_qwen3(long_msgs, think=False)[0], True)


def test_repair_budget_stops_without_tokenizer(fake, tmp_path):
    env = dict(os.environ, **{T.ENV_LLAMA_TOKENIZE: str(tmp_path / "missing")})
    p = _budget(tmp_path, env)
    assert p.returncode == 2 and "local token count unavailable" in p.stderr


# ---------------------------------------------------------------- real tokenizer (qwen3:8b blob)

def _real_available():
    binary = os.environ.get(T.ENV_LLAMA_TOKENIZE) or T.DEFAULT_LLAMA_TOKENIZE
    try:
        m = T.resolve_ollama_model("qwen3:8b")
    except T.TokenizerError:
        return False
    return os.access(binary, os.X_OK) and m["weights_sha256"] == T.QWEN3_WEIGHTS_SHA256


real = pytest.mark.skipif(not _real_available(), reason="llama-tokenize or the qwen3:8b blob is not on this machine")


@pytest.fixture(scope="module")
def qwen3():
    return T.OllamaCounter("qwen3:8b", expect_weights_sha256=T.QWEN3_WEIGHTS_SHA256)


# Token ids from llama-tokenize over the qwen3:8b blob; the same ids come from an independent Hugging Face
# `tokenizers` BPE built from the blob's vocabulary and merges (tools/tokcount_crosscheck.py, 2026-09-28).
REAL_IDS = [
    ("Hello world", False, [9707, 1879]),
    ("a\\nb", False, [64, 1699, 65]),  # backslash-n stays two characters (--no-escape)
    ("a\nb", False, [64, 198, 65]),
    ("ab\n\n", False, [370, 271]),
    ('print("x\\n")\n', False, [1350, 445, 87, 1699, 1138]),
    ("最优化 模型 ✓ é", False, [31235, 103983, 6567, 44401, 24300, 52375, 3958]),
    ("<think>x</think>", False, [151667, 87, 151668]),  # user-defined tokens are matched in both modes
    ("<|im_start|>user\nHi<|im_end|>\n", False, [27, 91, 318, 4906, 91, 29, 872, 198, 13048, 27, 91, 318, 6213, 91, 397]),
    ("<|im_start|>user\nHi<|im_end|>\n", True, [151644, 872, 198, 13048, 151645, 198]),
]
REAL_RENDERED = {"sys_user_nothink": 32, "sys_user_think": 26, "sys_user_unset": 24, "user_only_nothink": 17,
                 "repair_turn_nothink": 57, "repair_turn_think": 29, "tool_messages": 40, "unicode_and_braces": 39,
                 "empty_messages": 0}
REAL_SMOKE = {"smoke-001": 114, "smoke-002": 109, "smoke-003": 124}


@real
def test_real_counter_identity(qwen3):
    ident = qwen3.identity()
    assert ident["manifest_sha256"] == T.QWEN3_MANIFEST_SHA256
    assert ident["weights_sha256"] == T.QWEN3_WEIGHTS_SHA256 and ident["template_sha256"] == T.QWEN3_TEMPLATE_SHA256
    assert ident["tokenizer"]["verify"] == "full" and ident["tokenizer"]["version"]


@real
@pytest.mark.parametrize("text,special,ids", REAL_IDS)
def test_real_fixed_ids(qwen3, text, special, ids):
    assert qwen3.tok.ids(text, parse_special=special, model_bos=special) == ids


@real
def test_real_rendered_and_smoke_counts(qwen3):
    by_name = {c["name"]: c for c in GO_REF["cases"]}
    got = {k: qwen3.count_prompt(by_name[k]["messages"], by_name[k]["think"])[0] for k in REAL_RENDERED}
    assert got == REAL_RENDERED
    assert {s["id"]: qwen3.count(C.user_message({"text": s["Question"]})) for s in SMOKE} == REAL_SMOKE


@real
def test_real_blob_with_wrong_hash_is_refused():
    m = T.resolve_ollama_model("qwen3:8b")
    with pytest.raises(T.TokenizerError):
        T.LlamaCppTokenizer(m["weights_path"], "0" * 64, verify="name")


# ---------------------------------------------------------------- Ollama integration (dev rehearsal only)

@pytest.mark.skipif(os.environ.get("ORGENE_OLLAMA_TESTS") != "1",
                    reason="calls the model; set ORGENE_OLLAMA_TESTS=1 during the dev rehearsal")
@real
def test_ollama_prompt_eval_count_equals_local_rendered_count(qwen3):
    host = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434")

    def call(path, payload=None):
        req = urllib.request.Request(host + path, data=json.dumps(payload).encode() if payload else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read())

    loaded = call("/api/ps").get("models") or []
    if loaded:
        pytest.skip(f"another model is loaded ({len(loaded)}); not preempting it")
    convs = [[{"role": "system", "content": "You are a helper."},
              {"role": "user", "content": C.user_message({"text": SMOKE[0]["Question"]})}],
             [{"role": "system", "content": "S"}, {"role": "user", "content": "Problem:\nP\n"},
              {"role": "assistant", "content": "```python\nprint(1)\n```\n"}, {"role": "user", "content": "Fix it.\n"}]]
    for msgs in convs:
        resp = call("/api/chat", {"model": "qwen3:8b", "messages": msgs, "stream": False, "think": False,
                                  "keep_alive": 0, "options": {"temperature": 0, "seed": 1, "num_ctx": 32768,
                                                               "num_predict": 1}})
        assert resp["prompt_eval_count"] == qwen3.count_prompt(msgs, False)[0]


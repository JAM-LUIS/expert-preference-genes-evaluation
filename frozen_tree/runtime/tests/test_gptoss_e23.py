"""E23: gpt-oss as the second model — think levels, thinking kept apart from content, the harmony template port, the
fixed-date alias, the tokenizer-only GGUF and the tokenizer choice.

No model is called. Fake HTTP servers, a fake llama-tokenize, a fake tiktoken and fake Ollama model stores stand in;
the tests marked "real" read the host's Ollama store and .venv-tools (skipped without them; in a worktree set
ORGENE_TOOLS_PY and ORGENE_TIKTOKEN_DIR to the main checkout's). Text is self-made or the author-written smoke case.
"""
import hashlib
import json
import os
import stat
import struct
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import gguf_vocab as GV  # noqa: E402
from orgene import model_registry as MR  # noqa: E402
from orgene import tokcount as T  # noqa: E402
from orgene import tokcount_harmony as H  # noqa: E402
from orgene.backends import ollama as OB  # noqa: E402
from orgene.backends.base import OptionsError, RegistryMismatch, registry_guard, request_sha256  # noqa: E402
from orgene.backends.ollama import OllamaBackend, check_think, parse_think  # noqa: E402
from orgene.extract import extract  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
BASE_TEMPLATE = os.path.join(FIX, "gptoss_ollama_template.gotmpl")
ALIAS_TEMPLATE = os.path.join(FIX, "gptoss_date20260929_template.gotmpl")
GO_REF = json.load(open(os.path.join(FIX, "gptoss_template_go_reference.json"), encoding="utf-8"))
GO_REF_ALIAS = json.load(open(os.path.join(FIX, "gptoss_date20260929_template_go_reference.json"), encoding="utf-8"))
MODELFILE = os.path.join(ROOT, "configs", "ollama", "gpt-oss-20b-date20260929.Modelfile")
MSGS = [{"role": "system", "content": "You write PuLP programs."}, {"role": "user", "content": "Maximise 3x with x <= 2."}]
OPTS = {"temperature": 0.0, "top_k": 40, "top_p": 0.9, "seed": 1, "num_ctx": 32768, "num_predict": 6000,
        "think": "low", "keep_alive": 0}
CODE = "```python\nimport pulp\nprint('STATUS: Optimal')\nprint('FINAL_OBJECTIVE: 6')\n```"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def write_exe(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


# ---------------------------------------------------------------- a fake Ollama server

class _Fake(BaseHTTPRequestHandler):
    model = "gpt-oss:20b"
    digest = "d2" * 32
    answer = {"role": "assistant", "content": CODE, "thinking": "Short plan."}
    bodies = None

    def _send(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/version":
            return self._send({"version": "0.33.0"})
        if self.path == "/api/tags":
            return self._send({"models": [{"name": type(self).model, "model": type(self).model,
                                           "digest": type(self).digest, "size": 1}]})
        if self.path == "/api/ps":
            return self._send({"models": []})
        self.send_error(404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        if self.path == "/api/show":
            return self._send({"parameters": "temperature                    1", "capabilities": ["completion", "thinking"]})
        if self.path == "/api/chat":
            type(self).bodies.append(body)
            return self._send({"model": type(self).model, "message": dict(type(self).answer), "done_reason": "stop",
                               "prompt_eval_count": 50, "eval_count": 30, "total_duration": 1000,
                               "eval_duration": 500, "prompt_eval_duration": 100, "load_duration": 10})
        self.send_error(404)

    def log_message(self, *a):
        pass


@pytest.fixture
def fake():
    handler = type("H", (_Fake,), {"bodies": []})
    srv = HTTPServer(("127.0.0.1", 0), handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield {"host": f"http://127.0.0.1:{srv.server_address[1]}", "h": handler}
    srv.shutdown()


def _backend(fake, **kw):
    return OllamaBackend("gpt-oss:20b", host=fake["host"], max_attempts=1, retry_sleep=0, **kw)


# ---------------------------------------------------------------- think: levels as well as booleans

@pytest.mark.parametrize("level", ["low", "medium", "high"])
def test_a_reasoning_level_is_sent_verbatim(fake, level):
    rec = _backend(fake).call(MSGS, dict(OPTS, think=level))
    body = fake["h"].bodies[-1]
    assert body["think"] == level and rec["sent_opts"]["think"] == level and rec["ok"]


@pytest.mark.parametrize("value", [True, False])
def test_booleans_are_still_sent(fake, value):
    _backend(fake).call(MSGS, dict(OPTS, think=value))
    assert fake["h"].bodies[-1]["think"] is value


@pytest.mark.parametrize("bad", ["none", "", "LOW", "max", "true", 0, 1, None, 2.0, ["low"]])
def test_a_bad_think_value_is_refused_before_sending(fake, bad):
    with pytest.raises(OptionsError, match="think"):
        _backend(fake).call(MSGS, dict(OPTS, think=bad))
    assert fake["h"].bodies == []


def test_a_missing_think_is_refused_before_sending(fake):
    opts = dict(OPTS)
    del opts["think"]
    with pytest.raises(OptionsError, match=r"must be set explicitly: \['think'\]"):
        _backend(fake).call(MSGS, opts)
    assert fake["h"].bodies == []


def test_the_level_is_part_of_the_request_hash():
    b = OllamaBackend("gpt-oss:20b", host="http://127.0.0.1:9")
    hashes = {v: request_sha256(b.build_body(MSGS, dict(OPTS, think=v))) for v in ("low", "medium", "high", True, False)}
    assert len(set(hashes.values())) == 5


def test_parse_think_for_command_lines():
    assert parse_think("true") is True and parse_think("false") is False and parse_think("low") == "low"
    assert parse_think(True) is True and check_think("high") == "high"
    for bad in ("True", "maximal", "", None):
        with pytest.raises(OptionsError):
            parse_think(bad)


def test_registry_think_levels_follow_the_backend():
    assert MR.OLLAMA_THINK_LEVELS == OB.THINK_LEVELS == H.THINK_LEVELS


# ---------------------------------------------------------------- the registry guard checks the level

ENTRY = {"backend": "ollama", "model": "gpt-oss:20b", "opts": dict(OPTS), "seed_rule": "base+k"}


def test_guard_passes_the_registered_level():
    b = OllamaBackend("gpt-oss:20b", host="http://127.0.0.1:9")
    registry_guard(ENTRY, backend=b)(b.sent_opts(b.build_body(MSGS, OPTS)))
    assert MR.compare_sent(ENTRY, b.sent_opts(b.build_body(MSGS, OPTS)), backend_kind="ollama") == []


@pytest.mark.parametrize("sent", ["medium", "high", True, False])
def test_guard_refuses_another_level_or_a_boolean(sent):
    b = OllamaBackend("gpt-oss:20b", host="http://127.0.0.1:9")
    s = b.sent_opts(b.build_body(MSGS, dict(OPTS, think=sent)))
    with pytest.raises(RegistryMismatch, match="think"):
        registry_guard(ENTRY, backend=b)(s)
    assert any("think" in p for p in MR.compare_sent(ENTRY, s, backend_kind="ollama"))


def test_guard_refuses_a_level_where_the_registry_says_false():
    b = OllamaBackend("gpt-oss:20b", host="http://127.0.0.1:9")
    entry = dict(ENTRY, opts=dict(OPTS, think=False))
    with pytest.raises(RegistryMismatch, match="think"):
        registry_guard(entry, backend=b)(b.sent_opts(b.build_body(MSGS, OPTS)))


def _opts_problems(think):
    p = []
    MR._check_opts("x", "ollama", dict(OPTS, think=think), p)
    return p


def test_registry_validation_accepts_levels_and_refuses_others():
    for ok in ("low", "medium", "high", True, False):
        assert _opts_problems(ok) == []
    for bad in ("max", "LOW", 0, None, "extreme"):
        assert any("think" in x for x in _opts_problems(bad)), bad


# ---------------------------------------------------------------- thinking stays out of content

def test_thinking_is_recorded_apart_and_never_extracted(fake):
    fake["h"].answer = {"role": "assistant", "content": "No program.", "thinking": "Plan:\n" + CODE}
    rec = _backend(fake).call(MSGS, OPTS)
    assert rec["content"] == "No program." and CODE in rec["thinking"]
    assert rec["thinking_sha256"] == sha(rec["thinking"].encode()) and rec["content_sha256"] == sha(b"No program.")
    assert extract(rec["content"])["code"] is None      # the program in the reasoning is not the answer


def test_the_answer_is_extracted_from_content(fake):
    fake["h"].answer = {"role": "assistant", "content": CODE, "thinking": "print('FINAL_OBJECTIVE: 999')"}
    rec = _backend(fake).call(MSGS, OPTS)
    code = extract(rec["content"])["code"]
    assert code is not None and "FINAL_OBJECTIVE: 6" in code and "999" not in code


def test_a_record_without_thinking(fake):
    fake["h"].answer = {"role": "assistant", "content": CODE}
    rec = _backend(fake).call(MSGS, dict(OPTS, think=False))
    assert rec["thinking"] is None and rec["thinking_sha256"] is None


# ---------------------------------------------------------------- ollama_runner: --think [LEVEL]

def _run_runner(tmp_path, fake, *extra):
    reqs = tmp_path / "requests.jsonl"
    reqs.write_text(json.dumps({"request_id": "smoke-0001.C0", "case_id": "smoke-0001", "condition": "C0",
                                "meta": {}, "messages": MSGS}) + "\n")
    out = tmp_path / "run" / "gen.C0.r0"
    p = subprocess.run([sys.executable, os.path.join(RUNTIME, "ollama_runner.py"), "--host", fake["host"],
                        "--model", "gpt-oss:20b", "--requests", str(reqs), "--out", str(out), "--local-tokens", "off",
                        "--top-k", "40", "--top-p", "0.9", *extra], capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return p, out


@pytest.mark.parametrize("args,sent", [(["--think", "low"], "low"), (["--think", "high"], "high"), (["--think"], True),
                                       ([], False), (["--think", "false"], False), (["--think", "true"], True)])
def test_runner_sends_the_think_value_given(tmp_path, fake, args, sent):
    p, out = _run_runner(tmp_path, fake, *args)
    assert p.returncode == 0, p.stderr
    assert fake["h"].bodies[-1]["think"] == sent and type(fake["h"].bodies[-1]["think"]) is type(sent)
    assert json.load(open(out / "config.json"))["opts"]["think"] == sent


def test_runner_refuses_an_unknown_level_before_any_call(tmp_path, fake):
    p, out = _run_runner(tmp_path, fake, "--think", "maximal")
    assert p.returncode != 0 and "think" in p.stderr and fake["h"].bodies == []
    assert not (out / "config.json").exists()


def _registry(tmp_path, think):
    e = dict(ENTRY, opts=dict(OPTS, think=think), digest=_Fake.digest)
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"entries": {"gptoss-test": e}}))
    return str(path)


def test_runner_with_the_registry_entry(tmp_path, fake):
    p, out = _run_runner(tmp_path, fake, "--think", "low", "--registry", _registry(tmp_path, "low"),
                         "--registry-entry", "gptoss-test")
    assert p.returncode == 0, p.stderr
    assert json.load(open(out / "config.json"))["registry"]["entry_id"] == "gptoss-test"


@pytest.mark.parametrize("args", [["--think", "medium"], ["--think"], []])
def test_runner_refuses_other_think_than_the_entry(tmp_path, fake, args):
    p, out = _run_runner(tmp_path, fake, *args, "--registry", _registry(tmp_path, "low"),
                         "--registry-entry", "gptoss-test")
    assert p.returncode != 0 and "think" in p.stderr and fake["h"].bodies == []


def test_resume_with_another_level_is_refused(tmp_path, fake):
    p, _ = _run_runner(tmp_path, fake, "--think", "low")
    assert p.returncode == 0, p.stderr
    n = len(fake["h"].bodies)
    p2, _ = _run_runner(tmp_path, fake, "--think", "medium")
    assert p2.returncode != 0 and "resume refused" in p2.stderr and len(fake["h"].bodies) == n


# ---------------------------------------------------------------- the harmony template port

def test_template_fixtures_are_the_blobs():
    base = open(BASE_TEMPLATE, "rb").read()
    alias = open(ALIAS_TEMPLATE, "rb").read()
    assert sha(base) == H.GPTOSS_TEMPLATE_SHA256 == GO_REF["template_sha256"]
    assert sha(alias) == H.ALIAS_TEMPLATE_SHA256 == GO_REF_ALIAS["template_sha256"]
    assert base.count(b"{{ currentDate }}") == 1
    assert alias == base.replace(b"{{ currentDate }}", H.FIXED_DATE.encode()) and b"currentDate" not in alias


def test_the_modelfile_carries_exactly_the_alias_template():
    text = open(MODELFILE, encoding="utf-8").read()
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert lines[0] == "FROM gpt-oss:20b" and len([ln for ln in lines if ln.startswith(("FROM", "PARAMETER"))]) == 1
    body = text.split('TEMPLATE """', 1)[1].rsplit('"""', 1)[0]
    assert sha(body.encode()) == H.ALIAS_TEMPLATE_SHA256


@pytest.mark.parametrize("case", GO_REF["cases"], ids=lambda c: c["name"])
def test_render_matches_go_text_template(case):
    prompt, info = H.render_gptoss(case["messages"], think=case["think"], current_date=case["date"])
    assert prompt == case["prompt"] and info["current_date"] == case["date"]


@pytest.mark.parametrize("case", GO_REF_ALIAS["cases"], ids=lambda c: c["name"])
def test_alias_render_matches_go_text_template(case):
    render = T.TEMPLATE_RENDERERS[H.ALIAS_TEMPLATE_SHA256][1]
    prompt, info = render(case["messages"], think=case["think"])
    assert prompt == case["prompt"] and info["current_date"] == H.FIXED_DATE
    assert info["template_sha256"] == H.ALIAS_TEMPLATE_SHA256


def test_the_alias_changes_nothing_but_the_date():
    for c, d in zip(GO_REF["cases"], GO_REF_ALIAS["cases"]):
        assert (c["prompt"] == d["prompt"]) == (c["date"] == H.FIXED_DATE), c["name"]


def test_alias_refuses_another_date():
    render = T.TEMPLATE_RENDERERS[H.ALIAS_TEMPLATE_SHA256][1]
    with pytest.raises(T.TokenizerError, match="writes the date"):
        render(MSGS, think="low", current_date="2027-01-01")
    assert render(MSGS, think="low", current_date=H.FIXED_DATE)[0] == render(MSGS, think="low")[0]


def test_base_template_uses_the_local_date_by_default(monkeypatch):
    monkeypatch.setattr(H, "local_date", lambda: "2031-05-06")
    prompt, info = H.render_gptoss(MSGS, think="low")
    assert "Current date: 2031-05-06\n" in prompt and info["current_date"] == "2031-05-06"


@pytest.mark.parametrize("think,line", [(None, "medium"), (True, "medium"), (False, None), ("low", "low"),
                                        ("medium", "medium"), ("high", "high")])
def test_reasoning_line_follows_think(think, line):
    assert H.reasoning_line(think) == line
    prompt, info = H.render_gptoss(MSGS, think=think, current_date="2026-09-29")
    assert info["reasoning_line"] == line
    assert ("Reasoning:" in prompt) == (line is not None)
    if line:
        assert f"\n\nReasoning: {line}\n\n# Valid channels" in prompt


@pytest.mark.parametrize("msgs,think,date,match", [
    ([{"role": "tool", "content": "x"}], "low", "2026-09-29", "tool"),
    (MSGS, "max", "2026-09-29", "think"),
    (MSGS, "LOW", "2026-09-29", "think"),
    (MSGS, "low", "29/09/2026", "YYYY-MM-DD"),
    ([{"role": "user", "content": "x", "images": ["a"]}], "low", "2026-09-29", "images"),
])
def test_render_refuses_what_it_does_not_reproduce(msgs, think, date, match):
    with pytest.raises(T.TokenizerError, match=match):
        H.render_gptoss(msgs, think=think, current_date=date)


def test_both_templates_are_registered_with_tokcount():
    for s in (H.GPTOSS_TEMPLATE_SHA256, H.ALIAS_TEMPLATE_SHA256):
        assert T.TEMPLATE_RENDERERS[s][0] == H.RENDERER_GPTOSS and T.TEMPLATE_TOKENIZERS[s] is H.gptoss_tokenizer
    assert T.QWEN3_TEMPLATE_SHA256 not in T.TEMPLATE_TOKENIZERS   # qwen3 keeps llama-tokenize over its blob


# ---------------------------------------------------------------- the tokenizer-only GGUF

def _s(b):
    return struct.pack("<Q", len(b)) + b


def gguf(pairs, version=3, n_tensors=2, tail=b"\x00" * 64):
    """A small GGUF: pairs [(key, type, encoded value)], then some bytes standing for tensors."""
    body = b"GGUF" + struct.pack("<I", version) + struct.pack("<Q", n_tensors) + struct.pack("<Q", len(pairs))
    for k, t, v in pairs:
        body += _s(k.encode()) + struct.pack("<I", t) + v
    return body + tail


def s_val(x):
    return _s(x.encode())


def arr_str(xs):
    return struct.pack("<I", GV.T_STRING) + struct.pack("<Q", len(xs)) + b"".join(_s(x.encode()) for x in xs)


def arr_i32(xs):
    return struct.pack("<I", GV.T_INT32) + struct.pack("<Q", len(xs)) + struct.pack(f"<{len(xs)}i", *xs)


TOKEN_PAIRS = [
    ("general.architecture", GV.T_STRING, s_val("gptoss")),
    ("gptoss.block_count", GV.T_UINT32, struct.pack("<I", 24)),
    ("tokenizer.ggml.model", GV.T_STRING, s_val("gpt2")),
    ("tokenizer.ggml.tokens", GV.T_ARRAY, arr_str(["a", "b", "ab", "<|start|>"])),
    ("tokenizer.ggml.token_type", GV.T_ARRAY, arr_i32([1, 1, 1, 3])),
    ("tokenizer.ggml.merges", GV.T_ARRAY, arr_str(["a b"])),
    ("tokenizer.ggml.pre", GV.T_STRING, s_val("default")),
    ("tokenizer.ggml.add_bos_token", GV.T_BOOL, b"\x00"),
    ("tokenizer.ggml.eos_token_ids", GV.T_ARRAY, arr_i32([3])),
]


def test_gguf_read_and_vocab_only_copy():
    data = gguf(TOKEN_PAIRS)
    h = GV.parse_kv_bytes(data, decode=("*",))
    assert h["version"] == 3 and h["n_tensors"] == 2 and [p["key"] for p in h["pairs"]] == [k for k, _, _ in TOKEN_PAIRS]
    kv = {p["key"]: p["value"] for p in h["pairs"]}
    assert kv["tokenizer.ggml.tokens"] == ["a", "b", "ab", "<|start|>"] and kv["tokenizer.ggml.eos_token_ids"] == [3]
    out = GV.vocab_only_bytes(h, "gpt-oss", {"tokenizer.ggml.pre": "gpt-4o"})
    assert len(out) % GV.ALIGNMENT == 0
    h2 = GV.parse_kv_bytes(out, decode=("*",))
    assert h2["n_tensors"] == 0 and h2["pairs"][0]["key"] == "general.architecture" and h2["pairs"][0]["value"] == "gpt-oss"
    keys2 = [p["key"] for p in h2["pairs"]]
    assert keys2[1:] == [k for k, _, _ in TOKEN_PAIRS if k.startswith("tokenizer.")]      # nothing else copied
    src = {p["key"]: p["raw"] for p in h["pairs"]}
    for p in h2["pairs"][1:]:
        if p["key"] == "tokenizer.ggml.pre":
            assert p["value"] == "gpt-4o"
        else:
            assert p["raw"] == src[p["key"]]                                                # byte for byte
    assert GV.vocab_only_bytes(h, "gpt-oss", {"tokenizer.ggml.pre": "gpt-4o"}) == out     # deterministic


@pytest.mark.parametrize("data,match", [
    (b"GGML" + b"\x00" * 40, "magic"),
    (gguf(TOKEN_PAIRS)[:60], "truncated"),
    (gguf(TOKEN_PAIRS, version=1), "version"),
    (gguf(TOKEN_PAIRS + TOKEN_PAIRS[2:3]), "duplicate"),
    (gguf([("x", 99, b"")]), "value type"),
])
def test_gguf_reader_refusals(data, match):
    with pytest.raises(GV.GGUFError, match=match):
        GV.parse_kv_bytes(data)


def test_vocab_only_refusals():
    h = GV.parse_kv_bytes(gguf(TOKEN_PAIRS))
    with pytest.raises(GV.GGUFError, match="not in the source"):
        GV.vocab_only_bytes(h, "gpt-oss", {"tokenizer.ggml.nope": "x"})
    with pytest.raises(GV.GGUFError, match="not a string"):
        GV.vocab_only_bytes(h, "gpt-oss", {"tokenizer.ggml.add_bos_token": "x"})
    with pytest.raises(GV.GGUFError, match="no tokenizer"):
        GV.vocab_only_bytes(GV.parse_kv_bytes(gguf(TOKEN_PAIRS[:2])), "gpt-oss", {})


@pytest.fixture
def blob(tmp_path, monkeypatch):
    data = gguf(TOKEN_PAIRS)
    w = sha(data)
    d = tmp_path / "blobs"
    d.mkdir()
    path = d / f"sha256-{w}"
    path.write_bytes(data)
    derived = GV.vocab_only_bytes(GV.read_kv(str(path)), "gpt-oss", {"tokenizer.ggml.pre": "gpt-4o"})
    monkeypatch.setitem(H.DERIVED_VOCAB_SHA256, w, sha(derived))
    monkeypatch.setenv(H.ENV_VOCAB_DIR, str(tmp_path / "vocab"))
    return {"path": str(path), "sha": w, "derived_sha": sha(derived), "tmp": tmp_path}


def test_derived_vocab_is_written_once_and_checked(blob):
    p, s = H.derived_vocab(blob["path"], blob["sha"])
    assert s == blob["derived_sha"] and sha(open(p, "rb").read()) == s
    mtime = os.stat(p).st_mtime_ns
    assert H.derived_vocab(blob["path"], blob["sha"])[0] == p and os.stat(p).st_mtime_ns == mtime   # reused
    with open(p, "ab") as f:
        f.write(b"tampered")
    p2, _ = H.derived_vocab(blob["path"], blob["sha"])                                            # derived again
    assert sha(open(p2, "rb").read()) == blob["derived_sha"]


def test_derived_vocab_refusals(blob, monkeypatch, tmp_path):
    with pytest.raises(T.TokenizerError, match="no verified tokenizer derivation"):
        H.derived_vocab(blob["path"], "f" * 64)
    other = tmp_path / "blobs" / "renamed"
    other.write_bytes(open(blob["path"], "rb").read())
    with pytest.raises(T.TokenizerError, match="is not the blob"):
        H.derived_vocab(str(other), blob["sha"])
    monkeypatch.setitem(H.DERIVED_VOCAB_SHA256, blob["sha"], "0" * 64)
    with pytest.raises(T.TokenizerError, match="is not the pinned"):
        H.derived_vocab(blob["path"], blob["sha"])
    assert not os.path.exists(os.path.join(str(tmp_path / "vocab"), "x"))


# ---------------------------------------------------------------- OllamaCounter for gpt-oss (fake store)

FAKE_TOKENIZE = r'''#!{python}
import json, os, sys
args = sys.argv[1:]
if "--version" in args:
    print("version: 0.0.0 (build 0, commit fake)", file=sys.stderr); sys.exit(0)
path = args[args.index("-m") + 1]
if b"gpt-oss" not in open(path, "rb").read(4096):
    print("unknown model architecture", file=sys.stderr); sys.exit(1)
text = sys.stdin.buffer.read().decode("utf-8")
special = "--no-parse-special" not in args
ids, i = [], 0
while i < len(text):
    if special and text.startswith("<|", i) and "|>" in text[i:]:
        j = text.index("|>", i) + 2; ids.append(200000); i = j
    else:
        ids.extend(text[i].encode("utf-8")); i += 1
print(json.dumps(ids))
'''


def make_store(root, blob_bytes, template, family="gptoss", tag="gpt-oss:20b"):
    blobs = root / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)

    def put(b):
        h = sha(b)
        (blobs / f"sha256-{h}").write_bytes(b)
        return "sha256:" + h

    layers = [{"mediaType": "application/vnd.ollama.image.model", "digest": put(blob_bytes)},
              {"mediaType": "application/vnd.ollama.image.template", "digest": put(template)},
              {"mediaType": "application/vnd.ollama.image.params", "digest": put(b'{"temperature":1}')},
              {"mediaType": "application/vnd.ollama.image.license", "digest": put(b"license")}]
    man = json.dumps({"schemaVersion": 2, "config": {"digest": put(json.dumps({"model_family": family}).encode())},
                      "layers": layers}).encode()
    name, ver = tag.split(":")
    mdir = root / "manifests" / "registry.ollama.ai" / "library" / name
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / ver).write_bytes(man)
    return sha(man)


@pytest.fixture
def store(tmp_path, monkeypatch, blob):
    data = open(blob["path"], "rb").read()
    models = tmp_path / "models"
    digests = {"base": make_store(models, data, open(BASE_TEMPLATE, "rb").read()),
               "alias": make_store(models, data, open(ALIAS_TEMPLATE, "rb").read(), tag=H.ALIAS_TAG),
               "wrongfamily": make_store(models, data, open(BASE_TEMPLATE, "rb").read(), family="qwen3", tag="odd:1")}
    monkeypatch.setenv(T.ENV_OLLAMA_MODELS, str(models))
    monkeypatch.setenv(T.ENV_LLAMA_TOKENIZE, write_exe(tmp_path / "llama-tokenize",
                                                       FAKE_TOKENIZE.replace("{python}", sys.executable)))
    return dict(digests, weights=blob["sha"], derived=blob["derived_sha"])


def _fake_len(text, special):
    n, i = 0, 0
    while i < len(text):
        if special and text.startswith("<|", i) and "|>" in text[i:]:
            n, i = n + 1, text.index("|>", i) + 2
        else:
            n, i = n + len(text[i].encode("utf-8")), i + 1
    return n


def test_counter_with_llama_tokenize_over_the_derived_file(store, monkeypatch):
    monkeypatch.setenv(H.ENV_TOKENIZER, "llama-tokenize")
    c = T.OllamaCounter(H.ALIAS_TAG, expect_digest=store["alias"])
    ident = c.identity()
    assert ident["renderer"] == H.RENDERER_GPTOSS and ident["template_sha256"] == H.ALIAS_TEMPLATE_SHA256
    assert ident["tokenizer"]["gguf_sha256"] == store["derived"]
    assert ident["tokenizer"]["derived_from"] == {"weights_sha256": store["weights"], "recipe": H.VOCAB_RECIPE}
    rec = c.local_tokens(MSGS, "answer", "low", thinking="plan")
    prompt, _ = T.TEMPLATE_RENDERERS[H.ALIAS_TEMPLATE_SHA256][1](MSGS, think="low")
    assert rec["rendered_prompt"] == _fake_len(prompt, True) and rec["current_date"] == H.FIXED_DATE
    assert rec["completion"] == 6 and rec["completion_thinking"] == 4 and rec["think"] == "low"
    assert rec["content_by_message"] == [len(m["content"].encode()) for m in MSGS]


def test_counter_base_template_uses_the_date_it_renders_with(store, monkeypatch):
    monkeypatch.setenv(H.ENV_TOKENIZER, "llama-tokenize")
    monkeypatch.setattr(H, "local_date", lambda: "2031-01-02")
    c = T.OllamaCounter("gpt-oss:20b", expect_digest=store["base"])
    assert c.local_tokens(MSGS, "", "low")["current_date"] == "2031-01-02"


def test_counter_refusals(store, monkeypatch):
    monkeypatch.setenv(H.ENV_TOKENIZER, "llama-tokenize")
    with pytest.raises(T.TokenizerError, match="family"):
        T.OllamaCounter("odd:1")
    with pytest.raises(T.TokenizerError, match="not the local manifest"):
        T.OllamaCounter("gpt-oss:20b", expect_digest="e" * 64)
    monkeypatch.setenv(H.ENV_TOKENIZER, "sentencepiece")
    with pytest.raises(T.TokenizerError, match=H.ENV_TOKENIZER):
        T.OllamaCounter("gpt-oss:20b")
    monkeypatch.setenv(H.ENV_TOKENIZER, "tiktoken")        # the fake blob was never checked against o200k_harmony
    with pytest.raises(T.TokenizerError, match="not checked against"):
        T.OllamaCounter("gpt-oss:20b")
    monkeypatch.setenv(H.ENV_TOKENIZER, "llama-tokenize")
    monkeypatch.setenv(T.ENV_LLAMA_TOKENIZE, "/nonexistent/llama-tokenize")
    with pytest.raises(T.TokenizerError, match="llama-tokenize not found"):
        T.OllamaCounter("gpt-oss:20b")


# ---------------------------------------------------------------- the tiktoken tokenizer (fake tiktoken)

FAKE_TIKTOKEN = '''
__version__ = "0.0-fake"
class Encoding:
    def __init__(self, name, pat_str, mergeable_ranks, special_tokens, explicit_n_vocab=None):
        self.name, self.special = name, special_tokens
        self.n_vocab = explicit_n_vocab or (len(mergeable_ranks) + len(special_tokens))
    def encode(self, text, allowed_special=set(), disallowed_special="all"):
        out, i = [], 0
        while i < len(text):
            hit = next((s for s in self.special if text.startswith(s, i)), None) if allowed_special == "all" else None
            if hit:
                out.append(self.special[hit]); i += len(hit)
            else:
                out.append(ord(text[i])); i += 1
        return out
'''
FAKE_LOAD = '''
def read_file(blobpath):
    raise AssertionError("network")
def load_tiktoken_bpe(blobpath, expected_hash=None):
    raise AssertionError("must be replaced by the helper")
'''
FAKE_PUBLIC = '''
from tiktoken.load import load_tiktoken_bpe
EXPECTED = "{expected}"
def o200k_base():
    ranks = load_tiktoken_bpe("https://example.invalid/o200k_base.tiktoken", expected_hash=EXPECTED)
    return {{"name": "o200k_base", "pat_str": "x", "mergeable_ranks": ranks, "special_tokens": {{}}}}
def o200k_harmony():
    b = o200k_base()
    return {{"name": "o200k_harmony", "pat_str": b["pat_str"], "mergeable_ranks": b["mergeable_ranks"],
            "special_tokens": {{"<|start|>": 200006, "<|end|>": 200007}}, "explicit_n_vocab": {n_vocab}}}
ENCODING_CONSTRUCTORS = {{"o200k_base": o200k_base, "o200k_harmony": o200k_harmony}}
'''


@pytest.fixture
def fake_tiktoken(tmp_path):
    enc = tmp_path / "o200k_base.tiktoken"
    enc.write_bytes(b"YQ== 0\nYg== 1\n")
    pkgs = tmp_path / "site"
    (pkgs / "tiktoken").mkdir(parents=True)
    (pkgs / "tiktoken_ext").mkdir()
    (pkgs / "tiktoken" / "__init__.py").write_text(FAKE_TIKTOKEN)
    (pkgs / "tiktoken" / "load.py").write_text(FAKE_LOAD)
    (pkgs / "tiktoken_ext" / "openai_public.py").write_text(
        FAKE_PUBLIC.format(expected=sha(enc.read_bytes()), n_vocab=H.TIKTOKEN_N_VOCAB))
    py = write_exe(tmp_path / "toolspy", f'#!/bin/sh\n[ "$1" = "-I" ] && shift\n'
                                         f'PYTHONPATH="{pkgs}" exec "{sys.executable}" "$@"\n')
    return {"python": py, "file": str(enc), "sha256": sha(enc.read_bytes()), "pkgs": pkgs}


def test_tiktoken_tokenizer_counts_ids_and_modes(fake_tiktoken):
    ft = fake_tiktoken
    t = H.HarmonyTiktokenTokenizer(ft["file"], ft["sha256"], python=ft["python"])
    try:
        assert t.identity()["encoding"] == "o200k_harmony" and t.identity()["version"] == "0.0-fake"
        assert t.count("ab<|start|>", parse_special=False) == 11 and t.count("ab<|start|>", parse_special=True) == 3
        assert t.ids("a<|end|>", parse_special=True) == [97, 200007] and t.count("") == 0
        assert t.counts([("x", False), ("y", True), ("x", False)]) == [1, 1, 1]
    finally:
        t.close()


def test_tiktoken_tokenizer_refuses_text_the_server_reads_otherwise(fake_tiktoken):
    ft = fake_tiktoken
    t = H.HarmonyTiktokenTokenizer(ft["file"], ft["sha256"], python=ft["python"])
    try:
        for txt in ("a [PAD7] b", "<|reserved_200019|>", "<|reserved_200018|>"):
            with pytest.raises(T.TokenizerError, match="tokenizes differently"):
                t.count(txt, parse_special=True)
            assert t.count(txt, parse_special=False) == len(txt)          # plain text: counted as text
        assert t.count("<|reserved_200013|>", parse_special=True) > 0    # the same name in both
    finally:
        t.close()


def test_tiktoken_tokenizer_refusals(fake_tiktoken, tmp_path):
    ft = fake_tiktoken
    with pytest.raises(T.TokenizerError, match="interpreter with tiktoken not found"):
        H.HarmonyTiktokenTokenizer(ft["file"], ft["sha256"], python=str(tmp_path / "nopython"))
    with pytest.raises(T.TokenizerError, match="encoding file not found"):
        H.HarmonyTiktokenTokenizer(str(tmp_path / "none.tiktoken"), ft["sha256"], python=ft["python"])
    with pytest.raises(T.TokenizerError, match="not the registered"):
        H.HarmonyTiktokenTokenizer(ft["file"], "a" * 64, python=ft["python"])
    with pytest.raises(T.TokenizerError, match="unknown encoding"):
        H.HarmonyTiktokenTokenizer(ft["file"], ft["sha256"], python=ft["python"], encoding="cl100k_base")


def test_registered_encoding_and_directory_override(monkeypatch, tmp_path):
    monkeypatch.delenv(H.ENV_TIKTOKEN_DIR, raising=False)
    path, s = H.registered_encoding()
    rec = json.load(open(os.path.join(ROOT, "configs", "venv_tools.json")))["tiktoken"]["encodings"]["o200k_base"]
    assert s == rec["sha256"] and path == os.path.join(ROOT, rec["file"])
    monkeypatch.setenv(H.ENV_TIKTOKEN_DIR, str(tmp_path))
    assert H.registered_encoding()[0] == os.path.join(str(tmp_path), os.path.basename(rec["file"]))


# ---------------------------------------------------------------- real: the host's store, llama.cpp and tiktoken

def _real_counter(tag):
    try:
        return T.OllamaCounter(tag)
    except T.TokenizerError as e:
        pytest.skip(f"real gpt-oss counter unavailable: {e}")


# the server's prompt_eval_count for self-made probes (experiments/20260929-gptoss-20b-think-probe, E23 record)
Q1 = "What is 17 + 25? Reply with only the number."
Q2 = ("A workshop makes chairs and tables. A chair needs 2 units of wood and 1 hour of labor and sells for 40 dollars. "
      "A table needs 5 units of wood and 2 hours of labor and sells for 100 dollars. There are 40 units of wood and "
      "18 hours of labor. How many chairs and tables maximize revenue, and what is the revenue?")
SERVER_COUNTS = [(Q1, None, 81), (Q1, False, 76), (Q1, True, 81), (Q1, "low", 81), (Q1, "medium", 81),
                 (Q1, "high", 81), (Q2, "low", 144), (Q2, False, 139)]
# the server's own token ids for the Q1 prompt with think "low" (/api/generate context, both tags)
SERVER_IDS_HEAD = [200006, 17360, 200008, 3575, 553, 17554, 162016, 11, 261, 4410, 6439, 2359]
SERVER_IDS_TAIL = [2086, 13, 200007, 200006, 173781]


@pytest.mark.parametrize("tag", ["gpt-oss:20b", H.ALIAS_TAG])
def test_real_counts_equal_the_server(tag):
    c = _real_counter(tag)
    for q, think, n in SERVER_COUNTS:
        assert c.count_prompt([{"role": "user", "content": q}], think)[0] == n, (think, n)


def test_real_ids_equal_the_server_ids():
    c = _real_counter(H.ALIAS_TAG)
    prompt, _ = c.render([{"role": "user", "content": Q1}], "low")
    ids = c.tok.ids(prompt, parse_special=True)
    assert len(ids) == 81 and ids[:12] == SERVER_IDS_HEAD and ids[-5:] == SERVER_IDS_TAIL


def test_real_count_does_not_depend_on_the_date():
    c = _real_counter("gpt-oss:20b")
    msgs = [{"role": "system", "content": "Solve."}, {"role": "user", "content": Q2}]
    counts = set()
    for d in ("2026-09-29", "2026-12-31", "2027-01-01", "2030-10-10", "2099-02-28", "2000-01-01"):
        prompt, _ = H.render_gptoss(msgs, think="low", current_date=d)
        counts.add(c.tok.count(prompt, parse_special=True))
    assert len(counts) == 1


# ---------------------------------------------------------------- the registry entry gptoss-20b.main

REGISTRY = os.path.join(ROOT, "configs", "model_registry.json")


def _reg():
    return json.load(open(REGISTRY, encoding="utf-8"))


def test_registry_entry_decisions():
    reg = _reg()
    e = reg["entries"]["gptoss-20b.main"]
    assert e["backend"] == "ollama" and e["model"] == H.ALIAS_TAG and e["seed_rule"] == "base+k"
    assert e["opts"] == {"temperature": 0.0, "top_k": 40, "top_p": 0.9, "seed": 1, "num_ctx": 32768,
                         "num_predict": 6000, "think": "low", "keep_alive": 0}
    q = reg["entries"]["qwen3-8b.main"]["opts"]
    for k in ("temperature", "seed", "num_ctx", "num_predict", "keep_alive"):     # same settings as the main model
        assert e["opts"][k] == q[k], k
    assert not MR.entry_pending(e)              # num_predict fixed 2026-10-06 from the dev rehearsal (none of 93 calls at the limit)
    ident = e["identity"]
    assert ident["weights_blob_sha256"] == H.GPTOSS_WEIGHTS_SHA256
    assert ident["template_blob_sha256"] == H.ALIAS_TEMPLATE_SHA256 and ident["family"] == "gptoss"
    assert ident["inherited_by_calls"] == {} and ident["modelfile_params"] == {"temperature": 1}
    assert ident["ollama_version"] == "0.33.0" and ident["server"]["kv_cache_type"] == "q8_0"


def test_registry_models_alias_and_base():
    reg = _reg()
    alias, base = reg["models"][H.ALIAS_TAG], reg["models"]["gpt-oss:20b"]
    assert alias["modelfile_sha256"] == sha(open(MODELFILE, "rb").read())
    assert alias["digest"] == reg["entries"]["gptoss-20b.main"]["digest"]
    assert alias["template_blob_sha256"] == alias["show_template_sha256"] == H.ALIAS_TEMPLATE_SHA256
    assert base["digest"] == H.GPTOSS_MANIFEST_SHA256 and base["template_blob_sha256"] == H.GPTOSS_TEMPLATE_SHA256
    assert base["weights_blob_sha256"] == alias["weights_blob_sha256"] == H.GPTOSS_WEIGHTS_SHA256
    assert base["same_weights_as"] == H.ALIAS_TAG and base["quantization_level"] == "MXFP4"
    for k in ("params_blob_sha256", "license_blob_sha256", "params"):     # the alias changes nothing but the template
        assert alias[k] == base[k], k


def test_registry_tokenizer_record_matches_the_code():
    t = _reg()["tokenizers"]["gpt_oss"]
    assert t["default"] == H.DEFAULT_TOKENIZER
    assert set(t["templates"]) == set(H.GPTOSS_TEMPLATES)
    assert t["llama_tokenize"]["recipe"] == H.VOCAB_RECIPE
    assert t["llama_tokenize"]["derived_gguf_sha256"] == H.DERIVED_VOCAB_SHA256[H.GPTOSS_WEIGHTS_SHA256]
    assert t["tiktoken"]["encoding_sha256"] == H.registered_encoding()[1] and t["tiktoken"]["encoding"] == H.TIKTOKEN_ENCODING


def test_registry_is_valid_and_the_guard_uses_the_entry():
    reg = _reg()
    assert MR.validate(reg) == []
    e = reg["entries"]["gptoss-20b.main"]
    b = OllamaBackend(H.ALIAS_TAG, host="http://127.0.0.1:9")
    b._identity = {"digest": e["digest"]}
    for k in range(2):
        sent = b.sent_opts(b.build_body(MSGS, dict(e["opts"], seed=1 + k)))
        registry_guard(e, backend=b, repeat_index=k)(sent)
    for bad in (dict(e["opts"], think="medium"), dict(e["opts"], think=False), dict(e["opts"], num_ctx=16384)):
        with pytest.raises(RegistryMismatch):
            registry_guard(e, backend=b)(b.sent_opts(b.build_body(MSGS, bad)))
    b._identity = {"digest": H.GPTOSS_MANIFEST_SHA256}          # the base tag's digest is not the entry's
    with pytest.raises(RegistryMismatch, match="digest"):
        registry_guard(e, backend=b)(b.sent_opts(b.build_body(MSGS, e["opts"])))

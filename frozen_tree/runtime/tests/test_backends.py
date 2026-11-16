"""E08: backends with one call interface, explicit options on every call, per-call records, resume and registry refusals.

Everything runs against fake HTTP servers (Ollama, OpenAI-compatible, llama-server) in this process; no model is
called. Fixtures are self-made strings and the author-written smoke case only.
"""
import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import paths as PA  # noqa: E402
from orgene.backends import make_backend  # noqa: E402
from orgene.backends.base import (FORBIDDEN_CALL_FIELDS, OptionsError, RegistryMismatch, missing_call_fields,  # noqa: E402
                                  registry_guard, request_sha256)
from orgene.backends.ollama import OllamaBackend, parse_keep_alive, parse_modelfile_parameters  # noqa: E402
from orgene.backends.openai_compat import OpenAICompatBackend  # noqa: E402
from orgene.backends.llamacpp import LlamaCppBackend  # noqa: E402
from orgene.selftest import GOOD_CODE  # noqa: E402

OLLAMA_RUNNER = os.path.join(RUNTIME, "ollama_runner.py")
API_RUNNER = os.path.join(RUNTIME, "api_runner.py")
CLI = os.path.join(RUNTIME, "orgene_cli.py")
SMOKE_CASES = os.path.join(ROOT, "data", "cases", "smoke.jsonl")
MODEL = "fake-model:8b"
DIGEST = "d1" * 32
MODELFILE_PARAMS = 'repeat_penalty                 1\nstop                           "<|im_start|>"\nstop                           "<|im_end|>"\ntemperature                    0.6\ntop_k                          20\ntop_p                          0.95'
MSGS = [{"role": "system", "content": "You write PuLP programs."}, {"role": "user", "content": "Maximise 3x with x <= 2."}]
FULL_OPTS = {"temperature": 0.0, "top_k": 20, "top_p": 0.95, "seed": 1, "num_ctx": 32768, "num_predict": 6000, "think": False}
ANSWER = "```python\n" + GOOD_CODE + "```"


# ---------------------------------------------------------------------------------------------- fake servers


class FakeServer:
    """A tiny HTTP server whose behaviour is set by attributes; records every POST body per path."""

    def __init__(self):
        self.posts = {}  # path -> [body]
        self.headers_seen = []
        self.fail_next = 0  # respond 500 to the next n chat calls
        self.fail_error = "boom"
        self.digest = DIGEST
        self.digest_after_first_chat = None
        self.reject = None  # (substring of a body key, http code, message) for OpenAI-style 400s
        fs = self

        class H(BaseHTTPRequestHandler):
            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send(*fs.get(self.path))

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n))
                fs.posts.setdefault(self.path, []).append(body)
                fs.headers_seen.append(dict(self.headers))
                self._send(*fs.post(self.path, body))

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def n(self, path):
        return len(self.posts.get(path, []))

    def close(self):
        self.srv.shutdown()

    # Ollama + llama-server + OpenAI behaviour in one place
    def get(self, path):
        if path == "/api/version":
            return 200, {"version": "0.33.0"}
        if path == "/api/tags":
            return 200, {"models": [{"name": MODEL, "model": MODEL, "digest": self.digest, "size": 5,
                                     "modified_at": "2026-01-01T00:00:00Z", "details": {"quantization_level": "Q4_K_M"}}]}
        if path == "/api/ps":
            return 200, {"models": [{"name": "other-project-model:1b", "digest": "e" * 64, "expires_at": "x"}]}
        if path == "/props":
            return 200, {"model_path": "/" + "Users" + "/someone/models/anchor-q8_0.gguf", "build_info": "b9999-abc",
                         "chat_template": "{{ messages }}", "default_generation_settings": {"n_ctx": 8192}}
        return 404, {"error": "not found"}

    def post(self, path, body):
        if path == "/api/show":
            return 200, {"capabilities": ["completion"], "parameters": MODELFILE_PARAMS, "template": "{{ .Prompt }}"}
        if path == "/api/chat":
            if self.fail_next:
                self.fail_next -= 1
                return 500, {"error": self.fail_error}
            if self.digest_after_first_chat and self.n("/api/chat") == 1:
                self.digest = self.digest_after_first_chat
            return 200, {"model": body["model"], "created_at": "2026-01-01T00:00:01Z",
                         "message": {"role": "assistant", "content": ANSWER}, "done": True, "done_reason": "stop",
                         "prompt_eval_count": 11, "eval_count": 7, "load_duration": 1_000_000_000,
                         "prompt_eval_duration": 2000, "eval_duration": 3000, "total_duration": 1_000_009_000}
        if path == "/v1/messages":
            return 200, {"id": "msg-1", "model": body["model"], "stop_reason": "end_turn",
                         "content": [{"type": "text", "text": ANSWER}], "usage": {"input_tokens": 12, "output_tokens": 21}}
        if path.endswith("/chat/completions"):
            if self.reject and self.reject[0] in body:
                return self.reject[1], {"error": {"message": self.reject[2]}}
            return 200, {"id": "cmpl-1", "model": body["model"] + "-2026-01-01", "system_fingerprint": "fp_test",
                         "choices": [{"message": {"content": ANSWER}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 10, "completion_tokens": 20},
                         "timings": {"prompt_ms": 1.5, "predicted_ms": 2.5}}
        return 404, {"error": "not found"}


@pytest.fixture
def fake():
    s = FakeServer()
    yield s
    s.close()


def _ollama(fake, **kw):
    kw.setdefault("retry_sleep", 0)
    return OllamaBackend(MODEL, host=fake.url, **kw)


def _iso(s):
    return datetime.fromisoformat(s)


# ---------------------------------------------------------------------------------------------- Ollama backend


def test_ollama_call_sends_every_option_explicitly_and_records_the_call(fake):
    b = _ollama(fake)
    rec = b.call(MSGS, dict(FULL_OPTS, temperature=0.7, seed=5))
    body = fake.posts["/api/chat"][0]
    assert body["options"] == {"temperature": 0.7, "top_k": 20, "top_p": 0.95, "seed": 5, "num_ctx": 32768, "num_predict": 6000}
    assert body["think"] is False and body["keep_alive"] == 0 and body["stream"] is False
    assert body["messages"] == MSGS and body["model"] == MODEL
    assert missing_call_fields(rec) == []
    assert not any(k in rec for k in FORBIDDEN_CALL_FIELDS)
    assert rec["seed"] == 5 and rec["digest"] == DIGEST and rec["backend"] == "ollama"
    assert rec["request_sha256"] == request_sha256(body)
    assert _iso(rec["started_at"]) <= _iso(rec["finished_at"])
    assert rec["done_reason"] == "stop" and rec["prompt_eval_count"] == 11 and rec["eval_count"] == 7
    assert rec["load_duration_ns"] == 1_000_000_000 and rec["total_duration_source"] == "server"
    assert rec["sent_opts"] == dict(body["options"], think=False, keep_alive=0)
    assert rec["local_tokens"] is None and rec["local_tokens_counter"] is None


@pytest.mark.parametrize("key", ["temperature", "top_k", "top_p", "seed", "num_ctx", "num_predict", "think"])
def test_ollama_refuses_a_missing_option_before_sending(fake, key):
    b = _ollama(fake)
    opts = dict(FULL_OPTS)
    opts.pop(key)
    with pytest.raises(OptionsError):
        b.call(MSGS, opts)
    assert fake.n("/api/chat") == 0


@pytest.mark.parametrize("bad", [{"num_predic": 6000}, {"top_k": 20.5}, {"seed": True}, {"think": 0},
                                 {"temperature": "0"}, {"keep_alive": "soon"}, {"num_ctx": None},
                                 {"temperature": float("nan")}, {"top_p": float("inf")}, {"num_ctx": float("inf")},
                                 {"keep_alive": float("nan")}])
def test_ollama_refuses_unknown_or_mistyped_options(fake, bad):
    with pytest.raises(OptionsError):
        _ollama(fake).call(MSGS, dict(FULL_OPTS, **bad))
    assert fake.n("/api/chat") == 0


def test_keep_alive_parsing():
    assert parse_keep_alive(None) == 0 and parse_keep_alive("0") == 0 and parse_keep_alive(0) == 0
    assert parse_keep_alive("30m") == "30m" and parse_keep_alive("-1") == -1 and parse_keep_alive("1h30m") == "1h30m"
    for bad in ("abc", True, 1.5, "30 minutes"):
        with pytest.raises(OptionsError):
            parse_keep_alive(bad)


def test_request_hash_is_canonical():
    b = OllamaBackend(MODEL, host="http://127.0.0.1:9")
    h = lambda opts, msgs=MSGS: request_sha256(b.build_body(msgs, opts))  # noqa: E731
    base = h(FULL_OPTS)
    assert h(dict(FULL_OPTS, temperature=0)) == base            # 0 and 0.0 are the same setting
    assert h(dict(FULL_OPTS, keep_alive="30m")) == base         # transport-only field
    assert h(dict(FULL_OPTS, seed=2)) != base
    assert h(dict(FULL_OPTS, think=True)) != base
    assert h(FULL_OPTS, MSGS[:1] + [{"role": "user", "content": "Maximise 3x with x <= 3."}]) != base


def test_retries_are_recorded_per_attempt(fake):
    fake.fail_next = 1
    rec = _ollama(fake, max_attempts=2).call(MSGS, FULL_OPTS)
    assert rec["ok"] and [a["ok"] for a in rec["attempts"]] == [False, True]
    assert all(a["started_at"] and a["finished_at"] for a in rec["attempts"]) and "HTTP 500" in rec["attempts"][0]["error"]
    fake.fail_next = 1
    rec = _ollama(fake, max_attempts=1).call(MSGS, FULL_OPTS)
    assert rec["ok"] is False and rec["content"] == "" and rec["content_sha256"] is None and len(rec["attempts"]) == 1
    assert missing_call_fields(rec) == []


def test_error_texts_in_records_carry_no_home_paths(fake):
    """Server and tokenizer errors often quote a model file path under the user's home directory."""
    blob = "/" + "Users" + "/someone/.ollama/models/blobs/sha256-abc123"
    fake.fail_next, fake.fail_error = 1, f"llama runner process has terminated: error loading model {blob}"

    def broken(**kw):
        raise FileNotFoundError(f"no tokenizer at {blob}")

    rec = _ollama(fake, max_attempts=2, token_counter=broken, token_counter_id="tests:broken").call(MSGS, FULL_OPTS)
    assert rec["ok"] and "error loading model" in rec["attempts"][0]["error"]
    assert "sha256-abc123" in rec["attempts"][0]["error"] and "sha256-abc123" in rec["local_tokens_error"]
    assert not PA.find_absolute_paths(json.dumps(rec)) and "someone" not in json.dumps(rec)


def test_modelfile_parameters_that_still_apply_are_reported(fake):
    p = parse_modelfile_parameters(MODELFILE_PARAMS)
    assert p == {"repeat_penalty": 1, "stop": ["<|im_start|>", "<|im_end|>"], "temperature": 0.6, "top_k": 20, "top_p": 0.95}
    b = _ollama(fake)
    sent = b.sent_opts(b.build_body(MSGS, FULL_OPTS))
    assert b.inherited_defaults(sent) == {"repeat_penalty": 1, "stop": ["<|im_start|>", "<|im_end|>"]}


def test_loaded_models_reads_api_ps(fake):
    assert _ollama(fake).loaded_models()[0]["name"] == "other-project-model:1b"


# ---------------------------------------------------------------------------------------------- registry guard


REG_ENTRY = {"backend": "ollama", "model": MODEL, "digest": DIGEST, "seed_rule": "base+k",
             "opts": {"temperature": 0, "top_k": 20, "top_p": 0.95, "seed": 1, "num_ctx": 32768, "num_predict": 6000,
                      "think": False, "keep_alive": 0}}


def test_registry_guard_accepts_exactly_the_registered_settings(fake):
    b = _ollama(fake)
    sent = b.sent_opts(b.build_body(MSGS, FULL_OPTS))
    registry_guard(REG_ENTRY, backend=b, repeat_index=0)(sent)
    sent_k1 = b.sent_opts(b.build_body(MSGS, dict(FULL_OPTS, seed=2)))
    registry_guard(REG_ENTRY, backend=b, repeat_index=1)(sent_k1)  # seed = base + k


@pytest.mark.parametrize("change", [
    {"opts": dict(REG_ENTRY["opts"], num_ctx=16384)},
    {"opts": dict(REG_ENTRY["opts"], keep_alive="30m")},
    {"opts": dict(REG_ENTRY["opts"], think=0)},                           # a boolean is not a number
    {"opts": {k: v for k, v in REG_ENTRY["opts"].items() if k != "top_p"}},  # registry must cover every sent key
    {"digest": "f" * 64},
    {"model": "other:8b"},
    {"seed_rule": "fixed", "opts": dict(REG_ENTRY["opts"], seed=1)},     # fixed seed 1 but repeat 1 sends 2
])
def test_registry_guard_refuses_any_difference_before_sending(fake, change):
    b = _ollama(fake)
    entry = dict(REG_ENTRY, **change)
    k = 1 if "seed_rule" in change else 0
    with pytest.raises(RegistryMismatch):
        b.call(MSGS, dict(FULL_OPTS, seed=1 + k), guard=registry_guard(entry, backend=b, repeat_index=k))
    assert fake.n("/api/chat") == 0


# ---------------------------------------------------------------------------------------------- local token hook


def test_local_token_counter_hook(fake):
    seen = []

    def counter(messages, completion, backend, model, think, thinking):
        seen.append((len(messages), completion[:9], backend, model, think, thinking))
        return {"content_by_message": [len(m["content"]) for m in messages], "completion": len(completion)}

    rec = _ollama(fake, token_counter=counter, token_counter_id="tests:counter").call(MSGS, FULL_OPTS)
    assert rec["local_tokens"] == {"content_by_message": [24, 24], "completion": len(ANSWER)}
    assert rec["local_tokens_counter"] == "tests:counter" and rec["local_tokens_error"] is None
    assert seen == [(2, "```python", "ollama", MODEL, False, None)]

    def broken(**kw):
        raise FileNotFoundError("tokenizer file missing")

    rec = _ollama(fake, token_counter=broken, token_counter_id="tests:broken").call(MSGS, FULL_OPTS)
    assert rec["local_tokens"] is None and "tokenizer file missing" in rec["local_tokens_error"]


class _ObjCounter:
    """Same shape as orgene.tokcount's counters: local_tokens(messages, completion, think=, thinking=) + identity()."""

    def __init__(self, tag="tok-v1"):
        self.tag, self.calls = tag, []

    def identity(self):
        return {"tokenizer": "toy", "vocab_sha256": self.tag}

    def local_tokens(self, messages, completion, think=None, thinking=None):
        self.calls.append(think)
        return {"content_by_message": [len(m["content"].split()) for m in messages], "rendered_prompt": 99,
                "completion": len(completion.split())}


def test_object_counter_is_recorded_and_pinned_for_resume(fake, tmp_path):
    from orgene import runner as RN
    reqs = RN.load_requests(str(_requests_file(tmp_path, 2)))
    out = str(tmp_path / "gen")
    b = _ollama(fake, token_counter=_ObjCounter())
    assert RN.run_batch(b, reqs[:1], out, FULL_OPTS, requests_path=str(tmp_path / "requests.C0.jsonl")) == 0
    rec = json.load(open(os.path.join(out, "outputs", "toy-000.C0.r0.json")))
    assert rec["local_tokens"]["rendered_prompt"] == 99 and rec["local_tokens_counter"] == "_ObjCounter"
    assert b.token_counter.calls == [False, False]            # start-up probe + the call; think passed through
    cfg = json.load(open(os.path.join(out, "config.json")))
    assert cfg["local_tokenizer"] == {"tokenizer": "toy", "vocab_sha256": "tok-v1"}
    # a different tokenizer must not continue the same directory
    b2 = _ollama(fake, token_counter=_ObjCounter("tok-v2"))
    with pytest.raises(SystemExit, match="local_tokenizer"):
        RN.run_batch(b2, reqs, out, FULL_OPTS, requests_path=str(tmp_path / "requests.C0.jsonl"))
    assert fake.n("/api/chat") == 1


class _FlakyCounter(_ObjCounter):
    """An object counter that raises on the given invocations (0 is the runner's start-up probe)."""

    def __init__(self, fail_on=()):
        super().__init__()
        self.fail_on, self.n = set(fail_on), -1

    def local_tokens(self, messages, completion, think=None, thinking=None):
        self.n += 1
        if self.n in self.fail_on:
            raise RuntimeError("tokenizer hiccup")
        return super().local_tokens(messages, completion, think=think, thinking=thinking)


def test_metrics_count_answered_calls_without_local_tokens(fake, tmp_path):
    """Wave1 follow-up A5: a counter failure on one call keeps the answer (E08) and is counted in metrics.json, where
    the dev rehearsal's record-field check (plan 5.2, item 5) reads it through runner.local_token_gaps."""
    from orgene import runner as RN
    reqs = RN.load_requests(str(_requests_file(tmp_path, 3)))
    out = str(tmp_path / "gen")
    assert RN.run_batch(_ollama(fake, token_counter=_FlakyCounter(fail_on={2})), reqs, out, FULL_OPTS) == 0
    met = json.load(open(os.path.join(out, "metrics.json")))
    assert met["n_calls"] == met["n_answered_calls"] == 3 and met["n_calls_missing_local_tokens"] == 1
    assert met["local_tokens_counter"] == "_FlakyCounter"
    assert met["local_tokens_missing"] == {"calls": ["toy-001.C0.r0"], "n_listed": 1, "reasons": {"RuntimeError": 1}}
    rec = json.load(open(os.path.join(out, "outputs", "toy-001.C0.r0.json")))
    assert rec["ok"] and rec["content"] == ANSWER and "tokenizer hiccup" in rec["local_tokens_error"]
    keys = ("local_tokens_counter", "n_answered_calls", "n_calls_missing_local_tokens", "local_tokens_missing")
    gaps = RN.local_token_gaps(out)
    assert gaps["source"] == "metrics.json" and {k: gaps[k] for k in keys} == {k: met[k] for k in keys}
    # a directory written before these fields existed is recomputed from its call records
    json.dump({k: v for k, v in met.items() if k not in keys}, open(os.path.join(out, "metrics.json"), "w"))
    gaps = RN.local_token_gaps(out)
    assert gaps["source"] == "outputs" and {k: gaps[k] for k in keys} == {k: met[k] for k in keys}


def test_metrics_without_a_counter_and_failed_calls(fake, tmp_path):
    from orgene import runner as RN
    reqs = RN.load_requests(str(_requests_file(tmp_path, 2)))
    out = str(tmp_path / "gen")
    fake.fail_next = 2  # both attempts of the first request fail: no answer, so nothing to count locally
    assert RN.run_batch(_ollama(fake), reqs, out, FULL_OPTS) == 0
    met = json.load(open(os.path.join(out, "metrics.json")))
    assert (met["n_calls"], met["n_ok"], met["n_answered_calls"], met["n_calls_missing_local_tokens"]) == (2, 1, 1, 1)
    assert met["local_tokens_counter"] is None and met["local_tokens_missing"]["reasons"] == {"no counter": 1}
    assert met["local_tokens_missing"]["calls"] == ["toy-001.C0.r0"]


# ---------------------------------------------------------------------------------------------- batch runner (subprocess)


def _requests_file(tmp_path, n=2):
    p = tmp_path / "requests.C0.jsonl"
    p.write_text("".join(json.dumps({"request_id": f"toy-{i:03d}.C0", "case_id": f"toy-{i:03d}", "condition": "C0",
                                     "messages": MSGS, "meta": {"round": 0}}) + "\n" for i in range(n)))
    return p


def _run(script, *args, env=None):
    if script == OLLAMA_RUNNER and "--local-tokens" not in args and "--token-counter" not in args:
        # the fake server has no local model store or llama-tokenize, so these runs go without the built-in local
        # counter (E09, on by default); test_tokcount.py runs the runner with it against a fake store
        args = ("--local-tokens", "off") + args
    return subprocess.run([sys.executable, script, *map(str, args)], capture_output=True, text=True, timeout=120,
                          env=dict(os.environ, **(env or {})))


def _all_text(d):
    out = {}
    for dirpath, _, files in os.walk(d):
        for fn in files:
            p = os.path.join(dirpath, fn)
            out[os.path.relpath(p, d)] = open(p, encoding="utf-8", errors="replace").read()
    return out


def test_ollama_runner_writes_complete_call_records_and_resumes(fake, tmp_path):
    reqs, out = _requests_file(tmp_path), tmp_path / "gen.C0.r0"
    p = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", out, "--repeat", 2)
    assert p.returncode == 0, p.stderr
    bodies = fake.posts["/api/chat"]
    assert [b["options"]["seed"] for b in bodies] == [1, 2, 1, 2]           # seed = base + repeat index
    assert all(b["keep_alive"] == 0 and b["think"] is False for b in bodies)  # defaults: cold load, no thinking
    assert all(b["options"]["num_ctx"] == 32768 and b["options"]["top_k"] == 20 and b["options"]["top_p"] == 0.95 for b in bodies)
    recs = [json.load(open(out / "outputs" / f"toy-{i:03d}.C0.r{k}.json")) for i in range(2) for k in range(2)]
    for rec, body in zip(recs, bodies):
        assert missing_call_fields(rec) == [], rec
        assert rec["request_sha256"] == request_sha256(body) and rec["seed"] == body["options"]["seed"]
        assert rec["digest"] == DIGEST and rec["meta"] == {"round": 0}
    receipts = [json.loads(l) for l in open(out / "receipts.jsonl")]
    assert len(receipts) == 4 and all(r["started_at"] and r["finished_at"] and r["request_sha256"] and r["seed"] for r in receipts)
    cfg = json.load(open(out / "config.json"))
    assert cfg["opts"] == {"temperature": 0.0, "top_k": 20, "top_p": 0.95, "num_ctx": 32768, "num_predict": 6000,
                           "think": False, "keep_alive": 0}
    assert cfg["seed_base"] == 1 and cfg["identity"]["digest"] == DIGEST
    assert cfg["inherited_server_defaults"] == {"repeat_penalty": 1, "stop": ["<|im_start|>", "<|im_end|>"]}
    assert cfg["server_state_at_start"] == {"n_loaded": 1, "this_model_loaded": False, "n_other_models_loaded": 1}
    assert cfg["argv"][0] == "$R1/runtime/ollama_runner.py" and cfg["requests_path"] == "<outside-root>/requests.C0.jsonl"
    assert set(cfg["code_sha256"]) == {"runtime/ollama_runner.py", "runtime/orgene/runner.py",
                                       "runtime/orgene/backends/base.py", "runtime/orgene/backends/ollama.py"}
    met = json.load(open(out / "metrics.json"))
    assert met["n_calls"] == 4 and met["n_ok"] == 4 and met["identity_changed"] is False and met["total_model_load_seconds"] == 4.0
    texts = _all_text(out)
    for name, text in texts.items():
        assert "parse_ok" not in text and "parse_rate" not in text, name
        assert not PA.find_absolute_paths(text) and str(tmp_path) not in text, name
        assert "other-project-model" not in text, name   # other users' models are counted, never named
    # resume: nothing new is sent
    p2 = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", out, "--repeat", 2)
    assert p2.returncode == 0 and "already_done=4" in p2.stdout and fake.n("/api/chat") == 4


@pytest.mark.parametrize("changed", [["--top-p", "0.9"], ["--keep-alive", "30m"], ["--num-ctx", "16384"], ["--think"],
                                     ["--seed", "7"], ["--temperature", "0.7"]])
def test_ollama_runner_refuses_resume_when_a_setting_changes(fake, tmp_path, changed):
    reqs, out = _requests_file(tmp_path, 1), tmp_path / "gen"
    assert _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", out).returncode == 0
    before = open(out / "config.json").read()
    p = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", out, *changed)
    assert p.returncode != 0 and "resume refused" in p.stderr
    assert fake.n("/api/chat") == 1 and open(out / "config.json").read() == before


def _registry(tmp_path, **change):
    p = tmp_path / "model_registry.json"
    p.write_text(json.dumps({"entries": {"fake.main": dict(REG_ENTRY, **change)}}))
    return p


def test_ollama_runner_with_a_matching_registry_entry(fake, tmp_path):
    reqs, out = _requests_file(tmp_path, 1), tmp_path / "gen"
    reg = _registry(tmp_path)
    p = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", out, "--repeat", 2,
             "--registry", reg, "--registry-entry", "fake.main")
    assert p.returncode == 0, p.stderr
    cfg = json.load(open(out / "config.json"))
    assert cfg["registry"]["entry_id"] == "fake.main" and len(cfg["registry"]["entry_sha256"]) == 64
    assert cfg["registry"]["path"] == "<outside-root>/model_registry.json"


def test_registry_resume_depends_on_the_entry_not_on_the_rest_of_the_file(fake, tmp_path):
    reqs, out = _requests_file(tmp_path, 2), tmp_path / "gen"
    reg = _registry(tmp_path)
    args = ("--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", out, "--registry", reg, "--registry-entry", "fake.main")
    assert _run(OLLAMA_RUNNER, *args, "--limit", 1).returncode == 0
    doc = json.loads(reg.read_text())
    doc["entries"]["api.later"] = {"backend": "openai_compat", "model": "m", "opts": {}}
    reg.write_text(json.dumps(doc))                  # another entry added: the run may still resume
    p = _run(OLLAMA_RUNNER, *args)
    assert p.returncode == 0 and "already_done=1" in p.stdout and fake.n("/api/chat") == 2
    doc["entries"]["fake.main"]["opts"]["num_predict"] = 4000
    reg.write_text(json.dumps(doc))                  # the run's own entry changed: refused
    p = _run(OLLAMA_RUNNER, *args)
    assert p.returncode != 0 and fake.n("/api/chat") == 2


@pytest.mark.parametrize("change", [{"opts": dict(REG_ENTRY["opts"], num_ctx=16384)}, {"digest": "f" * 64},
                                    {"opts": dict(REG_ENTRY["opts"], keep_alive="30m")}])
def test_ollama_runner_refuses_settings_that_differ_from_the_registry(fake, tmp_path, change):
    reqs, out = _requests_file(tmp_path, 1), tmp_path / "gen"
    p = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", out,
             "--registry", _registry(tmp_path, **change), "--registry-entry", "fake.main")
    assert p.returncode != 0 and "registry" in p.stderr
    assert fake.n("/api/chat") == 0 and not (out / "receipts.jsonl").exists()


def test_ollama_runner_checks_every_repeat_against_the_registry_before_any_call(fake, tmp_path):
    """A "fixed" seed rule with --repeat 2: repeat 1 would send seed 2, so the run is refused before the first call."""
    reqs, out = _requests_file(tmp_path, 1), tmp_path / "gen"
    p = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", out, "--repeat", 2,
             "--registry", _registry(tmp_path, seed_rule="fixed"), "--registry-entry", "fake.main")
    assert p.returncode != 0 and "repeat 1" in p.stderr and "registry" in p.stderr
    assert fake.n("/api/chat") == 0 and not (out / "receipts.jsonl").exists()
    # the same entry is fine for a single repeat
    p = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", tmp_path / "gen1",
             "--registry", _registry(tmp_path, seed_rule="fixed"), "--registry-entry", "fake.main")
    assert p.returncode == 0, p.stderr
    assert fake.n("/api/chat") == 1


def test_ollama_runner_flags_a_model_that_changes_during_the_run(fake, tmp_path):
    fake.digest_after_first_chat = "c" * 64
    reqs, out = _requests_file(tmp_path, 2), tmp_path / "gen"
    p = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", out)
    assert p.returncode == 3 and "identity changed" in p.stderr
    met = json.load(open(out / "metrics.json"))
    assert met["identity_changed"] is True and met["identity_drift"]["digest"] == {"start": DIGEST, "end": "c" * 64}


def test_ollama_runner_local_token_counter_option(fake, tmp_path):
    reqs = _requests_file(tmp_path, 1)
    # required but not configured -> refused before any call
    p = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", tmp_path / "g0", "--require-local-tokens")
    assert p.returncode != 0 and "no --token-counter" in p.stderr and fake.n("/api/chat") == 0
    mod = tmp_path / "toycount.py"
    mod.write_text("def count(messages, completion, **kw):\n"
                   "    return {'content_by_message': [len(m['content'].split()) for m in messages], 'completion': len(completion.split())}\n"
                   "def broken(**kw):\n    raise FileNotFoundError('no tokenizer file')\n")
    env = {"PYTHONPATH": str(tmp_path)}
    # a counter that fails its start-up probe -> refused before any call
    p = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", tmp_path / "g1",
             "--token-counter", "toycount:broken", env=env)
    assert p.returncode != 0 and "probe" in p.stderr and fake.n("/api/chat") == 0
    p = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", tmp_path / "g2",
             "--token-counter", "toycount:count", "--require-local-tokens", env=env)
    assert p.returncode == 0, p.stderr
    rec = json.load(open(tmp_path / "g2" / "outputs" / "toy-000.C0.r0.json"))
    assert rec["local_tokens"]["content_by_message"] == [4, 6] and rec["local_tokens_counter"] == "toycount:count"
    assert json.load(open(tmp_path / "g2" / "config.json"))["local_tokens_counter"] == "toycount:count"
    # a counter together with --local-tokens off is contradictory -> refused before any call
    p = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", tmp_path / "g3",
             "--token-counter", "toycount:count", "--local-tokens", "off", env=env)
    assert p.returncode != 0 and "--local-tokens on" in p.stderr and fake.n("/api/chat") == 1
    assert not (tmp_path / "g3").exists()


def test_ollama_runner_builds_the_local_counter_by_default(fake, tmp_path):
    """E08 + E09: without --local-tokens off the runner builds tokcount's counter for the served model; against a
    server whose model is not in a local store it stops before any call (the default is never silently skipped)."""
    reqs = _requests_file(tmp_path, 1)
    env = {"OLLAMA_MODELS": str(tmp_path / "no-store")}
    p = subprocess.run([sys.executable, OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", str(reqs),
                        "--out", str(tmp_path / "gen")], capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, **env))
    assert p.returncode != 0 and "local token counts unavailable" in p.stderr
    assert fake.n("/api/chat") == 0 and not (tmp_path / "gen" / "receipts.jsonl").exists()


def test_round0_reuse_reads_the_settings_this_runner_records(fake, tmp_path):
    """E05 x E08 (wave1 merge check): run_condition.sh seeds C3L/C3E/C2E round 0 with reuse_c0_as_c3l.py, which
    compares its --expect-* values with the source generation's config.json. That config.json is written by this
    runner, so the check must read this runner's layout: matching settings pass, a different one is refused."""
    src, dst = tmp_path / "c0", tmp_path / "c3l"
    src.mkdir()
    dst.mkdir()
    reqs = _requests_file(src, 1)
    (dst / "requests.C3L.jsonl").write_text(reqs.read_text().replace(".C0", ".C3L").replace('"C0"', '"C3L"'))
    p = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", reqs, "--out", src / "gen.C0.r0")
    assert p.returncode == 0, p.stderr
    reuse = os.path.join(ROOT, "analysis", "reuse_c0_as_c3l.py")
    expect = {"--expect-model": MODEL, "--expect-num-ctx": 32768, "--expect-num-predict": 6000,
              "--expect-temperature": 0, "--expect-repeat": 1}

    def run_reuse(**change):
        args = [a for k, v in dict(expect, **change).items() for a in (k, v)]
        return _run(reuse, "--c0-run", src, "--c3l-run", dst, "--src-cond", "C0", "--dst-cond", "C3L", *args)

    bad = run_reuse(**{"--expect-num-ctx": 16384})
    assert bad.returncode != 0 and "num_ctx: source 32768" in bad.stderr, bad.stderr
    assert not (dst / "gen.C3L.r0").exists()
    ok = run_reuse()
    assert ok.returncode == 0 and "5 checked" in ok.stdout, ok.stderr
    assert (dst / "gen.C3L.r0" / "outputs" / "toy-000.C3L.r0.json").exists()


@pytest.mark.skipif(not os.path.exists(SMOKE_CASES), reason="data/cases/smoke.jsonl missing")
def test_ollama_runner_output_is_read_by_validate_and_score(fake, tmp_path):
    py = os.environ.get("ORGENE_PY") or "/opt/homebrew/bin/python3"
    if not os.path.exists(py):
        pytest.skip("generation interpreter not present on this host")
    run = tmp_path / "20260101-fake-smoke-dev-C0"
    assert _run(CLI, "requests", "--run", run, "--cases", SMOKE_CASES, "--cond", "C0", "--limit", "1").returncode == 0
    p = _run(OLLAMA_RUNNER, "--host", fake.url, "--model", MODEL, "--requests", run / "requests.C0.jsonl", "--out", run / "gen.C0.r0")
    assert p.returncode == 0, p.stderr
    for args in (["validate", "--run", run, "--cases", SMOKE_CASES, "--cond", "C0", "--round", "0"],
                 ["score", "--run", run, "--cases", SMOKE_CASES, "--cond", "C0"]):
        q = _run(CLI, *args)
        assert q.returncode == 0, q.stderr
    res = [json.loads(l) for l in open(run / "results.C0.jsonl") if l.strip()]
    assert res and res[0]["correct"] is True and res[0]["out_tokens"] == 7 and res[0]["in_tokens"] == 11


# ---------------------------------------------------------------------------------------------- OpenAI-compatible


KEY = "sk-test-LEAKCHECK-7f3a91"


def test_api_runner_records_fields_and_never_writes_the_key(fake, tmp_path):
    reqs, out = _requests_file(tmp_path, 1), tmp_path / "gen"
    p = _run(API_RUNNER, "--backend", "compat", "--base-url", fake.url + "/v1", "--api-key-env", "TEST_KEY",
             "--model", "mock-model", "--requests", reqs, "--out", out, "--top-p", "0.9", env={"TEST_KEY": KEY})
    assert p.returncode == 0, p.stderr
    body = fake.posts["/v1/chat/completions"][0]
    assert body["seed"] == 1 and body["temperature"] == 0.0 and body["top_p"] == 0.9 and body["max_completion_tokens"] == 4000
    assert fake.headers_seen[-1].get("Authorization") == f"Bearer {KEY}"
    rec = json.load(open(out / "outputs" / "toy-000.C0.r0.json"))
    assert missing_call_fields(rec) == []
    assert rec["seed"] == 1 and rec["response_model"] == "mock-model-2026-01-01" and rec["system_fingerprint"] == "fp_test"
    assert rec["request_sha256"] == request_sha256(body) and rec["temperature_sent"] is True
    assert rec["total_duration_source"] == "client_wall" and rec["digest"] is None
    for name, text in _all_text(out).items():
        assert KEY not in text, name
    assert KEY not in p.stdout + p.stderr


def test_api_runner_refuses_a_relay_endpoint(fake, tmp_path):
    p = _run(API_RUNNER, "--backend", "compat", "--base-url", "http://relay.example.invalid/v1", "--api-key-env", "TEST_KEY",
             "--model", "m", "--requests", _requests_file(tmp_path, 1), "--out", tmp_path / "gen", env={"TEST_KEY": KEY})
    assert p.returncode != 0 and "relay" in p.stderr and not (tmp_path / "gen").exists()


def test_openai_request_adjustment_is_recorded_and_guarded(fake, monkeypatch):
    monkeypatch.setenv("TEST_KEY", KEY)
    fake.reject = ("max_completion_tokens", 400, "Unsupported parameter: max_completion_tokens")
    b = OpenAICompatBackend("mock-model", preset="compat", base_url=fake.url + "/v1", key_env="TEST_KEY", retry_sleep=0)
    opts = {"temperature": 0.0, "top_p": None, "seed": 3, "max_tokens": 100}
    rec = b.call(MSGS, opts)
    final = fake.posts["/v1/chat/completions"][-1]
    assert rec["ok"] and "max_tokens" in final and "max_completion_tokens" not in final
    assert rec["request_adjustments"] == ["max_completion_tokens", "max_tokens"]
    assert rec["request_sha256"] == request_sha256(final) and rec["sent_opts"]["max_tokens"] == 100
    # a registry that pins temperature: dropping it would change the request, so the adjusted call is refused
    fake.reject = ("temperature", 400, "temperature is not supported with this model")
    entry = {"backend": "openai_compat", "model": "mock-model", "opts": dict(opts), "seed_rule": "fixed"}
    n0 = fake.n("/v1/chat/completions")
    with pytest.raises(RegistryMismatch):
        b.call(MSGS, opts, guard=registry_guard(entry, backend=b))
    assert fake.n("/v1/chat/completions") == n0 + 1  # only the rejected request went out


def test_anthropic_backend_call_record(fake, monkeypatch):
    from orgene.backends.anthropic import AnthropicBackend
    monkeypatch.setenv("TEST_KEY", KEY)
    b = AnthropicBackend("mock-claude", base_url=fake.url, key_env="TEST_KEY", retry_sleep=0)
    rec = b.call(MSGS, {"temperature": 0.0, "max_tokens": 64})
    body = fake.posts["/v1/messages"][0]
    assert body["system"] == MSGS[0]["content"] and body["messages"] == MSGS[1:]   # system joined into the top level
    assert body["temperature"] == 0.0 and body["max_tokens"] == 64 and "seed" not in body
    assert {k.lower(): v for k, v in fake.headers_seen[-1].items()}.get("x-api-key") == KEY
    assert missing_call_fields(rec) == [] and rec["seed"] is None and rec["digest"] is None
    assert rec["request_sha256"] == request_sha256(body) and rec["content"] == ANSWER
    assert rec["prompt_eval_count"] == 12 and rec["eval_count"] == 21 and rec["done_reason"] == "end_turn"
    assert KEY not in json.dumps(rec) and KEY not in json.dumps(b.identity())
    with pytest.raises(OptionsError):                                   # max_tokens is required
        b.call(MSGS, {"temperature": 0.0})
    assert fake.n("/v1/messages") == 1


# ---------------------------------------------------------------------------------------------- llama.cpp


def test_llamacpp_backend_sends_all_sampling_options_and_records_no_paths(fake):
    b = LlamaCppBackend("anchor", host=fake.url, retry_sleep=0, digest="a" * 64)
    opts = {"temperature": 0.0, "top_k": 20, "top_p": 0.95, "seed": 1, "max_tokens": 64}
    rec = b.call(MSGS, opts)
    body = fake.posts["/v1/chat/completions"][0]
    assert {k: body[k] for k in opts} == opts and body["stream"] is False
    assert missing_call_fields(rec) == [] and rec["digest"] == "a" * 64 and rec["system_fingerprint"] == "fp_test"
    ident = b.identity()
    assert ident["model_file"] == "anchor-q8_0.gguf" and ident["build_info"] == "b9999-abc" and ident["n_ctx"] == 8192
    assert not PA.find_absolute_paths(json.dumps(ident)) and not PA.find_absolute_paths(json.dumps(rec))
    with pytest.raises(OptionsError):
        b.call(MSGS, {k: v for k, v in opts.items() if k != "top_k"})
    assert fake.n("/v1/chat/completions") == 1


def test_make_backend_knows_every_kind(fake, monkeypatch):
    monkeypatch.setenv("TEST_KEY", KEY)
    assert make_backend("ollama", MODEL, host=fake.url).kind == "ollama"
    assert make_backend("llamacpp", "m", host=fake.url).kind == "llamacpp"
    assert make_backend("openai_compat", "m", base_url=fake.url, key_env="TEST_KEY").kind == "openai_compat"
    assert make_backend("anthropic", "m", base_url=fake.url, key_env="TEST_KEY").kind == "anthropic"
    with pytest.raises(OptionsError):
        make_backend("vllm", "m")


def test_v5_style_record_is_reported_incomplete():
    """Negative control for the field check: a v5 runner record (no start time, parse flag) must fail it."""
    v5 = {"request_id": "x", "repeat": 0, "seed": 1, "model": MODEL, "digest": DIGEST, "ok": True, "done_reason": "stop",
          "prompt_eval_count": 1, "eval_count": 1, "content": "c", "content_sha256": "0", "parse_ok": False, "parsed": None,
          "finished_at": "2026-01-01T00:00:00+00:00"}
    miss = missing_call_fields(v5)
    assert "started_at" in miss and "request_sha256" in miss and "local_tokens" in miss and "!parse_ok" in miss

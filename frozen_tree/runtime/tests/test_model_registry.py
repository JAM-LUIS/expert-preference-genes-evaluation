"""E19: model and decoding-parameter registry — file, validation, sent-settings checks, read-only snapshot, runs.

No model is called. The snapshot tests run against a fake Ollama HTTP server, a fake model store, a fake launchd job
file and a fake server log built in tmp_path; the committed registry is checked against its committed snapshot.
Tests marked "E08" use the runners' backends and skip until that branch is merged; the live check runs only with
ORGENE_LIVE_REGISTRY=1 on the host that serves the models.
"""
import copy
import getpass
import hashlib
import importlib.util
import json
import os
import plistlib
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import model_registry as MR  # noqa: E402
from orgene import model_snapshot as MS  # noqa: E402
from orgene.paths import find_absolute_paths  # noqa: E402

TOOL = os.path.join(ROOT, "tools", "model_registry.py")
REG_PATH = os.path.join(ROOT, "configs", "model_registry.json")
# identity strings that must never appear in the tree; spelled in pieces so this file does not contain them. The
# login and host names are taken from the machine at run time, so no part of them is written here.
FAKE_HOME = "/" + "Users" + "/someone"
# account and host names that say nothing about anyone (same idea as the E21 scanner's list)
_GENERIC_NAMES = {"root", "user", "admin", "runner", "ubuntu", "ec2-user", "debian", "vagrant", "jenkins", "build",
                  "builder", "circleci", "travis", "gitlab-runner", "localhost", "docker", "codespace", "vscode", "node",
                  "app", "test", "guest", "nobody", "worker", "default"}


def _local_names():
    names = [os.environ.get("USER"), os.environ.get("LOGNAME"), socket.gethostname().split(".")[0]]
    try:
        names.append(getpass.getuser())
    except Exception:  # noqa: BLE001
        pass
    return tuple(sorted({n.strip() for n in names
                         if n and len(n.strip()) >= 4 and n.strip().lower() not in _GENERIC_NAMES}))


IDENTITY_MARKERS = ("Lu" + "is", "JAM " + "Studio", "HR" + "gene") + _local_names()


def _assert_neutral(text):
    assert not find_absolute_paths(text)
    low = text.lower()
    for m in IDENTITY_MARKERS:
        assert m.lower() not in low, "identity marker found (not printed)"

QWEN_DIGEST = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"
QWEN_WEIGHTS = "a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f"
QWEN_TEMPLATE = "ae370d884f108d16e7cc8fd5259ebc5773a0afa6e078b11f4ed7e39a27e0dfc4"
MAIN_OPTS = {"temperature": 0.0, "top_k": 20, "top_p": 0.95, "seed": 1, "num_ctx": 32768, "num_predict": 6000,
             "think": False, "keep_alive": 0}


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _committed():
    return MR.read(REG_PATH)


# ================================================================================ the committed registry


def test_committed_registry_is_valid_and_neutral():
    reg = MR.load(REG_PATH)
    assert reg["schema_version"] == MR.SCHEMA_VERSION
    _assert_neutral(open(REG_PATH, encoding="utf-8").read())
    snap_path = os.path.join(ROOT, reg["generated"]["snapshot"])
    assert MR.file_sha256(snap_path) == reg["generated"]["snapshot_sha256"]
    _assert_neutral(open(snap_path, encoding="utf-8").read())


def test_e19_sources_carry_no_identity_marker():
    for p in ("runtime/orgene/model_registry.py", "runtime/orgene/model_snapshot.py", "tools/model_registry.py",
              "runtime/tests/test_model_registry.py"):
        _assert_neutral(open(os.path.join(ROOT, p), encoding="utf-8").read())


def _qwen3_entry_ids(reg):
    """The qwen3:8b entries (anchor entries, e.g. E18's LLMOPT entry, are tested with their adapters)."""
    return [eid for eid, e in reg["entries"].items() if e.get("model") == "qwen3:8b"]


def test_committed_entries_follow_the_decisions():
    e = {eid: _committed()["entries"][eid] for eid in _qwen3_entry_ids(_committed())}
    assert set(e) == {"qwen3-8b.main", "qwen3-8b.var07", "qwen3-8b.r0-v5", "qwen3-8b.r0-ctx16k"}
    assert e["qwen3-8b.main"]["opts"] == MAIN_OPTS
    assert e["qwen3-8b.var07"]["opts"] == dict(MAIN_OPTS, temperature=0.7)
    assert e["qwen3-8b.r0-v5"]["opts"] == dict(MAIN_OPTS, num_ctx=16384, keep_alive="30m")
    assert e["qwen3-8b.r0-ctx16k"]["opts"] == dict(MAIN_OPTS, num_ctx=16384)
    for ent in e.values():
        assert ent["backend"] == "ollama" and ent["model"] == "qwen3:8b" and ent["seed_rule"] == "base+k"
        assert ent["digest"] == QWEN_DIGEST
        ident = ent["identity"]
        assert ident["weights_blob_sha256"] == QWEN_WEIGHTS and ident["template_blob_sha256"] == QWEN_TEMPLATE
        assert ident["quantization_level"] == "Q4_K_M" and ident["ollama_version"] == "0.33.0"
        assert ident["server"] == {"flash_attention": True, "kv_cache_type": "q8_0", "num_parallel": "1"}
        # only repeat_penalty and the stop tokens come from the Modelfile
        assert sorted(ident["inherited_by_calls"]) == ["repeat_penalty", "stop"]
    reg = _committed()
    alias = reg["models"]["qwen3-8b-ctx32k:latest"]
    assert alias["weights_blob_sha256"] == QWEN_WEIGHTS and alias["same_weights_as"] == "qwen3:8b"
    assert alias["digest"] == "c009fe1fdc2681a9e203cdedf4edba17b780f16642b68c759edf93f4d4058ce2"
    assert alias["params"] == {"num_ctx": 32768, "num_predict": 6000, "repeat_penalty": 1, "seed": 1,
                               "stop": ["<|im_start|>", "<|im_end|>"], "temperature": 0, "top_k": 20, "top_p": 0.95}
    srv = reg["server"]["ollama"]
    assert srv["flash_attention"] is True and srv["kv_cache_type"] == "q8_0" and srv["sources_agree"] is True
    assert set(srv["sources"]) == {"launchd_job", "process_env", "startup_log"}
    for ev in srv["model_load_evidence"].values():
        assert ev == {"flash_attn_seen": ["enabled"], "kv_cache_seen": ["q8_0/q8_0"]}
    assert reg["execution"]["timeout_s"] == 60 and reg["execution"]["timeout_s_engineering_cases"] == 600
    assert reg["execution"]["pulp_version"] == "3.3.2" and reg["execution"]["cbc_version"] == "2.10.13"
    assert reg["anchors"]["orlm"]["hf_revision"] == "94fdc3c5738c6536d4880dc19a78f215529181c5"
    assert reg["anchors"]["llmopt"]["hf_revision"] == "ed0ae2dd051aec57989eedef064ce7e445b6726a"
    assert len(reg["anchors"]["orlm"]["safetensors_sha256"]) == 4 and len(reg["anchors"]["llmopt"]["safetensors_sha256"]) == 12
    assert reg["api_models"]["models"] == {}  # the API model is not chosen yet (D6)


def test_committed_registry_matches_its_committed_snapshot():
    reg = _committed()
    snap = json.load(open(os.path.join(ROOT, reg["generated"]["snapshot"]), encoding="utf-8"))
    mism, _ = MR.compare_snapshot(reg, snap)
    assert mism == []
    again, _ = MR.apply_snapshot(reg, snap)
    assert {k: v for k, v in again.items() if k != "generated"} == {k: v for k, v in reg.items() if k != "generated"}


def test_entry_hash_is_the_canonical_json_hash_and_covers_the_identity():
    reg = _committed()
    e = reg["entries"]["qwen3-8b.main"]
    want = _sha(json.dumps(e, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    assert MR.entry_sha256(e) == want
    assert MR.entry_record(REG_PATH, "qwen3-8b.main") == {"path": "configs/model_registry.json",
                                                          "entry_id": "qwen3-8b.main", "entry_sha256": want}
    e2 = copy.deepcopy(e)
    e2["identity"]["server"]["kv_cache_type"] = "f16"
    assert MR.entry_sha256(e2) != want
    # adding another entry to the file does not change this entry's hash
    reg2 = copy.deepcopy(reg)
    reg2["entries"]["qwen3-8b.extra"] = copy.deepcopy(e)
    assert MR.entry_sha256(reg2["entries"]["qwen3-8b.main"]) == want


# ================================================================================ settings about to be sent


def _main():
    return copy.deepcopy(_committed()["entries"]["qwen3-8b.main"])


def test_compare_sent_accepts_exactly_the_registered_settings():
    e = _main()
    for k in range(3):
        assert MR.compare_sent(e, dict(MAIN_OPTS, seed=1 + k), backend_kind="ollama", model="qwen3:8b",
                               digest=QWEN_DIGEST, repeat_index=k) == []
    # numbers compare by value: an integer temperature 0 is the registered 0.0
    assert MR.compare_sent(e, dict(MAIN_OPTS, temperature=0)) == []
    MR.require_sent(e, dict(MAIN_OPTS))


@pytest.mark.parametrize("sent,kw", [
    (dict(MAIN_OPTS, num_ctx=16384), {}),
    (dict(MAIN_OPTS, keep_alive="30m"), {}),
    (dict(MAIN_OPTS, think=0), {}),                                      # a number is not a boolean
    ({k: v for k, v in MAIN_OPTS.items() if k != "top_p"}, {}),         # every registered key must be sent
    (dict(MAIN_OPTS, min_p=0.0), {}),                                    # ... and every sent key registered
    (dict(MAIN_OPTS, temperature=0.7), {}),
    (dict(MAIN_OPTS, seed=1), {"repeat_index": 1}),                      # base+k: repeat 1 must send seed 2
    (dict(MAIN_OPTS), {"model": "qwen3-8b-ctx32k:latest"}),
    (dict(MAIN_OPTS), {"backend_kind": "openai_compat"}),
    (dict(MAIN_OPTS), {"digest": "f" * 64}),
])
def test_compare_sent_refuses_any_difference(sent, kw):
    e = _main()
    assert MR.compare_sent(e, sent, **kw)
    with pytest.raises(MR.RegistryMismatch):
        MR.require_sent(e, sent, **kw)


# ================================================================================ validation (negative controls)


def _mutations():
    def unknown_top(r):
        r["extra"] = 1

    def unknown_entry_key(r):
        r["entries"]["qwen3-8b.main"]["temprature"] = 0

    def missing_top_p(r):
        del r["entries"]["qwen3-8b.main"]["opts"]["top_p"]

    def think_int(r):
        r["entries"]["qwen3-8b.main"]["opts"]["think"] = 0

    def keep_alive_word(r):
        r["entries"]["qwen3-8b.main"]["opts"]["keep_alive"] = "soon"

    def bad_seed_rule(r):
        r["entries"]["qwen3-8b.main"]["seed_rule"] = "random"

    def no_digest(r):
        r["entries"]["qwen3-8b.main"]["digest"] = None

    def bad_digest(r):
        r["entries"]["qwen3-8b.main"]["digest"] = "500A1F"

    def planted_home_path(r):
        r["entries"]["qwen3-8b.main"]["purpose"] += " see " + FAKE_HOME + "/notes.txt"

    def split_identity(r):
        r["entries"]["qwen3-8b.var07"]["identity"]["weights_blob_sha256"] = "0" * 64

    def undated_api_model(r):
        r["entries"]["api.x"] = {"backend": "openai_compat", "model": "gpt-4o", "seed_rule": "fixed", "purpose": "x",
                                 "opts": {"temperature": 0.0, "top_p": 1.0, "seed": 1, "max_tokens": 6000}}

    def anthropic_seed(r):
        r["entries"]["api.y"] = {"backend": "anthropic", "model": "claude-x-20250101", "seed_rule": "fixed", "purpose": "y",
                                 "opts": {"temperature": 0.0, "max_tokens": 6000, "seed": 1}}

    def alias_other_weights(r):
        r["models"]["qwen3-8b-ctx32k:latest"]["weights_blob_sha256"] = "1" * 64

    def inherited_wrong(r):
        r["entries"]["qwen3-8b.main"]["identity"]["inherited_by_calls"] = {}

    def fa_differs_from_server(r):
        r["entries"]["qwen3-8b.main"]["identity"]["server"]["flash_attention"] = False

    def sources_disagree(r):
        r["server"]["ollama"]["sources_agree"] = False

    def setting_outside_allowlist(r):
        r["server"]["ollama"]["settings"]["OLLAMA_MODELS"] = "x"

    def bad_timeout(r):
        r["execution"]["timeout_s"] = 0

    return [unknown_top, unknown_entry_key, missing_top_p, think_int, keep_alive_word, bad_seed_rule, no_digest,
            bad_digest, planted_home_path, split_identity, undated_api_model, anthropic_seed, alias_other_weights,
            inherited_wrong, fa_differs_from_server, sources_disagree, setting_outside_allowlist, bad_timeout]


@pytest.mark.parametrize("mutate", _mutations(), ids=lambda f: f.__name__)
def test_validate_reports_each_planted_problem(mutate):
    reg = copy.deepcopy(_committed())
    assert MR.validate(reg) == []
    mutate(reg)
    assert MR.validate(reg), mutate.__name__


def test_dated_api_models_and_the_allowlist_pass():
    reg = copy.deepcopy(_committed())
    reg["entries"]["api.dated"] = {"backend": "openai_compat", "model": "gpt-4o-2024-08-06", "seed_rule": "fixed",
                                   "purpose": "x", "opts": {"temperature": 0.0, "top_p": 1.0, "seed": 1, "max_tokens": 6000}}
    reg["entries"]["api.nodate"] = {"backend": "anthropic", "model": "some-model", "seed_rule": "fixed", "purpose": "y",
                                    "opts": {"temperature": 0.0, "max_tokens": 6000, "seed": None}}
    assert any("some-model" in p for p in MR.validate(reg))
    reg["api_models"]["allowlist"] = ["some-model"]
    assert MR.validate(reg) == []
    assert MR.api_model_allowed(reg, "deepseek-chat-20250101") and not MR.api_model_allowed(reg, "gpt-4o")


# ================================================================================ fake host for snapshots


class _FakeOllama:
    """Ollama API stand-in: answers the read-only endpoints from a model table and counts every request."""

    def __init__(self, models, version="0.33.0"):
        self.models = models  # tag -> {"digest", "details", "template"}
        self.version = version
        self.seen = []
        self.chat_calls = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def _send(self, obj, code=200):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                outer.seen.append(("GET", self.path))
                if self.path == "/api/version":
                    return self._send({"version": outer.version})
                if self.path == "/api/tags":
                    return self._send({"models": [{"name": t, "model": t, "digest": m["digest"], "details": m["details"]}
                                                  for t, m in outer.models.items()]})
                if self.path == "/api/ps":
                    return self._send({"models": []})
                return self._send({"error": "not found"}, 404)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                outer.seen.append(("POST", self.path))
                if self.path == "/api/show":
                    m = outer.models.get(body.get("model"))
                    if not m:
                        return self._send({"error": "not found"}, 404)
                    return self._send({"template": m["template"], "details": m["details"], "capabilities": ["completion"],
                                       "parameters": m.get("parameters", ""), "model_info": {"general.architecture": "toy"}})
                if self.path == "/api/chat":
                    outer.chat_calls += 1
                    return self._send({"model": body.get("model"), "message": {"role": "assistant", "content": "ok"},
                                       "done": True, "done_reason": "stop", "prompt_eval_count": 3, "eval_count": 1,
                                       "eval_duration": 1000, "total_duration": 2000, "load_duration": 10})
                return self._send({"error": "not allowed in the fake"}, 405)

            def do_DELETE(self):
                outer.seen.append(("DELETE", self.path))
                return self._send({}, 200)

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


def _blob(models_dir, content):
    d = _sha(content)
    os.makedirs(os.path.join(models_dir, "blobs"), exist_ok=True)
    with open(os.path.join(models_dir, "blobs", "sha256-" + d), "wb") as f:
        f.write(content)
    return d


def _install(models_dir, tag, *, weights, template, params, license_text=b"toy licence"):
    """Write a manifest + blobs as Ollama does. Returns (manifest digest, layer digests)."""
    lay = {"model": _blob(models_dir, weights), "template": _blob(models_dir, template.encode()),
           "license": _blob(models_dir, license_text), "params": _blob(models_dir, json.dumps(params).encode())}
    cfg = _blob(models_dir, json.dumps({"model_format": "gguf", "model_family": "toy", "model_type": "1B",
                                        "file_type": "Q4_K_M"}).encode())
    man = {"schemaVersion": 2, "config": {"digest": "sha256:" + cfg, "size": 1},
           "layers": [{"mediaType": f"application/vnd.ollama.image.{k}", "digest": "sha256:" + v, "size": 10}
                      for k, v in lay.items()]}
    name, _, t = tag.partition(":")
    mpath = os.path.join(models_dir, "manifests", "registry.ollama.ai", "library", name, t or "latest")
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    raw = json.dumps(man).encode()
    with open(mpath, "wb") as f:
        f.write(raw)
    return _sha(raw), lay


TOY_TEMPLATE = "{{ .Prompt }}"
TOY_PARAMS = {"repeat_penalty": 1, "stop": ["<end>"], "temperature": 0.6, "top_k": 20, "top_p": 0.95}
ALIAS_PARAMS = dict(TOY_PARAMS, num_ctx=32768, temperature=0, seed=1)
OTHER_BLOB = "b" * 64


def _log_text(weights_blob):
    blobs = FAKE_HOME + "/.ollama/models/blobs/sha256-"
    start = ('time=2026-08-27T17:19:56.173-04:00 level=INFO source=routes.go:1 msg="server config" '
             'env="map[HTTPS_PROXY: OLLAMA_CONTEXT_LENGTH:0 OLLAMA_FLASH_ATTENTION:true OLLAMA_HOST:http://127.0.0.1:11434 '
             f'OLLAMA_KV_CACHE_TYPE:q8_0 OLLAMA_MODELS:{FAKE_HOME}/.ollama/models OLLAMA_NUM_PARALLEL:1 OLLAMA_ORIGINS:[http://localhost]]"\n')

    def load(t, blob, fa, kv, nctx):
        return (f'time={t} level=INFO source=server.go:109 msg="using llama-server for model" model={blobs}{blob}\n'
                f'time={t} level=INFO source=llama_server.go:1048 msg="loading model via llama-server" model={blobs}{blob}\n'
                f"llama_model_loader: loaded meta data with 28 key-value pairs and 399 tensors from {blobs}{blob} (version GGUF V3 (latest))\n"
                f"llama_context: n_ctx                 = {nctx}\n"
                f"llama_context: flash_attn            = {fa}\n"
                f"llama_kv_cache: size = 1.00 MiB ( {nctx} cells,  36 layers,  1/1 seqs), K ({kv}): 1.00 MiB, V ({kv}): 1.00 MiB\n"
                '[GIN] 2026/09/01 - 10:00:01 | 200 |  1.0s |  127.0.0.1 | POST     "/api/chat"\n')
    return (start + load("2026-09-01T10:00:00.000-04:00", weights_blob, "enabled", "q8_0", 16384)
            + load("2026-09-01T10:05:00.000-04:00", OTHER_BLOB, "disabled", "f16", 4096)   # another project's model
            + load("2026-09-02T09:00:00.000-04:00", weights_blob, "enabled", "q8_0", 32768))


@pytest.fixture
def host(tmp_path):
    """A fake host: model store with a toy model and its alias, launchd job file, server log, Ollama API."""
    md = str(tmp_path / "models")
    d_toy, lay = _install(md, "toy:1b", weights=b"toy weights", template=TOY_TEMPLATE, params=TOY_PARAMS)
    d_alias, lay_a = _install(md, "toy-long:latest", weights=b"toy weights", template=TOY_TEMPLATE, params=ALIAS_PARAMS)
    details = {"format": "gguf", "family": "toy", "parameter_size": "1B", "quantization_level": "Q4_K_M"}
    fake = _FakeOllama({"toy:1b": {"digest": d_toy, "details": details, "template": TOY_TEMPLATE},
                        "toy-long:latest": {"digest": d_alias, "details": details, "template": TOY_TEMPLATE},
                        "other-project:7b": {"digest": "c" * 64, "details": details, "template": "x"}})
    plist = tmp_path / "server.plist"
    with open(plist, "wb") as f:
        plistlib.dump({"EnvironmentVariables": {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0",
                                                "OLLAMA_MODELS": FAKE_HOME + "/.ollama/models"},
                       "StandardErrorPath": str(tmp_path / "server.log")}, f)
    (tmp_path / "server.log").write_text(_log_text(lay["model"]))
    yield {"fake": fake, "models_dir": md, "plist": str(plist), "log": str(tmp_path / "server.log"), "lay": lay,
           "digest": d_toy, "alias_digest": d_alias, "tmp": tmp_path}
    fake.close()


def _toy_registry():
    return {
        "schema_version": MR.SCHEMA_VERSION,
        "entries": {
            "toy.main": {"backend": "ollama", "model": "toy:1b", "digest": None, "seed_rule": "base+k",
                         "opts": dict(MAIN_OPTS), "purpose": "toy", "identity": {"server": {}}},
            "toy.var": {"backend": "ollama", "model": "toy:1b", "digest": None, "seed_rule": "base+k",
                        "opts": dict(MAIN_OPTS, temperature=0.7), "purpose": "toy variance", "identity": {"server": {}}},
        },
        "models": {"toy-long:latest": {"role": "alias", "same_weights_as": "toy:1b"}},
        "server": {"ollama": {}},
        "execution": {"timeout_s": 60, "timeout_s_engineering_cases": 600},
    }


def _snap(h, reg=None, **kw):
    args = dict(host=h["fake"].url, models_dir=h["models_dir"], plist_path=h["plist"], log_path=h["log"],
                parts=("ollama",), read_process=False,
                proc_env={"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"},
                proc_started="2026-08-27T21:19:55Z", n_proc=1)
    args.update(kw)
    return MS.snapshot(reg or _toy_registry(), **args)


# ================================================================================ snapshot


def test_snapshot_reads_only_and_records_no_paths(host):
    snap = _snap(host)
    assert set(host["fake"].seen) <= MS.READ_ONLY_ENDPOINTS and host["fake"].chat_calls == 0
    text = json.dumps(snap)
    assert not find_absolute_paths(text) and str(host["tmp"]) not in text and "someone" not in text
    assert "other-project" not in text and OTHER_BLOB not in text      # unregistered models are not recorded
    m = snap["ollama"]["models"]["toy:1b"]
    assert m["digest"] == host["digest"] and m["digest_matches_manifest"] is True
    assert m["layers"] == host["lay"] and m["template_matches_blob"] is True
    assert m["layer_hashes_verified"] == {"model": True, "template": True, "license": True, "params": True}  # small toy blobs
    assert m["params"] == TOY_PARAMS
    s = snap["ollama"]["server"]
    assert s["flash_attention"] is True and s["kv_cache_type"] == "q8_0" and s["agree"] is True
    assert s["settings_from"] == "startup_log" and "OLLAMA_MODELS" not in s["settings"] and "OLLAMA_HOST" not in s["settings"]
    assert s["settings"]["OLLAMA_NUM_PARALLEL"] == "1"
    assert s["startup_logged_at"] == "2026-08-27T21:19:56Z" and s["process_started_at"] == "2026-08-27T21:19:55Z"
    assert set(s["sources_seen"]) == {"launchd_job", "process_env", "startup_log"}
    # two loads of the registered weights (each announced three times), none of the other project's model
    assert list(s["model_loads"]) == [host["lay"]["model"]]
    ld = s["model_loads"][host["lay"]["model"]]
    assert ld["n_loads"] == 2 and ld["flash_attn_seen"] == ["enabled"] and ld["kv_cache_seen"] == ["q8_0/q8_0"]
    assert ld["n_ctx_seen"] == [16384, 32768] and ld["last_load_at"] == "2026-09-02T13:00:00Z"


@pytest.mark.parametrize("method,path", [("POST", "/api/chat"), ("POST", "/api/generate"), ("POST", "/api/pull"),
                                         ("POST", "/api/create"), ("DELETE", "/api/delete"), ("POST", "/api/copy"),
                                         ("GET", "/api/ps"), ("POST", "/api/embed")])
def test_ollama_request_refuses_every_other_endpoint(host, method, path):
    with pytest.raises(MS.ReadOnlyViolation):
        MS.ollama_request(host["fake"].url, method, path, {"model": "toy:1b"})
    assert host["fake"].seen == []


def test_disagreeing_sources_are_reported(host):
    snap = _snap(host, proc_env={"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "f16"})
    s = snap["ollama"]["server"]
    assert s["agree"] is False and any("OLLAMA_KV_CACHE_TYPE" in d for d in s["disagreements"])
    reg, _ = MR.apply_snapshot(_toy_registry(), snap)
    assert any("sources_agree" in p for p in MR.validate(reg))
    mism, _ = MR.compare_snapshot(reg, snap)
    assert any("disagree" in m for m in mism)


def test_corrupt_blob_and_manifest_mismatch_are_reported(host):
    reg, _ = MR.apply_snapshot(_toy_registry(), _snap(host))
    p = os.path.join(host["models_dir"], "blobs", "sha256-" + host["lay"]["params"])
    with open(p, "a") as f:
        f.write(" ")
    host["fake"].models["toy:1b"]["digest"] = "d" * 64
    snap = _snap(host)
    m = snap["ollama"]["models"]["toy:1b"]
    assert m["layer_hashes_verified"]["params"] is False and m["digest_matches_manifest"] is False
    mism, _ = MR.compare_snapshot(reg, snap)
    assert any("params blob content" in x for x in mism) and any("manifest" in x for x in mism)
    assert any(x.startswith("entries.toy.main.digest") for x in mism)


def test_weight_blobs_are_rehashed_only_on_request(host, monkeypatch):
    monkeypatch.setattr(MS, "SMALL_BLOB_MAX", 1)
    assert _snap(host)["ollama"]["models"]["toy:1b"]["layer_hashes_verified"]["model"] is None
    assert _snap(host, verify_weights=True)["ollama"]["models"]["toy:1b"]["layer_hashes_verified"]["model"] is True


# ================================================================================ update / check round trip


def test_update_fills_identity_and_check_passes(host, tmp_path):
    reg0 = _toy_registry()
    assert MR.validate(reg0)  # nothing observed yet
    snap = _snap(host)
    sp = tmp_path / "snap.json"
    sp.write_text(json.dumps(snap))
    reg, notes = MR.apply_snapshot(reg0, snap, snapshot_path=str(sp))
    assert MR.validate(reg) == [], MR.validate(reg)
    e = reg["entries"]["toy.main"]
    assert e["digest"] == host["digest"] and e["identity"]["weights_blob_sha256"] == host["lay"]["model"]
    assert e["identity"]["inherited_by_calls"] == {"repeat_penalty": 1, "stop": ["<end>"]}
    assert e["identity"]["server"] == {"flash_attention": True, "kv_cache_type": "q8_0", "num_parallel": "1"}
    assert reg["models"]["toy-long:latest"]["params"] == ALIAS_PARAMS
    assert reg["generated"]["snapshot_sha256"] == _sha(sp.read_bytes())
    # decisions are untouched
    assert e["opts"] == MAIN_OPTS and reg["entries"]["toy.var"]["opts"]["temperature"] == 0.7
    mism, notes = MR.compare_snapshot(reg, snap)
    assert mism == [] and not [n for n in notes if "not observed" in n and "server" in n]
    # a quick (no log) snapshot still agrees; the unread start-up settings are a note, not a mismatch
    quick = _snap(host, log_path=None)
    mism, notes = MR.compare_snapshot(reg, quick)
    assert mism == [] and any("start-up log not read" in n for n in notes)


def _mut_version(h):
    h["fake"].version = "0.34.0"


def _mut_kv_everywhere(h):
    text = open(h["log"]).read().replace("OLLAMA_KV_CACHE_TYPE:q8_0", "OLLAMA_KV_CACHE_TYPE:q4_0")
    open(h["log"], "w").write(text)
    with open(h["plist"], "rb") as f:
        d = plistlib.load(f)
    d["EnvironmentVariables"]["OLLAMA_KV_CACHE_TYPE"] = "q4_0"
    with open(h["plist"], "wb") as f:
        plistlib.dump(d, f)
    return {"proc_env": {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q4_0"}}


def _mut_fa_off(h):
    text = open(h["log"]).read().replace("OLLAMA_FLASH_ATTENTION:true", "OLLAMA_FLASH_ATTENTION:false")
    open(h["log"], "w").write(text)
    with open(h["plist"], "rb") as f:
        d = plistlib.load(f)
    d["EnvironmentVariables"]["OLLAMA_FLASH_ATTENTION"] = "0"
    with open(h["plist"], "wb") as f:
        plistlib.dump(d, f)
    return {"proc_env": {"OLLAMA_FLASH_ATTENTION": "0", "OLLAMA_KV_CACHE_TYPE": "q8_0"}}


def _mut_alias_params(h):
    _install(h["models_dir"], "toy-long:latest", weights=b"toy weights", template=TOY_TEMPLATE,
             params=dict(ALIAS_PARAMS, num_ctx=16384))
    man = open(MS._manifest_path(h["models_dir"], "toy-long:latest"), "rb").read()
    h["fake"].models["toy-long:latest"]["digest"] = _sha(man)


def _mut_quantization(h):
    h["fake"].models["toy:1b"]["details"] = dict(h["fake"].models["toy:1b"]["details"], quantization_level="Q8_0")


def _mut_f16_load(h):
    with open(h["log"], "a") as f:
        f.write(_log_text(h["lay"]["model"]).split("\n", 1)[1].replace("K (q8_0)", "K (f16)").replace("V (q8_0)", "V (f16)"))


@pytest.mark.parametrize("mutate,expect", [
    (_mut_version, "identity.ollama_version"),
    (_mut_kv_everywhere, "identity.server.kv_cache_type"),
    (_mut_fa_off, "identity.server.flash_attention"),
    (_mut_alias_params, "models.toy-long:latest.params"),
    (_mut_quantization, "identity.quantization_level"),
    (_mut_f16_load, "KV cache f16/f16"),
], ids=lambda x: getattr(x, "__name__", str(x)))
def test_check_reports_every_change_of_the_host(host, mutate, expect):
    reg, _ = MR.apply_snapshot(_toy_registry(), _snap(host))
    kw = mutate(host) or {}
    mism, _ = MR.compare_snapshot(reg, _snap(host, **kw))
    assert any(expect in m for m in mism), mism


def test_a_missing_model_or_an_unreachable_server_fails_the_check(host):
    reg, _ = MR.apply_snapshot(_toy_registry(), _snap(host))
    del host["fake"].models["toy-long:latest"]
    mism, _ = MR.compare_snapshot(reg, _snap(host))
    assert any("model toy-long:latest: not installed" in m for m in mism), mism
    snap = _snap(host, host="http://127.0.0.1:9")  # nothing listens there
    mism, _ = MR.compare_snapshot(reg, snap)
    assert any("Ollama" in m and "not reachable" in m for m in mism), mism


def test_a_failed_show_request_fails_the_check(host, monkeypatch):
    reg, _ = MR.apply_snapshot(_toy_registry(), _snap(host))
    real = MS.ollama_request

    def show_fails(h, method, path, payload=None, timeout=60):
        if path == "/api/show":
            raise OSError("connection refused")
        return real(h, method, path, payload, timeout)

    monkeypatch.setattr(MS, "ollama_request", show_fails)
    snap = _snap(host)
    assert snap["ollama"]["models"]["toy:1b"]["show_error"] == "OSError"
    mism, _ = MR.compare_snapshot(reg, snap)
    # the entry's model: its chat template is then unchecked, which must not pass silently
    assert any(m.startswith("snapshot: model toy:1b: /api/show failed") for m in mism), mism


def test_update_refuses_to_change_a_model_identity(host):
    reg, _ = MR.apply_snapshot(_toy_registry(), _snap(host))
    _install(host["models_dir"], "toy:1b", weights=b"other weights", template=TOY_TEMPLATE, params=TOY_PARAMS)
    host["fake"].models["toy:1b"]["digest"] = _sha(open(MS._manifest_path(host["models_dir"], "toy:1b"), "rb").read())
    snap = _snap(host)
    with pytest.raises(MR.IdentityChange):
        MR.apply_snapshot(reg, snap)
    new, notes = MR.apply_snapshot(reg, snap, accept_identity_change=True)
    assert new["entries"]["toy.main"]["digest"] == host["fake"].models["toy:1b"]["digest"]
    assert any("identity changed" in n for n in notes)
    # the alias no longer shares the weights of its base model
    assert any("same_weights_as" in p or "toy-long" in p for p in MR.validate(new))


def test_execution_part_uses_the_generation_interpreter():
    py = "/opt/homebrew/bin/python3"
    if not os.path.exists(py):
        pytest.skip("generation interpreter not present on this host")
    snap = MS.snapshot(_toy_registry(), parts=("execution",))
    assert snap["execution"]["ok"] is True and snap["execution"]["pulp_version"]
    reg, _ = MR.apply_snapshot(_toy_registry(), snap)
    assert reg["execution"]["pulp_version"] == snap["execution"]["pulp_version"]


# ================================================================================ runs


def _run_config(entry_id="qwen3-8b.main", **change):
    reg = _committed()
    e = reg["entries"][entry_id]
    cfg = {"backend": "ollama",
           "identity": {"model": "qwen3:8b", "digest": QWEN_DIGEST, "ollama_version": "0.33.0", "template_sha256": QWEN_TEMPLATE},
           "opts": {k: v for k, v in e["opts"].items() if k != "seed"}, "seed_base": e["opts"]["seed"],
           "registry": {"path": "configs/model_registry.json", "entry_id": entry_id, "entry_sha256": MR.entry_sha256(e)}}
    for k, v in change.items():
        cfg[k] = v
    return cfg


def test_verify_run_accepts_a_run_made_with_its_entry():
    reg = _committed()
    for eid in _qwen3_entry_ids(reg):
        assert MR.verify_run_config(reg, _run_config(eid)) == []


@pytest.mark.parametrize("cfg,expect", [
    (lambda: _run_config(registry=None), "names no registry entry"),
    (lambda: _run_config(registry={"entry_id": "qwen3-8b.main", "entry_sha256": "0" * 64}), "changed since the run"),
    (lambda: _run_config(opts=dict(_run_config()["opts"], num_ctx=16384)), "num_ctx"),
    (lambda: _run_config(seed_base=7), "seed"),
    (lambda: _run_config(identity=dict(_run_config()["identity"], ollama_version="0.34.0")), "ollama_version"),
    (lambda: _run_config(identity=dict(_run_config()["identity"], template_sha256="e" * 64)), "template"),
    (lambda: _run_config(identity=dict(_run_config()["identity"], digest="f" * 64)), "digest"),
    (lambda: _run_config(registry={"entry_id": "nope", "entry_sha256": "0" * 64}), "no registry entry"),
])
def test_verify_run_reports_each_difference(cfg, expect):
    problems = MR.verify_run_config(_committed(), cfg())
    assert any(expect in p for p in problems), problems


def test_api_observed_collects_returned_ids_fingerprints_and_dates():
    recs = [
        {"backend": "openai_compat", "model": "m-2025-01-01", "ok": True, "response_model": "m-2025-01-01",
         "system_fingerprint": "fp_a", "finished_at": "2026-10-01T10:00:00+00:00", "seed": 1},
        {"backend": "openai_compat", "model": "m-2025-01-01", "ok": True, "response_model": "m-2025-01-01",
         "system_fingerprint": "fp_b", "finished_at": "2026-10-02T10:00:00+00:00", "seed": 1},
        {"backend": "openai_compat", "model": "m-2025-01-01", "ok": True, "response_model": "m-2025-02-02",
         "system_fingerprint": None, "finished_at": "2026-10-02T11:00:00+00:00", "seed": 1},
        {"backend": "openai_compat", "model": "m-2025-01-01", "ok": False, "finished_at": "2026-10-02T12:00:00+00:00", "seed": 1},
        {"backend": "ollama", "model": "qwen3:8b", "ok": True},
    ]
    obs = MR.api_observed(recs)
    assert list(obs) == ["m-2025-01-01"]
    o = obs["m-2025-01-01"]
    assert o["returned_models"] == ["m-2025-01-01", "m-2025-02-02"] and o["n_model_mismatch"] == 1
    assert o["system_fingerprints"] == ["fp_a", "fp_b"] and o["n_without_fingerprint"] == 1
    assert o["call_dates_utc"] == ["2026-10-01", "2026-10-02"] and o["n_calls"] == 4 and o["n_ok"] == 3 and o["seed_sent"]
    run_a, run_b = "experiments/run-a/gen.C0.r0", "experiments/run-b/gen.C0.r0"
    reg = MR.merge_api_observed(_committed(), obs, source=run_a)
    reg = MR.merge_api_observed(reg, MR.api_observed(recs[:1]), source=run_b)
    m = reg["api_models"]["models"]["m-2025-01-01"]
    assert m["dated_snapshot"] is True and m["observed"]["n_calls"] == 5 and m["observed"]["system_fingerprints"] == ["fp_a", "fp_b"]
    assert sorted(m["observed_by_run"]) == [run_a, run_b]
    assert MR.validate(reg) == []
    # merging a run again never counts its calls twice
    assert MR.merge_api_observed(reg, obs, source=run_a) == reg
    # a resumed run replaces its earlier observation
    resumed = MR.merge_api_observed(reg, MR.api_observed(recs[:4] + recs[:1]), source=run_a)
    assert resumed["api_models"]["models"]["m-2025-01-01"]["observed"]["n_calls"] == 6
    # the merge needs a run directory relative to the repository
    for bad in (None, "", FAKE_HOME + "/run", "<outside-root>/gen.C0.r0"):
        with pytest.raises(MR.RegistryError):
            MR.merge_api_observed(reg, obs, source=bad)
    # a hand-edited aggregate that no longer follows the per-run observations is reported
    tampered = copy.deepcopy(reg)
    tampered["api_models"]["models"]["m-2025-01-01"]["observed"]["n_calls"] = 99
    assert any("observed_by_run" in p for p in MR.validate(tampered))
    del tampered["api_models"]["models"]["m-2025-01-01"]["observed_by_run"]
    assert any("observed_by_run" in p for p in MR.validate(tampered))


def test_cli_api_observed_update_refuses_run_directories_outside_the_repository(tmp_path):
    regp = tmp_path / "reg.json"
    regp.write_text(json.dumps(_committed()))
    run = tmp_path / "gen.C0.r0"
    (run / "outputs").mkdir(parents=True)
    (run / "outputs" / "x.json").write_text(json.dumps(
        {"backend": "openai_compat", "model": "m-2025-01-01", "ok": True, "response_model": "m-2025-01-01",
         "system_fingerprint": "fp_a", "finished_at": "2026-10-01T10:00:00+00:00", "seed": 1}))
    p = _tool("--registry", regp, "api-observed", run)
    assert p.returncode == 0 and json.loads(p.stdout)["m-2025-01-01"]["n_calls"] == 1
    p = _tool("--registry", regp, "api-observed", run, "--update")
    assert p.returncode == 2 and "inside the repository" in p.stderr
    assert json.loads(regp.read_text()) == _committed()  # nothing written


# ================================================================================ CLI


def _tool(*args, env=None):
    return subprocess.run([sys.executable, "-B", TOOL, *map(str, args)], capture_output=True, text=True, timeout=300,
                          env=dict(os.environ, **(env or {})))


def test_cli_validate_hash_and_verify_run(tmp_path):
    p = _tool("validate")
    assert p.returncode == 0 and f"OK: {len(_committed()['entries'])} entries" in p.stdout
    p = _tool("hash", "qwen3-8b.main")
    assert p.returncode == 0
    assert json.loads(p.stdout)["entry_sha256"] == MR.entry_sha256(_committed()["entries"]["qwen3-8b.main"])
    good, bad = tmp_path / "good", tmp_path / "bad"
    for d, cfg in ((good, _run_config()), (bad, _run_config(opts=dict(_run_config()["opts"], keep_alive="30m")))):
        d.mkdir()
        (d / "config.json").write_text(json.dumps(cfg))
    assert _tool("verify-run", good).returncode == 0
    p = _tool("verify-run", good, bad)
    assert p.returncode == 1 and "keep_alive" in p.stdout
    assert _tool("hash", "no.such.entry").returncode == 2


def test_cli_update_and_check_against_a_fake_host(host, tmp_path):
    regp = tmp_path / "reg.json"
    regp.write_text(json.dumps(_toy_registry()))
    snap = _snap(host)
    sp = tmp_path / "snap.json"
    sp.write_text(json.dumps(snap))
    assert _tool("--registry", regp, "validate").returncode == 1
    p = _tool("--registry", regp, "update", "--snapshot", sp)
    assert p.returncode == 0, p.stderr
    assert _tool("--registry", regp, "validate").returncode == 0
    p = _tool("--registry", regp, "check", "--snapshot", sp)
    assert p.returncode == 0 and "OK" in p.stdout, p.stdout
    snap["ollama"]["version"] = "9.9.9"
    sp.write_text(json.dumps(snap))
    p = _tool("--registry", regp, "check", "--snapshot", sp, "--entry", "toy.main")
    assert p.returncode == 1 and "MISMATCH entries.toy.main.identity.ollama_version" in p.stdout
    assert "entries.toy.var" not in p.stdout  # --entry limits the report
    # the alias is missing: the full check fails, the check for an entry that does not use it passes
    snap["ollama"]["version"] = "0.33.0"
    del snap["ollama"]["models"]["toy-long:latest"]
    sp.write_text(json.dumps(snap))
    p = _tool("--registry", regp, "check", "--snapshot", sp)
    assert p.returncode == 1 and "snapshot: model toy-long:latest: not observed" in p.stdout
    assert _tool("--registry", regp, "check", "--snapshot", sp, "--entry", "toy.main").returncode == 0


def test_cli_refuses_output_that_would_carry_a_path():
    spec = importlib.util.spec_from_file_location("model_registry_tool", TOOL)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    tool._neutral_or_die('{"x": "relative/path"}', "snapshot")
    with pytest.raises(SystemExit):
        tool._neutral_or_die(json.dumps({"x": FAKE_HOME + "/.ollama/models"}), "snapshot")
    with pytest.raises(SystemExit):
        tool._neutral_or_die(json.dumps({"x": os.path.expanduser("~") + "/y"}), "snapshot")


# ================================================================================ with the runners (E08)


def _e08():
    try:
        from orgene.backends import base  # noqa: F401
        from orgene import runner  # noqa: F401
    except ImportError:
        pytest.skip("runner backends (E08) not in this tree yet")
    from orgene.backends import base
    from orgene import runner
    return base, runner


def test_e08_guard_and_registry_agree_on_every_case():
    base, runner = _e08()
    from orgene.backends.ollama import REQUIRED_OPTS, OllamaBackend
    assert set(MR.BACKENDS["ollama"]["required"]) == set(REQUIRED_OPTS) | {"think", "keep_alive"}
    b = OllamaBackend("qwen3:8b", host="http://127.0.0.1:9")
    b._identity = {"digest": QWEN_DIGEST}
    reg = _committed()
    for eid in _qwen3_entry_ids(reg):
        e = reg["entries"][eid]
        opts = {k: v for k, v in e["opts"].items()}
        for k in range(2):
            sent = b.sent_opts(b.build_body([{"role": "user", "content": "x"}], dict(opts, seed=opts["seed"] + k)))
            base.registry_guard(e, backend=b, repeat_index=k)(sent)
            assert MR.compare_sent(e, sent, backend_kind="ollama", model="qwen3:8b", digest=QWEN_DIGEST, repeat_index=k) == []
        for bad in (dict(opts, num_ctx=8192), dict(opts, keep_alive=300), dict(opts, top_k=40), dict(opts, think=True)):
            sent = b.sent_opts(b.build_body([{"role": "user", "content": "x"}], bad))
            with pytest.raises(base.RegistryMismatch):
                base.registry_guard(e, backend=b, repeat_index=0)(sent)
            assert MR.compare_sent(e, sent, backend_kind="ollama", model="qwen3:8b", digest=QWEN_DIGEST)
        entry, rec = runner.load_registry_entry(REG_PATH, eid)
        assert rec["entry_sha256"] == MR.entry_sha256(e) == MR.entry_record(REG_PATH, eid)["entry_sha256"]


def test_e08_runner_refuses_settings_that_differ_from_the_committed_entry(tmp_path):
    _e08()
    runner_py = os.path.join(RUNTIME, "ollama_runner.py")
    # no template text in the fake (the real one is not needed): the run then records no template hash
    fake = _FakeOllama({"qwen3:8b": {"digest": QWEN_DIGEST, "template": None, "parameters": "",
                                     "details": {"format": "gguf", "family": "qwen3", "parameter_size": "8.2B",
                                                 "quantization_level": "Q4_K_M"}}})
    try:
        reqs = tmp_path / "requests.C0.jsonl"
        reqs.write_text(json.dumps({"request_id": "toy-1.C0", "case_id": "toy-1", "condition": "C0",
                                    "messages": [{"role": "user", "content": "Maximise x with x <= 1."}]}) + "\n")

        def run(out, entry, *extra):
            # --local-tokens off: this test is about the registry; with E09's counter on (the default) the runner
            # would read the host's own Ollama store and llama-tokenize, which a fake server does not stand for
            return subprocess.run([sys.executable, "-B", runner_py, "--host", fake.url, "--model", "qwen3:8b",
                                   "--requests", str(reqs), "--out", str(tmp_path / out), "--registry", REG_PATH,
                                   "--registry-entry", entry, "--retry-sleep", "0", "--local-tokens", "off", *extra],
                                  capture_output=True, text=True, timeout=120)
        # the runner's defaults are exactly the main entry; the R0 entries need their own two flags
        assert run("g_main", "qwen3-8b.main").returncode == 0
        assert run("g_r0", "qwen3-8b.r0-v5", "--num-ctx", "16384", "--keep-alive", "30m").returncode == 0
        assert run("g_var", "qwen3-8b.var07", "--temperature", "0.7", "--repeat", "2").returncode == 0
        n = fake.chat_calls
        for out, entry, extra in (("x1", "qwen3-8b.main", ("--num-ctx", "16384")),
                                  ("x2", "qwen3-8b.main", ("--keep-alive", "30m")),
                                  ("x3", "qwen3-8b.var07", ()),
                                  ("x4", "qwen3-8b.r0-ctx16k", ())):
            p = run(out, entry, *extra)
            assert p.returncode != 0 and "registry" in p.stderr, (entry, extra, p.stderr[-300:])
        assert fake.chat_calls == n  # nothing was sent for a refused run
        cfg = json.load(open(tmp_path / "g_main" / "config.json"))
        assert MR.verify_run_config(_committed(), cfg) == []
        cfg = json.load(open(tmp_path / "g_var" / "config.json"))
        assert MR.verify_run_config(_committed(), cfg) == []
    finally:
        fake.close()


# ================================================================================ live (opt-in)


@pytest.mark.skipif(os.environ.get("ORGENE_LIVE_REGISTRY") != "1", reason="set ORGENE_LIVE_REGISTRY=1 on the model host")
def test_live_quick_check_passes():
    p = _tool("check", "--quick")
    assert p.returncode == 0, p.stdout + p.stderr

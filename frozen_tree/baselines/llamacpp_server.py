"""llama-server start-up and identity checks shared by the anchor adapters (ORLM, E17; LLMOPT, E18).

  server_argv(entry, gguf_path, ...)   the llama-server command line from a registry entry's identity.server block;
                                       every setting that can change the output is explicit (context, slots, KV cache
                                       type, flash attention, GPU layers, batch sizes, context shift, prompt caches)
  ollama_loaded(host)                  models Ollama holds in memory (a launch waits until Ollama is idle)
  LlamaServer(argv, url, log_path)     start llama-server, wait for /health, stop it on exit; the log is kept with
                                       paths scrubbed
  check_server_identity(ident, ...)    what the running server reports (/props: model file, context, slots, build)
                                       against the registry entry
  file_sha256(path)                    the GGUF is hashed before a run (the server does not report its hash)

Moved out of baselines/orlm_adapter.py when the LLMOPT anchor moved to llama-server (wave2 merge); orlm_adapter keeps
the same names. Messages carry the caller's prefix ("[orlm]", "[llmopt]").
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RUNTIME = os.path.join(_ROOT, "runtime")
if _RUNTIME not in sys.path:
    sys.path.insert(0, _RUNTIME)

from orgene.backends.base import scrub_paths  # noqa: E402
from orgene.paths import rel  # noqa: E402

# llama-server launch settings a registry entry must fix (identity.server); see server_argv()
SERVER_KEYS = ("ctx_size", "parallel", "cache_type_k", "cache_type_v", "flash_attn", "gpu_layers", "batch_size",
               "ubatch_size", "context_shift", "cache_ram_mib", "cache_reuse")


class ServerRefused(SystemExit):
    """Refused before anything was started or sent."""

    def __init__(self, msg, prefix="[llama-server]"):
        super().__init__(f"{prefix} refused: {msg}")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def server_argv(entry, gguf_path, *, binary="llama-server", host="127.0.0.1", port=8080, prefix="[llama-server]"):
    """llama-server command line from the registry entry: every setting that can change the output is explicit."""
    s = (entry.get("identity") or {}).get("server") or {}
    missing = [k for k in SERVER_KEYS if k not in s]
    if missing:
        raise ServerRefused(f"registry entry identity.server lacks {missing}", prefix)
    return [binary, "-m", gguf_path, "--alias", entry["model"], "--host", host, "--port", str(port),
            "-c", str(s["ctx_size"]), "-np", str(s["parallel"]), "-ctk", str(s["cache_type_k"]),
            "-ctv", str(s["cache_type_v"]), "-fa", str(s["flash_attn"]), "-ngl", str(s["gpu_layers"]),
            "-b", str(s["batch_size"]), "-ub", str(s["ubatch_size"]),
            "--context-shift" if s["context_shift"] else "--no-context-shift",
            "--cache-ram", str(s["cache_ram_mib"]), "--cache-reuse", str(s["cache_reuse"]),
            "--no-webui", "--offline"]


def _get_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8") or "null")


def ollama_loaded(host):
    """Names of the models Ollama holds in memory ([] when Ollama is not reachable: nothing is loaded then)."""
    try:
        _, ps = _get_json(f"{host.rstrip('/')}/api/ps", timeout=10)
    except Exception:  # noqa: BLE001
        return []
    return [m.get("name") or m.get("model") for m in (ps or {}).get("models", [])]


class LlamaServer:
    """Start llama-server, wait until /health says ok, stop it on exit. The log (paths scrubbed) goes to log_path."""

    prefix = "[llama-server]"

    def __init__(self, argv, url, log_path, wait_s=900, prefix=None):
        self.argv, self.url, self.log_path, self.wait_s = argv, url.rstrip("/"), log_path, wait_s
        self.prefix = prefix or self.prefix
        self.proc, self._log = None, None

    def __enter__(self):
        try:
            _get_json(f"{self.url}/health", timeout=2)
            answered = True
        except urllib.error.HTTPError:        # something answers (a server still loading answers 503)
            answered = True
        except (urllib.error.URLError, ConnectionError, OSError):
            answered = False
        if answered:
            raise ServerRefused(f"a server already answers at {self.url}; stop it or choose another --port", self.prefix)
        self._log = tempfile.NamedTemporaryFile(prefix="orgene_llama_server_", suffix=".log", delete=False)
        self.proc = subprocess.Popen(self.argv, stdout=self._log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     start_new_session=True)
        t0 = time.monotonic()
        while time.monotonic() - t0 < self.wait_s:
            if self.proc.poll() is not None:
                self._stop()
                raise SystemExit(f"{self.prefix} llama-server exited during start-up (code {self.proc.returncode}); "
                                 f"log: {rel(self.log_path)}")
            try:
                code, body = _get_json(f"{self.url}/health", timeout=5)
                if code == 200 and (body or {}).get("status") == "ok":
                    return self
            except Exception:  # noqa: BLE001  (503 while loading, or not listening yet)
                pass
            time.sleep(1.0)
        self._stop()
        raise SystemExit(f"{self.prefix} llama-server did not become ready within {self.wait_s} s")

    def _stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=30)
        if self._log is not None:
            self._log.close()
            try:
                with open(self._log.name, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.read().splitlines()[-400:]
                os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
                with open(self.log_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(scrub_paths(line) for line in lines) + "\n")
            finally:
                os.unlink(self._log.name)
            self._log = None

    def __exit__(self, *exc):
        self._stop()
        return False


def check_server_identity(ident, entry, gguf_file, build=None):
    """Differences between what llama-server reports (/props) and the registry entry."""
    s = (entry.get("identity") or {}).get("server") or {}
    problems = []
    if ident.get("model_file") != gguf_file:
        problems.append(f"model file: server {ident.get('model_file')!r} != registry {gguf_file!r}")
    if ident.get("n_ctx") != s.get("ctx_size"):
        problems.append(f"context: server {ident.get('n_ctx')!r} != registry {s.get('ctx_size')!r}")
    if ident.get("total_slots") != s.get("parallel"):
        problems.append(f"slots: server {ident.get('total_slots')!r} != registry {s.get('parallel')!r}")
    if build is not None and not str(ident.get("build_info") or "").startswith(f"b{build}"):
        problems.append(f"llama.cpp build: server {ident.get('build_info')!r} is not b{build}")
    return problems

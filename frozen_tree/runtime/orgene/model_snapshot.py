"""Read-only snapshot of the model environment for the registry (E19).

What is read, and how (nothing is written, restarted, pulled, created or loaded):

  Ollama HTTP API   GET /api/version, GET /api/tags, POST /api/show (metadata only; does not load a model).
                    `ollama_request` refuses every other endpoint before opening a connection, so the snapshot
                    cannot start a generation (/api/chat, /api/generate) or change the model store.
  model store       manifest files and the small blobs (config, params, template, license) of the registered models,
                    read from the Ollama models directory; the manifest sha256 must equal the /api/tags digest and
                    every small blob's content must hash to its name. Weight blobs are re-hashed only on request.
  server settings   flash attention, KV cache type and the other result-relevant settings (allowlist
                    model_registry.SERVER_SETTING_KEYS), from up to three places that must agree:
                      - the launchd job that starts the server (EnvironmentVariables),
                      - the running server process's environment (`ps -E`, or /proc/<pid>/environ),
                      - the server log's own start-up line (`msg="server config"`),
                    plus, from the same log, what every load of a registered model's weights actually ran with
                    (llama_context flash_attn, llama_kv_cache K/V types, n_ctx).
  execution         the generation interpreter's start-up check (orgene.env.check_env: PuLP, CBC, a one-variable LP).
  baselines         package versions in the baselines interpreter via importlib.metadata (no package is imported),
                    whether a COPT license file exists (file existence only), glpk and llama.cpp versions.

Neutral output: no path, host or user name is ever recorded. Log lines are parsed for fixed fields only (a blob's
hex digest, a setting's value); models that are not in the registry (other projects) are not recorded at all.
Times are converted to UTC.
"""
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import env as E
from .model_registry import SERVER_SETTING_KEYS, registered_ollama_models

SNAPSHOT_SCHEMA = "orgene.r1.model_env_snapshot.v1"
DEFAULT_HOST = "http://127.0.0.1:11434"
# the only Ollama endpoints the snapshot may call
READ_ONLY_ENDPOINTS = frozenset({("GET", "/api/version"), ("GET", "/api/tags"), ("POST", "/api/show")})
SMALL_BLOB_MAX = 4 << 20  # config / params / template / license blobs are a few kB
FA_KV_KEYS = ("OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE")

# host defaults (all overridable; expanded at run time, never recorded)
DEFAULT_MODELS_DIR = os.path.join("~", ".ollama", "models")
DEFAULT_LAUNCHD_PLIST = os.path.join("~", "Library", "LaunchAgents", "homebrew.mxcl.ollama.plist")
DEFAULT_BASELINES_PY = os.path.join("~", "venvs", "baselines", "bin", "python")
DEFAULT_BIN_DIR = "/opt/homebrew/bin"

_BLOB_RE = re.compile(r"sha256[-:]([0-9a-f]{64})")
_TIME_RE = re.compile(r"\btime=(\S+)")
_ENVMAP_RE = re.compile(r'env="map\[(.*?)\]"')
_SETTING_RE = re.compile(r"(?:^|\s)(OLLAMA_[A-Z_]+):(\S*)")
_ENVVAR_RE = re.compile(r"(?:^|\s)(OLLAMA_[A-Z_]+)=(\S*)")
_NCTX_RE = re.compile(r"llama_context:\s+n_ctx\s+=\s+(\d+)")
_FA_RE = re.compile(r"llama_context:\s+flash_attn\s+=\s+(\w+)")
_KV_RE = re.compile(r"llama_kv_cache: size = .*?K \((\w+)\).*?V \((\w+)\)")
_LLAMA_VER_RE = re.compile(r"version:\s*(\S+)\s*\(build\s*(\d+),\s*commit\s*([0-9a-f]+)\)")
# log lines that start (or announce) one model load and name its weight blob
_LOAD_MARKERS = ('msg="using llama-server for model"', 'msg="loading model via llama-server"', 'msg="starting runner"',
                 'msg="starting llama server"', "llama_model_loader: loaded meta data")


class ReadOnlyViolation(RuntimeError):
    """An endpoint outside READ_ONLY_ENDPOINTS was requested."""


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_utc(ts):
    """ISO timestamp with an offset (as in the server log) -> 'YYYY-MM-DDTHH:MM:SSZ'. None if unparsable."""
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        return None
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------------- Ollama API


def ollama_request(host, method, path, payload=None, timeout=60):
    """One read-only request. Anything outside READ_ONLY_ENDPOINTS raises before a connection is opened."""
    if (method, path) not in READ_ONLY_ENDPOINTS:
        raise ReadOnlyViolation(f"{method} {path} is not a read-only endpoint; the snapshot only reads")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(host.rstrip("/") + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _manifest_path(models_dir, tag):
    name, _, t = tag.partition(":")
    t = t or "latest"
    parts = name.split("/")
    if len(parts) == 1:
        parts = ["registry.ollama.ai", "library"] + parts
    elif len(parts) == 2:
        parts = ["registry.ollama.ai"] + parts
    return os.path.join(models_dir, "manifests", *parts, t)


def _blob_path(models_dir, digest):
    return os.path.join(models_dir, "blobs", "sha256-" + digest)


def model_identity(tag, *, host, models_dir, tags_by_name, verify_weights=False):
    """Identity of one registered Ollama model from the API and the model store."""
    out = {"tag": tag}
    t = tags_by_name.get(tag)
    out["digest"] = (t or {}).get("digest")
    out["details"] = {k: (t or {}).get("details", {}).get(k) for k in ("format", "family", "parameter_size", "quantization_level")} if t else None
    if t is None:
        out["error"] = "not installed"
        return out
    mpath = _manifest_path(models_dir, tag)
    if os.path.isfile(mpath):
        out["manifest_sha256"] = _sha256_file(mpath)
        out["digest_matches_manifest"] = out["manifest_sha256"] == out["digest"]
        with open(mpath, "r", encoding="utf-8") as f:
            man = json.load(f)
        layers, verified = {}, {}
        for layer in man.get("layers", []):
            kind = str(layer.get("mediaType", "")).rsplit(".", 1)[-1]
            m = _BLOB_RE.search(str(layer.get("digest", "")))
            if not m:
                continue
            layers[kind] = m.group(1)
            bpath = _blob_path(models_dir, m.group(1))
            size = layer.get("size") or 0
            if not os.path.isfile(bpath):
                verified[kind] = False
            elif size <= SMALL_BLOB_MAX or verify_weights:
                verified[kind] = _sha256_file(bpath) == m.group(1)
            else:
                verified[kind] = None  # large blob, not re-hashed
        out["layers"] = layers
        out["layer_hashes_verified"] = verified
        cm = _BLOB_RE.search(str((man.get("config") or {}).get("digest", "")))
        if cm and os.path.isfile(_blob_path(models_dir, cm.group(1))):
            with open(_blob_path(models_dir, cm.group(1)), "r", encoding="utf-8") as f:
                cfg = json.load(f)
            out["config"] = {k: cfg.get(k) for k in ("model_format", "model_family", "model_type", "file_type")}
        if "params" in layers and os.path.isfile(_blob_path(models_dir, layers["params"])):
            with open(_blob_path(models_dir, layers["params"]), "r", encoding="utf-8") as f:
                text = f.read()
            out["params_blob_text"] = text
            try:
                out["params"] = json.loads(text)
            except ValueError:
                out["params"] = None
    else:
        out["manifest_sha256"] = None
        out["digest_matches_manifest"] = None
        out["error"] = "manifest file not found (models directory not readable here)"
    try:
        show = ollama_request(host, "POST", "/api/show", {"model": tag})
        tmpl = show.get("template")
        out["template_sha256"] = hashlib.sha256(tmpl.encode("utf-8")).hexdigest() if isinstance(tmpl, str) else None
        if out.get("layers", {}).get("template") and out["template_sha256"]:
            out["template_matches_blob"] = out["template_sha256"] == out["layers"]["template"]
        out["capabilities"] = show.get("capabilities")
        gi = show.get("model_info") or {}
        out["model_info"] = {k: gi.get(k) for k in ("general.architecture", "general.file_type", "general.parameter_count",
                                                     "general.quantization_version") if k in gi}
    except Exception as e:  # noqa: BLE001
        out["show_error"] = type(e).__name__
    return out


# ---------------------------------------------------------------------------------------------------- server settings


def _norm_fa(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on", "enabled"):
        return True
    if s in ("0", "false", "no", "off", "disabled"):
        return False
    return None if s == "" else s


def _norm_kv(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    return s or "f16"


def read_launchd_env(plist_path):
    """The allowlisted OLLAMA_* variables of the launchd job, or None when there is no such job file."""
    if not plist_path or not os.path.isfile(plist_path):
        return None
    with open(plist_path, "rb") as f:
        d = plistlib.load(f)
    ev = d.get("EnvironmentVariables") or {}
    return {k: str(v) for k, v in ev.items() if k in SERVER_SETTING_KEYS}


def _server_pids():
    try:
        out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=20).stdout
    except Exception:  # noqa: BLE001
        return []
    pids = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        argv = parts[1].split()
        if argv and os.path.basename(argv[0]) == "ollama" and len(argv) > 1 and argv[1] == "serve":
            pids.append(int(parts[0]))
    return pids


def read_process_env(pid=None):
    """(allowlisted OLLAMA_* variables of the running `ollama serve`, start time UTC, n processes). Values only."""
    pids = [pid] if pid else _server_pids()
    if not pids:
        return None, None, 0
    p = pids[0]
    env = None
    proc = f"/proc/{p}/environ"
    try:
        if os.path.exists(proc):
            with open(proc, "rb") as f:
                pairs = [x.decode("utf-8", "replace").split("=", 1) for x in f.read().split(b"\0") if b"=" in x]
            env = {k: v for k, v in pairs if k in SERVER_SETTING_KEYS}
        else:
            text = subprocess.run(["ps", "-E", "-p", str(p), "-o", "command="], capture_output=True, text=True,
                                  timeout=20).stdout
            env = {k: v for k, v in _ENVVAR_RE.findall(text) if k in SERVER_SETTING_KEYS}
    except Exception:  # noqa: BLE001
        env = None
    started = None
    try:
        ls = subprocess.run(["ps", "-p", str(p), "-o", "lstart="], capture_output=True, text=True, timeout=20).stdout.strip()
        if ls:
            t = time.mktime(time.strptime(ls, "%a %b %d %H:%M:%S %Y"))
            started = datetime.fromtimestamp(t, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:  # noqa: BLE001
        started = None
    return env, started, len(pids)


def scan_server_log(log_path, blobs_of_interest):
    """Parse the server log for the last start-up settings line and for every load of the given weight blobs.

    Returns {"startup": {settings}, "startup_logged_at": UTC, "n_startups": int,
             "loads": {blob: {n_loads, last_load_at, flash_attn_seen, kv_cache_seen, n_ctx_seen}}}.
    Only fixed fields are extracted; lines are never copied.
    """
    res = {"startup": None, "startup_logged_at": None, "n_startups": 0, "loads": {}}
    if not log_path or not os.path.isfile(log_path):
        return None
    want = set(blobs_of_interest or ())
    cur = None  # [blob, load time, KV line seen] of the load in progress, only for a blob of interest
    acc = {}
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if 'msg="server config"' in line:
                m = _ENVMAP_RE.search(line)
                if m:
                    res["startup"] = {k: v for k, v in _SETTING_RE.findall(m.group(1)) if k in SERVER_SETTING_KEYS}
                    t = _TIME_RE.search(line)
                    res["startup_logged_at"] = to_utc(t.group(1)) if t else None
                    res["n_startups"] += 1
                continue
            is_marker = "sha256-" in line and any(s in line for s in _LOAD_MARKERS)
            if is_marker:
                m = _BLOB_RE.search(line)
                blob = m.group(1) if m else None
                if blob not in want:
                    cur = None  # another model (or a file being imported): its lines are not recorded
                    continue
                t = _TIME_RE.search(line)
                at = to_utc(t.group(1)) if t else None
                if cur and cur[0] == blob and not cur[2]:
                    # the same load announced again ("using llama-server", "loading model via", "loaded meta data")
                    if at and not cur[1]:
                        cur[1] = at
                        acc[blob]["last_load_at"] = at
                    continue
                cur = [blob, at, False]
                d = acc.setdefault(blob, {"n_loads": 0, "last_load_at": None, "fa": set(), "kv": set(), "ctx": set()})
                d["n_loads"] += 1
                d["last_load_at"] = at
                continue
            if cur is None or not line.startswith("llama_"):
                continue
            d = acc[cur[0]]
            m = _FA_RE.search(line)
            if m:
                d["fa"].add(m.group(1))
                continue
            m = _NCTX_RE.search(line)
            if m:
                d["ctx"].add(int(m.group(1)))
                continue
            m = _KV_RE.search(line)
            if m:
                d["kv"].add(f"{m.group(1)}/{m.group(2)}")
                cur[2] = True
    for blob, d in sorted(acc.items()):
        res["loads"][blob] = {"n_loads": d["n_loads"], "last_load_at": d["last_load_at"],
                              "flash_attn_seen": sorted(d["fa"]), "kv_cache_seen": sorted(d["kv"]),
                              "n_ctx_seen": sorted(d["ctx"])}
    return res


def server_settings(*, plist_path, log_path, blobs_of_interest, proc_env=None, proc_started=None, n_proc=None,
                    read_process=True):
    """Combine the three sources. The start-up line is the server's own record of what it runs with; the launchd
    job and the process environment must agree with it on flash attention and the KV cache type."""
    plist_env = read_launchd_env(plist_path)
    if proc_env is None and read_process:
        proc_env, proc_started, n_proc = read_process_env()
    log = scan_server_log(log_path, blobs_of_interest)
    startup = (log or {}).get("startup")
    sources = {"launchd_job": plist_env, "process_env": proc_env, "startup_log": startup}
    seen = {name: ({k: s.get(k) for k in FA_KV_KEYS if k in s} if isinstance(s, dict) else None)
            for name, s in sources.items()}
    disagreements = []
    for key, norm in (("OLLAMA_FLASH_ATTENTION", _norm_fa), ("OLLAMA_KV_CACHE_TYPE", _norm_kv)):
        vals = {name: norm(s.get(key)) for name, s in sources.items() if isinstance(s, dict)}
        if len(set(map(repr, vals.values()))) > 1:
            disagreements.append(f"{key}: " + ", ".join(f"{n}={v}" for n, v in sorted(vals.items())))
    # effective values: the server's start-up line, else the process environment, else the launchd job
    eff_from, eff = next(((n, s) for n, s in (("startup_log", startup), ("process_env", proc_env),
                                              ("launchd_job", plist_env)) if isinstance(s, dict)), (None, None))
    observed_any = any(isinstance(s, dict) for s in sources.values())
    return {
        "settings": {k: eff[k] for k in sorted(eff)} if eff else None,
        "settings_from": eff_from,
        "flash_attention": _norm_fa(eff.get("OLLAMA_FLASH_ATTENTION")) if eff else None,
        "kv_cache_type": _norm_kv(eff.get("OLLAMA_KV_CACHE_TYPE", "")) if eff else None,
        "sources_seen": {k: v for k, v in seen.items() if v is not None},
        "agree": (not disagreements) if observed_any else None,
        "disagreements": disagreements,
        "process_started_at": proc_started,
        "n_server_processes": n_proc,
        "startup_logged_at": (log or {}).get("startup_logged_at"),
        "n_startups_in_log": (log or {}).get("n_startups"),
        "model_loads": (log or {}).get("loads") or {},
    }


# ---------------------------------------------------------------------------------------------------- baselines / tools

_BASELINE_CODE = r'''
import importlib.metadata as md, importlib.util as iu, json, os, sys
out = {"python_version": sys.version.split()[0], "packages": {}}
for p in sys.argv[1:]:
    try:
        out["packages"][p] = md.version(p)
    except md.PackageNotFoundError:
        out["packages"][p] = None
cands = [os.environ.get("COPT_LICENSE_DIR"), os.path.join(os.path.expanduser("~"), "copt")]
spec = iu.find_spec("coptpy")
if spec and spec.origin:
    cands.append(os.path.dirname(spec.origin))
found = False
for d in cands:
    if d and os.path.isdir(d):
        for fn in ("license.dat", "license.key"):
            if os.path.isfile(os.path.join(d, fn)):
                found = True
out["copt_license_file_found"] = found
print(json.dumps(out))
'''


def baselines_env(python, packages=("coptpy", "pyomo", "numpy", "gguf", "transformers", "torch")):
    """Package versions (metadata only; nothing is imported, no bytecode written) and the COPT license-file probe."""
    if not python or not os.path.exists(python):
        return {"observed": False, "error": "baselines interpreter not present"}
    try:
        p = subprocess.run([python, "-I", "-B", "-c", _BASELINE_CODE, *packages], capture_output=True, text=True,
                           timeout=60, env={"PATH": os.environ.get("PATH", ""), "HOME": os.path.expanduser("~")})
        info = json.loads((p.stdout or "").strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001
        return {"observed": False, "error": f"could not run the baselines interpreter: {type(e).__name__}"}
    info["observed"] = True
    return info


def _which(name, bin_dir):
    p = os.path.join(bin_dir, name) if bin_dir else None
    if p and os.path.isfile(p) and os.access(p, os.X_OK):
        return p
    return shutil.which(name)


def tool_versions(bin_dir=DEFAULT_BIN_DIR):
    out = {}
    for name in ("llama-server", "llama-tokenize"):
        exe = _which(name, bin_dir)
        if not exe:
            continue
        try:
            p = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
            m = _LLAMA_VER_RE.search((p.stdout or "") + (p.stderr or ""))
            if m:
                out[name.replace("-", "_")] = {"version": m.group(1), "build": int(m.group(2)), "commit": m.group(3)}
        except Exception:  # noqa: BLE001
            pass
    exe = _which("glpsol", bin_dir)
    if exe:
        try:
            p = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
            m = re.search(r"GLPK LP/MIP Solver\s+(\S+)", p.stdout or "")
            if m:
                out["glpsol"] = {"version": m.group(1)}
        except Exception:  # noqa: BLE001
            pass
    return out


# ---------------------------------------------------------------------------------------------------- snapshot


def snapshot(reg, *, host=DEFAULT_HOST, models_dir=None, plist_path=None, log_path=None, baselines_python=None,
             bin_dir=DEFAULT_BIN_DIR, orgene_python=None, verify_weights=False, scan_log=True, parts=None,
             proc_env=None, proc_started=None, n_proc=None, read_process=True):
    """Collect the observed facts for every model and setting the registry names. Read-only; see module docstring."""
    parts = set(parts or ("ollama", "execution", "baselines", "tools"))
    models_dir = os.path.expanduser(models_dir or os.environ.get("OLLAMA_MODELS") or DEFAULT_MODELS_DIR)
    snap = {"snapshot_schema": SNAPSHOT_SCHEMA, "taken_at": now_utc(), "read_only": True,
            "tool": "tools/model_registry.py snapshot"}
    if "ollama" in parts:
        o = {}
        try:
            o["version"] = ollama_request(host, "GET", "/api/version").get("version")
            tags = ollama_request(host, "GET", "/api/tags").get("models", [])
        except (urllib.error.URLError, OSError, ValueError) as e:
            o["error"] = f"Ollama server not reachable: {type(e).__name__}"
            tags = None
        if tags is not None:
            by_name = {}
            for t in tags:
                for n in (t.get("name"), t.get("model")):
                    if n:
                        by_name[n] = t
            o["models"] = {tag: model_identity(tag, host=host, models_dir=models_dir, tags_by_name=by_name,
                                               verify_weights=verify_weights)
                           for tag in registered_ollama_models(reg)}
            blobs = sorted({(m.get("layers") or {}).get("model") for m in o["models"].values()} - {None})
            o["server"] = server_settings(
                plist_path=os.path.expanduser(plist_path or DEFAULT_LAUNCHD_PLIST),
                log_path=os.path.expanduser(log_path) if (log_path and scan_log) else None,
                blobs_of_interest=blobs, proc_env=proc_env, proc_started=proc_started, n_proc=n_proc,
                read_process=read_process)
        snap["ollama"] = o
    if "execution" in parts:
        ex = E.check_env(orgene_python or E.orgene_python())
        snap["execution"] = {k: ex.get(k) for k in ("ok", "interpreter", "interpreter_source", "python_version", "machine",
                                                    "pulp_version", "cbc_version", "lp_status", "error")}
    if "baselines" in parts:
        snap["baselines"] = baselines_env(os.path.expanduser(baselines_python or os.environ.get("ORGENE_BASELINES_PY")
                                                             or DEFAULT_BASELINES_PY))
    if "tools" in parts:
        snap["tools"] = tool_versions(bin_dir)
    return snap


def default_log_path(plist_path=None):
    """The server log named by the launchd job (StandardErrorPath), if any."""
    p = os.path.expanduser(plist_path or DEFAULT_LAUNCHD_PLIST)
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        d = plistlib.load(f)
    return d.get("StandardErrorPath") or d.get("StandardOutPath")

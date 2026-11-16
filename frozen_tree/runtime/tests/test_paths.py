"""E02: relative paths in artifacts, fixed interpreter for generated programs, no PATH python3 in entry points.

Fixtures are the author-written smoke case and self-made strings only; no benchmark case is read.
"""
import json
import os
import re
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import env as E  # noqa: E402
from orgene import paths as PA  # noqa: E402
from orgene.execute import run_program  # noqa: E402
from orgene.selftest import GOOD_CODE  # noqa: E402

CLI = os.path.join(RUNTIME, "orgene_cli.py")
SMOKE_CASES = os.path.join(ROOT, "data", "cases", "smoke.jsonl")
# a home-directory path built in pieces so that this file itself stays free of such literals
FAKE_HOME_PATH = "/" + "Users" + "/someone/project/data/cases/x.jsonl"


def _no_pulp_python(tmp_path):
    """An interpreter that exists and runs, but cannot import pulp (site-packages disabled)."""
    w = tmp_path / "python-no-pulp"
    w.write_text(f"#!/bin/sh\nexec '{sys.executable}' -S \"$@\"\n")
    w.chmod(w.stat().st_mode | stat.S_IEXEC)
    return str(w)


# ------------------------------------------------------------------ paths.rel / sanitize_argv


def test_rel_inside_root_is_relative():
    assert PA.rel(os.path.join(ROOT, "data", "cases", "smoke.jsonl")) == "data/cases/smoke.jsonl"
    assert PA.rel(ROOT) == "."
    assert PA.rel(None) is None


def test_rel_outside_root_keeps_only_the_basename(tmp_path):
    p = tmp_path / "deep" / "requests.C0.jsonl"
    assert PA.rel(str(p)) == "<outside-root>/requests.C0.jsonl"
    assert PA.rel(FAKE_HOME_PATH) == "<outside-root>/x.jsonl"


def test_sanitize_argv_replaces_root_and_outside_paths(tmp_path):
    argv = [os.path.join(RUNTIME, "ollama_runner.py"), "--requests", os.path.join(ROOT, "experiments", "r", "requests.C0.jsonl"),
            "--out=" + str(tmp_path / "gen"), "--model", "qwen3:8b", "relative/path.jsonl"]
    got = PA.sanitize_argv(argv)
    assert got == ["$R1/runtime/ollama_runner.py", "--requests", "$R1/experiments/r/requests.C0.jsonl",
                   "--out=<outside-root>/gen", "--model", "qwen3:8b", "relative/path.jsonl"]
    assert not PA.find_absolute_paths(json.dumps(got))


def test_scanner_reports_a_planted_absolute_path(tmp_path):
    """Negative control: an absolute home path written into an artifact must be reported."""
    art = tmp_path / "run_config.json"
    art.write_text(json.dumps({"cases_path": FAKE_HOME_PATH, "ok": "data/cases/x.jsonl"}))
    hits = PA.find_absolute_paths(art.read_text())
    assert hits == [FAKE_HOME_PATH]


# ------------------------------------------------------------------ full fake-backend run


class _MockOpenAI(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        out = {"id": "mock-1", "model": body["model"],
               "choices": [{"message": {"content": "```python\n" + GOOD_CODE + "```"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 20}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.mark.skipif(not os.path.exists(SMOKE_CASES), reason="data/cases/smoke.jsonl missing")
def test_full_fake_backend_run_writes_no_absolute_paths(tmp_path):
    run = tmp_path / "20260101-mock-smoke-dev-C0"
    py = E.orgene_python()
    if not os.path.exists(py):
        pytest.skip(f"generation interpreter {py} not present on this host")
    base = [sys.executable, CLI]
    p = subprocess.run(base + ["requests", "--run", str(run), "--cases", SMOKE_CASES, "--cond", "C0", "C3L", "--limit", "1"],
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr
    srv = HTTPServer(("127.0.0.1", 0), _MockOpenAI)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        g = subprocess.run([sys.executable, os.path.join(RUNTIME, "api_runner.py"), "--backend", "compat",
                            "--base-url", f"http://127.0.0.1:{srv.server_address[1]}/v1", "--api-key-env", "MOCK_KEY",
                            "--model", "mock-model", "--requests", str(run / "requests.C0.jsonl"), "--out", str(run / "gen.C0.r0")],
                           capture_output=True, text=True, env=dict(os.environ, MOCK_KEY="x"), timeout=120)
    finally:
        srv.shutdown()
    assert g.returncode == 0, g.stderr
    for args in (["validate", "--run", str(run), "--cases", SMOKE_CASES, "--cond", "C0", "--round", "0"],
                 ["score", "--run", str(run), "--cases", SMOKE_CASES, "--cond", "C0"],
                 ["report", "--run", str(run)]):
        q = subprocess.run(base + args, capture_output=True, text=True, timeout=300)
        assert q.returncode == 0, q.stderr
    cfg = json.load(open(run / "run_config.json"))
    assert cfg["cases_path"] == "data/cases/smoke.jsonl"
    assert cfg["prompts"]["gene_store_path"] == "genes/genes.r1.jsonl"
    assert cfg["python_env"]["ok"] is True
    rcfg = json.load(open(run / "gen.C0.r0" / "config.json"))
    assert rcfg["requests_path"] == "<outside-root>/requests.C0.jsonl"
    assert rcfg["argv"][0] == "$R1/runtime/api_runner.py"
    res = [json.loads(l) for l in open(run / "results.C0.jsonl") if l.strip()]
    assert res and res[0]["correct"] is True
    hits = []
    for dirpath, _, files in os.walk(run):
        for fn in files:
            text = open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace").read()
            hits += [(fn, h) for h in PA.find_absolute_paths(text)]
            assert str(tmp_path) not in text, fn
    assert not hits, hits


# ------------------------------------------------------------------ interpreter


def test_default_interpreter_is_fixed_not_path(monkeypatch):
    monkeypatch.delenv(E.ENV_VAR, raising=False)
    assert E.orgene_python() == "/opt/homebrew/bin/python3"
    monkeypatch.setenv(E.ENV_VAR, "/some/other/python")
    assert E.orgene_python() == "/some/other/python"


def test_env_check_passes_for_the_generation_interpreter():
    py = E.orgene_python()
    if not os.path.exists(py):
        pytest.skip(f"generation interpreter {py} not present on this host")
    r = E.check_env(py)
    assert r["ok"], r
    assert r["lp_status"] == "Optimal" and r["lp_objective"] == 1.0
    assert r["pulp_version"] and r["cbc_path"]
    assert not PA.find_absolute_paths(json.dumps(r))


def test_env_check_fails_for_an_interpreter_without_pulp(tmp_path, monkeypatch):
    bad = _no_pulp_python(tmp_path)
    r = E.check_env(bad)
    assert r["ok"] is False and "pulp" in r["error"]
    E._CACHE.pop(bad, None)
    with pytest.raises(SystemExit):
        E.require_env(bad)
    # the CLI entry point exits non-zero
    p = subprocess.run([sys.executable, CLI, "env", "--python", bad], capture_output=True, text=True, timeout=120)
    assert p.returncode == 1
    # ... and so does `requests`, before writing anything
    run = tmp_path / "run"
    p = subprocess.run([sys.executable, CLI, "requests", "--run", str(run), "--cases", SMOKE_CASES, "--cond", "C0", "--python", bad],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode != 0 and not run.exists()
    missing = E.check_env(str(tmp_path / "no-such-python"))
    assert missing["ok"] is False and missing["error"] == "interpreter not found"


def test_run_program_uses_orgene_py_not_the_calling_interpreter(tmp_path, monkeypatch):
    """With ORGENE_PY pointing at a python without pulp, the canned good program must fail to import pulp."""
    monkeypatch.setenv(E.ENV_VAR, _no_pulp_python(tmp_path))
    r = run_program(GOOD_CODE, timeout=60)
    assert not r["exec_ok"] and "pulp" in r["stderr_tail"]


def test_no_entry_point_calls_path_python3():
    """Shell entry points must use $ORGENE_PY (default /opt/homebrew/bin/python3), never a bare `python3` from PATH."""
    bad = []
    pat = re.compile(r"(^|[\s;|&(`])python3?(\s|$)")
    for d in ("runtime", "analysis", "tools"):
        for dirpath, _, files in os.walk(os.path.join(ROOT, d)):
            for fn in files:
                if not fn.endswith(".sh"):
                    continue
                for i, line in enumerate(open(os.path.join(dirpath, fn), encoding="utf-8"), 1):
                    code = line.split(" #", 1)[0]
                    if code.lstrip().startswith("#"):
                        continue
                    if pat.search(code):
                        bad.append(f"{fn}:{i}")
    assert not bad, bad


# ------------------------------------------------------------------ program output (execute.run_program, wave2 merge)


def test_neutral_exec_text_drops_the_run_program_directories_and_the_home_directory(tmp_path, monkeypatch):
    home = str(tmp_path / "h")
    monkeypatch.setenv("HOME", home)
    tmp_root = "/" + "var" + "/" + "folders" + "/ab/cd/T/"  # spelled in pieces, as in paths.py
    text = (f'File "{tmp_root}orgene_exec_k3j2x9/prog.py", line 3\n'
            f"cwd={tmp_root}orgene_exec_k3j2x9 rec=({tmp_root}orgene_rec_z9/importlib_bootstrap/solve_recorder.py)\n"
            f'  File "{home}/venvs/b/lib/x.py", line 1\n{home}\n{home}x/y\n')
    out = PA.neutral_exec_text(text)
    assert out == ('File "prog.py", line 3\ncwd=<prog-dir> rec=(importlib_bootstrap/solve_recorder.py)\n'
                   '  File "~/venvs/b/lib/x.py", line 1\n~\n' + home + 'x/y\n')  # only whole components
    assert PA.neutral_exec_text(None) is None and PA.neutral_exec_text("") == ""
    # a traceback line reads as the repair-message scrub (genes.scrub_exec_paths) always left it
    from orgene import genes as G
    first = text.splitlines()[0]
    assert G.scrub_exec_paths(first) == PA.neutral_exec_text(first)


def test_neutral_home_takes_this_process_home_and_its_real_path(tmp_path, monkeypatch):
    real = tmp_path / "real_home"
    real.mkdir()
    link = tmp_path / "link_home"
    link.symlink_to(real)
    monkeypatch.setenv("HOME", str(link))
    text = f"{link}/a and {os.path.realpath(real)}/b and {tmp_path}/c"
    assert PA.neutral_home(text) == f"~/a and ~/b and {tmp_path}/c"

"""E21: the evidence snapshot takes dev runs only; test runs only with --include-test and after the freeze gate.

Runs the real script on a copy of the runtime with invented run directories (metrics files with made-up numbers).
"""
import json
import os
import shutil
import stat
import subprocess
import sys

from conftest import ROOT, copy_runtime_repo, write

SCRIPT = os.path.join(ROOT, "analysis", "make_evidence_snapshot.sh")


def _setup(tmp_path):
    root = copy_runtime_repo(tmp_path / "copy")
    os.makedirs(os.path.join(root, "analysis"))
    shutil.copy(SCRIPT, os.path.join(root, "analysis", "make_evidence_snapshot.sh"))
    for name in ("20261101-m-toy-dev-C0", "20261101-m-toy-test-C0", "20261101-m-toy-smoke-C0", "20261101-m-toy-other-C0"):
        write(root, f"experiments/{name}/metrics.C0.json", json.dumps({"condition": "C0", "n": 1}))
    return root


def _run(root, *args):
    env = dict(os.environ, ORGENE_PY=sys.executable)
    return subprocess.run(["bash", os.path.join(root, "analysis", "make_evidence_snapshot.sh")] + list(args),
                          capture_output=True, text=True, timeout=300, env=env, cwd=root)


def _unlock(path):
    for dirpath, dirnames, files in os.walk(path):
        os.chmod(dirpath, os.stat(dirpath).st_mode | stat.S_IWUSR)


def test_default_snapshot_takes_dev_and_smoke_only(tmp_path):
    root = _setup(tmp_path)
    p = _run(root, "dev-snap")
    dst = os.path.join(root, "paper", "evidence", "dev-snap")
    try:
        assert p.returncode == 0, p.stderr
        assert sorted(os.listdir(os.path.join(dst, "runs"))) == ["20261101-m-toy-dev-C0", "20261101-m-toy-smoke-C0"]
        assert "not taken (name contains test): 20261101-m-toy-test-C0" in p.stdout
        sums = open(os.path.join(dst, "SHA256SUMS")).read()
        assert "test-C0" not in sums
    finally:
        _unlock(dst)


def test_default_snapshot_skips_dev_named_runs_that_touch_sealed_cases(tmp_path):
    # the copy declares smoke-0002 / smoke-0003 sealed; the run names say dev, the contents do not
    root = _setup(tmp_path)
    runs = {"20261101-m-toy-dev-C1": ("requests.C1.jsonl", json.dumps({"case_id": "smoke-0002"}) + "\n"),
            "20261101-m-toy-dev-C2": ("run_config.json", json.dumps({"split": "test"})),
            "20261101-m-toy-dev-C3": ("freeze_gate.jsonl", "{}\n"),
            "20261101-m-toy-dev-C4": ("requests.C4.jsonl", json.dumps({"case_id": "smoke-0001"}) + "\n")}
    for name, (fn, text) in runs.items():
        write(root, f"experiments/{name}/metrics.C0.json", json.dumps({"condition": "C0", "n": 1}))
        write(root, f"experiments/{name}/{fn}", text)
    p = _run(root, "dev-snap")
    dst = os.path.join(root, "paper", "evidence", "dev-snap")
    try:
        assert p.returncode == 0, p.stderr
        assert sorted(os.listdir(os.path.join(dst, "runs"))) == [
            "20261101-m-toy-dev-C0", "20261101-m-toy-dev-C4", "20261101-m-toy-smoke-C0"]
        for name in ("20261101-m-toy-dev-C1", "20261101-m-toy-dev-C2", "20261101-m-toy-dev-C3"):
            assert f"not taken (run touches sealed cases): {name}" in p.stdout
    finally:
        _unlock(dst)


def test_include_test_is_refused_without_a_registered_freeze(tmp_path):
    root = _setup(tmp_path)
    p = _run(root, "--include-test", "all-snap")
    assert p.returncode != 0 and "refused by the freeze gate" in p.stderr
    assert not os.path.exists(os.path.join(root, "paper", "evidence", "all-snap"))


def test_include_test_after_the_freeze_records_the_gate(tmp_path, terms_file):
    root = _setup(tmp_path)
    fz = os.path.join(root, "tools", "freeze.py")
    assert subprocess.run([sys.executable, fz, "make", "--anon-terms", terms_file], capture_output=True, text=True).returncode == 0
    assert subprocess.run([sys.executable, fz, "register", "--osf", "q7m2k"], capture_output=True, text=True).returncode == 0
    p = _run(root, "--include-test", "all-snap")
    dst = os.path.join(root, "paper", "evidence", "all-snap")
    try:
        assert p.returncode == 0, p.stderr
        assert "20261101-m-toy-test-C0" in os.listdir(os.path.join(dst, "runs"))
        rec = json.loads(open(os.path.join(dst, "freeze_gate.jsonl")).read().splitlines()[-1])
        assert rec["stage"] == "snapshot" and rec["osf_registration_id"] == "q7m2k"
    finally:
        _unlock(dst)

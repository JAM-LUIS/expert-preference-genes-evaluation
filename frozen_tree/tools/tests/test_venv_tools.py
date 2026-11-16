"""The analysis and tokenizer environment record (configs/venv_tools.json, configs/venv_tools.freeze.txt) and its check
tools/venv_tools_check.py. Self-made files only; the real environment is checked only where it exists (it is
git-ignored, so an anonymous clone skips that test)."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

import pytest

from conftest import ROOT, write

from orgene import paths as PA  # noqa: E402

_spec = importlib.util.spec_from_file_location("venv_tools_check", os.path.join(ROOT, "tools", "venv_tools_check.py"))
VT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VT)

RECORD = os.path.join(ROOT, "configs", "venv_tools.json")
FREEZE = os.path.join(ROOT, "configs", "venv_tools.freeze.txt")
VENV_PY = os.path.join(ROOT, ".venv-tools", "bin", "python")


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def test_record_and_freeze_file_agree():
    rec = json.load(open(RECORD, encoding="utf-8"))
    text = open(FREEZE, encoding="utf-8").read()
    assert rec["schema"] == VT.RECORD_SCHEMA and rec["freeze_file"] == "configs/venv_tools.freeze.txt"
    assert rec["freeze_sha256"] == _sha(text.encode("utf-8"))
    pins, problems = VT.parse_freeze(text)
    assert problems == [] and len(pins) == rec["n_packages"]
    for req in rec["requested"]:
        assert VT.norm(req) in pins, req
    assert pins["tiktoken"] == rec["tiktoken"]["version"]
    # neutral writing: no absolute or local path in the freeze file or the record's paths
    assert not PA.find_absolute_paths(text) and "file:" not in text and " @ " not in text
    for name, e in rec["tiktoken"]["encodings"].items():
        assert e["file"].startswith(rec["tiktoken"]["cache_dir"] + "/") and not os.path.isabs(e["file"]), name
        assert e["sha256"] == e["tiktoken_expected_sha256"] and len(e["sha256"]) == 64, name
        # the cache file name is tiktoken's key for the URL
        assert os.path.basename(e["file"]) == hashlib.sha1(e["url"].encode()).hexdigest(), name
    assert set(rec["tiktoken"]["encodings"]) == {"cl100k_base", "o200k_base"}


@pytest.mark.parametrize("line", ["numpy>=2.0", "pkg @ file:///tmp/pkg", "-e git+https://example.org/x.git#egg=x",
                                  "scipy", "pandas==3.0.6 ; python_version>'3'"])
def test_freeze_parser_rejects_unpinned_or_local_lines(line):
    pins, problems = VT.parse_freeze("numpy==2.5.3\n" + line + "\n")
    assert len(problems) == 1


def test_package_comparison_names_every_difference():
    pins, _ = VT.parse_freeze("numpy==2.5.3\ntyping_extensions==4.16.0\nPygments==2.21.0\ntiktoken==0.14.0\n")
    same = {"numpy": "2.5.3", "typing-extensions": "4.16.0", "pygments": "2.21.0", "tiktoken": "0.14.0", "pip": "26.2.1"}
    assert VT.compare_packages(pins, same) == []  # names normalised; pip is not listed by the freeze
    changed = dict(same, numpy="2.5.4", requests="2.34.2")
    del changed["tiktoken"]
    probs = VT.compare_packages(pins, changed)
    assert len(probs) == 3
    assert any("missing package tiktoken" in p for p in probs)
    assert any("requests 2.34.2 is installed but not in the freeze file" in p for p in probs)
    assert any("numpy: installed 2.5.4, freeze 2.5.3" in p for p in probs)


def test_encoding_files_are_checked_by_hash_and_size(tmp_path):
    data = b"aGVsbG8= 0\nd29ybGQ= 1\n"
    write(tmp_path, ".cache/tiktoken/abc", data.decode())
    rec = {"tiktoken": {"encodings": {"toy_base": {"file": ".cache/tiktoken/abc", "bytes": len(data), "sha256": _sha(data),
                                                    "tiktoken_expected_sha256": _sha(data)}}}}
    assert VT.check_encodings(str(tmp_path), rec) == []
    write(tmp_path, ".cache/tiktoken/abc", data.decode() + "Zm9v 2\n")
    assert [p for p in VT.check_encodings(str(tmp_path), rec) if "sha256" in p or "bytes" in p]
    os.remove(tmp_path / ".cache" / "tiktoken" / "abc")
    assert VT.check_encodings(str(tmp_path), rec) == ["encoding toy_base: file .cache/tiktoken/abc missing"]


@pytest.mark.skipif(not os.path.isfile(VENV_PY), reason=".venv-tools not present (git-ignored)")
def test_the_real_environment_matches_its_record(tmp_path):
    cli = os.path.join(ROOT, "tools", "venv_tools_check.py")
    p = subprocess.run([sys.executable, cli], capture_output=True, text=True, timeout=600)
    assert p.returncode == 0 and "[venv-tools] OK" in p.stdout, p.stdout + p.stderr
    assert "offline tiktoken load" in p.stdout
    # a record that differs from the environment fails: another Python version, another tiktoken n_vocab
    rec = json.load(open(RECORD, encoding="utf-8"))
    rec["python_version"] = "3.99.0"
    rec["tiktoken"]["encodings"]["o200k_base"]["n_vocab"] = 1
    bad = tmp_path / "venv_tools.json"
    bad.write_text(json.dumps(rec), encoding="utf-8")
    p = subprocess.run([sys.executable, cli, "--record", str(bad)], capture_output=True, text=True, timeout=600)
    assert p.returncode == 1 and "Python 3.14" in p.stdout and "n_vocab 200019, recorded 1" in p.stdout, p.stdout
    assert ROOT not in p.stdout + p.stderr

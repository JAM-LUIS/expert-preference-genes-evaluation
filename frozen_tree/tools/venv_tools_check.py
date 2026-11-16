#!/usr/bin/env python3
"""Check R1's analysis and tokenizer environment (.venv-tools) against its record (DECISIONS R1-D5, default 14).

  $PY tools/venv_tools_check.py [--record configs/venv_tools.json] [--venv .venv-tools] [--no-tiktoken-probe] [--json]

Nothing is downloaded or installed. Checks:
  1. the freeze file (configs/venv_tools.freeze.txt, pip freeze of the venv) has the sha256 in the record, pins every
     package with == and carries no local or absolute path;
  2. the venv's interpreter has the recorded Python version, and its installed distributions equal the freeze file:
     same names, same versions, nothing missing, nothing extra (pip itself is not listed);
  3. every registered tiktoken encoding file is in the cache directory with its registered sha256 and size;
  4. unless --no-tiktoken-probe: each encoding loads offline through runtime/orgene/tokcount.TiktokenCounter (its helper
     blocks every download) and reports the recorded tiktoken version and n_vocab.
Exit 0 and "[venv-tools] OK" when everything holds, 1 otherwise; problems name the item, never file contents.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DEFAULT_RECORD = os.path.join("configs", "venv_tools.json")
RECORD_SCHEMA = "orgene.r1.venv_tools.v1"
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.+!_-]*)$")
_NOT_LISTED = {"pip"}  # pip freeze --exclude pip

# run inside the venv's interpreter: its Python version and installed distributions
_LIST_DISTS = r'''
import json, platform
from importlib import metadata
d = {}
for dist in metadata.distributions():
    name = dist.metadata["Name"]
    if name:
        d[name] = dist.version
print(json.dumps({"python_version": platform.python_version(), "dists": d}))
'''


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(name):
    """PEP 503 project name normalisation."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_freeze(text):
    """({normalised name: version}, [problems]) from pip freeze text. Every line must be `name==version`."""
    pins, problems = {}, []
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = _PIN.match(s)
        if not m:
            problems.append(f"freeze line {i} is not a pinned name==version (local, editable or unpinned install)")
            continue
        n = norm(m.group(1))
        if n in pins:
            problems.append(f"freeze line {i}: {m.group(1)} listed twice")
        pins[n] = m.group(2)
    return pins, problems


def compare_packages(pins, installed):
    """Problems where the installed distributions ({name: version}) differ from the freeze pins."""
    have = {norm(k): v for k, v in installed.items() if norm(k) not in _NOT_LISTED}
    problems = []
    for n in sorted(set(pins) - set(have)):
        problems.append(f"missing package {n} (freeze {pins[n]})")
    for n in sorted(set(have) - set(pins)):
        problems.append(f"package {n} {have[n]} is installed but not in the freeze file")
    for n in sorted(set(pins) & set(have)):
        if pins[n] != have[n]:
            problems.append(f"package {n}: installed {have[n]}, freeze {pins[n]}")
    return problems


def check_encodings(root, record):
    """Problems with the registered tiktoken encoding files (existence, size, sha256)."""
    problems = []
    for name, e in sorted(((record.get("tiktoken") or {}).get("encodings") or {}).items()):
        path = os.path.join(root, e["file"])
        if not os.path.isfile(path):
            problems.append(f"encoding {name}: file {e['file']} missing")
            continue
        if e.get("bytes") is not None and os.path.getsize(path) != e["bytes"]:
            problems.append(f"encoding {name}: {os.path.getsize(path)} bytes, registered {e['bytes']}")
        got = sha256_file(path)
        if got != e["sha256"]:
            problems.append(f"encoding {name}: sha256 {got[:12]}, registered {e['sha256'][:12]}")
        if e.get("tiktoken_expected_sha256") not in (None, e["sha256"]):
            problems.append(f"encoding {name}: registered sha256 is not the one tiktoken expects")
    return problems


def venv_state(python):
    p = subprocess.run([python, "-I", "-c", _LIST_DISTS], capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"the venv interpreter failed (rc={p.returncode})")
    return json.loads(p.stdout.strip().splitlines()[-1])


def probe_tiktoken(root, record, python):
    """Problems when an encoding does not load offline with the recorded version and n_vocab."""
    sys.path.insert(0, os.path.join(root, "runtime"))
    from orgene.tokcount import TiktokenCounter, TokenizerError
    problems = []
    tk = record.get("tiktoken") or {}
    for name, e in sorted((tk.get("encodings") or {}).items()):
        try:
            ident = TiktokenCounter("venv-check", name, os.path.join(root, e["file"]), e["sha256"], python=python).identity()
        except TokenizerError as err:
            problems.append(f"encoding {name}: does not load offline ({err})")
            continue
        tok = ident["tokenizer"]
        if tok.get("version") != tk.get("version"):
            problems.append(f"encoding {name}: tiktoken {tok.get('version')}, recorded {tk.get('version')}")
        if e.get("n_vocab") is not None and tok.get("n_vocab") != e["n_vocab"]:
            problems.append(f"encoding {name}: n_vocab {tok.get('n_vocab')}, recorded {e['n_vocab']}")
    return problems


def check(root=ROOT, record_path=None, venv=None, probe=True):
    """Report {ok, problems, checked}. `venv` overrides the record's venv directory."""
    root = os.path.abspath(root)
    rp = record_path or os.path.join(root, DEFAULT_RECORD)
    record = json.load(open(rp, encoding="utf-8"))
    problems, checked = [], []
    if record.get("schema") != RECORD_SCHEMA:
        problems.append(f"record schema must be {RECORD_SCHEMA}")
    fp = os.path.join(root, record["freeze_file"])
    pins = {}
    if not os.path.isfile(fp):
        problems.append(f"freeze file {record['freeze_file']} missing")
    else:
        if sha256_file(fp) != record.get("freeze_sha256"):
            problems.append("freeze file sha256 differs from the record")
        pins, bad = parse_freeze(open(fp, encoding="utf-8").read())
        problems += bad
        if record.get("n_packages") is not None and len(pins) != record["n_packages"]:
            problems.append(f"freeze file lists {len(pins)} packages, record {record['n_packages']}")
        for req in record.get("requested", []):
            if norm(req) not in pins:
                problems.append(f"requested package {req} is not in the freeze file")
        tv = (record.get("tiktoken") or {}).get("version")
        if tv and pins.get("tiktoken") != tv:
            problems.append(f"tiktoken {pins.get('tiktoken')} in the freeze file, {tv} in the record")
        checked.append("freeze file")
    venv_dir = venv or os.path.join(root, record["venv"])
    python = os.path.join(venv_dir, "bin", "python")
    if not os.path.isfile(python):
        problems.append(f"no interpreter in {record['venv']} (create the environment first)")
    else:
        try:
            st = venv_state(python)
        except (OSError, RuntimeError, ValueError, IndexError, subprocess.SubprocessError) as e:
            problems.append(f"cannot list the environment: {type(e).__name__}")
            st = None
        if st is not None:
            if st["python_version"] != record.get("python_version"):
                problems.append(f"Python {st['python_version']} in the environment, {record.get('python_version')} recorded")
            problems += compare_packages(pins, st["dists"])
            checked.append("installed packages")
    enc_problems = check_encodings(root, record)
    problems += enc_problems
    checked.append("encoding files")
    if probe and os.path.isfile(python) and not enc_problems:
        problems += probe_tiktoken(root, record, python)
        checked.append("offline tiktoken load")
    return {"ok": not problems, "problems": problems, "checked": checked}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="venv_tools_check", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    ap.add_argument("--record", default=None, help="default configs/venv_tools.json")
    ap.add_argument("--venv", default=None, help="environment directory (default: the record's)")
    ap.add_argument("--no-tiktoken-probe", action="store_true", help="skip loading the encodings through tiktoken")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = check(a.root, a.record, a.venv, probe=not a.no_tiktoken_probe)
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        for p in rep["problems"]:
            print(f"[venv-tools] PROBLEM: {p}")
        print(f"[venv-tools] {'OK' if rep['ok'] else 'FAIL'} (checked: {', '.join(rep['checked']) or 'nothing'})")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

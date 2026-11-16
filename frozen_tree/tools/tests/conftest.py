"""Fixtures for the E21 tests: throw-away git repositories in tmp_path, self-made files only.

No benchmark case is read by these fixtures. Identity terms used here are invented ("Alice Example", "ACME Labs").
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RUNTIME = os.path.join(ROOT, "runtime")
if RUNTIME not in sys.path:
    sys.path.insert(0, RUNTIME)

IDENTITY = ("orgene-r1", "orgene-r1@example.invalid")
FAKE_TERMS = "# invented identity terms for the tests\nAlice Example\nACME Labs\nre:\\bacme\\.\n"
MINI_SPEC = {
    "schema": "orgene.freeze_spec.v1",
    "items": [
        {"id": "code", "category": "code", "glob": "code/*.py"},
        {"id": "template", "category": "prompts", "path": "conditions/t.md"},
        {"id": "splits", "category": "data", "glob": "data/splits/**/*.json"},
    ],
    "computed": [
        {"id": "git_trees", "kind": "git_trees", "dirs": ["code", "conditions", "tools", "configs"]},
        {"id": "prov", "kind": "call", "call": "tools/prov.py:compute", "path_args": ["conditions/t.md"]},
    ],
}
PROVIDER = '''import hashlib


def compute(path):
    return {"template_sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(), "salt": 1}
'''


def git(root, *args, check=True):
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1")
    p = subprocess.run(["git", "-C", str(root), "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"] + list(args),
                       capture_output=True, text=True, env=env, timeout=60)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {p.stderr[-400:]}")
    return p.stdout


def init_repo(root, name=IDENTITY[0], email=IDENTITY[1]):
    git(root, "init", "-q")
    git(root, "config", "user.name", name)
    git(root, "config", "user.email", email)


def commit_all(root, msg="commit"):
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", msg)


def write(root, rel, text):
    p = os.path.join(str(root), rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


@pytest.fixture
def terms_file(tmp_path):
    p = tmp_path / "terms.txt"
    p.write_text(FAKE_TERMS, encoding="utf-8")
    return str(p)


@pytest.fixture
def mini_repo(tmp_path):
    """A committed repository with a small freeze spec: code/, conditions/, data/splits/toy/, tools/prov.py."""
    root = tmp_path / "repo"
    root.mkdir()
    write(root, ".gitignore", "experiments/\nPROVENANCE/\n__pycache__/\n")
    write(root, "configs/freeze_spec.json", json.dumps(MINI_SPEC, indent=2))
    write(root, "code/a.py", "x = 1\n")
    write(root, "code/b.py", "y = 2\n")
    write(root, "conditions/t.md", "Solve the problem.\n")
    write(root, "tools/prov.py", PROVIDER)
    write(root, "data/splits/toy/dev_ids.json", json.dumps(["toy-0001"]))
    write(root, "data/splits/toy/test_ids.json", json.dumps(["toy-0002", "toy-0003"]))
    write(root, "notes.md", "working notes, not frozen\n")
    init_repo(root)
    commit_all(root, "initial")
    return str(root)


def copy_runtime_repo(dst):
    """A copy of the real runtime with the smoke case only, for CLI tests of the gate (no benchmark case copied)."""
    dst = str(dst)
    for d in ("runtime/orgene",):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(dst, d), ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(os.path.join(ROOT, "runtime", "orgene_cli.py"), os.path.join(dst, "runtime", "orgene_cli.py"))
    shutil.copytree(os.path.join(ROOT, "conditions"), os.path.join(dst, "conditions"), ignore=shutil.ignore_patterns("variants", "ora"))
    shutil.copytree(os.path.join(ROOT, "schema"), os.path.join(dst, "schema"))
    # the whole gene directory (library, activation lexicon when present) and the configuration registries, so the
    # copy runs whatever the runtime of this branch needs; the freeze spec is replaced below
    shutil.copytree(os.path.join(ROOT, "genes"), os.path.join(dst, "genes"), ignore=shutil.ignore_patterns("__pycache__"))
    if os.path.isdir(os.path.join(ROOT, "configs")):
        shutil.copytree(os.path.join(ROOT, "configs"), os.path.join(dst, "configs"))
    os.makedirs(os.path.join(dst, "data", "cases"))
    shutil.copy(os.path.join(ROOT, "data", "cases", "smoke.jsonl"), os.path.join(dst, "data", "cases", "smoke.jsonl"))
    for d in ("tools",):
        os.makedirs(os.path.join(dst, d), exist_ok=True)
    for f in ("freeze.py", "anon_scan.py"):
        shutil.copy(os.path.join(ROOT, "tools", f), os.path.join(dst, "tools", f))
    write(dst, "data/splits/smoke/dev_ids.json", json.dumps(["smoke-0001"]))
    write(dst, "data/splits/smoke/test_ids.json", json.dumps(["smoke-0002", "smoke-0003"]))
    write(dst, ".gitignore", "experiments/\nPROVENANCE/\n__pycache__/\n.pytest_cache/\npaper/\n")
    spec = {"schema": "orgene.freeze_spec.v1",
            "items": [{"id": "runtime_code", "category": "code", "glob": ["runtime/**/*.py"]},
                      {"id": "genes", "category": "gene", "path": "genes/genes.r1.jsonl"},
                      {"id": "templates", "category": "prompts", "glob": "conditions/*.md"},
                      {"id": "cases", "category": "data", "glob": "data/cases/*.jsonl"},
                      {"id": "splits", "category": "data", "glob": "data/splits/**/*.json"}],
            "computed": [{"id": "git_trees", "kind": "git_trees", "dirs": ["runtime", "conditions", "genes", "configs", "tools"]}]}
    write(dst, "configs/freeze_spec.json", json.dumps(spec, indent=2))
    init_repo(dst)
    commit_all(dst, "copy")
    return dst

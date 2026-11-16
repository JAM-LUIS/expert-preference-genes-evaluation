"""E21 neutral-writing scan: every planted marker kind is caught; reports never echo the matched text.

All markers are invented and assembled at run time, so this file itself stays clean for the repository self-check.
"""
import json
import os
import subprocess
import sys

import pytest

from conftest import ROOT, commit_all, git, init_repo, write

from orgene import anon as A  # noqa: E402

HOME_POSIX = "/" + "Us" + "ers" + "/alice/project/run_config.json"
HOME_LINUX = "/" + "ho" + "me" + "/alice/data/x.jsonl"
TMP_MAC = "/" + "private/var/" + "folders" + "/zz/abc123/T/x"
HOME_WIN = "C:" + "\\" + "Us" + "ers" + "\\" + "alice" + "\\" + "proj"
EMAIL = "alice.example" + "@" + "acme-mail.com"
TERM = "Alice" + " Example"
ORG = "ACME" + " Labs"
PREFIX = "acme" + ".gene.x"
FILE_URL = "pkg @ file://" + HOME_POSIX  # pip freeze form of a local install: three slashes before the home path
FILE_URL_HOST = "file://localhost" + HOME_POSIX
JSON_ESCAPED = HOME_POSIX.replace("/", "\\/")


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv(A.TERMS_ENV, raising=False)
    monkeypatch.setattr(A.getpass, "getuser", lambda: "runner")
    monkeypatch.setattr(A.socket, "gethostname", lambda: "localhost")


@pytest.fixture
def repo(tmp_path, clean_env):
    root = tmp_path / "repo"
    root.mkdir()
    write(root, ".gitignore", "experiments/\nPROVENANCE/\nreleases/v1.0/\ndata/raw/\n.venv-tools/\n")
    write(root, "README.md", "neutral text\n")
    init_repo(root)
    commit_all(root, "initial")
    return str(root)


def _scan(root, terms_file=None, **kw):
    return A.scan(root, terms_file=terms_file, **kw)


def _dets(rep):
    return sorted({h["detector"] for h in rep["hits"]})


def test_clean_repository_has_no_hits(repo, terms_file):
    rep = _scan(repo, terms_file)
    assert rep["hits"] == [], A.format_hits(rep)
    assert rep["identity_terms"] == 3 and rep["git"]["commits"] == 1


@pytest.mark.parametrize("marker,detector", [
    (HOME_POSIX, "home_path"), (HOME_LINUX, "home_path"), (TMP_MAC, "home_path"), (HOME_WIN, "home_path"),
    (FILE_URL, "home_path"), (FILE_URL_HOST, "home_path"), (JSON_ESCAPED, "home_path"),
    (EMAIL, "email"), (TERM, "term"), (ORG.lower(), "term"), (PREFIX, "term")])
def test_planted_marker_is_caught(repo, terms_file, marker, detector):
    write(repo, "runtime/x.py", f"# header\nvalue = '{marker}'\n")
    rep = _scan(repo, terms_file)
    hits = [h for h in rep["hits"] if h["path"] == "runtime/x.py"]
    assert hits and hits[0]["detector"] == detector and hits[0]["line"] == 2


def test_markers_in_untracked_files_and_artifacts_are_caught(repo, terms_file):
    write(repo, "notes/untracked.md", TERM + "\n")
    write(repo, "experiments/20261101-m-toy-dev-C0/run_config.json", json.dumps({"cases_path": HOME_POSIX}))
    rep = _scan(repo, terms_file)
    paths = {h["path"] for h in rep["hits"]}
    assert "notes/untracked.md" in paths
    assert "experiments/20261101-m-toy-dev-C0/run_config.json" in paths
    rep = _scan(repo, terms_file, artifacts=False)
    assert "experiments/20261101-m-toy-dev-C0/run_config.json" not in {h["path"] for h in rep["hits"]}


def test_provenance_raw_data_and_environments_are_not_scanned(repo, terms_file):
    for rel in ("PROVENANCE/v5_pristine/x.md", "releases/v1.0/genes.jsonl", "data/raw/src/y.json", ".venv-tools/lib/z.py",
                ".cache/tiktoken/9b5ad71b"):
        write(repo, rel, TERM + " " + HOME_POSIX + "\n")
    assert _scan(repo, terms_file)["hits"] == []


def test_ignored_evidence_snapshots_are_still_scanned(repo, terms_file):
    # paper/evidence/ is git-ignored (snapshots are not committed) but its files are hashed and shared: an artifact
    # directory, scanned like experiments/
    with open(os.path.join(repo, ".gitignore"), "a", encoding="utf-8") as f:
        f.write("paper/evidence/\n")
    commit_all(repo, "ignore snapshots")
    write(repo, "paper/evidence/dev-snapshot-x/runs/r1/run_config.json", json.dumps({"cases_path": HOME_POSIX}))
    rep = _scan(repo, terms_file)
    assert [h["path"] for h in rep["hits"]] == ["paper/evidence/dev-snapshot-x/runs/r1/run_config.json"]
    assert _scan(repo, terms_file, artifacts=False)["hits"] == []


def test_gitignore_and_scan_scope_are_compared(repo):
    # the fixture ignores the provenance, raw-data and environment paths and experiments/, not .cache/ or paper/evidence/
    assert A.gitignore_mismatches(repo) == ([], [".cache/", "paper/evidence/"])
    with open(os.path.join(repo, ".gitignore"), "a", encoding="utf-8") as f:
        f.write("# comment\n/paper/evidence/\n.cache/\nnotes/\n*.log\n__pycache__/\n.venv-other/\n")
    unaccounted, not_ignored = A.gitignore_mismatches(repo)
    assert unaccounted == ["notes/", "*.log"] and not_ignored == []
    write(repo, ".gitignore", "experiments/\npaper/evidence/\nPROVENANCE/\n.cache/\n")
    assert A.gitignore_mismatches(repo) == ([], ["releases/v1.0/", "data/raw/"])


def test_identity_in_a_file_name_is_caught(repo, terms_file):
    write(repo, "docs/alice example notes.md", "neutral\n")
    rep = _scan(repo, terms_file)
    assert _dets(rep) == ["term_in_path"]


@pytest.mark.parametrize("ok", ["orgene-r1" + "@" + "example.invalid", "noreply" + "@" + "vendor.com",
                                "user" + "@" + "example.org", "https://example.org/" + "ho" + "me" + "/page",
                                "git" + "@" + "codehost.org:org/repo.git", "@pytest.mark.parametrize", "a @ b"])
def test_allowed_or_non_matching_text_is_not_reported(repo, terms_file, ok):
    write(repo, "runtime/x.py", ok + "\n")
    assert _scan(repo, terms_file)["hits"] == []


def test_local_login_and_host_names_are_caught(repo, monkeypatch):
    monkeypatch.setattr(A.getpass, "getuser", lambda: "qzuser42")
    monkeypatch.setattr(A.socket, "gethostname", lambda: "qz-workstation.local")
    write(repo, "a.txt", "built by qzuser42\n")
    write(repo, "b.txt", "on QZ-Workstation\n")
    rep = _scan(repo)
    assert sorted((h["path"], h["detail"]) for h in rep["hits"]) == [("a.txt", "login"), ("b.txt", "host")]


def test_generic_local_names_are_ignored(repo, monkeypatch):
    monkeypatch.setattr(A.getpass, "getuser", lambda: "runner")
    monkeypatch.setattr(A.socket, "gethostname", lambda: "localhost")
    assert A.local_identity_terms() == []


def test_git_identity_and_messages_are_checked(repo, terms_file):
    write(repo, "c.txt", "neutral\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=" + TERM, "-c", "user.email=" + EMAIL, "commit", "-q", "-m", "fix")
    write(repo, "d.txt", "neutral\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "update\n\nreviewed with " + ORG)
    rep = _scan(repo, terms_file)
    dets = _dets(rep)
    assert "git_author" in dets and "git_committer" in dets  # -c user.* sets both
    assert "git_message:term" in dets
    git(repo, "config", "user.email", EMAIL)
    rep = _scan(repo, terms_file)
    assert "git_config" in _dets(rep)
    rep = _scan(repo, terms_file, git_meta=False)
    assert not [d for d in _dets(rep) if d.startswith("git")]


def test_committer_other_than_author_is_caught(repo, terms_file):
    write(repo, "e.txt", "neutral\n")
    git(repo, "add", "-A")
    env_commit = subprocess.run(["git", "-C", repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "x"],
                                capture_output=True, text=True,
                                env=dict(os.environ, GIT_COMMITTER_NAME="Someone", GIT_COMMITTER_EMAIL="s" + "@" + "corp.com"))
    assert env_commit.returncode == 0, env_commit.stderr
    assert "git_committer" in _dets(_scan(repo, terms_file))


def test_reports_never_echo_the_matched_text(repo, terms_file):
    secret_line = f"Contact {TERM} at {EMAIL}, files in {HOME_POSIX}"
    write(repo, "data/cases/toy.jsonl", json.dumps({"case_id": "toy-1", "text": secret_line}) + "\n")
    rep = _scan(repo, terms_file)
    assert len(rep["hits"]) == 3
    blob = json.dumps(rep) + A.format_hits(rep)
    for s in (TERM, EMAIL, HOME_POSIX, "alice", "Contact"):
        assert s not in blob


def test_binary_files_are_skipped(repo, terms_file):
    with open(os.path.join(repo, "blob.bin"), "wb") as f:
        f.write(b"\0\1\2" + TERM.encode())
    rep = _scan(repo, terms_file)
    assert rep["hits"] == [] and rep["binary_skipped"] == 1


# ------------------------------------------------------------------ terms file


def test_terms_lookup_order(repo, terms_file, tmp_path, monkeypatch):
    assert A.find_terms_file(repo) is None
    write(repo, "PROVENANCE/anon_terms.txt", "Somebody Else\n")
    assert A.find_terms_file(repo) == os.path.join(repo, "PROVENANCE", "anon_terms.txt")
    monkeypatch.setenv(A.TERMS_ENV, terms_file)
    assert A.find_terms_file(repo) == terms_file
    assert A.find_terms_file(repo, explicit=terms_file) == terms_file
    monkeypatch.setenv(A.TERMS_ENV, str(tmp_path / "missing.txt"))
    with pytest.raises(A.TermsError):
        A.find_terms_file(repo)


def test_worktree_finds_the_main_checkout_terms_file(repo, tmp_path):
    write(repo, "PROVENANCE/anon_terms.txt", TERM + "\n")
    wt = str(tmp_path / "wt")
    git(repo, "worktree", "add", "-q", wt, "-b", "side")
    assert A.main_checkout_root(wt) == os.path.realpath(repo)
    assert A.find_terms_file(wt) == os.path.join(os.path.realpath(repo), "PROVENANCE", "anon_terms.txt")
    write(wt, "x.md", TERM + "\n")
    assert _dets(_scan(wt)) == ["term"]


def test_bad_terms_are_rejected(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("re:(unclosed\n")
    with pytest.raises(A.TermsError):
        A.load_terms(str(p))
    p.write_text("re:x*\n")
    with pytest.raises(A.TermsError):
        A.load_terms(str(p))
    p.write_text("# only comments\n\n")
    assert A.load_terms(str(p)) == []


def test_require_terms(repo):
    with pytest.raises(A.TermsError):
        _scan(repo, require_terms=True)


# ------------------------------------------------------------------ CLI


def test_cli_exit_codes_and_masking(repo, terms_file):
    cli = os.path.join(ROOT, "tools", "anon_scan.py")
    run = lambda *a: subprocess.run([sys.executable, cli, "--root", repo, "--no-local"] + list(a),  # noqa: E731
                                    capture_output=True, text=True, timeout=120, env=dict(os.environ, **{A.TERMS_ENV: ""}))
    p = run("--terms", terms_file)
    assert p.returncode == 0, p.stdout + p.stderr
    write(repo, "runtime/y.py", "who = '" + TERM + "'\n")
    p = run("--terms", terms_file)
    assert p.returncode == 1 and "runtime/y.py:1:" in p.stdout and TERM not in p.stdout + p.stderr
    p = run("--require-terms")
    assert p.returncode == 2
    p = run("--terms", terms_file, "--json")
    assert json.loads(p.stdout)["hits"][0]["detector"] == "term"

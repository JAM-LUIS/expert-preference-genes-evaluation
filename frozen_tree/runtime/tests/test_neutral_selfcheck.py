"""E21 self-check, run with every commit: the working tree, the artifacts and the git metadata carry no identity trace.

This keeps "the hashes taken at the freeze stay valid at submission" true (DECISIONS R1-D2). Identity terms are read
from a terms file outside git (runtime/orgene/anon.py); without it only the generic detectors and this machine's login
and host names run. Failures are reported as path:line:col and detector, never with the matched text.
"""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import anon as A  # noqa: E402


def _git_ok():
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "--verify", "-q", "HEAD"], capture_output=True,
                              timeout=30).returncode == 0
    except OSError:
        return False


def test_repository_is_neutral():
    rep = A.scan(ROOT)
    note = "" if rep["terms_file_found"] else " (identity terms file not found: generic detectors only)"
    assert rep["hits"] == [], f"{len(rep['hits'])} identity trace(s){note}:\n" + A.format_hits(rep)


@pytest.mark.skipif(not _git_ok(), reason="not a git checkout")
def test_ignored_provenance_is_not_tracked():
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "--", "PROVENANCE", "releases/v1.0", "data/raw"],
                         capture_output=True, text=True, timeout=30).stdout
    assert out.strip() == ""


def test_gitignore_matches_the_scan_scope():
    # every ignored path is either scanned as an artifact directory or deliberately excluded, and every exclusion is
    # ignored by git (otherwise it could be committed without ever being scanned)
    unaccounted, not_ignored = A.gitignore_mismatches(ROOT)
    assert unaccounted == [], f".gitignore entries the neutral-writing scan does not account for: {unaccounted}"
    assert not_ignored == [], f"scan exclusions or artifact directories missing from .gitignore: {not_ignored}"


@pytest.mark.skipif(not _git_ok(), reason="not a git checkout")
def test_nothing_git_tracks_or_would_add_escapes_the_scan():
    # The scan also skips directory names anywhere in a path (.venv*, __pycache__, node_modules, ...), and .gitignore
    # covers some spellings only (.venv-*/): a file there that git tracks, or would add with `git add -A`, would be
    # committed without ever being scanned.
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True, timeout=60).stdout
    escaped = [f for f in out.split("\0") if f and A._excluded(f)]
    assert escaped == [], f"files git tracks or would add that the neutral-writing scan skips: {escaped[:20]}"


@pytest.mark.skipif(not _git_ok(), reason="not a git checkout")
def test_terms_file_if_present_is_outside_git():
    tf = A.find_terms_file(ROOT)
    if tf is None:
        pytest.skip("no identity terms file on this host")
    p = subprocess.run(["git", "-C", ROOT, "ls-files", "--error-unmatch", "--", tf], capture_output=True, timeout=30)
    assert p.returncode != 0

#!/usr/bin/env python3
"""Neutral-writing self-check (E21). Library and detector list: runtime/orgene/anon.py.

  /opt/homebrew/bin/python3 tools/anon_scan.py [paths ...] [--terms FILE] [--require-terms] [--no-artifacts]
                                               [--no-git] [--no-local] [--json]

Without paths: the git working tree (tracked and untracked, not ignored) plus the git-ignored artifact directories
experiments/ and paper/evidence/; PROVENANCE/, releases/v1.0/, data/raw/, environments and caches are never scanned
by default (runtime/orgene/anon.py; runtime/tests/test_neutral_selfcheck.py keeps this equal to .gitignore). Exit 0 when clean, 1 when anything is found, 2 when the
terms file is required but missing or malformed. Reports give path:line:col, the detector and a masked match; the
matched line is never printed.
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene import anon as A  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="anon_scan", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="files or directories relative to the repository root")
    ap.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    ap.add_argument("--terms", default=None, help=f"identity terms file (default ${A.TERMS_ENV}, then PROVENANCE/anon_terms.txt)")
    ap.add_argument("--require-terms", action="store_true", help="fail when no identity terms file is found")
    ap.add_argument("--no-artifacts", action="store_true", help="skip the artifact directories (experiments/, paper/evidence/)")
    ap.add_argument("--no-git", action="store_true", help="skip commit identities and messages")
    ap.add_argument("--no-local", action="store_true", help="skip this machine's login and host name")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        rep = A.scan(a.root, paths=a.paths or None, terms_file=a.terms, require_terms=a.require_terms,
                     artifacts=not a.no_artifacts, git_meta=not a.no_git, local=not a.no_local)
    except A.TermsError as e:
        print(f"[anon_scan] {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(rep, indent=2, sort_keys=True))
    else:
        if rep["hits"]:
            print(A.format_hits(rep))
        note = "" if rep["terms_file_found"] else " (no identity terms file: generic detectors only)"
        print(f"[anon_scan] {rep['files_scanned']} files ({rep['selection']}), {rep['binary_skipped']} binary skipped, "
              f"{rep['git'].get('commits', 0)} commits; identity terms {rep['identity_terms']}, "
              f"local names {rep['local_identity_terms']}{note}; hits {len(rep['hits'])}", file=sys.stderr)
    return 1 if rep["hits"] else 0


if __name__ == "__main__":
    sys.exit(main())

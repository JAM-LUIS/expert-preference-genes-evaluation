#!/usr/bin/env python3
"""Check the gene library version rule against the previous release (E04).

  /opt/homebrew/bin/python3 tools/check_gene_versions.py [--prev releases/v1.0/genes.v3.jsonl] [--new genes/genes.r1.jsonl]

Prints JSON (paths relative to the repository root) and exits 1 when a gene changed without a version bump, was
removed, was bumped without a change, or carries a malformed version. Rules: runtime/orgene/versioning.py.
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene import genes as G  # noqa: E402
from orgene.paths import rel, resolve  # noqa: E402
from orgene.versioning import compare_stores  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prev", default="releases/v1.0/genes.v3.jsonl")
    ap.add_argument("--new", default="genes/genes.r1.jsonl")
    a = ap.parse_args(argv)
    prev, new = resolve(a.prev), resolve(a.new)
    if not os.path.exists(prev):
        print(json.dumps({"ok": None, "skipped": f"previous release {rel(prev)} not present"}))
        return 0
    res = compare_stores(G.load_store(prev), G.load_store(new))
    print(json.dumps(dict({"prev": rel(prev), "new": rel(new)}, **res), indent=2, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

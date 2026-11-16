#!/usr/bin/env python3
"""Derive data/splits_r1/<set>/ for every id set of data/analysis_sets/analysis_sets.v2.json (E14).

  /opt/homebrew/bin/python3 tools/derive_splits_r1.py [--check] [--force]

Each id set is placed on the frozen v5 split of its benchmark (data/splits/<benchmark>/, read only):
dev = frozen dev ∩ set, test = frozen test ∩ set; a case listed on the other side, or outside the frozen split,
stops the run. The counts and the dev/test id hashes recorded in the id-set file must be reproduced.
Writes SPLIT_LOCK.json (kind "subset", parent lock hash, id-set file hash), dev_ids.json, test_ids.json and
removed_ids.json per set. --check derives into a temporary directory and compares byte for byte with the
committed files instead of writing. Prints counts and hash prefixes only.
"""
import argparse
import os
import shutil
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene import analysis_sets as A  # noqa: E402
from orgene import split as S  # noqa: E402
from orgene.paths import rel, resolve  # noqa: E402

OUT_DIR = "data/splits_r1"
FILES = ("SPLIT_LOCK.json", "dev_ids.json", "test_ids.json", "removed_ids.json")


def derive_all(root, out_dir, id_sets_path=A.ID_SETS_PATH, force=False):
    doc = A.load_id_sets(id_sets_path, root)
    src_path = resolve(id_sets_path, root)
    src = {"path": rel(src_path, root), "sha256": A.sha256_path(src_path)}
    infos = {}
    for name, s in doc["sets"].items():
        expect = {"n_dev": s["n_dev"], "n_test": s["n_test"],
                  "dev_sha256": s["dev_ids_sha256"], "test_sha256": s["test_ids_sha256"]}
        infos[name] = S.derive_subset_lock(resolve(os.path.join(A.SPLITS_DIR, s["benchmark"]), root),
                                           {"dev": s["dev"], "test": s["test"]}, os.path.join(out_dir, name),
                                           name=name, source=dict(src, set=name), expect=expect, force=force,
                                           root=root)
    return infos


def check(root, out_dir, id_sets_path=A.ID_SETS_PATH):
    """Problems (empty = the committed subset locks are exactly what the id-set file derives)."""
    problems = []
    tmp = tempfile.mkdtemp(prefix="splits_r1_check_")
    try:
        infos = derive_all(root, tmp, id_sets_path)
        for name in infos:
            for fn in FILES:
                a, b = os.path.join(tmp, name, fn), os.path.join(out_dir, name, fn)
                if not os.path.exists(b) or open(a, "rb").read() != open(b, "rb").read():
                    problems.append(f"{rel(b, root)} differs from a fresh derivation")
            problems += S.verify_subset_lock(os.path.join(out_dir, name), root)
        extra = sorted(set(os.listdir(out_dir)) - set(infos) - {"README.md"}) if os.path.isdir(out_dir) else []
        problems += [f"{OUT_DIR}/{e} is not an id set of the id-set file" for e in extra]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return problems, infos


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite different content (only before any test run; record it)")
    a = ap.parse_args(argv)
    out_dir = resolve(OUT_DIR, a.root)
    if a.check:
        problems, infos = check(a.root, out_dir)
    else:
        problems, infos = [], derive_all(a.root, out_dir, force=a.force)
    for name, i in infos.items():
        print(f"{name:40s} dev {i['n_dev']:3d}  test {i['n_test']:3d}  removed {i['n_removed_dev']:3d}/{i['n_removed_test']:3d}  "
              f"dev {i['dev_sha256'][:12]}  test {i['test_sha256'][:12]}")
    for p in problems:
        print("BAD", p)
    print("RESULT:", "PASS" if not problems else "FAIL", "(check)" if a.check else f"(written to {OUT_DIR})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

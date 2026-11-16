#!/usr/bin/env python3
"""Draw the variance subset (test ids) and the determinism set (dev ids) by a recorded seed (todo 1D, E07/E20).

  /opt/homebrew/bin/python3 tools/draw_subsets_r1.py [--check]

Population: the main-analysis subset locks of data/splits_r1/ (MAMO cleaned subset and IndustryOR 2026 revision,
both *_excl0905). Only id files are read; no case record is opened.
  variance      100 test ids, for the temperature 0.7 x 3 repeats
  determinism    20 dev ids, for the reverse-order rerun and the 20-case end-to-end rehearsals
Stratified by benchmark: the sizes are proportional to the stratum sizes, rounded by largest remainder (ties go
to the stratum named first). Within a stratum the ids are ordered by sha256("<seed>|<subset>|<case_id>") and the
first n are taken. Writes data/subsets_r1/variance_determinism_ids.json with the seed, the rule, the hash of
each split lock read and the hash of each id list. --check draws again and compares byte for byte with the
committed file instead of writing. Prints counts and hash prefixes only.
"""
import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

SEED = 20261004
OUT = "data/subsets_r1/variance_determinism_ids.json"
STRATA = (("mamo_complex_lp", "data/splits_r1/mamo_main_clean111_excl0905"),
          ("industryor", "data/splits_r1/industryor_main_rev2026_100_excl0905"))
SUBSETS = (("variance", "test", 100), ("determinism", "dev", 20))
RULE = ("per benchmark: n proportional to the stratum size, largest remainder; within a stratum the first n ids "
        "in ascending order of sha256('<seed>|<subset>|<case_id>')")


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def ids_sha256(ids):
    return sha256_bytes("\n".join(ids).encode())


def allocate(sizes, n):
    """Largest-remainder allocation of n over strata of the given sizes (in order)."""
    total = sum(sizes)
    if not 0 < n <= total:
        raise ValueError(f"cannot draw {n} of {total}")
    quota = [n * s / total for s in sizes]
    alloc = [int(q) for q in quota]
    order = sorted(range(len(sizes)), key=lambda i: (-(quota[i] - alloc[i]), i))
    for i in order[:n - sum(alloc)]:
        alloc[i] += 1
    return alloc


def draw_ids(ids, n, seed, subset):
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate ids")
    ranked = sorted(ids, key=lambda c: hashlib.sha256(f"{seed}|{subset}|{c}".encode()).hexdigest())
    return sorted(ranked[:n])


def draw(root=ROOT, seed=SEED):
    doc = {"schema": "orgene-r1/seeded_subsets/v1", "seed": seed, "rule": RULE, "sources": [], "subsets": {}}
    pools = {}
    for bench, d in STRATA:
        lock = os.path.join(root, d, "SPLIT_LOCK.json")
        doc["sources"].append({"benchmark": bench, "split_dir": d,
                               "split_lock_sha256": sha256_bytes(open(lock, "rb").read())})
        for side in ("dev", "test"):
            pools[(bench, side)] = json.load(open(os.path.join(root, d, f"{side}_ids.json")))
    for name, side, n in SUBSETS:
        sizes = [len(pools[(b, side)]) for b, _ in STRATA]
        alloc = allocate(sizes, n)
        strata, all_ids = {}, []
        for (bench, _), k in zip(STRATA, alloc):
            ids = draw_ids(pools[(bench, side)], k, seed, name)
            strata[bench] = {"population": len(pools[(bench, side)]), "n": k, "ids": ids}
            all_ids += ids
        doc["subsets"][name] = {"split": side, "n": n, "ids_sha256": ids_sha256(all_ids), "strata": strata}
    return doc


def render(doc):
    return (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    body = render(draw())
    out = os.path.join(ROOT, OUT)
    if a.check:
        ok = os.path.exists(out) and open(out, "rb").read() == body
        print(f"RESULT: {'PASS' if ok else 'FAIL'} ({OUT} {'equals' if ok else 'differs from'} a fresh draw)")
        return 0 if ok else 1
    if os.path.exists(out) and open(out, "rb").read() != body:
        print(f"refused: {OUT} exists with different content", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(body)
    doc = json.loads(body)
    for name, s in doc["subsets"].items():
        parts = ", ".join(f"{b} {v['n']}/{v['population']}" for b, v in s["strata"].items())
        print(f"{name}: {s['n']} {s['split']} ids ({parts}), ids sha256 {s['ids_sha256'][:12]}")
    print(f"wrote {OUT} sha256 {sha256_bytes(body)[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

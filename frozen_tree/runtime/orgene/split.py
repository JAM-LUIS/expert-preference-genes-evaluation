"""Frozen dev/test split. Genes and prompts may only be tuned on dev; test is touched once per condition."""
import hashlib
import json
import os
import random

from .data import load_cases
from .paths import rel, resolve


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_split(cases_path, out_dir, n_dev, seed, force=False, numeric_only=True):
    lock = os.path.join(out_dir, "SPLIT_LOCK.json")
    if os.path.exists(lock) and not force:
        raise SystemExit(f"split already frozen at {lock}; use --force only before any test run has happened (and record it)")
    cases = load_cases(cases_path)
    if numeric_only:
        cases = [c for c in cases if c["reference"]["objective"] is not None or c["reference"]["status"]]
    ids = [c["case_id"] for c in cases]
    rng = random.Random(seed)
    rng.shuffle(ids)
    dev, test = sorted(ids[:n_dev]), sorted(ids[n_dev:])
    os.makedirs(out_dir, exist_ok=True)
    json.dump(dev, open(os.path.join(out_dir, "dev_ids.json"), "w"), indent=0)
    json.dump(test, open(os.path.join(out_dir, "test_ids.json"), "w"), indent=0)
    info = {"cases_path": rel(cases_path), "cases_sha256": sha256_file(cases_path), "seed": seed,
            "n_dev": len(dev), "n_test": len(test), "numeric_only": numeric_only,
            "dev_sha256": hashlib.sha256(json.dumps(dev).encode()).hexdigest(),
            "test_sha256": hashlib.sha256(json.dumps(test).encode()).hexdigest()}
    json.dump(info, open(lock, "w"), indent=2)
    return info


def load_split_ids(out_dir, which):
    return set(json.load(open(os.path.join(out_dir, f"{which}_ids.json"))))


def ids_sha256(ids):
    """The dev/test hash exactly as make_split writes it (json.dumps of the sorted id list)."""
    return hashlib.sha256(json.dumps(ids).encode()).hexdigest()


def neutralize_split_lock(src_lock, out_lock, cases_path_rel, cases_file=None):
    """Rewrite a SPLIT_LOCK.json so that cases_path is relative and cases_sha256 is that of the neutral cases file.

    Every other key keeps its value and position; the serialisation is make_split's (json.dump, indent=2). The
    dev/test id files next to the lock are not touched; their hashes are re-checked against the lock here.
    """
    if os.path.isabs(cases_path_rel):
        raise ValueError("cases_path must be relative to the repository root")
    raw = open(src_lock, "r", encoding="utf-8").read()
    lock = json.loads(raw)
    if json.dumps(lock, indent=2) != raw:
        raise ValueError("SPLIT_LOCK is not in make_split's serialisation; refusing to re-serialise it")
    d = os.path.dirname(os.path.abspath(src_lock))
    for which in ("dev", "test"):
        ids = json.load(open(os.path.join(d, f"{which}_ids.json"), encoding="utf-8"))
        if ids_sha256(ids) != lock[f"{which}_sha256"]:
            raise ValueError(f"{which}_ids.json does not match {which}_sha256 in the lock")
    cases_file = cases_file or resolve(cases_path_rel)
    new = dict(lock)
    new["cases_path"] = cases_path_rel
    new["cases_sha256"] = sha256_file(cases_file)
    with open(out_lock, "w", encoding="utf-8") as f:
        f.write(json.dumps(new, indent=2))
    return {"src_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "out_sha256": sha256_file(out_lock),
            "cases_path": cases_path_rel, "cases_sha256_before": lock["cases_sha256"], "cases_sha256_after": new["cases_sha256"],
            "dev_sha256": lock["dev_sha256"], "test_sha256": lock["test_sha256"],
            "changed": "cases_path, cases_sha256 only"}


# ------------------------------------------------------------------ R1 (E14): subsets that keep the frozen split
#
# D7/D5 as revised for R1: no case is re-assigned and nothing is re-sampled. An analysis subset keeps every case on
# the side the frozen split put it (dev = parent dev ∩ subset, test = parent test ∩ subset); cases outside the
# subset are only dropped. A new data source (none is planned) goes entirely to test.

SUBSET_RULE = ("dev = parent dev ∩ subset; test = parent test ∩ subset; no case changes side; "
               "cases outside the subset are dropped, never re-sampled")
NEW_SOURCE_RULE = "a new data source goes entirely to test (D7); nothing is added to dev"


def _write_ids(path, ids):
    # same serialisation as make_split (json.dump, indent=0); the hash is ids_sha256 of the sorted list
    with open(path, "w") as f:
        json.dump(ids, f, indent=0)


def read_lock_dir(lock_dir):
    """(lock, dev_ids, test_ids) of a split directory, after checking the id files against the lock's hashes."""
    lock = json.load(open(os.path.join(lock_dir, "SPLIT_LOCK.json"), encoding="utf-8"))
    ids = {}
    for which in ("dev", "test"):
        lst = json.load(open(os.path.join(lock_dir, f"{which}_ids.json"), encoding="utf-8"))
        if lst != sorted(set(lst)):
            raise ValueError(f"{rel(lock_dir)}/{which}_ids.json is not a sorted list of distinct ids")
        if ids_sha256(lst) != lock[f"{which}_sha256"] or len(lst) != lock[f"n_{which}"]:
            raise ValueError(f"{rel(lock_dir)}/{which}_ids.json does not match {which}_sha256 / n_{which} in its lock")
        ids[which] = lst
    if set(ids["dev"]) & set(ids["test"]):
        raise ValueError(f"{rel(lock_dir)}: dev and test share cases")
    return lock, ids["dev"], ids["test"]


def split_subset(parent_dev, parent_test, subset_ids):
    """Place a subset on the frozen split. Returns {"dev": [...], "test": [...]} (sorted).

    `subset_ids` is either a flat iterable of ids (sides come from the parent) or a mapping {"dev": [...], "test": [...]}
    of declared sides, which must agree with the parent. Raises ValueError for an id outside the parent split, a
    duplicate id, or an id declared on the other side than the frozen split put it (a "side switch").
    """
    pdev, ptest = set(parent_dev), set(parent_test)
    if isinstance(subset_ids, dict):
        unknown_keys = set(subset_ids) - {"dev", "test"}
        if unknown_keys:
            raise ValueError(f"subset sides must be 'dev' / 'test', got {sorted(unknown_keys)}")
        declared = {w: list(subset_ids.get(w, [])) for w in ("dev", "test")}
    else:
        flat = list(subset_ids)
        declared = {"dev": [c for c in flat if c in pdev], "test": [c for c in flat if c not in pdev]}
    both = declared["dev"] + declared["test"]
    dup = sorted({c for c in both if both.count(c) > 1})
    if dup:
        raise ValueError(f"subset lists {len(dup)} id(s) more than once or on both sides: {dup[:5]}")
    outside = sorted(c for c in both if c not in pdev and c not in ptest)
    if outside:
        raise ValueError(f"{len(outside)} subset id(s) are not in the parent split: {outside[:5]}")
    switched = sorted([c for c in declared["dev"] if c in ptest] + [c for c in declared["test"] if c in pdev])
    if switched:
        raise ValueError(f"{len(switched)} subset id(s) are declared on the other side than the frozen split: {switched[:5]}")
    return {"dev": sorted(declared["dev"]), "test": sorted(declared["test"])}


def _subset_files(parent_lock_dir, sides, name, source, root=None):
    lock_path = os.path.join(parent_lock_dir, "SPLIT_LOCK.json")
    lock, pdev, ptest = read_lock_dir(parent_lock_dir)
    removed = {"dev": sorted(set(pdev) - set(sides["dev"])), "test": sorted(set(ptest) - set(sides["test"]))}
    info = {
        "kind": "subset",
        "name": name,
        "rule": SUBSET_RULE,
        "parent_lock": rel(lock_path, root),
        "parent_lock_sha256": sha256_file(lock_path),
        "parent_dev_sha256": lock["dev_sha256"],
        "parent_test_sha256": lock["test_sha256"],
        "cases_path": lock["cases_path"],
        "cases_sha256": lock["cases_sha256"],
        "seed": lock.get("seed"),
        "subset_source": source,
        "subset_sha256": ids_sha256(sorted(sides["dev"] + sides["test"])),
        "n_dev": len(sides["dev"]),
        "n_test": len(sides["test"]),
        "dev_sha256": ids_sha256(sides["dev"]),
        "test_sha256": ids_sha256(sides["test"]),
        "n_removed_dev": len(removed["dev"]),
        "n_removed_test": len(removed["test"]),
        "removed_dev_sha256": ids_sha256(removed["dev"]),
        "removed_test_sha256": ids_sha256(removed["test"]),
    }
    return info, removed


def derive_subset_lock(parent_lock_dir, subset_ids, out_dir, name=None, source=None, expect=None, force=False, root=None):
    """Write data/splits_r1/<set>/ for a subset of a frozen split, keeping every case on its frozen side.

    Files: SPLIT_LOCK.json (kind "subset"; parent lock path + sha256, cases path + sha256 inherited from the parent,
    subset hash, dev/test hashes and counts), dev_ids.json, test_ids.json, removed_ids.json. `source` records where
    the ids came from ({"path", "sha256", "set"}; paths relative). `expect` may give n_dev / n_test / dev_sha256 /
    test_sha256 that must be reproduced. The parent split is only read. Re-running with the same inputs is a no-op;
    different content in an existing directory is refused unless force=True. `root` is the repository root that
    recorded paths are relative to (default: this checkout).
    """
    _, pdev, ptest = read_lock_dir(parent_lock_dir)
    sides = split_subset(pdev, ptest, subset_ids)
    name = name or os.path.basename(os.path.normpath(out_dir))
    info, removed = _subset_files(parent_lock_dir, sides, name, source, root)
    for k, want in (expect or {}).items():
        if info.get(k) != want:
            raise ValueError(f"subset {name}: {k} = {info.get(k)!r}, expected {want!r}")
    files = {
        "SPLIT_LOCK.json": json.dumps(info, indent=2, ensure_ascii=False),
        "dev_ids.json": json.dumps(sides["dev"], indent=0),
        "test_ids.json": json.dumps(sides["test"], indent=0),
        "removed_ids.json": json.dumps(removed, indent=0),
    }
    lock_path = os.path.join(out_dir, "SPLIT_LOCK.json")
    if os.path.exists(lock_path):
        same = all(os.path.exists(os.path.join(out_dir, fn)) and
                   open(os.path.join(out_dir, fn), encoding="utf-8").read() == txt for fn, txt in files.items())
        if same:
            return info
        if not force:
            raise SystemExit(f"subset lock already exists with different content at {rel(lock_path, root)}; "
                             "use force only before any test run has happened (and record it)")
    os.makedirs(out_dir, exist_ok=True)
    for fn, txt in files.items():
        with open(os.path.join(out_dir, fn), "w", encoding="utf-8") as f:
            f.write(txt)
    return info


def verify_subset_lock(lock_dir, root=None):
    """Re-check a subset lock against its parent. Returns a list of problems (empty = consistent)."""
    problems = []
    try:
        lock, dev, test = read_lock_dir(lock_dir)
    except (ValueError, OSError, KeyError) as e:
        return [str(e)]
    if lock.get("kind") != "subset":
        return [f"{rel(lock_dir)}: not a subset lock"]
    parent_lock = resolve(lock["parent_lock"], root)
    parent_dir = os.path.dirname(parent_lock)
    if not os.path.exists(parent_lock):
        return [f"{rel(lock_dir)}: parent lock {lock['parent_lock']} is missing"]
    if sha256_file(parent_lock) != lock["parent_lock_sha256"]:
        problems.append(f"{rel(lock_dir)}: parent lock changed since the subset was derived")
    try:
        plock, pdev, ptest = read_lock_dir(parent_dir)
    except (ValueError, OSError, KeyError) as e:
        return problems + [str(e)]
    for k in ("cases_path", "cases_sha256"):
        if lock[k] != plock[k]:
            problems.append(f"{rel(lock_dir)}: {k} differs from the parent lock")
    try:
        sides = split_subset(pdev, ptest, {"dev": dev, "test": test})
    except ValueError as e:
        problems.append(f"{rel(lock_dir)}: {e}")
        return problems
    if lock["subset_sha256"] != ids_sha256(sorted(sides["dev"] + sides["test"])):
        problems.append(f"{rel(lock_dir)}: subset_sha256 does not match the id files")
    rem_path = os.path.join(lock_dir, "removed_ids.json")
    if os.path.exists(rem_path):
        removed = json.load(open(rem_path, encoding="utf-8"))
        if removed.get("dev") != sorted(set(pdev) - set(dev)) or removed.get("test") != sorted(set(ptest) - set(test)):
            problems.append(f"{rel(lock_dir)}: removed_ids.json is not parent minus subset")
    else:
        problems.append(f"{rel(lock_dir)}: removed_ids.json is missing")
    return problems


def assign_new_source(ids, existing_ids=()):
    """D7 rule for a new data source: every case goes to test, none to dev. Not used by the confirmed design
    (no new cases), kept so that the rule is executable. Raises on duplicates or on ids already in another split."""
    ids = list(ids)
    dup = sorted({c for c in ids if ids.count(c) > 1})
    if dup:
        raise ValueError(f"duplicate ids in the new source: {dup[:5]}")
    clash = sorted(set(ids) & set(existing_ids))
    if clash:
        raise ValueError(f"{len(clash)} id(s) of the new source already belong to a frozen split: {clash[:5]}")
    return {"dev": [], "test": sorted(ids)}


def freeze_new_source(cases_path, out_dir, existing_split_dirs=(), force=False):
    """Freeze a new source's split with assign_new_source (all test). Same files and hashes as make_split."""
    lock = os.path.join(out_dir, "SPLIT_LOCK.json")
    if os.path.exists(lock) and not force:
        raise SystemExit(f"split already frozen at {rel(lock)}")
    existing = set()
    for d in existing_split_dirs:
        _, dev, test = read_lock_dir(d)
        existing |= set(dev) | set(test)
    sides = assign_new_source([c["case_id"] for c in load_cases(cases_path)], existing)
    os.makedirs(out_dir, exist_ok=True)
    _write_ids(os.path.join(out_dir, "dev_ids.json"), sides["dev"])
    _write_ids(os.path.join(out_dir, "test_ids.json"), sides["test"])
    info = {"cases_path": rel(cases_path), "cases_sha256": sha256_file(cases_path), "seed": None,
            "n_dev": 0, "n_test": len(sides["test"]), "numeric_only": False, "rule": NEW_SOURCE_RULE,
            "dev_sha256": ids_sha256(sides["dev"]), "test_sha256": ids_sha256(sides["test"])}
    with open(lock, "w", encoding="utf-8") as f:
        f.write(json.dumps(info, indent=2))
    return info


# ------------------------------------------------------------------ R1 (E22): engineering-source hold-out

ENG_HOLDOUT_RULE = ("every case of the engineering-source set is eng_holdout: neither dev nor test; no gene work, no dev "
                    "tuning, run once after the freeze (E22)")


def freeze_eng_holdout(cases_path, out_dir, existing_split_dirs=(), force=False):
    """Write the split directory of the engineering-source cases: dev_ids.json and test_ids.json empty, every case in
    eng_holdout_ids.json. The lock has make_split's keys (so every reader of SPLIT_LOCK works) plus kind, rule,
    n_eng_holdout and eng_holdout_sha256. Refuses ids that already belong to another frozen split."""
    lock = os.path.join(out_dir, "SPLIT_LOCK.json")
    existing = set()
    for d in existing_split_dirs:
        _, dev, test = read_lock_dir(d)
        existing |= set(dev) | set(test)
        eh = os.path.join(d, "eng_holdout_ids.json")
        if os.path.exists(eh):
            existing |= set(json.load(open(eh, encoding="utf-8")))
    ids = [c["case_id"] for c in load_cases(cases_path)]
    dup = sorted({c for c in ids if ids.count(c) > 1})
    if dup:
        raise ValueError(f"duplicate case ids: {dup[:5]}")
    clash = sorted(set(ids) & existing)
    if clash:
        raise ValueError(f"{len(clash)} engineering case id(s) already belong to a frozen split: {clash[:5]}")
    held = sorted(ids)
    info = {"kind": "eng_holdout", "rule": ENG_HOLDOUT_RULE, "cases_path": rel(cases_path),
            "cases_sha256": sha256_file(cases_path), "seed": None, "n_dev": 0, "n_test": 0,
            "n_eng_holdout": len(held), "numeric_only": False,
            "dev_sha256": ids_sha256([]), "test_sha256": ids_sha256([]), "eng_holdout_sha256": ids_sha256(held)}
    files = {"SPLIT_LOCK.json": json.dumps(info, indent=2), "dev_ids.json": json.dumps([], indent=0),
             "test_ids.json": json.dumps([], indent=0), "eng_holdout_ids.json": json.dumps(held, indent=0)}
    if os.path.exists(lock):
        same = all(os.path.exists(os.path.join(out_dir, fn)) and open(os.path.join(out_dir, fn), encoding="utf-8").read() == txt
                   for fn, txt in files.items())
        if same:
            return info
        if not force:
            raise SystemExit(f"split already frozen at {rel(lock)}")
    os.makedirs(out_dir, exist_ok=True)
    for fn, txt in files.items():
        with open(os.path.join(out_dir, fn), "w", encoding="utf-8") as f:
            f.write(txt)
    return info


def verify_eng_holdout(out_dir, cases_path=None):
    """Problems (empty = consistent) of an eng_holdout split directory: id files against the lock, cases hash."""
    problems = []
    try:
        lock, dev, test = read_lock_dir(out_dir)
    except (ValueError, OSError, KeyError) as e:
        return [str(e)]
    if lock.get("kind") != "eng_holdout":
        return [f"{rel(out_dir)}: not an eng_holdout split"]
    if dev or test:
        problems.append(f"{rel(out_dir)}: an eng_holdout split has no dev or test ids")
    eh = os.path.join(out_dir, "eng_holdout_ids.json")
    held = json.load(open(eh, encoding="utf-8")) if os.path.exists(eh) else None
    if held is None:
        return problems + [f"{rel(out_dir)}: eng_holdout_ids.json is missing"]
    if held != sorted(set(held)) or ids_sha256(held) != lock.get("eng_holdout_sha256") or len(held) != lock.get("n_eng_holdout"):
        problems.append(f"{rel(out_dir)}: eng_holdout_ids.json does not match the lock")
    cp = cases_path or resolve(lock["cases_path"])
    if not os.path.exists(cp) or sha256_file(cp) != lock["cases_sha256"]:
        problems.append(f"{rel(out_dir)}: cases file changed since the split was frozen")
    elif sorted(c["case_id"] for c in load_cases(cp)) != held:
        problems.append(f"{rel(out_dir)}: the cases file and eng_holdout_ids.json list different ids")
    return problems

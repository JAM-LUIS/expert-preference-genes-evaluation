"""E14: subsets keep the frozen split (no case changes side, nothing is re-sampled); a new source goes to test.

Fixtures are self-made toy cases only; no benchmark case is read.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, RUNTIME)

from orgene import data as D  # noqa: E402
from orgene import split as S  # noqa: E402
from orgene.paths import find_absolute_paths  # noqa: E402


def _toy_repo(root, n=10, n_dev=4, source="toy"):
    """root/data/cases/<source>.jsonl (n toy cases) and root/data/splits/<source>/ frozen with make_split."""
    raw = root / "data" / "raw" / f"{source}.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_text("".join(json.dumps({"question": f"maximise {i}x s.t. x <= 1", "answer": str(i)}) + "\n"
                           for i in range(1, n + 1)), encoding="utf-8")
    cases = root / "data" / "cases" / f"{source}.jsonl"
    D.build_cases(source, str(raw), str(cases))
    split_dir = root / "data" / "splits" / source
    S.make_split(str(cases), str(split_dir), n_dev=n_dev, seed=7)
    lock = json.loads((split_dir / "SPLIT_LOCK.json").read_text())
    lock["cases_path"] = f"data/cases/{source}.jsonl"          # as the neutral R1 locks record it
    (split_dir / "SPLIT_LOCK.json").write_text(json.dumps(lock, indent=2))
    dev = json.loads((split_dir / "dev_ids.json").read_text())
    test = json.loads((split_dir / "test_ids.json").read_text())
    return split_dir, dev, test


# ------------------------------------------------------------------ split_subset


def test_split_subset_keeps_sides_for_flat_and_declared_input(tmp_path):
    _, dev, test = _toy_repo(tmp_path)
    flat = [dev[0], test[0], test[1]]
    assert S.split_subset(dev, test, flat) == {"dev": [dev[0]], "test": sorted(test[:2])}
    assert S.split_subset(dev, test, {"dev": [dev[0]], "test": test[:2]}) == {"dev": [dev[0]], "test": sorted(test[:2])}


def test_split_subset_rejects_side_switch_foreign_ids_and_duplicates(tmp_path):
    _, dev, test = _toy_repo(tmp_path)
    with pytest.raises(ValueError, match="other side"):
        S.split_subset(dev, test, {"dev": [test[0]], "test": []})          # a test case declared dev
    with pytest.raises(ValueError, match="other side"):
        S.split_subset(dev, test, {"dev": [], "test": [dev[0]]})           # a dev case declared test
    with pytest.raises(ValueError, match="not in the parent"):
        S.split_subset(dev, test, [dev[0], "toy-0999"])
    with pytest.raises(ValueError, match="not in the parent"):
        S.split_subset(dev, test, {"dev": [], "test": ["other-0001"]})
    with pytest.raises(ValueError, match="more than once"):
        S.split_subset(dev, test, {"dev": [dev[0]], "test": [dev[0]]})
    with pytest.raises(ValueError, match="more than once"):
        S.split_subset(dev, test, [test[0], test[0]])
    with pytest.raises(ValueError, match="sides"):
        S.split_subset(dev, test, {"dev": [], "holdout": [test[0]]})


# ------------------------------------------------------------------ derive_subset_lock / verify_subset_lock


def test_derive_subset_lock_writes_a_consistent_relative_lock(tmp_path):
    split_dir, dev, test = _toy_repo(tmp_path)
    before = {p.name: p.read_bytes() for p in split_dir.iterdir()}
    sub = {"dev": dev[:2], "test": test[1:4]}
    out = tmp_path / "data" / "splits_r1" / "toy_sub"
    src = {"path": "data/analysis_sets/x.json", "sha256": "0" * 64, "set": "toy_sub"}
    info = S.derive_subset_lock(str(split_dir), sub, str(out), source=src, root=str(tmp_path),
                                expect={"n_dev": 2, "n_test": 3})
    assert {p.name: p.read_bytes() for p in split_dir.iterdir()} == before          # parent only read
    lock = json.loads((out / "SPLIT_LOCK.json").read_text())
    assert lock == info and lock["kind"] == "subset" and lock["name"] == "toy_sub"
    assert lock["parent_lock"] == "data/splits/toy/SPLIT_LOCK.json" and lock["subset_source"] == src
    assert lock["cases_path"] == "data/cases/toy.jsonl"
    parent = json.loads((split_dir / "SPLIT_LOCK.json").read_text())
    assert lock["cases_sha256"] == parent["cases_sha256"] and lock["seed"] == parent["seed"]
    assert lock["dev_sha256"] == S.ids_sha256(sorted(sub["dev"])) and lock["test_sha256"] == S.ids_sha256(sorted(sub["test"]))
    assert json.loads((out / "dev_ids.json").read_text()) == sorted(sub["dev"])
    removed = json.loads((out / "removed_ids.json").read_text())
    assert removed == {"dev": sorted(set(dev) - set(sub["dev"])), "test": sorted(set(test) - set(sub["test"]))}
    assert (lock["n_removed_dev"], lock["n_removed_test"]) == (len(dev) - 2, len(test) - 3)
    assert not find_absolute_paths((out / "SPLIT_LOCK.json").read_text())
    assert S.verify_subset_lock(str(out), str(tmp_path)) == []
    # the result is a normal split directory for the existing readers
    assert S.load_split_ids(str(out), "test") == set(sub["test"])
    lk, d2, t2 = S.read_lock_dir(str(out))
    assert (d2, t2) == (sorted(sub["dev"]), sorted(sub["test"]))


def test_derive_subset_lock_is_idempotent_and_refuses_different_content(tmp_path):
    split_dir, dev, test = _toy_repo(tmp_path)
    out = tmp_path / "data" / "splits_r1" / "s"
    S.derive_subset_lock(str(split_dir), [dev[0], test[0]], str(out), root=str(tmp_path))
    S.derive_subset_lock(str(split_dir), [dev[0], test[0]], str(out), root=str(tmp_path))       # same -> no-op
    with pytest.raises(SystemExit):
        S.derive_subset_lock(str(split_dir), [dev[0], test[1]], str(out), root=str(tmp_path))
    S.derive_subset_lock(str(split_dir), [dev[0], test[1]], str(out), root=str(tmp_path), force=True)
    assert S.load_split_ids(str(out), "test") == {test[1]}


def test_derive_subset_lock_negative_cases(tmp_path):
    split_dir, dev, test = _toy_repo(tmp_path)
    out = str(tmp_path / "o")
    with pytest.raises(ValueError, match="not in the parent"):
        S.derive_subset_lock(str(split_dir), [dev[0], "toy-0999"], out, root=str(tmp_path))
    with pytest.raises(ValueError, match="other side"):
        S.derive_subset_lock(str(split_dir), {"dev": [test[0]], "test": []}, out, root=str(tmp_path))
    with pytest.raises(ValueError, match="expected"):
        S.derive_subset_lock(str(split_dir), [dev[0], test[0]], out, root=str(tmp_path), expect={"n_test": 2})
    assert not os.path.exists(out)
    # a parent whose id file no longer matches its lock is refused
    (split_dir / "dev_ids.json").write_text(json.dumps(sorted(dev[:-1]), indent=0))
    with pytest.raises(ValueError, match="does not match"):
        S.derive_subset_lock(str(split_dir), [test[0]], out, root=str(tmp_path))


def test_verify_subset_lock_catches_tampering(tmp_path):
    split_dir, dev, test = _toy_repo(tmp_path)
    out = tmp_path / "data" / "splits_r1" / "s"
    S.derive_subset_lock(str(split_dir), {"dev": dev[:2], "test": test[:3]}, str(out), root=str(tmp_path))
    # a test case moved into the subset's dev list (hashes updated so that only the side check can catch it)
    lock = json.loads((out / "SPLIT_LOCK.json").read_text())
    new_dev, new_test = sorted(dev[:2] + [test[0]]), sorted(test[1:3])
    (out / "dev_ids.json").write_text(json.dumps(new_dev, indent=0))
    (out / "test_ids.json").write_text(json.dumps(new_test, indent=0))
    lock.update(dev_sha256=S.ids_sha256(new_dev), test_sha256=S.ids_sha256(new_test), n_dev=3, n_test=2)
    (out / "SPLIT_LOCK.json").write_text(json.dumps(lock, indent=2))
    assert any("other side" in p for p in S.verify_subset_lock(str(out), str(tmp_path)))
    # the parent lock changed after derivation
    out2 = tmp_path / "data" / "splits_r1" / "s2"
    S.derive_subset_lock(str(split_dir), [dev[0]], str(out2), root=str(tmp_path))
    plock = json.loads((split_dir / "SPLIT_LOCK.json").read_text())
    plock["note"] = "edited"
    (split_dir / "SPLIT_LOCK.json").write_text(json.dumps(plock, indent=2))
    assert any("parent lock changed" in p for p in S.verify_subset_lock(str(out2), str(tmp_path)))


# ------------------------------------------------------------------ new source -> all test (D7)


def test_assign_new_source_puts_everything_in_test():
    assert S.assign_new_source(["n-0002", "n-0001"]) == {"dev": [], "test": ["n-0001", "n-0002"]}
    with pytest.raises(ValueError, match="duplicate"):
        S.assign_new_source(["n-0001", "n-0001"])
    with pytest.raises(ValueError, match="already belong"):
        S.assign_new_source(["n-0001", "toy-0001"], existing_ids={"toy-0001"})


def test_freeze_new_source_writes_an_all_test_lock(tmp_path):
    split_dir, dev, test = _toy_repo(tmp_path)
    split_new, dev_new, test_new = _toy_repo(tmp_path / "second", n=3, n_dev=1, source="newsrc")
    new_cases = tmp_path / "second" / "data" / "cases" / "newsrc.jsonl"
    out = tmp_path / "data" / "splits" / "newsrc_all_test"
    info = S.freeze_new_source(str(new_cases), str(out), existing_split_dirs=[str(split_dir)])
    assert info["n_dev"] == 0 and info["n_test"] == 3 and info["rule"] == S.NEW_SOURCE_RULE
    assert json.loads((out / "dev_ids.json").read_text()) == []
    assert json.loads((out / "test_ids.json").read_text()) == sorted(dev_new + test_new)
    lk, d, t = S.read_lock_dir(str(out))
    assert d == [] and len(t) == 3
    with pytest.raises(SystemExit):
        S.freeze_new_source(str(new_cases), str(out))
    # a source whose ids collide with an existing split is refused
    with pytest.raises(ValueError, match="already belong"):
        S.freeze_new_source(str(tmp_path / "data" / "cases" / "toy.jsonl"), str(tmp_path / "x"),
                            existing_split_dirs=[str(split_dir)])


def test_industryor_license_constant_is_the_checked_card_value():
    assert D.LICENSES["industryor"].startswith("CC-BY-NC-4.0")
    assert "VERIFY" not in D.LICENSES["industryor"]

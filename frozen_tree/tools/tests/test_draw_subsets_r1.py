"""Seeded variance and determinism subsets (tools/draw_subsets_r1.py). Synthetic ids only, except the last test,
which compares the committed file with a fresh draw (ids only; no case record is read)."""
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import draw_subsets_r1 as D  # noqa: E402


def test_allocate_is_proportional_with_largest_remainder():
    assert D.allocate([80, 71], 100) == [53, 47]
    assert D.allocate([30, 25], 20) == [11, 9]
    assert D.allocate([10, 10], 5) == [3, 2]          # tie: the stratum named first
    assert sum(D.allocate([7, 5, 3], 11)) == 11
    with pytest.raises(ValueError):
        D.allocate([3, 2], 6)


def test_draw_ids_depends_on_seed_and_subset_not_on_input_order():
    ids = [f"toy-{i:04d}" for i in range(40)]
    a = D.draw_ids(ids, 10, 1, "variance")
    assert a == D.draw_ids(list(reversed(ids)), 10, 1, "variance") == sorted(a)
    assert len(set(a)) == 10 and set(a) <= set(ids)
    assert a != D.draw_ids(ids, 10, 2, "variance")
    assert a != D.draw_ids(ids, 10, 1, "determinism")
    with pytest.raises(ValueError):
        D.draw_ids(ids + ids[:1], 5, 1, "variance")


def test_draw_on_a_synthetic_tree(tmp_path):
    for (_, d), (n_dev, n_test) in zip(D.STRATA, ((30, 80), (25, 71))):
        p = tmp_path / d
        p.mkdir(parents=True)
        (p / "SPLIT_LOCK.json").write_text("{}")
        tag = os.path.basename(d)[:4]
        (p / "dev_ids.json").write_text(json.dumps([f"{tag}-d{i:03d}" for i in range(n_dev)]))
        (p / "test_ids.json").write_text(json.dumps([f"{tag}-t{i:03d}" for i in range(n_test)]))
    doc = D.draw(str(tmp_path))
    v, t = doc["subsets"]["variance"], doc["subsets"]["determinism"]
    assert [s["n"] for s in v["strata"].values()] == [53, 47] and v["split"] == "test"
    assert [s["n"] for s in t["strata"].values()] == [11, 9] and t["split"] == "dev"
    assert all("-t" in c for s in v["strata"].values() for c in s["ids"])
    assert all("-d" in c for s in t["strata"].values() for c in s["ids"])
    assert D.render(doc) == D.render(D.draw(str(tmp_path)))


def test_committed_file_equals_a_fresh_draw():
    out = os.path.join(ROOT, D.OUT)
    if not os.path.exists(out):
        pytest.skip("subset file not drawn yet")
    assert open(out, "rb").read() == D.render(D.draw())

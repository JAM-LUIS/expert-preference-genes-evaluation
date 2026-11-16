"""E14: the stage-1 id sets, the derived subset locks (data/splits_r1) and the analysis-set definitions.

Only case ids, counts and hashes are used (the id-set file and the frozen split id files); no case text is read and
no result is involved. Exclusion lists that will come from the annotations are fabricated from ids for the tests.
"""
import copy
import json
import os
import shutil
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from orgene import analysis_sets as A  # noqa: E402
from orgene import split as S  # noqa: E402

import derive_splits_r1  # noqa: E402

ID_SETS = os.path.join(ROOT, A.ID_SETS_PATH)
# sizes and hashes recorded by the stage-1 task and in the engineering plan (E14, "怎么测")
EXPECTED = {
    "mamo_main_clean111": (30, 81, None),
    "mamo_sensitivity_full211": (60, 151, None),
    "industryor_main_rev2026_100": (25, 75, None),
    "mamo_main_clean111_excl0905": (30, 80, "6aaa1d3b"),
    "industryor_main_rev2026_100_excl0905": (25, 71, "c38c425d"),
    "mamo_sensitivity_full211_excl0905": (60, 146, "5990623f"),
}


@pytest.fixture(scope="module")
def id_sets():
    return A.load_id_sets(None, ROOT)


def _copy_tree(dst):
    """The files the definitions need, copied into a scratch root (ids only)."""
    for rel in ("data/splits", "data/analysis_sets", "configs", A.UNDERSPEC_PATH):
        src, out = os.path.join(ROOT, rel), os.path.join(dst, rel)
        if os.path.isdir(src):
            shutil.copytree(src, out)
        else:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy(src, out)
    return str(dst)


def _write_exclusions(root, nl, q3, status="final"):
    doc = {"schema": A.EXCLUSIONS_SCHEMA,
           A.NL: {"status": status, "ids": sorted(nl), "pending_ids": []},
           A.Q3: {"status": status, "ids": sorted(q3), "pending_ids": []}}
    with open(os.path.join(root, A.EXCLUSIONS_PATH), "w") as f:
        json.dump(doc, f)


# ------------------------------------------------------------------ the id-set file


def test_id_set_file_is_the_stage1_v2_file(id_sets):
    defs = json.load(open(os.path.join(ROOT, A.SET_DEFS_PATH)))
    assert A.sha256_path(ID_SETS) == defs["id_sets"]["sha256"]
    assert id_sets["schema"] == A.ID_SETS_SCHEMA
    assert id_sets["primary_sets"] == {"mamo_complex_lp": "mamo_main_clean111_excl0905",
                                       "industryor": "industryor_main_rev2026_100_excl0905"}


def test_id_sets_sizes_hashes_and_sides(id_sets):
    assert A.validate_id_sets(id_sets, root=ROOT) == []
    for name, (n_dev, n_test, test_prefix) in EXPECTED.items():
        s = id_sets["sets"][name]
        assert (len(s["dev"]), len(s["test"])) == (n_dev, n_test), name
        assert S.ids_sha256(s["test"]) == s["test_ids_sha256"]
        if test_prefix:
            assert s["test_ids_sha256"].startswith(test_prefix)
    assert id_sets["sets"]["mamo_main_clean111"]["dev_ids_sha256"].startswith("cbf22bfa")
    assert id_sets["sets"]["mamo_main_clean111"]["test_ids_sha256"].startswith("c877ee5d")
    # every set lies on the frozen split of its benchmark (no case changed side)
    for s in id_sets["sets"].values():
        _, dev, test = S.read_lock_dir(os.path.join(ROOT, "data", "splits", s["benchmark"]))
        assert set(s["dev"]) <= set(dev) and set(s["test"]) <= set(test)


def test_seen_20260905_cases_are_only_in_the_incl_sets(id_sets):
    seen = set(id_sets["exclusions"][A.SEEN]["ids"])
    assert len(seen) == 9
    sets = id_sets["sets"]
    assert len(seen & set(sets["mamo_main_clean111"]["test"])) == 1
    assert len(seen & set(sets["mamo_sensitivity_full211"]["test"])) == 5
    assert len(seen & set(sets["industryor_main_rev2026_100"]["test"])) == 4
    for name in EXPECTED:
        if name.endswith(A.EXCL_SUFFIX):
            assert not seen & (set(sets[name]["dev"]) | set(sets[name]["test"])), name


def _rehash(s):
    for side in A.SIDES:
        s[side] = sorted(s[side])
        s[f"n_{side}"] = len(s[side])
        s[f"{side}_ids_sha256"] = S.ids_sha256(s[side])
    s["n"] = s["n_dev"] + s["n_test"]


def test_validate_id_sets_negative_cases(id_sets):
    seen = sorted(id_sets["exclusions"][A.SEEN]["ids"])
    # a viewed case put back into an excl0905 set (counts and hashes updated so only the exclusion check can fail)
    bad = copy.deepcopy(id_sets)
    s = bad["sets"]["industryor_main_rev2026_100_excl0905"]
    s["test"].append(next(c for c in seen if c.startswith("industryor")))
    _rehash(s)
    assert any(A.SEEN in p for p in A.validate_id_sets(bad, root=ROOT))
    # an id that is not in the frozen split
    bad = copy.deepcopy(id_sets)
    s = bad["sets"]["mamo_main_clean111"]
    s["test"].append("mamo_complex_lp-0999")
    _rehash(s)
    assert any("not in the parent split" in p for p in A.validate_id_sets(bad, root=ROOT))
    # a dev case declared test (side switch)
    bad = copy.deepcopy(id_sets)
    s = bad["sets"]["mamo_main_clean111"]
    moved = s["dev"].pop(0)
    s["test"].append(moved)
    _rehash(s)
    assert any("other side" in p for p in A.validate_id_sets(bad, root=ROOT))
    # a stale hash
    bad = copy.deepcopy(id_sets)
    bad["sets"]["mamo_main_clean111"]["test_ids_sha256"] = "0" * 64
    assert any("test_ids_sha256" in p for p in A.validate_id_sets(bad, root=ROOT, check_splits=False))


# ------------------------------------------------------------------ data/splits_r1


def test_splits_r1_reproduce_from_the_id_sets():
    problems, infos = derive_splits_r1.check(ROOT, os.path.join(ROOT, "data", "splits_r1"))
    assert problems == []
    for name, (n_dev, n_test, _) in EXPECTED.items():
        assert (infos[name]["n_dev"], infos[name]["n_test"]) == (n_dev, n_test)
    lock = json.load(open(os.path.join(ROOT, "data", "splits_r1", "mamo_main_clean111", "SPLIT_LOCK.json")))
    assert (lock["n_removed_dev"], lock["n_removed_test"]) == (30, 70)
    assert lock["parent_lock"] == "data/splits/mamo_complex_lp/SPLIT_LOCK.json"
    assert lock["subset_source"]["path"] == A.ID_SETS_PATH


# ------------------------------------------------------------------ definitions


def test_definitions_resolve_on_the_working_tree_with_pending_lists():
    res, lists = A.resolve_all(ROOT, strict=False)
    assert lists[A.NL]["status"] == lists[A.Q3]["status"] == "pending"
    assert res["dev_signal55"]["n"] == 55 and res["dev_signal55"]["pending"] == []
    assert res["dev_all85"]["n"] == 85 and res["dev_error_type_only30"]["n"] == 30
    assert res["main"]["pending"] == [A.NL, A.Q3]
    assert {b: len(v) for b, v in res["main"]["by_benchmark"].items()} == {"mamo_complex_lp": 80, "industryor": 71}
    assert not set(res["main"]["ids"]) & lists[A.SEEN]["ids"]
    with pytest.raises(A.PendingError):
        A.analysis_set("main", ROOT)                     # strict by default
    assert A.analysis_set("dev_signal55", ROOT)["n"] == 55


def test_definitions_with_final_lists(tmp_path, id_sets):
    root = _copy_tree(tmp_path)
    ior = id_sets["sets"]["industryor_main_rev2026_100_excl0905"]["test"]
    mamo = id_sets["sets"]["mamo_main_clean111_excl0905"]["test"]
    mamo_removed = sorted(set(id_sets["sets"]["mamo_sensitivity_full211_excl0905"]["test"]) - set(mamo))
    nl, q3 = ior[:2], [ior[2], mamo[0], mamo_removed[0]]
    _write_exclusions(root, nl, q3)
    res, lists = A.resolve_all(root, strict=True)
    seen = lists[A.SEEN]["ids"]
    main = set(res["main"]["ids"])
    assert res["main"]["n"] == 80 + 71 - 2 - 2 and not main & (set(nl) | set(q3) | seen)
    assert res["sens_orig_ref"]["ids"] == res["main"]["ids"] and res["sens_orig_ref"]["reference"] == "original"
    full = set(res["sens_full211"]["ids"])
    assert set(q3) <= full and not full & (set(nl) | seen) and main <= full
    assert res["sens_full211"]["n"] == 146 + 71 - 2
    incl = set(res["sens_incl0905"]["ids"])
    assert main <= incl and incl - main <= seen and len(incl - main) == 5
    assert res["sens_full211_incl0905"]["n"] == 151 + 75 - 2
    assert set(res["nl_separate"]["ids"]) == set(nl)
    _write_exclusions(root, [], q3)                                   # no NL case at all is a valid outcome
    res0, _ = A.resolve_all(root, strict=True)
    assert res0["nl_separate"]["n"] == 0 and res0["main"]["n"] == 80 + 71 - 2
    ws = set(res["well_specified"]["ids"])
    assert ws <= main and not ws & lists[A.UNDERSPEC]["ids"]


def test_definitions_negative_cases(tmp_path, id_sets):
    root = _copy_tree(tmp_path)
    _write_exclusions(root, [], [])
    defs = A.load_set_defs(None, root)
    lists = A.load_named_lists(id_sets, root)
    # main built from the set that still has the viewed cases -> must_exclude fails
    bad = copy.deepcopy(defs)
    bad["sets"]["main"]["terms"][0]["set"] = "mamo_main_clean111"
    with pytest.raises(A.DefinitionError, match=A.SEEN):
        A.resolve_sets(bad, id_sets, lists)
    # a viewed case added to main through a list -> must_exclude fails
    bad = copy.deepcopy(defs)
    bad["sets"]["main"]["terms"].append({"set": "industryor_main_rev2026_100", "only": [A.SEEN]})
    with pytest.raises(A.DefinitionError, match=A.SEEN):
        A.resolve_sets(bad, id_sets, lists)
    # a wrong expected count
    bad = copy.deepcopy(defs)
    bad["sets"]["dev_signal55"]["expect"]["n"] = 54
    with pytest.raises(A.DefinitionError, match="expected 54"):
        A.resolve_sets(bad, id_sets, lists)
    # a relation that does not hold
    bad = copy.deepcopy(defs)
    bad["sets"]["sens_incl0905"]["relations"][0]["difference_within"] = []
    with pytest.raises(A.DefinitionError, match="must lie in"):
        A.resolve_sets(bad, id_sets, lists)
    # unknown names and self-reference
    bad = copy.deepcopy(defs)
    bad["sets"]["main"]["terms"][0]["minus"] = ["no_such_list"]
    with pytest.raises(A.DefinitionError, match="unknown"):
        A.resolve_sets(bad, id_sets, lists)
    bad = copy.deepcopy(defs)
    bad["sets"]["main"]["terms"] = [{"def": "main"}]
    with pytest.raises(A.DefinitionError, match="itself"):
        A.resolve_sets(bad, id_sets, lists)


def test_definitions_refuse_a_different_id_set_file(tmp_path):
    root = _copy_tree(tmp_path)
    p = os.path.join(root, A.ID_SETS_PATH)
    with open(p, "a") as f:
        f.write("\n")
    with pytest.raises(A.DefinitionError, match="sha256"):
        A.load_set_defs(None, root)


def test_pending_list_status_is_propagated(tmp_path, id_sets):
    root = _copy_tree(tmp_path)
    _write_exclusions(root, [], [], status="pending")
    res, _ = A.resolve_all(root, strict=False)
    assert res["well_specified"]["pending"] == [A.NL, A.Q3]            # through its "def": "main" term
    assert res["dev_all85"]["pending"] == []
    with pytest.raises(A.PendingError):
        A.resolve_all(root, strict=True)

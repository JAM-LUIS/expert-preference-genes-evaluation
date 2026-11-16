"""Neutral case headers and SPLIT_LOCKs (relative paths; case records and split ids byte-identical to v5).

Function tests use self-made two-line case files. The working-tree checks compare hashes only (no case text is
printed on failure); the comparison with the v5 originals runs only where PROVENANCE/v5_pristine exists.
"""
import hashlib
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import data as D  # noqa: E402
from orgene import split as S  # noqa: E402
from orgene.paths import find_absolute_paths  # noqa: E402

PRISTINE = os.path.join(ROOT, "PROVENANCE", "v5_pristine")
SOURCES = ("mamo_complex_lp", "industryor")
FAKE_ABS = "/" + "Users" + "/someone/v5/data/raw/toy.jsonl"


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _toy_cases(path, raw_path=FAKE_ABS):
    header = {"_header": True, "source": "toy", "raw_path": raw_path, "n": 2, "n_reference_numeric": 2,
              "question_key": "q", "answer_key": "a", "id_key": None}
    rows = [{"case_id": f"toy-{i:04d}", "source": "toy", "source_id": str(i), "text": f"maximise {i}x subject to x <= 1 (é)",
             "reference": {"objective": float(i), "raw": str(i), "status": None}, "extra": {}, "license": "CC0"} for i in (1, 2)]
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------ functions on self-made files


def test_neutralize_cases_changes_only_the_header_raw_path(tmp_path):
    src, out = tmp_path / "toy.jsonl", tmp_path / "toy.neutral.jsonl"
    _toy_cases(src)
    info = D.neutralize_cases(str(src), str(out), "data/raw/toy.jsonl")
    a, b = src.read_bytes(), out.read_bytes()
    assert a.split(b"\n", 1)[1] == b.split(b"\n", 1)[1]
    assert info["lines2plus_sha256"] == _sha(a.split(b"\n", 1)[1]) and info["out_sha256"] == _sha(b)
    ha, hb = json.loads(a.split(b"\n", 1)[0]), json.loads(b.split(b"\n", 1)[0])
    assert hb["raw_path"] == "data/raw/toy.jsonl" and info["raw_path_was_absolute"] is True
    assert list(ha) == list(hb) and {k: v for k, v in ha.items() if k != "raw_path"} == {k: v for k, v in hb.items() if k != "raw_path"}
    assert D.load_cases(str(src)) == D.load_cases(str(out))
    assert not find_absolute_paths(b.decode("utf-8"))


def test_neutralize_cases_refuses_bad_input(tmp_path):
    src = tmp_path / "toy.jsonl"
    _toy_cases(src)
    with pytest.raises(ValueError):
        D.neutralize_cases(str(src), str(tmp_path / "o.jsonl"), FAKE_ABS)  # still absolute
    odd = tmp_path / "odd.jsonl"
    lines = src.read_text(encoding="utf-8").split("\n", 1)
    odd.write_text(json.dumps(json.loads(lines[0]), indent=1).replace("\n", " ") + "\n" + lines[1], encoding="utf-8")
    with pytest.raises(ValueError):
        D.neutralize_cases(str(odd), str(tmp_path / "o2.jsonl"), "data/raw/toy.jsonl")  # non-canonical header
    nohead = tmp_path / "nohead.jsonl"
    nohead.write_text(lines[1], encoding="utf-8")
    with pytest.raises(ValueError):
        D.neutralize_cases(str(nohead), str(tmp_path / "o3.jsonl"), "data/raw/toy.jsonl")


def test_neutralize_split_lock_keeps_ids_and_their_hashes(tmp_path):
    src = tmp_path / "toy.jsonl"
    _toy_cases(src)
    split_dir = tmp_path / "splits"
    info0 = S.make_split(str(src), str(split_dir), n_dev=1, seed=7)
    assert info0["cases_path"] == "<outside-root>/toy.jsonl"
    neutral = tmp_path / "toy.neutral.jsonl"
    D.neutralize_cases(str(src), str(neutral), "data/cases/toy.jsonl")
    before = (split_dir / "SPLIT_LOCK.json").read_text()
    out = tmp_path / "SPLIT_LOCK.neutral.json"
    info = S.neutralize_split_lock(str(split_dir / "SPLIT_LOCK.json"), str(out), "data/cases/toy.jsonl", cases_file=str(neutral))
    a, b = json.loads(before), json.loads(out.read_text())
    assert list(a) == list(b)
    assert b["cases_path"] == "data/cases/toy.jsonl" and b["cases_sha256"] == _sha(neutral.read_bytes())
    assert {k: v for k, v in a.items() if k not in ("cases_path", "cases_sha256")} == \
           {k: v for k, v in b.items() if k not in ("cases_path", "cases_sha256")}
    assert info["dev_sha256"] == a["dev_sha256"] and info["test_sha256"] == a["test_sha256"]
    assert out.read_text() == json.dumps(b, indent=2)
    # negative: an id file that no longer matches its lock hash is refused
    (split_dir / "dev_ids.json").write_text(json.dumps(["toy-0009"]))
    with pytest.raises(ValueError):
        S.neutralize_split_lock(str(split_dir / "SPLIT_LOCK.json"), str(tmp_path / "x.json"), "data/cases/toy.jsonl",
                                cases_file=str(neutral))
    with pytest.raises(ValueError):
        S.neutralize_split_lock(str(split_dir / "SPLIT_LOCK.json"), str(tmp_path / "y.json"), FAKE_ABS, cases_file=str(neutral))


# ------------------------------------------------------------------ the R1 working tree (hashes only)


def _lines2plus_sha(path):
    data = open(path, "rb").read()
    return _sha(data[data.find(b"\n") + 1:])


@pytest.mark.parametrize("source", SOURCES)
def test_working_split_lock_is_relative_and_consistent(source):
    d = os.path.join(ROOT, "data", "splits", source)
    lock = json.load(open(os.path.join(d, "SPLIT_LOCK.json"), encoding="utf-8"))
    assert not os.path.isabs(lock["cases_path"])
    assert lock["cases_path"] == f"data/cases/{source}.jsonl"
    cases = os.path.join(ROOT, lock["cases_path"])
    assert _sha(open(cases, "rb").read()) == lock["cases_sha256"]
    for which in ("dev", "test"):
        ids = json.load(open(os.path.join(d, f"{which}_ids.json"), encoding="utf-8"))
        assert S.ids_sha256(ids) == lock[f"{which}_sha256"]


@pytest.mark.parametrize("source", SOURCES + ("smoke",))
def test_working_case_headers_are_relative(source):
    path = os.path.join(ROOT, "data", "cases", f"{source}.jsonl")
    with open(path, "rb") as f:
        head = json.loads(f.readline())
    assert head.get("_header") is True
    assert not os.path.isabs(head["raw_path"]) and head["raw_path"].startswith("data/")
    assert not find_absolute_paths(json.dumps(head, ensure_ascii=False))


def test_working_smoke_cases_equal_a_fresh_build(tmp_path):
    out = tmp_path / "smoke.jsonl"
    D.build_cases("smoke", os.path.join(ROOT, "data", "smoke", "smoke_raw.jsonl"), str(out))
    assert _sha(out.read_bytes()) == _sha(open(os.path.join(ROOT, "data", "cases", "smoke.jsonl"), "rb").read())


@pytest.mark.skipif(not os.path.isdir(PRISTINE), reason="PROVENANCE/v5_pristine is not in the anonymous repository")
@pytest.mark.parametrize("source", SOURCES + ("smoke",))
def test_case_records_are_byte_identical_to_v5(source):
    a = _lines2plus_sha(os.path.join(PRISTINE, "data", "cases", f"{source}.jsonl"))
    b = _lines2plus_sha(os.path.join(ROOT, "data", "cases", f"{source}.jsonl"))
    assert a == b


@pytest.mark.skipif(not os.path.isdir(PRISTINE), reason="PROVENANCE/v5_pristine is not in the anonymous repository")
@pytest.mark.parametrize("source", SOURCES)
def test_split_ids_are_byte_identical_to_v5(source):
    for which in ("dev", "test"):
        a = _sha(open(os.path.join(PRISTINE, "data", "splits", source, f"{which}_ids.json"), "rb").read())
        b = _sha(open(os.path.join(ROOT, "data", "splits", source, f"{which}_ids.json"), "rb").read())
        assert a == b
    va = json.load(open(os.path.join(PRISTINE, "data", "splits", source, "SPLIT_LOCK.json"), encoding="utf-8"))
    vb = json.load(open(os.path.join(ROOT, "data", "splits", source, "SPLIT_LOCK.json"), encoding="utf-8"))
    assert {k: v for k, v in va.items() if k not in ("cases_path", "cases_sha256")} == \
           {k: v for k, v in vb.items() if k not in ("cases_path", "cases_sha256")}

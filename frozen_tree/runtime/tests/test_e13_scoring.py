"""E13: three tolerance tiers (absolute = relative) and reference overrides scored by the R1-D5 rule.

Fixtures are self-made toy cases only (source "toy"); no benchmark case is read, except that override files checked
into data/reference_overrides/ are validated against their cases file by hash and reference value (no text printed).
"""
import copy
import hashlib
import json
import math
import os
import random
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import cli  # noqa: E402
from orgene import data as D  # noqa: E402
from orgene import pipeline as P  # noqa: E402
from orgene import refs as R  # noqa: E402
from orgene.conditions import read_jsonl, write_jsonl  # noqa: E402
from orgene.score import PRIMARY_TOL, TOLERANCES, correct_by_tol, is_correct, tol_key  # noqa: E402

EV = hashlib.sha256(b"toy evidence").hexdigest()
# the scoring rule as frozen for R1 (R1-D5); a change of SCORING_RULES must be deliberate and update this digest
# (3bb2fccc... until 2026-09-29, when the category rule for non-numeric references was added: test_status_categories.py;
# b19ad9f9... until the engineering-source cases were merged on 2026-10-05, which added the reference_kind block, E22)
RULES_SHA256 = "8c14104e40fcf83cbfe8de58c05aac48c569b58c1daaecedebc09cb09e838b0b"

# toy references: case -> stored reference (objective, status)
TOY = {
    "toy-0001": (100.0, None),     # CORRECT
    "toy-0002": (1235.0, None),    # CORRECT_ROUNDED -> 1234.56
    "toy-0003": (50.0, None),      # INCORRECT -> 75
    "toy-0004": (20.0, None),      # INCORRECT -> infeasible
    "toy-0005": (10.0, None),      # AMBIGUOUS
    "toy-0006": (30.0, None),      # UNDERSPECIFIED
    "toy-0007": (40.0, None),      # not checked
    "toy-0008": (None, "infeasible"),  # not checked, non-numeric reference
}


def _write_toy_cases(path, source="toy", extra_blank_line=False):
    header = {"_header": True, "source": source, "raw_path": "data/raw/toy.jsonl", "n": len(TOY),
              "n_reference_numeric": 7, "question_key": "q", "answer_key": "a", "id_key": None}
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for cid, (obj, st) in TOY.items():
            raw = "infeasible" if st else str(obj)
            rec = {"case_id": cid.replace("toy", source), "source": source, "source_id": cid[-4:],
                   "text": f"self-made toy case {cid}", "reference": {"objective": obj, "raw": raw, "status": st},
                   "extra": {}, "license": "CC0"}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if extra_blank_line:
            f.write("\n")
    return str(path)


def _entry(cid, orig, new, verdict, checkers=("A", "B"), **kw):
    e = {"case_id": cid, "original_value": orig, "new_value": new, "verdict": verdict, "checkers": list(checkers),
         "method": "independent_agreement", "adjudicator": "", "date": "2026-10-01", "evidence_sha256": EV}
    e.update(kw)
    return e


def _entries():
    return [
        _entry("toy-0001", 100.0, 100.00001, "CORRECT", checkers=["A"], method="single_check_correct"),
        _entry("toy-0002", 1235.0, 1234.56, "CORRECT_ROUNDED"),
        _entry("toy-0003", 50.0, 75.0, "INCORRECT", checkers=["A", "B", "C"], method="adjudication", adjudicator="C"),
        _entry("toy-0004", 20.0, "infeasible", "INCORRECT"),
        _entry("toy-0005", 10.0, 12.0, "AMBIGUOUS"),
        _entry("toy-0006", 30.0, None, "UNDERSPECIFIED", method="discussion"),
    ]


@pytest.fixture
def toy(tmp_path):
    cases = _write_toy_cases(tmp_path / "toy.jsonl")
    doc = R.build_overrides_doc("toy", cases, _entries())
    ov_path = str(tmp_path / "toy.overrides.json")
    sha = R.write_overrides(doc, ov_path)
    return {"cases": cases, "ov": ov_path, "sha": sha, "doc": doc, "tmp": tmp_path}


# ------------------------------------------------------------------ tolerance tiers


def test_tiers_and_keys():
    assert [tol_key(t) for t in TOLERANCES] == ["1e-06", "0.0001", "0.01"]
    assert PRIMARY_TOL == 1e-4 and PRIMARY_TOL in TOLERANCES


@pytest.mark.parametrize("t", TOLERANCES)
@pytest.mark.parametrize("ref", [0.0, 1e6, -1e6])
@pytest.mark.parametrize("sign", [1, -1])
def test_difference_equal_to_tolerance_is_correct_and_slightly_larger_is_not(t, ref, sign):
    tol = max(t, t * abs(ref))
    obj = ref + sign * tol
    assert abs(obj - ref) == tol  # the boundary is exact in binary floating point for these values
    assert is_correct(obj, ref, tol=t) == (True, "match")
    assert correct_by_tol(obj, ref)[tol_key(t)] is True
    over = math.nextafter(obj, sign * math.inf)
    assert abs(over - ref) > tol
    assert is_correct(over, ref, tol=t) == (False, "objective_mismatch")
    assert correct_by_tol(over, ref)[tol_key(t)] is False
    # tiers below t reject the boundary value of tier t
    for lower in (x for x in TOLERANCES if x < t):
        assert correct_by_tol(obj, ref)[tol_key(lower)] is False


def test_absolute_tolerance_decides_near_zero():
    # |ref| < 1: max(t, t*|ref|) = t, the absolute part; the relative part alone would reject these
    assert is_correct(0.508, 0.5, tol=1e-2)[0]
    assert not is_correct(0.508, 0.5, rel_tol=1e-2, abs_tol=0.0)[0]
    assert is_correct(5e-5, 0.0, tol=1e-4)[0]
    assert not is_correct(5e-5, 0.0, rel_tol=1e-4, abs_tol=0.0)[0]
    assert correct_by_tol(5e-5, 0.0) == {"1e-06": False, "0.0001": True, "0.01": True}


def test_relative_tolerance_decides_for_large_references():
    # |ref| > 1: max(t, t*|ref|) = t*|ref|, the relative part; the absolute part alone would reject these
    assert is_correct(1e6 + 50, 1e6, tol=1e-4)[0]
    assert not is_correct(1e6 + 50, 1e6, rel_tol=0.0, abs_tol=1e-4)[0]
    assert correct_by_tol(1e6 + 50, 1e6) == {"1e-06": False, "0.0001": True, "0.01": True}
    assert correct_by_tol(-1e6 - 0.5, -1e6) == {"1e-06": True, "0.0001": True, "0.01": True}


def test_tol_sets_absolute_and_relative_to_the_same_value_and_default_is_primary():
    rng = random.Random(20260928)
    for _ in range(3000):
        ref = rng.choice([0.0, rng.uniform(-2, 2), rng.uniform(-1e7, 1e7)])
        obj = ref + rng.choice([-1, 1]) * abs(ref or 1) * 10 ** rng.uniform(-8, -1)
        tiers = correct_by_tol(obj, ref)
        for t in TOLERANCES:
            assert is_correct(obj, ref, tol=t) == is_correct(obj, ref, rel_tol=t, abs_tol=t)
        # v5 behaviour unchanged: the default is the primary tier
        assert is_correct(obj, ref) == is_correct(obj, ref, tol=PRIMARY_TOL)
        assert tiers["0.0001"] == is_correct(obj, ref)[0]
        # nested tiers: correct at a tighter tier implies correct at a looser one
        assert (not tiers["1e-06"] or tiers["0.0001"]) and (not tiers["0.0001"] or tiers["0.01"])


def test_non_numeric_cases_are_the_same_at_every_tier():
    assert set(correct_by_tol(None, None, "infeasible", status="Infeasible").values()) == {True}
    assert set(correct_by_tol(None, None, "infeasible", status="Optimal").values()) == {False}
    assert set(correct_by_tol(None, 5.0).values()) == {False}
    assert set(correct_by_tol(float("nan"), 5.0).values()) == {False}
    assert set(correct_by_tol(5.0, None, None, status="Optimal").values()) == {False}


# ------------------------------------------------------------------ override file: rule applied at load time


def test_load_cases_without_overrides_is_unchanged(toy):
    stored = [json.loads(l) for l in open(toy["cases"], encoding="utf-8") if l.strip()][1:]
    assert D.load_cases(toy["cases"]) == stored
    assert D.load_cases(toy["cases"], ids={"toy-0002"}) == [stored[1]]


def test_override_rule_by_verdict_and_original_kept(toy):
    cases = {c["case_id"]: c for c in D.load_cases(toy["cases"], overrides=toy["ov"])}
    ver = f"override@{toy['sha'][:16]}"
    expect = {  # case: (effective objective, effective status, verdict, main_eligible, version)
        "toy-0001": (100.0, None, "CORRECT", True, "original"),          # CORRECT keeps the original, not 100.00001
        "toy-0002": (1234.56, None, "CORRECT_ROUNDED", True, ver),
        "toy-0003": (75.0, None, "INCORRECT", True, ver),
        "toy-0004": (None, "infeasible", "INCORRECT", True, ver),
        "toy-0005": (10.0, None, "AMBIGUOUS", False, "original"),
        "toy-0006": (30.0, None, "UNDERSPECIFIED", False, "original"),
        "toy-0007": (40.0, None, None, True, "original"),
        "toy-0008": (None, "infeasible", None, True, "original"),
    }
    for cid, (obj, st, verdict, main, version) in expect.items():
        ref = cases[cid]["reference"]
        assert (ref["objective"], ref["status"], ref["verdict"], ref["main_eligible"], ref["version"]) == (obj, st, verdict, main, version), cid
        # the stored value stays next to the effective one
        assert (ref["original_objective"], ref["original_status"]) == TOY[cid], cid
        assert ref["raw"] == ("infeasible" if TOY[cid][1] else str(TOY[cid][0]))
        assert ref["overrides_file"]["sha256"] == toy["sha"] and ref["overrides_file"]["mode"] == "path"
    # the text and every other field are untouched
    plain = {c["case_id"]: c for c in D.load_cases(toy["cases"])}
    for cid in TOY:
        assert {k: v for k, v in cases[cid].items() if k != "reference"} == {k: v for k, v in plain[cid].items() if k != "reference"}
    assert R.main_excluded_ids(R.load_overrides(toy["ov"])) == ["toy-0005", "toy-0006"]


def test_overrides_none_annotates_with_original_values(toy):
    for c in D.load_cases(toy["cases"], overrides="none"):
        ref = c["reference"]
        assert (ref["objective"], ref["status"]) == TOY[c["case_id"]] == (ref["original_objective"], ref["original_status"])
        assert ref["version"] == "original" and ref["verdict"] is None and ref["main_eligible"] is True
        assert ref["overrides_file"]["mode"] == "none" and ref["overrides_file"]["path"] is None


def test_auto_mode_uses_the_source_file_only_when_present(toy, monkeypatch, tmp_path):
    d = tmp_path / "overrides_dir"
    d.mkdir()
    monkeypatch.setattr(R, "OVERRIDES_DIR", str(d))
    cases = D.load_cases(toy["cases"], overrides="auto")
    assert {c["reference"]["version"] for c in cases} == {"original"}
    assert cases[0]["reference"]["overrides_file"]["mode"] == "auto" and cases[0]["reference"]["overrides_file"]["path"] is None
    with pytest.raises(R.OverrideIntegrityError):  # pinned by hash but absent
        D.load_cases(toy["cases"], overrides="auto", overrides_sha256=toy["sha"])
    (d / "toy.json").write_bytes(open(toy["ov"], "rb").read())
    cases = {c["case_id"]: c for c in D.load_cases(toy["cases"], overrides="auto")}
    assert cases["toy-0003"]["reference"]["objective"] == 75.0
    assert cases["toy-0003"]["reference"]["overrides_file"]["path"] == "<outside-root>/toy.json"


# ------------------------------------------------------------------ scoring: rows and metrics


def _final(run, cond, outcomes):
    rows = []
    for cid, (obj, status) in outcomes.items():
        rows.append({"case_id": cid, "repeat": 0, "condition": cond, "round": 0,
                     "exec": {"exec_ok": True, "protocol_ok": True, "objective": obj, "status": status, "seconds": 0.1},
                     "hard_failed_genes": [], "soft_failed_genes": [], "out_tokens": 10, "in_tokens": 20,
                     "rounds": [{"round": 0, "out_tokens": 10, "in_tokens": 20, "hard_failed_genes": [], "soft_failed_genes": [],
                                 "exec_ok": True, "decision": "accepted"}], "provisional": False})
    write_jsonl(os.path.join(run, f"final.{cond}.jsonl"), rows)


OUTCOMES = {  # printed (objective, status) per toy case
    "toy-0001": (100.0, "Optimal"),
    "toy-0002": (1234.56, "Optimal"),     # right against the exact value, wrong against the rounded original
    "toy-0003": (50.0, "Optimal"),        # right only against the (wrong) original
    "toy-0004": (None, "Infeasible"),     # right against the corrected "infeasible"
    "toy-0005": (10.0, "Optimal"),
    "toy-0006": (31.0, "Optimal"),
    "toy-0007": (40.2, "Optimal"),        # |diff| 0.2: wrong at 1e-6 and 1e-4 (tol 0.004), right at 1e-2 (tol 0.4)
    "toy-0008": (None, "Infeasible"),
}


def test_score_condition_rows_and_metrics(toy):
    run = str(toy["tmp"] / "run")
    os.makedirs(run)
    _final(run, "C0", OUTCOMES)
    cases = {c["case_id"]: c for c in D.load_cases(toy["cases"], overrides=toy["ov"])}
    m = P.score_condition(run, "C0", cases)
    rows = {r["case_id"]: r for r in read_jsonl(os.path.join(run, "results.C0.jsonl"))}
    expect = {  # case: (correct, correct_original_ref, correct_tol 1e-6 / 1e-4 / 1e-2)
        "toy-0001": (True, True, (True, True, True)),
        "toy-0002": (True, False, (True, True, True)),
        "toy-0003": (False, True, (False, False, False)),
        "toy-0004": (True, False, (True, True, True)),
        "toy-0005": (True, True, (True, True, True)),
        "toy-0006": (False, False, (False, False, False)),
        "toy-0007": (False, False, (False, False, True)),
        "toy-0008": (True, True, (True, True, True)),
    }
    for cid, (c, co, tiers) in expect.items():
        r = rows[cid]
        assert (r["correct"], r["correct_original_ref"]) == (c, co), cid
        assert tuple(r["correct_tol"][k] for k in ("1e-06", "0.0001", "0.01")) == tiers, cid
        assert r["correct"] == r["correct_tol"]["0.0001"]  # `correct` is the primary tier
        assert r["reference_objective"] == cases[cid]["reference"]["objective"]
        assert (r["reference_original_objective"], r["reference_original_status"]) == TOY[cid]
    assert rows["toy-0002"]["reference_version"] == f"override@{toy['sha'][:16]}"
    assert rows["toy-0007"]["reference_version"] == "original" and rows["toy-0007"]["reference_verdict"] is None
    assert [cid for cid, r in sorted(rows.items()) if not r["reference_main_eligible"]] == ["toy-0005", "toy-0006"]
    assert m["n_correct"] == 5 and m["n_correct_original_ref"] == 4
    assert m["n_correct_by_tol"] == {"1e-06": 5, "0.0001": 5, "0.01": 6}
    assert m["accuracy_by_tol"]["0.01"] == round(6 / 8, 4) and m["tolerance_tiers"] == ["1e-06", "0.0001", "0.01"]
    ref = m["reference"]
    assert ref["n_overridden"] == 3 and ref["n_main_excluded"] == 2 and ref["rules_sha256"] == R.rules_sha256()
    assert ref["verdict_counts"] == {"AMBIGUOUS": 1, "CORRECT": 1, "CORRECT_ROUNDED": 1, "INCORRECT": 2,
                                     "NOT_CHECKED": 2, "UNDERSPECIFIED": 1}
    assert [f["sha256"] for f in ref["overrides_files"]] == [toy["sha"]]
    assert m["by_source"]["toy"]["n_correct_by_tol"] == m["n_correct_by_tol"]
    assert json.load(open(os.path.join(run, "metrics.C0.json")))["accuracy_original_ref"] == 0.5


def test_score_condition_on_plain_cases_keeps_v5_fields(toy):
    run = str(toy["tmp"] / "run_plain")
    os.makedirs(run)
    _final(run, "C0", OUTCOMES)
    m = P.score_condition(run, "C0", {c["case_id"]: c for c in D.load_cases(toy["cases"])})
    for r in read_jsonl(os.path.join(run, "results.C0.jsonl")):
        assert r["reference_version"] == "original" and r["reference_verdict"] is None and r["reference_main_eligible"] is True
        assert r["correct_original_ref"] == r["correct"] == r["correct_tol"]["0.0001"]
        assert r["reference_objective"] == TOY[r["case_id"]][0]
    assert m["n_correct"] == m["n_correct_original_ref"] == 4
    assert m["tolerance"] == {"rel": 1e-4, "abs": 1e-4} and m["reference"]["overrides_files"] == []


# ------------------------------------------------------------------ integrity: frozen hash / freeze manifest


def test_hash_mismatch_refuses(toy):
    wrong = "0" * 64
    with pytest.raises(R.OverrideIntegrityError):
        R.load_overrides(toy["ov"], expected_sha256=wrong)
    with pytest.raises(R.OverrideIntegrityError):
        D.load_cases(toy["cases"], overrides=toy["ov"], overrides_sha256=wrong)
    assert R.load_overrides(toy["ov"], expected_sha256=toy["sha"])["integrity_check"] == "expected_sha256"
    # one changed byte (still valid JSON) is caught by the hash
    tampered = toy["tmp"] / "tampered.json"
    tampered.write_bytes(open(toy["ov"], "rb").read().replace(b"1234.56", b"1234.57"))
    with pytest.raises(R.OverrideIntegrityError):
        R.load_overrides(str(tampered), expected_sha256=toy["sha"])


def _manifest(path, files):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"files": files}, f)
    return str(path)


def test_freeze_manifest_gates_scoring(toy, monkeypatch, tmp_path):
    d = tmp_path / "ovdir"
    d.mkdir()
    monkeypatch.setattr(R, "OVERRIDES_DIR", str(d))
    target = str(d / "toy.json")
    with open(target, "wb") as f:
        f.write(open(toy["ov"], "rb").read())
    key = R.manifest_key(target)
    good = _manifest(tmp_path / "good.json", {key: toy["sha"]})
    cases = R.load_scoring_cases(toy["cases"], freeze_manifest=good)
    fi = cases[0]["reference"]["overrides_file"]
    assert fi["integrity_check"].startswith("freeze_manifest:") and fi["sha256"] == toy["sha"] and fi["mode"] == "auto"
    # list shape and {"sha256": ...} values are accepted as well
    assert R.load_scoring_cases(toy["cases"], freeze_manifest=_manifest(tmp_path / "l.json", [{"path": key, "sha256": toy["sha"]}]))
    assert R.load_scoring_cases(toy["cases"], freeze_manifest=_manifest(tmp_path / "d.json", {key: {"sha256": toy["sha"]}}))
    with pytest.raises(R.OverrideIntegrityError):  # hash differs from the manifest
        R.load_scoring_cases(toy["cases"], freeze_manifest=_manifest(tmp_path / "bad.json", {key: "f" * 64}))
    with pytest.raises(R.OverrideIntegrityError):  # file in use but not frozen
        R.load_scoring_cases(toy["cases"], freeze_manifest=_manifest(tmp_path / "other.json", {"data/x.json": toy["sha"]}))
    with pytest.raises(R.OverrideIntegrityError):  # --overrides-sha256 contradicts the manifest
        R.load_scoring_cases(toy["cases"], freeze_manifest=good, expected_sha256="e" * 64)
    os.remove(target)
    with pytest.raises(R.OverrideIntegrityError):  # frozen but missing
        R.load_scoring_cases(toy["cases"], freeze_manifest=good)
    # explicit original-reference scoring reads no file and is allowed
    assert {c["reference"]["version"] for c in R.load_scoring_cases(toy["cases"], overrides="none", freeze_manifest=good)} == {"original"}


def test_cli_score_refuses_on_manifest_mismatch_and_writes_nothing(toy, tmp_path, capsys):
    run = str(tmp_path / "run_cli")
    os.makedirs(run)
    _final(run, "C0", OUTCOMES)
    bad = _manifest(tmp_path / "bad.json", {R.manifest_key(toy["ov"]): "a" * 64})
    with pytest.raises(SystemExit) as ei:
        cli.main(["score", "--run", run, "--cases", toy["cases"], "--cond", "C0", "--overrides", toy["ov"], "--freeze-manifest", bad])
    assert ei.value.code not in (0, None) and "refused" in str(ei.value.code)
    assert not os.path.exists(os.path.join(run, "results.C0.jsonl")) and not os.path.exists(os.path.join(run, "metrics.C0.json"))
    with pytest.raises(SystemExit):
        cli.main(["score", "--run", run, "--cases", toy["cases"], "--cond", "C0", "--overrides", toy["ov"], "--overrides-sha256", "b" * 64])
    assert not os.path.exists(os.path.join(run, "results.C0.jsonl"))
    good = _manifest(tmp_path / "good.json", {R.manifest_key(toy["ov"]): toy["sha"]})
    cli.main(["score", "--run", run, "--cases", toy["cases"], "--cond", "C0", "--overrides", toy["ov"], "--freeze-manifest", good])
    rows = read_jsonl(os.path.join(run, "results.C0.jsonl"))
    assert sum(r["correct"] for r in rows) == 5 and sum(r["correct_original_ref"] for r in rows) == 4
    err = capsys.readouterr().err
    assert "check freeze_manifest:" in err and toy["sha"][:16] in err


# ------------------------------------------------------------------ validation (negative cases)


def _mutated(i, **changes):
    es = copy.deepcopy(_entries())
    es[i].update(changes)
    return es


BAD_ENTRY_SETS = {
    "rounded_but_within_tolerance": _mutated(1, new_value=1235.0001),
    "incorrect_but_within_tolerance": _mutated(2, new_value=50.000001),
    "incorrect_single_checker": _mutated(3, checkers=["A"], method=None),
    "incorrect_single_check_method": _mutated(3, method="single_check_correct"),
    "correct_with_value_outside_tolerance": _mutated(0, new_value=101.0),
    "rounded_to_status_word": _mutated(1, new_value="infeasible"),
    "replacing_without_new_value": _mutated(2, new_value=None),
    "unknown_verdict": _mutated(0, verdict="WRONG"),
    "free_text_field": _mutated(0, note="free text is not allowed"),
    "missing_date": [{k: v for k, v in e.items() if k != "date"} for e in _entries()],
    "bad_date": _mutated(0, date="2026-13-01"),
    "bad_evidence_hash": _mutated(0, evidence_sha256="xyz"),
    "boolean_value": _mutated(1, new_value=True),
    "nan_value": _mutated(1, new_value=float("nan")),
    "string_number": _mutated(1, new_value="1234.56"),
    "checker_name_not_code": _mutated(1, checkers=["Alice", "B"]),
    "duplicate_checker": _mutated(1, checkers=["A", "A"]),
    "adjudication_without_adjudicator": _mutated(2, adjudicator=""),
    "unknown_method": _mutated(1, method="vote"),
    "duplicate_case": _entries() + [_entry("toy-0002", 1235.0, 1234.56, "CORRECT_ROUNDED")],
    "case_not_in_cases_file": _entries() + [_entry("toy-0099", 1.0, 2.0, "INCORRECT")],
    "other_source_case_id": _entries() + [_entry("industryor-0000", 1.0, 2.0, "INCORRECT")],
    "original_does_not_match_cases_file": _mutated(0, original_value=101.0),
    "original_status_does_not_match": _entries() + [_entry("toy-0008", 5.0, 6.0, "INCORRECT")],
}


@pytest.mark.parametrize("name", sorted(BAD_ENTRY_SETS))
def test_invalid_entries_are_rejected(name, tmp_path):
    cases = _write_toy_cases(tmp_path / "toy.jsonl")
    with pytest.raises(R.OverrideError):
        R.build_overrides_doc("toy", cases, BAD_ENTRY_SETS[name])


def test_file_level_checks(toy):
    doc = toy["doc"]
    bad_docs = {
        "rules": dict(doc, rules_sha256="0" * 64),
        "schema": dict(doc, schema="orgene.reference_overrides.v0"),
        "extra_key": dict(doc, comment="x"),
        "entries_not_list": dict(doc, entries={}),
    }
    for name, d in bad_docs.items():
        p = toy["tmp"] / f"{name}.json"
        p.write_bytes(R.dumps_overrides(d))
        with pytest.raises(R.OverrideError):
            R.load_overrides(str(p))
    p = toy["tmp"] / "notjson.json"
    p.write_bytes(b"{not json")
    with pytest.raises(R.OverrideError):
        R.load_overrides(str(p))
    # written against another version of the cases file (same records, different bytes)
    other = _write_toy_cases(toy["tmp"] / "toy_v2.jsonl", extra_blank_line=True)
    with pytest.raises(R.OverrideError):
        D.load_cases(other, overrides=toy["ov"])
    # applied to another source
    other_src = _write_toy_cases(toy["tmp"] / "toy2.jsonl", source="toyb")
    with pytest.raises(R.OverrideError):
        D.load_cases(other_src, overrides=toy["ov"])


def test_error_messages_do_not_echo_cell_contents(tmp_path):
    cases = _write_toy_cases(tmp_path / "toy.jsonl")
    secret = "SECRET-PROBLEM-TEXT"
    for es in (_mutated(0, note=secret), _mutated(0, verdict=secret), _mutated(0, checkers=[secret]),
               _mutated(0, new_value=secret), _mutated(0, date=secret), _mutated(0, case_id=secret),
               _mutated(0, method=secret), _mutated(2, adjudicator=secret)):
        with pytest.raises(R.OverrideError) as ei:
            R.build_overrides_doc("toy", cases, es)
        assert secret not in str(ei.value)


# ------------------------------------------------------------------ writing, digest, repository files


def test_written_file_is_canonical_and_order_independent(toy):
    shuffled = list(reversed(_entries()))
    doc2 = R.build_overrides_doc("toy", toy["cases"], shuffled)
    p2 = str(toy["tmp"] / "again.json")
    assert R.write_overrides(doc2, p2) == toy["sha"] == R.sha256_file(toy["ov"])
    assert open(p2, "rb").read() == R.dumps_overrides(toy["doc"])
    assert list(R.load_overrides(p2)["entries"]) == sorted(TOY)[:6]


def test_rules_digest_is_pinned():
    assert R.rules_sha256() == RULES_SHA256
    assert R.SCORING_RULES["reference_by_verdict"]["INCORRECT"]["reference"] == "new_value"
    assert [k for k, v in R.SCORING_RULES["reference_by_verdict"].items() if not v["main_analysis"]] == ["AMBIGUOUS", "UNDERSPECIFIED"]
    assert {k: v["judged"] for k, v in R.SCORING_RULES["reference_kind"].items()} == {
        "cbc_optimal": "point", "cbc_attains_published_optimum": "point", "cbc_time_limited": "interval"}  # E22


def test_override_files_in_the_repository_are_valid():
    d = os.path.join(ROOT, "data", "reference_overrides")
    files = sorted(f for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else []
    for fn in files:
        source = fn[:-5]
        cases_path = os.path.join(ROOT, "data", "cases", f"{source}.jsonl")
        if not os.path.exists(cases_path):
            pytest.skip(f"data/cases/{source}.jsonl missing")
        # the cases file holds test statements: report only the error message (case ids, no values), no traceback
        try:
            D.load_cases(cases_path, overrides=os.path.join(d, fn))
        except R.OverrideError as exc:
            pytest.fail(f"data/reference_overrides/{fn}: {exc}", pytrace=False)

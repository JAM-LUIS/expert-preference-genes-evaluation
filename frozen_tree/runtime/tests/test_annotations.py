"""E14 interface: type labels, reference-override entries (rule Q3, E13 file format) and R1 exclusions.

All sheets here are self-made: toy ids and made-up labels / values. The command-line tests run on the working tree
with dev ids only and --dry-run (nothing is written, nothing about test cases is printed). Tests that build override
files need runtime/orgene/refs.py (E13) and are skipped where it is not merged yet.
"""
import csv
import importlib.util
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import analysis_sets as A  # noqa: E402
from orgene import annotations as N  # noqa: E402

TYPE_COLS = ["case_id", "split", "final_label", "final_type_after_linearization", "method", "adjudicator", "note"]
REF_COLS = ["case_id", "benchmark", "split", "checker", "reference", "verdict_A", "value_A", "within_tol_A",
            "verdict_B", "value_B", "within_tol_B", "minutes_A", "minutes_B", "status",
            "final_verdict", "final_value", "method", "adjudicator"]


def _csv(path, cols, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return str(path)


def _ior(i):
    return f"industryor-{i:04d}"


def _mamo(i):
    return f"mamo_complex_lp-{i:04d}"


def _load_cli():
    spec = importlib.util.spec_from_file_location("ingest_annotations", os.path.join(ROOT, "data", "ingest_annotations.py"))
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


# ------------------------------------------------------------------ type labels


EXPECTED = {_ior(i): ("dev" if i <= 2 else "test") for i in range(1, 7)}


def _type_rows():
    return [
        # A and B agreed independently
        {"case_id": _ior(1), "final_label": "LP", "method": "independent_agreement"},
        {"case_id": _ior(2), "final_label": "NL_LINEARIZABLE", "final_type_after_linearization": "MILP",
         "method": "independent_agreement"},
        # A and B disagreed, not resolved yet
        {"case_id": _ior(3), "final_label": "", "note": "free text is never read"},
        # disagreement settled by a third person
        {"case_id": _ior(4), "final_label": "NL_NOT_LINEARIZABLE", "method": "third_party", "adjudicator": "C"},
        # settled by discussion
        {"case_id": _ior(5), "final_label": "IP", "method": "discussion"},
        # _ior(6) missing from the sheet
    ]


def test_type_labels_agreement_disagreement_and_adjudication(tmp_path):
    doc = N.ingest_type_labels(_csv(tmp_path / "t.csv", TYPE_COLS, _type_rows()), EXPECTED)
    assert doc["status"] == "pending" and doc["pending"] == [_ior(3), _ior(6)]
    assert doc["labels"][_ior(1)]["type"] == "LP" and doc["labels"][_ior(1)]["method"] == "independent_agreement"
    assert doc["labels"][_ior(2)]["effective_type"] == "MILP"
    assert doc["labels"][_ior(4)] == {"split": "test", "type": "NL_NOT_LINEARIZABLE", "type_after_linearization": None,
                                      "effective_type": "NL_NOT_LINEARIZABLE", "method": "third_party", "adjudicator": "C"}
    assert doc["nl_not_linearizable"] == [_ior(4)]
    assert doc["problems"] == [] and doc["counts"]["IP"] == 1
    with pytest.raises(N.AnnotationError, match="pending"):
        N.ingest_type_labels(str(tmp_path / "t.csv"), EXPECTED, strict=True)
    # once resolved, strict ingestion passes
    rows = _type_rows()
    rows[2].update(final_label="MILP", method="third_party", adjudicator="C")
    rows.append({"case_id": _ior(6), "final_label": "LP", "method": "independent_agreement"})
    doc = N.ingest_type_labels(_csv(tmp_path / "t2.csv", TYPE_COLS, rows), EXPECTED, strict=True)
    assert doc["status"] == "final" and doc["pending"] == []


def test_type_labels_invalid_cells_are_reported_without_content(tmp_path):
    rows = _type_rows()
    rows[0]["final_label"] = "LINEAR maybe (see statement: minimise cost of ...)"
    rows[1]["final_type_after_linearization"] = ""
    rows[3]["adjudicator"] = "Some Person"
    rows[4]["method"] = "coin_flip"
    rows.append({"case_id": "free text instead of an id", "final_label": "LP", "method": "independent_agreement"})
    doc = N.ingest_type_labels(_csv(tmp_path / "t.csv", TYPE_COLS, rows), EXPECTED)
    text = json.dumps(doc)
    assert "statement" not in text and "Some Person" not in text and "free text" not in text
    assert doc["invalid"] == [_ior(1), _ior(2), _ior(4), _ior(5)]
    assert any("not shown" in p for p in doc["problems"])
    assert _ior(4) not in doc["nl_not_linearizable"]            # an invalid row never enters a list


def test_type_labels_linear_unresolved_counts_as_linear(tmp_path):
    """PREREG_R1: a linear-class disagreement the objective check cannot settle is final as LINEAR_UNRESOLVED."""
    rows = _type_rows()
    rows[2].update(final_label="LINEAR_UNRESOLVED", method="independent_agreement")
    rows.append({"case_id": _ior(6), "final_label": "LP", "method": "independent_agreement"})
    doc = N.ingest_type_labels(_csv(tmp_path / "t.csv", TYPE_COLS, rows), EXPECTED, strict=True)
    assert doc["status"] == "final" and doc["pending"] == []
    assert doc["labels"][_ior(3)]["type"] == "LINEAR_UNRESOLVED" and doc["labels"][_ior(3)]["effective_type"] is None
    assert doc["linear_unresolved"] == [_ior(3)] and doc["nl_not_linearizable"] == [_ior(4)]
    assert doc["counts"]["LINEAR_UNRESOLVED"] == 1
    ex = N.build_exclusions(doc, None)
    assert ex["nl_not_linearizable"]["status"] == "final" and ex["nl_not_linearizable"]["ids"] == [_ior(4)]
    # only the batch comparison sets it: no adjudicator, no post-linearisation type
    for bad in ({"method": "third_party", "adjudicator": "C"}, {"final_type_after_linearization": "MILP"}):
        rows2 = [dict(r) for r in rows]
        rows2[2].update(bad)
        doc = N.ingest_type_labels(_csv(tmp_path / "t2.csv", TYPE_COLS, rows2), EXPECTED)
        assert doc["invalid"] == [_ior(3)] and doc["linear_unresolved"] == []


# ------------------------------------------------------------------ reference checks (rule Q3)


SAMPLE = {"rows": [
    {"case_id": _mamo(1), "benchmark": "mamo_complex_lp", "split": "dev", "checker": "A"},
    {"case_id": _mamo(2), "benchmark": "mamo_complex_lp", "split": "test", "checker": "B"},
    {"case_id": _mamo(3), "benchmark": "mamo_complex_lp", "split": "test", "checker": "A"},
    {"case_id": _ior(1), "benchmark": "industryor", "split": "dev", "checker": "A+B"},
    {"case_id": _ior(2), "benchmark": "industryor", "split": "test", "checker": "A+B"},
    {"case_id": _ior(3), "benchmark": "industryor", "split": "test", "checker": "B"},
    {"case_id": _ior(4), "benchmark": "industryor", "split": "test", "checker": "A"},
    {"case_id": _ior(5), "benchmark": "industryor", "split": "test", "checker": "A+B"},
]}
ORIGINALS = {_mamo(i): (100.0 * i, None) for i in range(1, 10)} | {_ior(i): (10.0 * i, None) for i in range(1, 10)}


def _ref_rows():
    two = {"verdict_A": "x", "verdict_B": "x"}          # both checked (the column content is not used)
    return [
        # single check, CORRECT -> entry kept for the record, original reference used
        {"case_id": _mamo(1), "checker": "A", "reference": "100.0", "verdict_A": "CORRECT", "final_verdict": "CORRECT",
         "final_value": "100", "method": "single_check_correct"},
        # first check by B, second check by A, both say the reference is a rounded value -> replace
        {"case_id": _mamo(2), "checker": "B", "reference": "200.0", **two, "final_verdict": "CORRECT_ROUNDED",
         "final_value": "200.4", "method": "independent_agreement"},
        # A and B disagreed, still open -> pending
        {"case_id": _mamo(3), "checker": "A", "reference": "300.0", **two, "final_verdict": ""},
        # INCORRECT settled by a third person -> replace
        {"case_id": _ior(1), "checker": "A+B", "reference": "10.0", **two, "final_verdict": "INCORRECT",
         "final_value": "12.5", "method": "third_party", "adjudicator": "C"},
        # INCORRECT, the true answer is infeasible
        {"case_id": _ior(2), "checker": "A+B", "reference": "20.0", **two, "final_verdict": "INCORRECT",
         "final_value": "infeasible", "method": "independent_agreement"},
        # AMBIGUOUS / UNDERSPECIFIED -> out of main
        {"case_id": _ior(3), "checker": "B", "reference": "30.0", **two, "final_verdict": "AMBIGUOUS", "final_value": "31",
         "method": "discussion"},
        {"case_id": _ior(4), "checker": "A", "reference": "40.0", **two, "final_verdict": "UNDERSPECIFIED",
         "method": "independent_agreement"},
        # _ior(5) sampled but not in the sheet -> pending
    ]


def test_reference_checks_apply_rule_q3(tmp_path):
    res = N.ingest_reference_checks(_csv(tmp_path / "r.csv", REF_COLS, _ref_rows()), SAMPLE, ORIGINALS, date="2026-10-01")
    assert res["problems"] == [] and res["pending"] == sorted([_mamo(3), _ior(5)]) and not res["final"]
    ev = N.sha256_path(str(tmp_path / "r.csv"))
    m = {e["case_id"]: e for e in res["entries"]["mamo_complex_lp"]}
    i = {e["case_id"]: e for e in res["entries"]["industryor"]}
    assert m[_mamo(1)] == {"case_id": _mamo(1), "original_value": 100.0, "new_value": 100.0, "verdict": "CORRECT",
                           "checkers": ["A"], "method": "single_check_correct", "adjudicator": "",
                           "date": "2026-10-01", "evidence_sha256": ev}
    assert (m[_mamo(2)]["verdict"], m[_mamo(2)]["original_value"], m[_mamo(2)]["new_value"]) == ("CORRECT_ROUNDED", 200.0, 200.4)
    assert m[_mamo(2)]["checkers"] == ["A", "B"]
    assert (i[_ior(1)]["new_value"], i[_ior(1)]["method"], i[_ior(1)]["adjudicator"]) == (12.5, "adjudication", "C")
    assert i[_ior(2)]["new_value"] == "infeasible"
    assert i[_ior(3)]["new_value"] is None and i[_ior(3)]["verdict"] == "AMBIGUOUS"   # value not used for scoring
    assert set(i) == {_ior(1), _ior(2), _ior(3), _ior(4)} and set(m) == {_mamo(1), _mamo(2)}
    assert res["q3"]["ids"] == [_ior(3), _ior(4)] and res["q3"]["status"] == "pending"
    assert res["q3"]["by_verdict"] == {"AMBIGUOUS": [_ior(3)], "UNDERSPECIFIED": [_ior(4)]}
    assert res["counts"] == {"CORRECT": 1, "CORRECT_ROUNDED": 1, "INCORRECT": 2, "AMBIGUOUS": 1, "UNDERSPECIFIED": 1}
    with pytest.raises(N.AnnotationError):
        N.ingest_reference_checks(str(tmp_path / "r.csv"), SAMPLE, ORIGINALS, strict=True)


def test_reference_checks_negative_cases(tmp_path):
    rows = _ref_rows()
    rows[0].update(final_verdict="INCORRECT", final_value="150")               # a single check cannot settle INCORRECT
    rows[1].update(final_value="")                                             # CORRECT_ROUNDED without a value
    rows[3].update(adjudicator="Somebody Else")                                # a name instead of a code
    rows[5].update(reference="31.0")                                           # checked against another reference
    rows[6].update(verdict_B="")                                               # UNDERSPECIFIED by one checker only
    rows.append({"case_id": _mamo(9), "checker": "A", "final_verdict": "CORRECT", "final_value": "900",
                 "method": "independent_agreement"})                            # not in the sample
    res = N.ingest_reference_checks(_csv(tmp_path / "r.csv", REF_COLS, rows), SAMPLE, ORIGINALS)
    text = " ".join(res["problems"])
    assert "single check" in text and "needs a numeric" in text and "not a single code" in text
    assert "not the frozen reference" in text and "not in the reference-check sample" in text
    assert "needs two checkers" in text
    assert "Somebody" not in json.dumps(res)
    assert res["entries"]["mamo_complex_lp"] == []
    assert [e["case_id"] for e in res["entries"]["industryor"]] == [_ior(2)]
    assert res["q3"]["ids"] == []
    assert {_mamo(1), _mamo(2), _ior(1), _ior(3), _ior(4)} <= set(res["q3"]["pending_ids"])
    ex = N.build_exclusions(None, res)
    assert ex["q3_removed"]["status"] == "pending" and _ior(3) in ex["q3_removed"]["pending_ids"]


def test_replacing_verdict_within_tolerance_is_refused(tmp_path):
    rows = _ref_rows()
    rows[1].update(final_value="200.000001")                     # that is CORRECT, not CORRECT_ROUNDED (E13 rule)
    res = N.ingest_reference_checks(_csv(tmp_path / "r.csv", REF_COLS, rows), SAMPLE, ORIGINALS)
    assert any("within tolerance" in p for p in res["problems"])


# ------------------------------------------------------------------ exclusions feed the analysis-set lists


def test_exclusions_file_feeds_the_analysis_set_lists(tmp_path):
    labels = N.ingest_type_labels(_csv(tmp_path / "t.csv", TYPE_COLS, _type_rows()), EXPECTED)
    ref = N.ingest_reference_checks(_csv(tmp_path / "r.csv", REF_COLS, _ref_rows()), SAMPLE, ORIGINALS)
    ex = N.build_exclusions(labels, ref, date="2026-10-01")
    assert ex["schema"] == A.EXCLUSIONS_SCHEMA
    assert ex["nl_not_linearizable"]["ids"] == [_ior(4)] and ex["nl_not_linearizable"]["status"] == "pending"
    assert ex["q3_removed"]["ids"] == [_ior(3), _ior(4)]
    root = tmp_path / "repo"
    N.write_json(str(root / N.EXCLUSIONS_PATH), ex)
    fake_sets = {"exclusions": {A.SEEN: {"ids": []}}}
    lists = A.load_named_lists(fake_sets, str(root))
    assert lists[A.NL]["ids"] == {_ior(4)} and lists[A.NL]["status"] == "pending"
    assert lists[A.Q3]["ids"] == {_ior(3), _ior(4)}
    ex0 = N.build_exclusions()                                   # nothing ingested -> both pending and empty
    assert ex0["nl_not_linearizable"]["status"] == ex0["q3_removed"]["status"] == "pending"


def test_q3_list_must_match_the_override_files(tmp_path):
    root = tmp_path / "repo"
    ex = N.build_exclusions()
    ex["q3_removed"].update(status="final", ids=[_ior(3), _ior(4)])
    N.write_json(str(root / N.EXCLUSIONS_PATH), ex)
    fake_sets = {"exclusions": {A.SEEN: {"ids": []}}}
    ov = {"entries": [{"case_id": _ior(3), "verdict": "AMBIGUOUS"}, {"case_id": _ior(4), "verdict": "UNDERSPECIFIED"},
                      {"case_id": _ior(1), "verdict": "INCORRECT"}]}
    N.write_json(str(root / N.OVERRIDES_DIR / "industryor.json"), ov)
    assert A.load_named_lists(fake_sets, str(root))[A.Q3]["ids"] == {_ior(3), _ior(4)}
    ov["entries"][0]["verdict"] = "CORRECT"
    N.write_json(str(root / N.OVERRIDES_DIR / "industryor.json"), ov)
    with pytest.raises(A.DefinitionError, match="differs"):
        A.load_named_lists(fake_sets, str(root))
    ex["q3_removed"]["status"] = "pending"
    N.write_json(str(root / N.EXCLUSIONS_PATH), ex)
    with pytest.raises(A.DefinitionError, match="no final"):
        A.load_named_lists(fake_sets, str(root))


# ------------------------------------------------------------------ E13 file format (needs runtime/orgene/refs.py)


def _toy_cases(path):
    rows = [{"case_id": _ior(i), "source": "industryor", "source_id": str(i), "text": "toy",
             "reference": {"objective": 10.0 * i, "raw": str(10 * i), "status": None}, "extra": {}, "license": "CC0"}
            for i in range(1, 7)]
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"_header": True, "source": "industryor", "raw_path": "data/raw/toy.json", "n": 6}) + "\n")
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_entries_build_valid_e13_override_files(tmp_path):
    refs = pytest.importorskip("orgene.refs")
    rows = [r for r in _ref_rows() if r["case_id"].startswith("industryor")]
    sample = {"rows": [r for r in SAMPLE["rows"] if r["benchmark"] == "industryor" and r["case_id"] != _ior(5)]}
    res = N.ingest_reference_checks(_csv(tmp_path / "r.csv", REF_COLS, rows), sample, ORIGINALS, date="2026-10-01",
                                    strict=True)
    cases = tmp_path / "industryor.jsonl"
    _toy_cases(cases)
    doc = refs.build_overrides_doc("industryor", str(cases), res["entries"]["industryor"])
    path = tmp_path / "industryor.json"
    refs.write_overrides(doc, str(path))
    ov = refs.load_overrides(str(path))
    assert refs.main_excluded_ids(ov) == res["q3"]["ids"]
    applied = {c["case_id"]: c["reference"] for c in refs.apply_to_cases(
        [json.loads(line) for line in open(cases) if '"_header"' not in line], ov,
        {_ior(i): {"objective": 10.0 * i, "status": None} for i in range(1, 7)}, source="industryor")}
    assert applied[_ior(1)]["objective"] == 12.5 and applied[_ior(1)]["original_objective"] == 10.0
    assert applied[_ior(2)]["status"] == "infeasible"
    assert applied[_ior(3)]["main_eligible"] is False and applied[_ior(6)]["version"] == "original"


# ------------------------------------------------------------------ command line (working tree, dev ids only)


def _dev_inputs(tmp_path, settled_both):
    sets = A.load_id_sets(None, ROOT)["sets"]
    ior_dev = sets["industryor_main_rev2026_100"]["dev"]
    mamo_dev = sets["mamo_main_clean111"]["dev"]
    t = _csv(tmp_path / "type_final_labels.csv", TYPE_COLS,
             [{"case_id": c, "final_label": "LP", "method": "independent_agreement"} for c in ior_dev])
    originals = N.originals_from_cases([os.path.join(ROOT, "data", "cases", f"{b}.jsonl") for b in ("mamo_complex_lp", "industryor")])
    sample = {"rows": [{"case_id": mamo_dev[0], "benchmark": "mamo_complex_lp", "split": "dev", "checker": "A+B"},
                       {"case_id": ior_dev[0], "benchmark": "industryor", "split": "dev", "checker": "A+B"}]}
    sp = tmp_path / "reference_check_sample.json"
    sp.write_text(json.dumps(sample))
    new_value = repr((originals[mamo_dev[0]][0] or 0.0) * 1.5 + 7.0)
    rows = [{"case_id": mamo_dev[0], "checker": "A+B", "verdict_A": "x", "verdict_B": "x", "final_verdict": "INCORRECT",
             "final_value": new_value, "method": "independent_agreement"},
            {"case_id": ior_dev[0], "checker": "A+B", "verdict_A": "x", "verdict_B": "x",
             "final_verdict": "UNDERSPECIFIED" if settled_both else "", "method": "third_party", "adjudicator": "C"}]
    r = _csv(tmp_path / "ref_check.csv", REF_COLS, rows)
    return sets, ior_dev, t, r, str(sp)


def test_command_line_dry_run_on_dev_ids(tmp_path, capsys):
    cli = _load_cli()
    sets, ior_dev, t, r, sp = _dev_inputs(tmp_path, settled_both=False)
    before = {p: os.path.exists(os.path.join(ROOT, p)) for p in (N.LABELS_PATH, N.EXCLUSIONS_PATH)}
    code = cli.main(["--type", t, "--ref", r, "--sample", sp, "--dry-run", "--date", "2026-10-01"])
    out = capsys.readouterr().out
    assert code == 0 and "dry run" in out and "not settled yet" in out
    assert f"final {len(ior_dev)}/100" in out and "pending 75" in out
    assert "entries industryor 0, mamo_complex_lp 1" in out and f"pending 1: {ior_dev[0]}" in out
    assert {p: os.path.exists(os.path.join(ROOT, p)) for p in before} == before
    test_ids = set(sets["industryor_main_rev2026_100"]["test"])
    printed_pending = out.split("[type] pending 75:")[1].split("\n")[0].split()
    assert set(printed_pending) <= test_ids                       # only ids are printed for the unlabelled cases
    with pytest.raises(N.AnnotationError):
        cli.main(["--type", t, "--strict", "--dry-run"])


def test_command_line_settled_checks_need_the_e13_writer(tmp_path, capsys):
    cli = _load_cli()
    _, ior_dev, t, r, sp = _dev_inputs(tmp_path, settled_both=True)
    try:
        import orgene.refs  # noqa: F401
        has_refs = True
    except ImportError:
        has_refs = False
    if has_refs:
        assert cli.main(["--ref", r, "--sample", sp, "--dry-run", "--date", "2026-10-01"]) == 0
        assert f"q3_removed 1: {ior_dev[0]}" in capsys.readouterr().out
    else:
        with pytest.raises(N.AnnotationError, match="refs.py"):
            cli.main(["--ref", r, "--sample", sp, "--dry-run", "--date", "2026-10-01"])

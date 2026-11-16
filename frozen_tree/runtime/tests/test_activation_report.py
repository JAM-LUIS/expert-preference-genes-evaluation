"""analysis/r1/activation_report.py on a self-written toy benchmark (no benchmark text, no real test ids)."""
import copy
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)
sys.path.insert(0, os.path.join(ROOT, "analysis", "r1"))

import activation_report as R  # noqa: E402
from orgene import genes as G  # noqa: E402

R_INT = {"feature": "integer_terms", "op": "==", "value": True}
BIGM = "orgene.numeric.bigm_bounded"

TOY = {  # case_id -> self-written statement
    "toy-0001": "Trucks come in whole units only; minimize the rental cost.",
    "toy-0002": "Blend two oils in any proportion to minimize cost.",
    "toy-0003": "An integer number of machines must be bought.",
    "toy-0004": "Maximize the profit of a bakery.",
    "toy-0005": "Buses are hired in integer numbers for a school trip.",
    "toy-0006": "Mix three feeds to meet a protein target.",
}
DEV, TEST = ["toy-0001", "toy-0002", "toy-0003", "toy-0004"], ["toy-0005", "toy-0006"]


def _jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return str(path)


@pytest.fixture()
def toy(tmp_path):
    cases = _jsonl(tmp_path / "toy.jsonl", [{"_header": True, "source": "toy"}] + [
        {"case_id": cid, "source": "toy", "text": t, "reference": {"objective": 1.0}} for cid, t in TOY.items()])
    split = tmp_path / "splits" / "toy"
    split.mkdir(parents=True)
    json.dump(DEV, open(split / "dev_ids.json", "w"))
    json.dump(TEST, open(split / "test_ids.json", "w"))
    sets = tmp_path / "analysis_sets.json"
    json.dump({"primary_sets": {"toy": "toy_main"}, "sets": {"toy_main": {"dev": ["toy-0001", "toy-0002"]}}},
              open(sets, "w"))
    store = []
    for g in G.load_store(os.path.join(ROOT, "genes", "genes.r1.jsonl")):
        g = copy.deepcopy(g)
        if g["geneId"] == BIGM:
            g["activation"] = {"rule": R_INT, "rationale": "integer models only"}
            g["version"] = "1.1.0"
        store.append(g)
    genes = _jsonl(tmp_path / "genes.jsonl", store)
    run = tmp_path / "20260101-toy-model-toy-dev-C3L-ALL"
    run.mkdir()

    def issue(ok):
        return {"geneId": BIGM, "ok": ok, "severity": "soft"}

    validated = _jsonl(run / "validated.C3L.round0.jsonl", [
        {"case_id": "toy-0001", "issues": [issue(True)]},   # active, never failed
        {"case_id": "toy-0002", "issues": [issue(False)]},  # failed although inactive -> missed activation
        {"case_id": "toy-0003", "issues": [issue(False)]},  # active and failed
        {"case_id": "toy-0004", "issues": []},              # not evaluated
    ])
    return {"tmp": tmp_path, "cases": cases, "splits": str(tmp_path / "splits"), "sets": str(sets),
            "genes": genes, "validated": validated}


def _run(toy, *extra):
    out = str(toy["tmp"] / "rep.json")
    md = str(toy["tmp"] / "rep.md")
    args = ["--cases", toy["cases"], "--splits", toy["splits"], "--genes", toy["genes"], "--out", out, "--md", md,
            *extra]
    assert R.main(args) == 0
    return json.load(open(out)), open(out).read() + open(md).read()


def test_dev_report_columns_rates_and_case_lists(toy):
    rep, text = _run(toy, "--analysis-sets", toy["sets"], "--validated", toy["validated"])
    assert rep["split"] == "dev" and rep["columns"] == {"dev_main": 2, "dev_removed": 2}
    row = {r["geneId"]: r for r in rep["genes_report"]}[BIGM]
    assert row["features_used"] == ["integer_terms"] and row["version"] == "1.1.0"
    main, removed = row["columns"]["dev_main"], row["columns"]["dev_removed"]
    assert (main["n_active"], main["activation_rate"]) == (1, 0.5)
    assert main["missed_activation"] == ["toy-0002"] and main["active_never_failed"] == ["toy-0001"]
    assert (removed["n_active"], removed["n_evaluated"], removed["n_failed"]) == (1, 1, 1)
    assert removed["missed_activation"] == [] and removed["active_never_failed"] == []
    always = {r["geneId"]: r for r in rep["genes_report"]}["orgene.execution.runs"]
    assert always["rule"] == "always" and always["columns"]["dev_main"]["activation_rate"] == 1.0
    assert rep["feature_prevalence"]["dev_main"]["integer_terms"]["rate"] == 0.5
    for cid in TEST:
        assert cid not in text
    for t in TOY.values():
        assert t not in text
    assert "/" + "Users" + "/" not in text


def test_dev_report_without_sets_has_one_column(toy):
    rep, _ = _run(toy)
    assert rep["columns"] == {"dev_all": 4}
    row = {r["geneId"]: r for r in rep["genes_report"]}[BIGM]
    assert row["columns"]["dev_all"]["activation_rate"] == 0.5 and "missed_activation" not in row["columns"]["dev_all"]


def test_dev_report_refuses_test_ids_in_validated_input(toy):
    d = toy["tmp"] / "20260101-toy-model-toy-dev-C0"
    d.mkdir()
    bad = _jsonl(d / "validated.C0.round0.jsonl", [{"case_id": "toy-0005", "issues": []}])
    with pytest.raises(SystemExit, match="test case id"):
        _run(toy, "--validated", bad)


def test_dev_report_refuses_validated_files_from_test_runs(toy):
    d = toy["tmp"] / "20260101-toy-model-toy-test-C3L"
    d.mkdir()
    bad = _jsonl(d / "validated.C3L.round0.jsonl", [{"case_id": "toy-0001", "issues": []}])
    with pytest.raises(SystemExit, match="test run"):
        _run(toy, "--validated", bad)
    nested = d / "units" / "round1"  # a test run's subdirectory is refused too, before the file is opened
    nested.mkdir(parents=True)
    bad2 = _jsonl(nested / "validated.C3L.round1.jsonl", [{"case_id": "toy-0001", "issues": []}])
    with pytest.raises(SystemExit, match="test run"):
        _run(toy, "--validated", bad2)


def test_test_mode_refuses_before_the_freeze_gate(toy):
    with pytest.raises(SystemExit, match="freeze gate"):
        _run(toy, "--split", "test")
    with pytest.raises(SystemExit, match="freeze gate"):
        _run(toy, "--split", "test", "--after-freeze", "--freeze-manifest", str(toy["tmp"] / "none.json"))


def test_test_mode_after_the_gate_reports_rates_only(toy):
    manifest = toy["tmp"] / "FREEZE_MANIFEST.json"
    manifest.write_text("{}")
    with pytest.raises(SystemExit, match="rates only"):
        _run(toy, "--split", "test", "--after-freeze", "--freeze-manifest", str(manifest),
             "--validated", toy["validated"])
    rep, text = _run(toy, "--split", "test", "--after-freeze", "--freeze-manifest", str(manifest))
    assert rep["split"] == "test" and rep["n"] == 2
    assert {r["geneId"]: r["activation_rate"] for r in rep["genes_report"]}[BIGM] == 0.5
    assert set(rep["genes_report"][0]) == {"geneId", "version", "activation_rate"}
    for cid in TOY:
        assert cid not in text

"""E14: analysis/check_test_isolation.py -- relative paths, wider scan, injected leaks are caught.

A scratch repository with toy cases is built for each case (ids only; no benchmark text). The run on the working
tree hashes the frozen case files and reads id files only.
"""
import importlib.util
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

_spec = importlib.util.spec_from_file_location("check_test_isolation", os.path.join(ROOT, "analysis", "check_test_isolation.py"))
CTI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CTI)


def _repo(root):
    """Scratch repo: 12 toy 'industryor' cases frozen 4 dev / 8 test, a gene library, a condition, a dev run."""
    raw = root / "data" / "raw" / "toy.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps([{"en_question": f"maximise {i}x s.t. x <= 1", "en_answer": str(i)} for i in range(1, 13)]))
    cases = root / "data" / "cases" / "industryor.jsonl"
    D.build_cases("industryor", str(raw), str(cases))
    split_dir = root / "data" / "splits" / "industryor"
    S.make_split(str(cases), str(split_dir), n_dev=4, seed=3)
    lock = json.loads((split_dir / "SPLIT_LOCK.json").read_text())
    lock["cases_path"] = "data/cases/industryor.jsonl"
    (split_dir / "SPLIT_LOCK.json").write_text(json.dumps(lock, indent=2))
    dev = json.loads((split_dir / "dev_ids.json").read_text())
    test = json.loads((split_dir / "test_ids.json").read_text())
    (root / "genes").mkdir()
    (root / "genes" / "genes.r1.jsonl").write_text(
        json.dumps({"geneId": "orgene.toy.rule", "audit": {"devCaseIds": dev[:2]}}) + "\n")
    (root / "genes" / "CANDIDATES.md").write_text(f"candidate seen on dev case {dev[0]}\n")
    (root / "conditions").mkdir()
    (root / "conditions" / "C0.md").write_text("Write a PuLP program.\n")
    run = root / "experiments" / "20260930-toy-industryor-dev-C0"
    run.mkdir(parents=True)
    (run / "requests.C0.jsonl").write_text("".join(json.dumps({"case_id": c, "condition": "C0"}) + "\n" for c in dev))
    return dev, test


def _run(root, capsys, *extra):
    code = CTI.main(["--root", str(root), *extra])
    out = capsys.readouterr().out
    return code, out


def test_clean_scratch_repo_passes_and_prints_relative_paths(tmp_path, capsys):
    _repo(tmp_path)
    code, out = _run(tmp_path, capsys)
    assert code == 0 and "RESULT: PASS" in out
    assert str(tmp_path) not in out and not find_absolute_paths(out)
    assert "[data/splits/industryor]" in out


def test_default_paths_do_not_depend_on_the_working_directory(tmp_path, capsys, monkeypatch):
    _repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    code, out = _run(tmp_path, capsys)
    assert code == 0 and "RESULT: PASS" in out


def test_test_id_in_a_dev_request_fails(tmp_path, capsys):
    dev, test = _repo(tmp_path)
    req = tmp_path / "experiments" / "20260930-toy-industryor-dev-C0" / "requests.C0.jsonl"
    with open(req, "a") as f:
        f.write(json.dumps({"case_id": test[0], "condition": "C0"}) + "\n")
    code, out = _run(tmp_path, capsys)
    assert code == 1 and "RESULT: FAIL" in out and test[0] in out


def test_test_id_in_a_unit_file_of_a_dev_run_fails(tmp_path, capsys):
    dev, test = _repo(tmp_path)
    units = tmp_path / "experiments" / "20260930-toy-industryor-dev-C3L" / "units"
    units.mkdir(parents=True)
    (units / "u.json").write_text(json.dumps({"unit": [test[1], "C3L"]}))
    assert _run(tmp_path, capsys)[0] == 1


def test_test_runs_are_skipped_and_not_opened(tmp_path, capsys, monkeypatch):
    dev, test = _repo(tmp_path)
    run = tmp_path / "experiments" / "20261010-toy-industryor-test-C0"
    run.mkdir(parents=True)
    (run / "requests.C0.jsonl").write_text(json.dumps({"case_id": test[0]}) + "\n")
    opened = []
    real_open = open

    def spy(path, *a, **k):
        opened.append(str(path))
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", spy)
    code, out = _run(tmp_path, capsys)
    monkeypatch.undo()
    assert code == 0 and "1 test run(s) skipped" in out
    assert not [p for p in opened if "-test-" in p]


def test_test_id_in_gene_dev_case_ids_fails(tmp_path, capsys):
    dev, test = _repo(tmp_path)
    (tmp_path / "genes" / "genes.r1.jsonl").write_text(
        json.dumps({"geneId": "orgene.toy.rule", "audit": {"devCaseIds": [dev[0], test[2]]}}) + "\n")
    code, out = _run(tmp_path, capsys)
    assert code == 1 and f"{test[2]} (held-out)" in out


def test_unknown_id_in_gene_dev_case_ids_fails(tmp_path, capsys):
    _repo(tmp_path)
    (tmp_path / "genes" / "genes.r1.jsonl").write_text(
        json.dumps({"geneId": "orgene.toy.rule", "audit": {"devCaseIds": ["industryor-0999"]}}) + "\n")
    code, out = _run(tmp_path, capsys)
    assert code == 1 and "not a frozen dev id" in out


@pytest.mark.parametrize("fmt", ["canonical", "short", "spaced"])
def test_test_id_in_condition_or_gene_text_fails(tmp_path, capsys, fmt):
    dev, test = _repo(tmp_path)
    num = test[0].split("-")[1]
    text = {"canonical": f"see {test[0]}", "short": f"like IndustryOR-{num} did", "spaced": f"(industryor {num})"}[fmt]
    (tmp_path / "conditions" / "C0.md").write_text(f"Write a PuLP program {text}.\n")
    code, out = _run(tmp_path, capsys)
    assert code == 1 and test[0] in out


def test_dev_id_in_text_is_allowed(tmp_path, capsys):
    dev, _ = _repo(tmp_path)
    (tmp_path / "conditions" / "C0.md").write_text(f"example from {dev[1]}\n")
    assert _run(tmp_path, capsys)[0] == 0


def test_baseline_training_manifest_with_a_test_id_fails(tmp_path, capsys):
    dev, test = _repo(tmp_path)
    b = tmp_path / "baselines" / "alphaopt"
    b.mkdir(parents=True)
    (b / "train_manifest.json").write_text(json.dumps({"case_ids": dev}))
    assert _run(tmp_path, capsys)[0] == 0
    (b / "train_manifest.json").write_text(json.dumps({"case_ids": dev + [test[3]]}))
    assert _run(tmp_path, capsys)[0] == 1
    # an explicitly named manifest must exist
    (b / "train_manifest.json").write_text(json.dumps({"case_ids": dev}))
    assert _run(tmp_path, capsys, "--train-manifest", "baselines/alphaopt/missing.json")[0] == 1


def test_eng_holdout_ids_are_held_out(tmp_path, capsys):
    dev, test = _repo(tmp_path)
    (tmp_path / "data" / "splits" / "industryor" / "eng_holdout_ids.json").write_text(json.dumps(["pglib_uc-0001"]))
    code, out = _run(tmp_path, capsys)
    assert code == 0 and "eng_holdout industryor=1" in out
    req = tmp_path / "experiments" / "20260930-toy-industryor-dev-C0" / "requests.C0.jsonl"
    with open(req, "a") as f:
        f.write(json.dumps({"case_id": "pglib_uc-0001", "condition": "C0"}) + "\n")
    code, out = _run(tmp_path, capsys)
    assert code == 1 and "pglib_uc-0001" in out
    sc = CTI.Scanner({"pglib_uc-0001", test[0]})
    assert sc.ids_in("uses pglib_uc-0001 data") == {"pglib_uc-0001"}
    assert sc.ids_in("uses pglib_uc-00012 data") == set()
    assert sc.ids_in(f"mamo 0001 and {test[0]}") == {test[0]}


def test_tampered_subset_lock_fails(tmp_path, capsys):
    dev, test = _repo(tmp_path)
    out = tmp_path / "data" / "splits_r1" / "sub"
    S.derive_subset_lock(str(tmp_path / "data" / "splits" / "industryor"), [dev[0], test[0]], str(out), root=str(tmp_path))
    assert _run(tmp_path, capsys)[0] == 0
    (out / "test_ids.json").write_text(json.dumps([test[1]], indent=0))
    lock = json.loads((out / "SPLIT_LOCK.json").read_text())
    lock["test_sha256"] = S.ids_sha256([test[1]])
    (out / "SPLIT_LOCK.json").write_text(json.dumps(lock, indent=2))
    code, out_txt = _run(tmp_path, capsys)
    assert code == 1 and "subset_sha256" in out_txt


def test_working_tree_passes(capsys):
    code, out = _run(ROOT, capsys)
    assert code == 0, out
    assert "RESULT: PASS" in out and "6 subset lock(s)" in out
    assert "PEND main" in out and "dev_signal55 (dev): 55 cases" in out
    assert not find_absolute_paths(out)

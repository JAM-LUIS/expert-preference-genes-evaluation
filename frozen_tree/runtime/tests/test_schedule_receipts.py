"""E07 input and ownership receipts: synthetic cases and a local fake model only.

These regressions reject stale or unattributed work before further model generation.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

import test_unit_exec as TE  # noqa: E402
from test_schedule_execute import _setup, _spy_preflight  # noqa: E402
from orgene import cli, data as D, paths as PTH, schedule as S, unit_exec as U  # noqa: E402


def _argument(argv, name):
    return argv[argv.index(name) + 1]


def _replace_argument(argv, name, value):
    changed = list(argv)
    changed[changed.index(name) + 1] = str(value)
    return changed


def _change_selected_case(path, field):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    case = next(row for row in rows if row.get("case_id") == "u-a")
    if field == "text":
        case["text"] += " The production instructions have changed."
    elif field == "reference":
        case["reference"]["objective"] += 1
        case["reference"]["raw"] = str(case["reference"]["objective"])
    else:
        raise AssertionError(field)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


@pytest.mark.parametrize("mutation", ["text", "reference", "cases_path"])
def test_input_receipt_refuses_changed_cases_and_restored_input_resumes(tmp_path, monkeypatch, mutation):
    entries = ("canned.main", "canned.secondary")
    argv, _ = _setup(tmp_path, entries=entries, configs=("C0",), cases=("u-a",))
    checks, renders, _ = _spy_preflight(monkeypatch)
    cases_path = Path(_argument(argv, "--cases"))
    original_bytes = cases_path.read_bytes()
    fake = TE._FakeOllama()
    try:
        cli.main(argv + ["--host", fake.url])
        baseline_chats = fake.chats
        assert baseline_chats == len(entries)
        receipt_path = tmp_path / "run" / "schedule_inputs.json"
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes)
        assert receipt["cases_path"] == PTH.rel(str(cases_path.resolve()))  # neutral form; the digest pins the real path
        assert receipt["cases_path_sha256"] == hashlib.sha256(str(cases_path.resolve()).encode()).hexdigest()
        assert receipt["cases_sha256"] == hashlib.sha256(original_bytes).hexdigest()
        selected_digests = receipt["selected_case_sha256"]
        assert set(selected_digests) == set(entries)
        assert all(isinstance(digest, str) and len(digest) == 64 for digest in selected_digests.values())
        assert len(set(selected_digests.values())) == 1  # both contexts selected the same toy case

        changed_argv = list(argv)
        if mutation == "cases_path":
            alternative = tmp_path / "same_bytes_different_path.jsonl"
            alternative.write_bytes(original_bytes)
            assert alternative.read_bytes() == original_bytes
            assert alternative.resolve() != cases_path.resolve()
            changed_argv = _replace_argument(argv, "--cases", alternative)
        else:
            _change_selected_case(cases_path, mutation)
            assert cases_path.read_bytes() != original_bytes

        before_checks, before_renders = list(checks), list(renders)
        with pytest.raises((SystemExit, S.ScheduleError), match=r"(?i)(input|cases)"):
            cli.main(changed_argv + ["--host", fake.url])
        assert fake.chats == baseline_chats
        assert checks == before_checks and renders == before_renders
        assert receipt_path.read_bytes() == receipt_bytes

        cases_path.write_bytes(original_bytes)
        cli.main(argv + ["--host", fake.url])
        assert fake.chats == baseline_chats
        assert receipt_path.read_bytes() == receipt_bytes
    finally:
        fake.close()


def test_nonempty_unattributed_model_run_is_refused_before_execution(tmp_path, monkeypatch):
    argv, _ = _setup(tmp_path, configs=("C0",), cases=("u-a",))
    checks, renders, _ = _spy_preflight(monkeypatch)
    run = tmp_path / "run" / "by-model" / "canned.main"
    run.mkdir(parents=True)
    artifact = run / "final.C0.jsonl"
    prior_bytes = (json.dumps({"case_id": "u-a", "config_id": "C0", "repeat": 0}) + "\n").encode()
    artifact.write_bytes(prior_bytes)
    fake = TE._FakeOllama()
    try:
        with pytest.raises((SystemExit, S.ScheduleError), match=r"(?i)(existing|unattributed|scheduled)"):
            cli.main(argv + ["--host", fake.url])
        assert fake.chats == 0
        assert checks == [] and renders == []
        assert artifact.read_bytes() == prior_bytes
    finally:
        fake.close()


@pytest.mark.parametrize("artifact_name", ["final.C0.jsonl", "run_config.json"])
def test_partial_two_model_receipt_cannot_adopt_second_model_artifacts(tmp_path, monkeypatch, artifact_name):
    entries = ("canned.main", "canned.secondary")
    argv, plan = _setup(tmp_path, entries=entries, configs=("C0",), cases=("u-a",))
    checks, _, _ = _spy_preflight(monkeypatch)
    first = plan["units"][0]["registry_entry"]
    second = next(entry for entry in entries if entry != first)
    root = tmp_path / "run"
    stale_context = root / "by-model" / second
    stale_context.mkdir(parents=True)
    artifact = stale_context / artifact_name
    prior_bytes = (json.dumps({"case_id": "u-a", "config_id": "C0", "repeat": 0}) + "\n").encode()
    artifact.write_bytes(prior_bytes)
    assert not (stale_context / "units").exists()  # the former early-return hole
    cases_path = Path(_argument(argv, "--cases"))
    selected = D.load_cases(str(cases_path), {"u-a"})
    receipt = {"schema_version": 1, "plan_sha256": _argument(argv, "--plan-sha256"),
               "cases_path": PTH.rel(str(cases_path.resolve())),
               "cases_path_sha256": hashlib.sha256(str(cases_path.resolve()).encode()).hexdigest(),
               "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
               "selected_case_sha256": {first: hashlib.sha256(S._canonical(selected)).hexdigest()}}
    receipt_path = root / "schedule_inputs.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    receipt_bytes = receipt_path.read_bytes()
    fake = TE._FakeOllama()
    try:
        with pytest.raises((SystemExit, S.ScheduleError), match=r"(?i)(existing|unattributed|receipt)"):
            cli.main(argv + ["--host", fake.url])
        assert fake.chats == 0 and second not in checks
        assert artifact.read_bytes() == prior_bytes
        assert receipt_path.read_bytes() == receipt_bytes
        assert second not in json.loads(receipt_path.read_bytes())["selected_case_sha256"]
    finally:
        fake.close()


@pytest.mark.parametrize("status", [U.COMPLETE, U.INCOMPLETE, U.RUNNING])
@pytest.mark.parametrize("tampering", ["plan_sha256", "planned_index", "remove_schedule"])
def test_unit_schedule_attribution_is_verified_for_every_status(tmp_path, monkeypatch, status, tampering):
    argv, plan = _setup(tmp_path, configs=("C0",), cases=("u-a",))
    _spy_preflight(monkeypatch)
    fake = TE._FakeOllama()
    try:
        cli.main(argv + ["--host", fake.url])
        assert fake.chats == 1
        root = tmp_path / "run"
        run = root / "by-model" / "canned.main"
        # Valid run-level and setup receipts must not mask a corrupt unit receipt.
        assert (root / "schedule_plan.sha256").read_text().strip() == _argument(argv, "--plan-sha256")
        assert (root / "schedule_inputs.json").is_file()
        assert (run / "units" / U.SETUP_FILE).is_file()
        planned = plan["units"][0]
        path = Path(U.unit_path(str(run), planned["case_id"], planned["config_id"], planned["repeat"]))
        unit = json.loads(path.read_text(encoding="utf-8"))
        assert unit["status"] == U.COMPLETE
        assert unit["schedule"]["plan_sha256"] == _argument(argv, "--plan-sha256")
        assert unit["schedule"]["planned_index"] == 0
        original_bytes = path.read_bytes()
        unit["status"] = status
        if tampering == "remove_schedule":
            del unit["schedule"]
        elif tampering == "plan_sha256":
            unit["schedule"]["plan_sha256"] = "0" * 64
        elif tampering == "planned_index":
            unit["schedule"]["planned_index"] = 1
        else:
            raise AssertionError(tampering)
        path.write_text(json.dumps(unit), encoding="utf-8")
        corrupt_bytes = path.read_bytes()

        with pytest.raises((SystemExit, S.ScheduleError), match=r"(?i)(schedule|attribut|plan|unit)"):
            cli.main(argv + ["--host", fake.url])
        assert fake.chats == 1
        assert path.read_bytes() == corrupt_bytes

        path.write_bytes(original_bytes)
        cli.main(argv + ["--host", fake.url])
        assert fake.chats == 1
    finally:
        fake.close()


def test_gate_record_is_not_an_artifact_of_a_model_context(tmp_path):
    """On a sealed stage the freeze gate appends its record to the model context before the input receipt is written;
    that record (and the lock) must not make the context look like one with unattributed artifacts (2026-10-06: the
    first launch of the held-out run was refused for this reason)."""
    ctx = tmp_path / "by-model" / "m"
    ctx.mkdir(parents=True)
    assert not S._context_has_artifacts(ctx)
    (ctx / ".lock").write_text("")
    (ctx / "freeze_gate.jsonl").write_text("{}\n")
    assert not S._context_has_artifacts(ctx)
    (ctx / "run_config.json").write_text("{}")
    assert S._context_has_artifacts(ctx)


"""E07 execution integration: self-made toy cases and a local fake Ollama HTTP server only."""
import copy
import json
import os
import sys
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

import test_unit_exec as TE  # noqa: E402
from orgene import cli, configs as CF, data as D, freeze as FZ, schedule as S, unit_exec as U  # noqa: E402


def _setup(tmp_path, entries=("canned.main",), configs=("C0", "C3E"), cases=("u-a", "u-b"), order="random"):
    registry = TE._model_registry(tmp_path, execution={"timeout_s": 45})
    doc = json.loads(Path(registry).read_text())
    original = doc["entries"]["canned.main"]
    doc["entries"] = {entry: copy.deepcopy(original) for entry in entries}
    Path(registry).write_text(json.dumps(doc))
    cases_path = TE.write_cases(str(tmp_path / "toy.jsonl"))
    split = TE._split_dir(tmp_path, list(cases), ["u-c", "u-d", "u-e"])
    units = [dict(case_id=case, config_id=cfg, repeat=0, registry_entry=model)
             for case in cases for cfg in configs for model in entries]
    plan = S.make_plan({"schema_version": 1, "units": units}, CF.load_registry(), seed=73, order=order)
    plan_path = str(tmp_path / "plan.json")
    digest = S.write_plan(plan_path, plan)
    return ["execute", "--run", str(tmp_path / "run"), "--cases", cases_path,
            "--split-dir", split, "--split", "dev", "--registry", registry,
            "--plan", plan_path, "--plan-sha256", digest, "--local-tokens", "off", "--export-validated"], plan


def _spy_preflight(monkeypatch):
    checks, renders, gates = [], [], []
    monkeypatch.setattr(U, "preflight_registry_check", lambda entry, registry: checks.append(entry))
    original_render, original_gate = U.precheck_render, FZ.gate_stage

    def render(*args, **kwargs):
        renders.append(True)
        return original_render(*args, **kwargs)

    def gate(stage, **kwargs):
        gates.append((stage, kwargs))
        return original_gate(stage, **kwargs)
    monkeypatch.setattr(U, "precheck_render", render)
    monkeypatch.setattr(FZ, "gate_stage", gate)
    return checks, renders, gates


def test_cli_global_plan_separate_model_contexts_reuse_and_resume(tmp_path, monkeypatch):
    argv, plan = _setup(tmp_path, entries=("canned.main", "canned.secondary"))
    checks, renders, gates = _spy_preflight(monkeypatch)
    fake = TE._FakeOllama()
    try:
        cli.main(argv + ["--host", fake.url])
        assert sorted(checks) == ["canned.main", "canned.secondary"]
        assert len(renders) == 2 and [stage for stage, _ in gates] == ["execute", "execute"]
        assert all(argv[argv.index("--plan") + 1] in kw["inputs"] for _, kw in gates)
        assert fake.chats == 8  # per model: two C0 + two repairs; C3E round 0 is reused.
        by_id = {}
        for model in ("canned.main", "canned.secondary"):
            run = tmp_path / "run" / "by-model" / model
            units = U.load_units(str(run))
            assert len(units) == 4 and all(u["status"] == U.COMPLETE for u in units)
            assert all(u["started_at"] and u["finished_at"] for u in units)
            for unit in units:
                by_id[(model, unit["case_id"], unit["config_id"], unit["repeat"])] = unit
                assert unit["schedule"]["plan_sha256"] == argv[argv.index("--plan-sha256") + 1]
                if unit["config_id"] == "C3E":
                    assert unit["round0"]["reused_from"]["config_id"] == "C0"
            assert (run / "validated.C3E.round1.jsonl").exists()
        for index, planned in enumerate(plan["units"]):
            unit = by_id[S.unit_key(planned)]
            assert unit["schedule"]["planned_index"] == index
        events = [json.loads(line) for line in (tmp_path / "run" / "schedule_events.jsonl").read_text().splitlines()]
        assert [e["unit"] for e in events if e["event"] == "unit_start"] == plan["units"]
        cli.main(argv + ["--host", fake.url])
        assert fake.chats == 8  # completed units cause no new model generation.
    finally:
        fake.close()


@pytest.mark.parametrize("sealed", ["test", "eng_holdout"])
def test_scheduler_preserves_freeze_gate_before_protected_case_loading(tmp_path, monkeypatch, sealed):
    argv, _ = _setup(tmp_path, cases=("u-c",), configs=("C0",))
    argv[argv.index("--split") + 1] = sealed
    started = []
    monkeypatch.setattr(U, "preflight_registry_check", lambda *a: started.append(True))
    def forbidden_case_load(*args, **kwargs):
        raise AssertionError("protected cases were parsed before the freeze gate")
    monkeypatch.setattr(D, "load_cases", forbidden_case_load)
    monkeypatch.setattr(D, "load_case_ids", forbidden_case_load)
    with pytest.raises(SystemExit, match="refused by the test gate"):
        cli.main(argv)
    assert started == []


@pytest.mark.parametrize("label", [None, "dev"])
def test_scheduler_gates_sealed_plan_ids_even_if_split_label_is_absent_or_dev(tmp_path, monkeypatch, label):
    argv, _ = _setup(tmp_path, configs=("C0",), cases=("u-a",))
    if label is None:
        pos = argv.index("--split")
        del argv[pos:pos + 2]
    monkeypatch.setattr(FZ, "sealed_ids", lambda root=None: {"u-a"})
    def forbidden_case_load(*args, **kwargs):
        raise AssertionError("protected case object was parsed before ids gate")
    monkeypatch.setattr(D, "load_cases", forbidden_case_load)
    with pytest.raises(SystemExit, match="refused by the test gate"):
        cli.main(argv)


def test_scheduler_refuses_reverse_protocol_before_any_model_setup(tmp_path, monkeypatch):
    argv, plan = _setup(tmp_path, order="reverse")
    assert plan["reverse_protocol_status"] != "not_requested"
    started = []
    monkeypatch.setattr(U, "prepare_run", lambda *a, **kw: started.append(True))
    with pytest.raises(SystemExit, match="reverse execution is not authorized"):
        cli.main(argv)
    assert started == []


def test_bad_plan_hash_is_refused_before_preflight(tmp_path, monkeypatch):
    argv, _ = _setup(tmp_path)
    argv[argv.index("--plan-sha256") + 1] = "0" * 64
    started = []
    monkeypatch.setattr(U, "prepare_run", lambda *a, **kw: started.append(True))
    with pytest.raises(SystemExit, match="SHA-256 mismatch"):
        cli.main(argv)
    assert started == []


def test_run_directory_rejects_changed_plan_even_with_valid_new_hash(tmp_path, monkeypatch):
    argv, _ = _setup(tmp_path)
    root = tmp_path / "run"
    root.mkdir()
    (root / "schedule_plan.sha256").write_text("0" * 64 + "\n")
    with pytest.raises(SystemExit, match="different plan"):
        cli.main(argv)


def test_dependency_blocked_after_source_incomplete_and_retries_on_resume(tmp_path, monkeypatch):
    argv, plan = _setup(tmp_path, cases=("u-a",))
    _spy_preflight(monkeypatch)
    original_run = U.run_unit
    once = {"fail": True}

    def run(case, cfg, repeat, backend, ctx, **kwargs):
        if cfg["id"] == "C0" and once["fail"]:
            once["fail"] = False
            return {"status": U.INCOMPLETE}
        return original_run(case, cfg, repeat, backend, ctx, **kwargs)

    monkeypatch.setattr(U, "run_unit", run)
    fake = TE._FakeOllama()
    try:
        with pytest.raises(SystemExit) as exc:
            cli.main(argv + ["--host", fake.url])
        assert exc.value.code == 4 and fake.chats == 0
        log_path = tmp_path / "run" / "schedule_events.jsonl"
        assert "dependency_blocked" in log_path.read_text()
        cli.main(argv + ["--host", fake.url])
        assert fake.chats == 1
        assert len(U.load_units(str(tmp_path / "run" / "by-model" / "canned.main"))) == 2
    finally:
        fake.close()

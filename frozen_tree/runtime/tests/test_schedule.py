"""E07 scheduler checks using only synthetic units, registries and occupancy responses.

No benchmark cases, model requests, network calls or wall-clock sleeps are used.
"""
import copy
import hashlib
import json
import os
import sys
from collections import Counter

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, RUNTIME)

from orgene import configs as CF  # noqa: E402
from orgene import schedule as S  # noqa: E402


def _config(config_id, *, prompt="C0", round0="own", scope=None, repair="none"):
    return {
        "id": config_id,
        "prompt": prompt,
        "round0": round0,
        "validator": "gene" if repair != "none" else "none",
        "gene_scope": scope,
        "activation": "per_problem" if scope else "none",
        "repair": repair,
        "closing": "spec_and_program" if prompt == "C2" else "program",
        "max_rounds": 2 if repair != "none" else 0,
        "num_predict": 64,
        "num_ctx": 256,
        "variant": None,
    }


@pytest.fixture
def registry_file(tmp_path):
    raw = {
        "schema": CF.SCHEMA,
        "configs": [
            _config("C0"),
            _config("C1", prompt="C1"),
            _config("C2", prompt="C2"),
            _config("C3L", round0="reuse:C0", scope="C3L", repair="gene"),
            _config("C3E", round0="reuse:C0", scope="C3E", repair="generic"),
            _config("C2E", prompt="C2", round0="reuse:C2", scope="C3E", repair="generic"),
        ],
    }
    path = tmp_path / "toy_configs.json"
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def registry(registry_file):
    return CF.load_registry(str(registry_file))


def _unit(config_id="C0", *, case_id="toy-a", repeat=0, registry_entry="m.main"):
    return {
        "case_id": case_id,
        "config_id": config_id,
        "repeat": repeat,
        "registry_entry": registry_entry,
    }


def _matrix(units=None):
    if units is None:
        units = [
            _unit(config_id, case_id=case_id, repeat=repeat, registry_entry=registry_entry)
            for case_id in ("toy-a", "toy-b")
            for repeat in (0, 1)
            for registry_entry in ("m.main", "m.secondary")
            for config_id in ("C0", "C1", "C2", "C3L", "C3E", "C2E")
        ]
    return {"schema_version": 1, "units": units}


def _key(unit):
    return (unit["case_id"], unit["config_id"], unit["repeat"], unit["registry_entry"])


def _assert_dependencies(plan, registry, seed):
    positions = {_key(unit): index for index, unit in enumerate(plan["units"])}
    for unit in plan["units"]:
        source = CF.reuse_source(registry["configs"][unit["config_id"]])
        if source:
            source_key = (unit["case_id"], source, unit["repeat"], unit["registry_entry"])
            assert source_key in positions, (seed, unit)
            assert positions[source_key] < positions[_key(unit)], (seed, unit, plan["units"])


def test_plan_is_deterministic_and_preserves_inputs(registry):
    matrix = _matrix()
    original_matrix, original_registry = copy.deepcopy(matrix), copy.deepcopy(registry)
    first = S.make_plan(matrix, registry, seed=73, order="random")
    second = S.make_plan(matrix, registry, seed=73, order="random")
    assert first == second
    assert first["seed"] == 73
    assert first["order"] == "random"
    assert first["config_registry_sha256"] == registry["sha256"]
    assert isinstance(first["dependency_moves"], list)
    expected = Counter(_key(unit) for unit in matrix["units"])
    assert Counter(_key(unit) for unit in first["raw_units"]) == expected
    assert Counter(_key(unit) for unit in first["units"]) == expected
    assert matrix == original_matrix
    assert registry == original_registry


def test_random_and_reverse_preserve_dependencies_for_1000_seeds(registry):
    matrix = _matrix()
    expected = Counter(_key(unit) for unit in matrix["units"])
    observed_orders = set()
    saw_dependency_move = False
    for seed in range(1000):
        forward = S.make_plan(matrix, registry, seed=seed, order="random")
        reverse = S.make_plan(matrix, registry, seed=seed, order="reverse")
        forward_raw = tuple(_key(unit) for unit in forward["raw_units"])
        reverse_raw = tuple(_key(unit) for unit in reverse["raw_units"])
        assert reverse_raw == tuple(reversed(forward_raw)), seed
        observed_orders.add(forward_raw)
        for plan in (forward, reverse):
            assert Counter(_key(unit) for unit in plan["raw_units"]) == expected, seed
            assert Counter(_key(unit) for unit in plan["units"]) == expected, seed
            _assert_dependencies(plan, registry, seed)
            saw_dependency_move = saw_dependency_move or bool(plan["dependency_moves"])
    assert len(observed_orders) > 1
    assert saw_dependency_move


@pytest.mark.parametrize("order", ["random", "reverse"])
def test_independent_units_keep_the_seeded_raw_order(registry, order):
    matrix = _matrix([_unit("C0", case_id=f"toy-{i}") for i in range(8)])
    plan = S.make_plan(matrix, registry, seed=19, order=order)
    assert [_key(unit) for unit in plan["units"]] == [_key(unit) for unit in plan["raw_units"]]
    assert plan["dependency_moves"] == []


def test_duplicate_unit_identity_is_rejected(registry):
    unit = _unit()
    with pytest.raises(S.ScheduleError):
        S.make_plan(_matrix([unit, copy.deepcopy(unit)]), registry, seed=0)


@pytest.mark.parametrize("source_changes", [
    {"case_id": "another-toy-case"},
    {"repeat": 1},
    {"registry_entry": "m.secondary"},
])
def test_reuse_source_must_match_case_repeat_and_registry_entry(registry, source_changes):
    source = _unit("C0")
    source.update(source_changes)
    with pytest.raises(S.ScheduleError):
        S.make_plan(_matrix([source, _unit("C3L")]), registry, seed=0)


def test_missing_round_zero_source_is_rejected(registry):
    with pytest.raises(S.ScheduleError):
        S.make_plan(_matrix([_unit("C3L")]), registry, seed=0)


@pytest.mark.parametrize("repeat", [-1, True, 1.5, "0", None])
def test_invalid_repeat_is_rejected(registry, repeat):
    with pytest.raises(S.ScheduleError):
        S.make_plan(_matrix([_unit(repeat=repeat)]), registry, seed=0)


@pytest.mark.parametrize("registry_entry", ["", "bad name", "../bad", "m.main\n", 7, None])
def test_invalid_registry_entry_is_rejected(registry, registry_entry):
    with pytest.raises(S.ScheduleError):
        S.make_plan(_matrix([_unit(registry_entry=registry_entry)]), registry, seed=0)


def test_unknown_configuration_is_rejected(registry):
    with pytest.raises(S.ScheduleError):
        S.make_plan(_matrix([_unit("UNKNOWN")]), registry, seed=0)


@pytest.mark.parametrize("field", ["case_id", "config_id", "repeat", "registry_entry"])
def test_missing_unit_fields_are_rejected(registry, field):
    unit = _unit()
    del unit[field]
    with pytest.raises(S.ScheduleError):
        S.make_plan(_matrix([unit]), registry, seed=0)


@pytest.mark.parametrize("seed", [True, 1.5, "0", None])
def test_non_integer_seed_is_rejected(registry, seed):
    with pytest.raises(S.ScheduleError):
        S.make_plan(_matrix([_unit()]), registry, seed=seed)


def test_unknown_order_is_rejected(registry):
    with pytest.raises(S.ScheduleError):
        S.make_plan(_matrix([_unit()]), registry, seed=0, order="alphabetical")


def test_write_and_load_plan_verify_exact_bytes_and_configuration_digest(tmp_path, registry, registry_file):
    plan = S.make_plan(_matrix(), registry, seed=29, order="reverse")
    path = tmp_path / "plan.json"
    digest = S.write_plan(str(path), plan)
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    loaded = S.load_plan(str(path), digest, configs_path=str(registry_file))
    assert loaded == plan


def test_plan_byte_tampering_is_rejected(tmp_path, registry, registry_file):
    plan = S.make_plan(_matrix(), registry, seed=29)
    path = tmp_path / "plan.json"
    digest = S.write_plan(str(path), plan)
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(S.ScheduleError):
        S.load_plan(str(path), digest, configs_path=str(registry_file))


def test_configuration_byte_tampering_is_rejected(tmp_path, registry, registry_file):
    plan = S.make_plan(_matrix(), registry, seed=29)
    path = tmp_path / "plan.json"
    digest = S.write_plan(str(path), plan)
    # Still valid JSON, but different registry bytes must not pass a pinned plan.
    registry_file.write_bytes(registry_file.read_bytes() + b"\n")
    with pytest.raises(S.ScheduleError):
        S.load_plan(str(path), digest, configs_path=str(registry_file))


def test_modified_final_order_cannot_be_resealed_as_a_valid_plan(tmp_path, registry, registry_file):
    plan = S.make_plan(_matrix(), registry, seed=29)
    modified = copy.deepcopy(plan)
    modified["units"] = list(reversed(modified["units"]))
    path = tmp_path / "modified_plan.json"
    path.write_text(json.dumps(modified), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(S.ScheduleError):
        S.load_plan(str(path), digest, configs_path=str(registry_file))


def _occupancy(responses):
    calls = []
    remaining = iter(responses)

    def get_models(host):
        calls.append(host)
        response = next(remaining)
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)

    return get_models, calls


@pytest.mark.parametrize("response", [[], [{"name": "toy-model:latest"}], [{"model": "toy-model:latest"}]])
def test_empty_or_same_model_occupancy_passes_without_sleep(response):
    get_models, calls = _occupancy([response])
    logs, sleeps = [], []
    waited = S.wait_until_idle("http://toy-host", "toy-model:latest", logs.append,
                               get_models=get_models, sleep=sleeps.append, max_wait=6, interval=2)
    assert waited == 0
    assert calls == ["http://toy-host"]
    assert sleeps == []


def test_foreign_model_is_logged_and_waited_for_before_proceeding():
    get_models, calls = _occupancy([
        [{"name": "foreign-model:latest"}, {"name": "toy-model:latest"}],
        [{"name": "toy-model:latest"}],
    ])
    logs, sleeps = [], []
    waited = S.wait_until_idle("http://toy-host", "toy-model:latest", logs.append,
                               get_models=get_models, sleep=sleeps.append, max_wait=6, interval=2)
    assert sleeps == [2]
    assert waited == 2
    assert calls == ["http://toy-host", "http://toy-host"]
    assert logs and all(isinstance(event, dict) for event in logs)
    assert "foreign-model:latest" in json.dumps(logs)


def test_foreign_model_wait_is_bounded():
    calls, logs, sleeps = [], [], []

    def always_busy(host):
        calls.append(host)
        return [{"name": "foreign-model:latest"}]

    with pytest.raises(S.ScheduleError):
        S.wait_until_idle("http://toy-host", "toy-model:latest", logs.append,
                          get_models=always_busy, sleep=sleeps.append, max_wait=5, interval=2)
    assert sleeps
    assert 0 < sum(sleeps) <= 5
    assert len(calls) <= 4
    assert "foreign-model:latest" in json.dumps(logs)


@pytest.mark.parametrize("response", [
    None,
    {"models": []},
    "not a model list",
    [None],
    [{}],
    [{"name": None}],
    [{"name": 7}],
    [{"name": ""}],
])
def test_unknown_or_malformed_occupancy_refuses_execution(response):
    get_models, calls = _occupancy([response])
    logs, sleeps = [], []
    with pytest.raises(S.ScheduleError):
        S.wait_until_idle("http://toy-host", "toy-model:latest", logs.append,
                          get_models=get_models, sleep=sleeps.append, max_wait=6, interval=2)
    assert calls == ["http://toy-host"]
    assert sleeps == []


def test_occupancy_request_error_refuses_execution():
    get_models, calls = _occupancy([OSError("synthetic occupancy endpoint failure")])
    logs, sleeps = [], []
    with pytest.raises(S.ScheduleError):
        S.wait_until_idle("http://toy-host", "toy-model:latest", logs.append,
                          get_models=get_models, sleep=sleeps.append, max_wait=6, interval=2)
    assert calls == ["http://toy-host"]
    assert sleeps == []

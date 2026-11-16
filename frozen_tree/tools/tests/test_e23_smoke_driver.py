"""Smoke resource guard tests: every process/HTTP observation is mocked.

No model, HTTP endpoint, subprocess, SSH or benchmark file is accessed.
"""
import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("e23_smoke_driver_under_test", TOOLS / "execute_e23_smoke.py")
DRIVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRIVER)


@pytest.fixture
def mocked_observations(monkeypatch):
    state = {"payload": {"models": []}, "listing": "", "http_calls": [], "process_calls": []}

    def urlopen(url, timeout):
        state["http_calls"].append((url, timeout))
        assert url == "http://127.0.0.1:11434/api/ps" and timeout == 30
        return io.BytesIO(json.dumps(state["payload"]).encode("utf-8"))

    def check_output(command, text):
        state["process_calls"].append((command, text))
        assert command == ["ps", "ax", "-o", "pid=,ppid=,command="] and text is True
        return state["listing"]

    monkeypatch.setattr(DRIVER.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(DRIVER.subprocess, "check_output", check_output)
    monkeypatch.setattr(DRIVER.os, "getpid", lambda: 42)
    monkeypatch.setattr(DRIVER.os, "getppid", lambda: 41)
    monkeypatch.setattr(DRIVER, "now", lambda: "2026-09-30T00:00:00+00:00")
    return state


def test_idle_snapshot_has_no_loaded_model_or_competing_process(mocked_observations):
    mocked_observations["listing"] = "1 0 /sbin/launchd\n99 1 /usr/bin/python unrelated_cpu_script.py\n"
    result = DRIVER.resource_snapshot()
    assert result == {"at": "2026-09-30T00:00:00+00:00", "models": [], "competing_processes": [],
                      "own_caffeinate_helpers": []}
    assert len(mocked_observations["http_calls"]) == len(mocked_observations["process_calls"]) == 1


def test_loaded_model_is_preserved_as_an_occupied_resource(mocked_observations):
    model = {"name": "invented-model:latest", "digest": "0" * 64, "size_vram": 1024}
    mocked_observations["payload"] = {"models": [model]}
    result = DRIVER.resource_snapshot()
    assert result["models"] == [model] and result["competing_processes"] == []
    # Snapshot only observes; it must never send a model unload or generate request.
    assert mocked_observations["http_calls"] == [("http://127.0.0.1:11434/api/ps", 30)]


@pytest.mark.parametrize("marker", ["llama-server", "runtime/unit_runner.py", "run_gene_it0_dev.py", "alphaopt/run",
                                   "runtime/ollama_runner.py", "tools/gptoss_tokenizer_check.py", "tools/execute_e23_smoke.py"])
def test_model_callers_are_detected_even_before_a_model_loads(mocked_observations, marker):
    mocked_observations["listing"] = f"71 1 /invented/python /invented/{marker} --invented-option\n"
    result = DRIVER.resource_snapshot()
    assert result["models"] == []
    assert len(result["competing_processes"]) == 1
    process = result["competing_processes"][0]
    assert process["pid"] == 71 and process["ppid"] == 1 and marker in process["markers"]


def test_self_process_and_malformed_process_lines_are_ignored(mocked_observations):
    mocked_observations["listing"] = (
        "42 41 /invented/python tools/execute_e23_smoke.py --campaign invented-dev\n"
        "\ninvalid-pid 1 runtime/unit_runner.py\n123 invalid-parent runtime/unit_runner.py\n123 1\n"
        "73 1 /invented/python runtime/unit_runner.py --run invented-dev\n"
    )
    result = DRIVER.resource_snapshot()
    assert [p["pid"] for p in result["competing_processes"]] == [73]


@pytest.mark.parametrize("pid,executable,expected", [
    (41, "caffeinate", []), (41, "/usr/bin/caffeinate", []),
    (99, "caffeinate", [99]), (41, "/invented/python", [41]), (41, "/bin/bash -c caffeinate", [41]),
])
def test_only_this_drivers_caffeinate_parent_is_exempt(mocked_observations, pid, executable, expected):
    mocked_observations["listing"] = f"{pid} 1 {executable} /invented/python tools/execute_e23_smoke.py\n"
    result = DRIVER.resource_snapshot()
    assert [p["pid"] for p in result["competing_processes"]] == expected
    expected_helpers = [{"pid": 41, "ppid": 1, "relation": "parent"}] if not expected else []
    assert result["own_caffeinate_helpers"] == expected_helpers


def test_current_drivers_caffeinate_helper_child_is_reported_and_exempt(mocked_observations):
    # Confirmed exec-style topology: Python driver owns a caffeinate helper child.
    mocked_observations["listing"] = "43 42 /usr/bin/caffeinate /invented/python tools/execute_e23_smoke.py\n"
    result = DRIVER.resource_snapshot()
    assert result["competing_processes"] == []
    assert result["own_caffeinate_helpers"] == [{"pid": 43, "ppid": 42, "relation": "child"}]


def test_another_drivers_caffeinate_helper_child_is_occupied(mocked_observations):
    mocked_observations["listing"] = "43 99 /usr/bin/caffeinate /invented/python tools/execute_e23_smoke.py\n"
    result = DRIVER.resource_snapshot()
    assert result["own_caffeinate_helpers"] == []
    assert result["competing_processes"] == [{"pid": 43, "ppid": 99, "markers": ["tools/execute_e23_smoke.py"]}]


def test_related_caffeinate_for_a_different_driver_is_not_exempt(mocked_observations):
    mocked_observations["listing"] = (
        "43 42 /usr/bin/caffeinate /invented/python tools/different_smoke_driver.py runtime/unit_runner.py\n"
    )
    result = DRIVER.resource_snapshot()
    assert result["own_caffeinate_helpers"] == []
    assert result["competing_processes"] == [{"pid": 43, "ppid": 42, "markers": ["runtime/unit_runner.py"]}]


@pytest.mark.parametrize("marker", ["runtime/unit_runner.py", "runtime/ollama_runner.py", "tools/gptoss_tokenizer_check.py"])
def test_this_drivers_model_calling_children_still_block(mocked_observations, marker):
    mocked_observations["listing"] = f"43 42 /invented/python {marker}\n"
    result = DRIVER.resource_snapshot()
    assert result["own_caffeinate_helpers"] == []
    assert result["competing_processes"] == [{"pid": 43, "ppid": 42, "markers": [marker]}]


@pytest.mark.parametrize("payload", [{}, {"models": None}, {"models": "unknown"}, {"models": {}}, []])
def test_unknown_model_occupancy_fails_closed(mocked_observations, payload):
    mocked_observations["payload"] = payload
    with pytest.raises((ValueError, RuntimeError)):
        DRIVER.resource_snapshot()


def test_unreachable_resource_endpoint_stops_without_retry(monkeypatch, mocked_observations):
    calls = []

    def unavailable(url, timeout):
        calls.append((url, timeout))
        raise RuntimeError("invented endpoint unavailable")

    monkeypatch.setattr(DRIVER.urllib.request, "urlopen", unavailable)
    with pytest.raises(RuntimeError, match="invented endpoint unavailable"):
        DRIVER.resource_snapshot()
    assert len(calls) == 1 and mocked_observations["process_calls"] == []

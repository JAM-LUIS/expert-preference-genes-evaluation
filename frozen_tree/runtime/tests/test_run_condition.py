"""runtime/run_condition.sh (wave1 follow-up A4): every runner call names a model registry entry, and a repair round
whose prompts do not fit the context stops the run before it is generated.

The script runs for real against stand-ins for the programs it calls (orgene_cli.py, ollama_runner.py,
repair_prompt_budget.py, reuse_c0_as_c3l.py), which only log their arguments; no model, no case text.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))

STUB = r'''import json, os, sys
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.environ["RC_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps([name] + args) + "\n")


def val(flag):
    return args[args.index(flag) + 1] if flag in args else None


if name == "orgene_cli.py" and args and args[0] == "validate" and val("--round") == "0":
    # round 0 asks for one repair, later rounds for none
    with open(os.path.join(val("--run"), "requests." + val("--cond") + ".repair1.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"request_id": "toy-1." + val("--cond"), "case_id": "toy-1", "messages": []}) + "\n")
if name == "repair_prompt_budget.py":
    sys.exit(int(os.environ.get("BUDGET_RC", "0")))
'''
CLEAR = ("REGISTRY", "REGISTRY_ENTRY", "NUM_CTX", "KEEP_ALIVE", "OLLAMA_EXTRA", "ROUND0_FROM", "MAX_ROUNDS", "BUDGET_RC")


@pytest.fixture
def sandbox(tmp_path):
    for rel in ("runtime/orgene_cli.py", "runtime/ollama_runner.py", "analysis/repair_prompt_budget.py",
                "analysis/reuse_c0_as_c3l.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(STUB, encoding="utf-8")
    shutil.copy(os.path.join(RUNTIME, "run_condition.sh"), tmp_path / "runtime" / "run_condition.sh")
    (tmp_path / "configs").mkdir()
    shutil.copy(os.path.join(ROOT, "configs", "model_registry.json"), tmp_path / "configs" / "model_registry.json")
    (tmp_path / "run").mkdir()
    return tmp_path


def _run(sb, *args, **env):
    log = sb / "calls.jsonl"
    if log.exists():
        log.unlink()
    e = {k: v for k, v in os.environ.items() if k not in CLEAR}
    e.update(ORGENE_PY=sys.executable, RC_LOG=str(log), **env)
    p = subprocess.run(["bash", str(sb / "runtime" / "run_condition.sh"), str(sb / "run"), *args],
                       capture_output=True, text=True, timeout=120, env=e)
    calls = [json.loads(line) for line in open(log, encoding="utf-8")] if log.exists() else []
    return p, calls


def _val(call, flag):
    return call[call.index(flag) + 1] if flag in call else None


def _runner_calls(calls):
    return [c for c in calls if c[0] == "ollama_runner.py"]


def test_every_runner_call_names_the_registry_entry(sandbox):
    p, calls = _run(sandbox, "C3", "cases.jsonl")
    assert p.returncode == 0, p.stderr
    runs = _runner_calls(calls)
    assert [_val(c, "--out").rsplit("/", 1)[-1] for c in runs] == ["gen.C3.r0", "gen.C3.repair1"]
    reg = str(sandbox / "configs" / "model_registry.json")
    for c in runs:
        assert _val(c, "--registry") == reg and _val(c, "--registry-entry") == "qwen3-8b.main", c
        assert (_val(c, "--num-ctx"), _val(c, "--num-predict"), _val(c, "--keep-alive"), _val(c, "--temperature")) == \
            ("32768", "6000", "0", "0"), c
        assert "--think" not in c
    budget = [c for c in calls if c[0] == "repair_prompt_budget.py"]
    assert len(budget) == 1 and "--think" not in budget[0]
    assert (_val(budget[0], "--num-ctx"), _val(budget[0], "--num-predict")) == ("32768", "6000")
    # the budget check comes before the repair round's generation
    names = [c[0] for c in calls]
    assert names.index("repair_prompt_budget.py") < max(i for i, n in enumerate(names) if n == "ollama_runner.py")


def test_registry_entry_from_argument_or_environment(sandbox):
    _, calls = _run(sandbox, "C3", "cases.jsonl", "qwen3:8b", "6000", "1", "0", "qwen3-8b.r0-v5",
                    NUM_CTX="16384", KEEP_ALIVE="30m")
    c = _runner_calls(calls)[0]
    assert (_val(c, "--registry-entry"), _val(c, "--num-ctx"), _val(c, "--keep-alive")) == ("qwen3-8b.r0-v5", "16384", "30m")
    _, calls = _run(sandbox, "C3", "cases.jsonl", REGISTRY_ENTRY="qwen3-8b.r0-ctx16k", NUM_CTX="16384")
    assert {_val(c, "--registry-entry") for c in _runner_calls(calls)} == {"qwen3-8b.r0-ctx16k"}
    _, calls = _run(sandbox, "C3", "cases.jsonl", "qwen3:8b", "6000", "1", "0", "qwen3-8b.var07",
                    REGISTRY_ENTRY="qwen3-8b.r0-ctx16k")
    assert {_val(c, "--registry-entry") for c in _runner_calls(calls)} == {"qwen3-8b.var07"}  # the argument wins


def test_missing_registry_file_stops_before_anything(sandbox):
    p, calls = _run(sandbox, "C3", "cases.jsonl", REGISTRY=str(sandbox / "no-registry.json"))
    assert p.returncode != 0 and "model registry not found" in p.stderr and calls == []


def test_think_is_passed_to_the_budget_check(sandbox):
    _, calls = _run(sandbox, "C3", "cases.jsonl", OLLAMA_EXTRA="--think")
    budget = [c for c in calls if c[0] == "repair_prompt_budget.py"]
    assert len(budget) == 1 and "--think" in budget[0]
    assert all("--think" in c for c in _runner_calls(calls))


@pytest.mark.parametrize("rc", ["1", "2"])
def test_repair_round_over_budget_stops_the_run(sandbox, rc):
    # 1: a prompt does not fit; 2: the local count is unavailable. Either way the round is not generated.
    p, calls = _run(sandbox, "C3", "cases.jsonl", BUDGET_RC=rc)
    assert p.returncode != 0 and "repair round 1 stopped" in p.stderr
    assert [_val(c, "--out").rsplit("/", 1)[-1] for c in _runner_calls(calls)] == ["gen.C3.r0"]
    assert not [c for c in calls if c[0] == "orgene_cli.py" and c[1] in ("score", "report")]
    assert not [c for c in calls if c[0] == "orgene_cli.py" and c[1] == "validate" and _val(c, "--round") == "1"]


def test_reused_round0_must_come_from_the_same_registry_entry(sandbox):
    _, calls = _run(sandbox, "C3L", "cases.jsonl", ROUND0_FROM=str(sandbox / "run"))
    reuse = [c for c in calls if c[0] == "reuse_c0_as_c3l.py"]
    assert len(reuse) == 1 and _val(reuse[0], "--expect-registry-entry") == "qwen3-8b.main"
    assert [_val(c, "--out").rsplit("/", 1)[-1] for c in _runner_calls(calls)] == ["gen.C3L.repair1"]

"""E17: the ORLM anchor adapter, llama-server's native /completion backend, the registry entry, and the solve
recorder's coptpy path.

No model is called and COPT is never run: generation goes to an in-process (or launched) stand-in llama-server, and
programs run against a stand-in `coptpy` package in a throw-away virtual environment. Fixtures are self-made; the
only benchmark-free real text used is the author-written smoke cases' problem text (prompt hashes).
The optional real-coptpy test runs only with ORGENE_COPT_TESTS=1 and ORGENE_BASELINES_PY set.
"""
import ast
import copy
import hashlib
import json
import os
import re
import socket
import stat
import subprocess
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
for p in (RUNTIME, os.path.join(ROOT, "baselines"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import orlm_adapter as OA  # noqa: E402
import orlm_fixtures as FX  # noqa: E402
from fake_llama_server import FakeLlamaServer  # noqa: E402
from orgene import misreport as MIS  # noqa: E402
from orgene import model_registry as MR  # noqa: E402
from orgene import paths as PA  # noqa: E402
from orgene import score as SC  # noqa: E402
from orgene import solve_recorder as SR  # noqa: E402
from orgene.backends import make_backend  # noqa: E402
from orgene.backends.base import OptionsError, RegistryMismatch, missing_call_fields, registry_guard, request_sha256  # noqa: E402
from orgene.backends import llamacpp as LC  # noqa: E402
from orgene.execute import run_program  # noqa: E402

REG_PATH = os.path.join(ROOT, "configs", "model_registry.json")
ENTRY_ID = "orlm-llama3-8b.anchor"
GGUF_NAME = "ORLM-LLaMA-3-8B-F16.gguf"
TEMP_NAME = re.compile(r"orgene_(exec|rec)_[A-Za-z0-9_]+")


def _entry():
    return MR.read(REG_PATH)["entries"][ENTRY_ID]


def _opts():
    return dict(_entry()["opts"])


# ------------------------------------------------------------------------------------------------ prompt and template


def test_template_and_add_script_are_orlm_verbatim():
    # pinned: changing either one is a change of the anchor's method and must be deliberate
    assert OA.TEMPLATE_SHA256 == "4b5e5ea9e6db1227273a65a2853a9613214278042161fa6339b7a4d332ec3f4e"
    assert OA.ADD_SCRIPT_SHA256 == "78b499244e7a044f93f29125ca9111e1fc0bb8c700c73ba9a5073b4a7be54635"
    assert OA.orlm_prompt("  Maximise x.  \n") == (
        "Below is an operations research question. Build a mathematical model and corresponding python code using "
        "`coptpy` that appropriately addresses the question.\n\n# Question:\nMaximise x.\n\n# Response:")
    # the registry entry names the same template
    assert _entry()["identity"]["prompt_template_sha256"] == OA.TEMPLATE_SHA256


def test_prompts_match_the_baseline_environment_record_on_the_smoke_cases():
    """The environment task sent sha256-recorded official prompts for the three author-written smoke cases."""
    smoke = os.path.join(ROOT, "data", "cases", "smoke.jsonl")
    if not os.path.exists(smoke):
        pytest.skip("data/cases/smoke.jsonl not in this checkout")
    want = {"smoke-001": "26045e060f1f728a0e515948b7cbffa1ed128178703cde264e29cd8619b5c7be",
            "smoke-002": "dc5205ec3710a1a24d5c4c930a95d0549d386d2c74a3a1fd0b16e92da9741ad3",
            "smoke-003": "e645a126d437e1ff693540020b48ce65781e2d785b90db172fbfddc5cf04a929"}
    got = {}
    for line in open(smoke, encoding="utf-8"):
        r = json.loads(line)
        if r.get("source_id") in want:
            got[r["source_id"]] = OA.sha256_text(OA.orlm_prompt(r["text"]))
    assert got == want


# ------------------------------------------------------------------------------------------------ code extraction

CODE = "import coptpy as cp\nprint(1)\n"


@pytest.mark.parametrize("text, script, reason, closed", [
    (FX.answer(CODE), "\n" + CODE, None, True),                                              # ORLM's usual layout
    (FX.answer(CODE) + "\n```python\nprint(2)\n```\n", "\n" + CODE, None, True),              # a second block is ignored
    ("## Model\nno code at all", None, "no_python_block", None),
    (FX.answer(CODE, fence="```Python"), None, "no_python_block", None),                    # the official search is exact
    (FX.answer(CODE, fence="```"), None, "no_python_block", None),                          # a bare fence is not python
    ("```python\n   \n```", None, "empty_python_block", True),
    (FX.answer(CODE, closing=None), "\n" + CODE[:-1], None, False),                        # unclosed: last char dropped
    ("text ```python3\nx = 1\n``` more", "3\nx = 1\n", None, True),                          # official quirk, kept
    ("```python\nx = 1\n```text```python\ny = 2\n```", "\nx = 1\n", None, True),
])
def test_extraction_follows_orlm_eval_execute(text, script, reason, closed):
    got, info = OA.extract_code(text)
    assert got == script
    assert info["ok"] is (script is not None) and info["reason"] == reason and info["block_closed"] is closed
    assert info["method"] == "orlm_official_first_python_block"


def test_extraction_matches_a_literal_transcription_of_the_official_lines():
    """eval/execute.py lines 94-105 transcribed literally; every fixture above must agree with it."""
    def official(output):
        start = output.find("```python")
        if start == -1:
            return None
        end = output.find("```", start + 9)
        script = output[start:end].replace("```python", "")
        return None if script.strip() == "" else script
    texts = [FX.answer(CODE), FX.answer(CODE, closing=None), "```python\n\n```", "a ```python\nq\n", "```pythonx=1```",
             FX.answer(FX.program()), "nothing", "```python```"]
    for t in texts:
        assert OA.extract_code(t)[0] == official(t)


# ------------------------------------------------------------------------------------------------ status mapping


def test_status_words_normalise_to_the_copt_constant_names():
    names = [n for n, _ in OA.COPT_STATUS_LABELS]
    labels = [lbl for _, lbl in OA.COPT_STATUS_LABELS]
    assert len(set(names)) == len(names) and len(set(labels)) == len(labels)
    assert dict(OA.COPT_STATUS_LABELS)["OPTIMAL"] == "Optimal"
    assert dict(OA.COPT_STATUS_LABELS)["INFEASIBLE"] == "Infeasible"
    assert dict(OA.COPT_STATUS_LABELS)["UNBOUNDED"] == "Unbounded"
    for n, lbl in OA.COPT_STATUS_LABELS:
        assert MIS.canonical_status(lbl) == MIS.canonical_status(n), (n, lbl)
    # every name the harness maps is a name the solve recorder records (so printed and recorded status can agree)
    assert set(names) == set(SR.COPT_STATUS_NAMES)


def test_status_words_under_the_main_scoring_function():
    assert SC.is_correct(None, None, "infeasible", status="Infeasible")[0]
    assert SC.is_correct(None, None, "unbounded", status="Unbounded")[0]
    assert not SC.is_correct(None, None, "infeasible", status="Optimal")[0]
    assert not SC.is_correct(None, None, "infeasible", status="Unstarted")[0]
    # The scoring rule fixed before the freeze (2026-09-29): status words are compared by category, and COPT's
    # undecided INF_OR_UNB and the local results never match a non-numeric reference (the earlier substring test let
    # "Infeasible or Unbounded" match an infeasible or an unbounded reference, and "Local Infeasible" an infeasible one).
    for ref in ("infeasible", "unbounded"):
        assert SC.is_correct(None, None, ref, status="Infeasible or Unbounded") == (False, "status_undecided")
    assert SC.is_correct(None, None, "infeasible", status="Local Infeasible") == (False, "status_undecided")
    cats = {lbl: SC.status_category(lbl) for _, lbl in OA.COPT_STATUS_LABELS}
    assert {lbl for lbl, c in cats.items() if c in SC.MATCHABLE_STATUS_CATEGORIES} == {"Infeasible", "Unbounded"}
    assert {lbl for lbl, c in cats.items() if c in SC.UNDECIDED_STATUS_CATEGORIES} == {
        "Infeasible or Unbounded", "Local Optimal", "Local Infeasible"}


# ------------------------------------------------------------------------------------------------ the harness, run


@pytest.fixture(scope="module")
def fake_py(tmp_path_factory):
    py = FX.make_fake_venv(str(tmp_path_factory.mktemp("fakecopt") / "venv"))
    if py is None:
        pytest.skip("could not create a throw-away virtual environment")
    return py


def _run(fake_py, code, harness=True):
    script, info = OA.extract_code(FX.answer(code))
    assert info["ok"]
    return run_program(OA.build_program(script) if harness else script, timeout=60, python=fake_py)


def test_harness_prints_the_protocol_lines_for_an_optimal_model(fake_py):
    ex = _run(fake_py, FX.program("OPTIMAL:2600"))
    assert ex["exec_ok"] and ex["protocol_ok"], ex["stderr_tail"]
    assert ex["status"] == "Optimal" and ex["objective"] == 2600.0
    lines = ex["stdout_tail"].splitlines()
    assert lines[-2:] == ["STATUS: Optimal", "FINAL_OBJECTIVE: 2600.0"]
    assert "Just print the best solution: 2600.0" in lines and "Maximum total profit: 2600.0" in lines
    note = OA.parse_harness(ex["stdout_tail"])
    assert note == {"target": "model", "official_add_script": "ok", "status_code": 1}
    # the solve recorder saw the (compiled-module) Model.solve call, recorded under the backend name coptpy
    assert ex["solve_recorder"]["recorded"] and ex["solve_recorder"]["n_solves"] == 1
    (s,) = ex["solve_records"]
    assert s["backend"] == "coptpy" and s["entry"] == "Model.solve" and s["status"] == "OPTIMAL"
    assert s["objective"] == 2600.0 and s["sense"] == "maximize" and s["n_variables"] == 2 and s["n_constraints"] == 2
    mr = MIS.misreport(ex)
    assert mr["consistent"] is True and mr["any_misreport"] is False and mr["reported_without_solve"] is False
    assert OA.official_prediction(ex, note) == ("2600.0", "best_solution")
    assert OA.copt_flags(ex) == {"size_limited": False, "no_license_notice": True}


@pytest.mark.parametrize("name, label", [(n, lbl) for n, lbl in OA.COPT_STATUS_LABELS if n != "OPTIMAL"] + [("99", "99")])
def test_harness_maps_every_status_and_prints_na(fake_py, name, label):
    ex = _run(fake_py, FX.program(f"{name}:7"))
    assert ex["exec_ok"] and ex["status"] == label and ex["objective"] is None
    assert ex["stdout_tail"].splitlines()[-1] == "FINAL_OBJECTIVE: NA"
    assert OA.official_prediction(ex, OA.parse_harness(ex["stdout_tail"])) == ("No Best Solution", "no_best_solution")
    mr = MIS.misreport(ex)
    assert mr["status_misreport"] is False and mr["objective_misreport"] is False, (name, mr)


def test_harness_uses_the_only_copt_model_when_it_is_not_called_model(fake_py):
    ex = _run(fake_py, FX.program("OPTIMAL:5360", model_var="m"))
    note = OA.parse_harness(ex["stdout_tail"])
    assert note["target"] == "global:m" and ex["status"] == "Optimal" and ex["objective"] == 5360.0
    # officially ADD_SCRIPT reads the global `model`: NameError there, so the official column has no prediction
    assert note["official_add_script"] == "NameError" and ex["exec_ok"]
    assert OA.official_prediction(ex, note) == (None, "failed:add_script")


def test_official_add_script_needs_the_copt_name_the_protocol_lines_do_not(fake_py):
    ex = _run(fake_py, FX.program("OPTIMAL:380", import_copt_name=False))
    note = OA.parse_harness(ex["stdout_tail"])
    assert note["target"] == "model" and note["official_add_script"] == "NameError"
    assert ex["status"] == "Optimal" and ex["objective"] == 380.0
    assert OA.official_prediction(ex, note)[0] is None


def test_no_protocol_lines_when_the_model_is_not_a_global(fake_py):
    ex = _run(fake_py, FX.program("OPTIMAL:2600", main_function=True))
    note = OA.parse_harness(ex["stdout_tail"])
    assert note["target"] == "none" and not ex["protocol_ok"] and ex["status"] is None and ex["objective"] is None
    assert ex["solve_recorder"]["n_solves"] == 1           # the solve happened and was recorded
    mr = MIS.misreport(ex)
    assert mr["any_misreport"] is False and mr["reported_without_solve"] is False  # the harness claims nothing


def test_two_models_without_a_global_model_are_ambiguous(fake_py):
    code = FX.program("OPTIMAL:1", model_var="m1") + "\n" + FX.program("OPTIMAL:2", model_var="m2").split("\n", 2)[2]
    ex = _run(fake_py, code)
    assert OA.parse_harness(ex["stdout_tail"])["target"] == "ambiguous" and not ex["protocol_ok"]
    assert MIS.misreport(ex)["multi_problem"] is True


def test_a_program_that_crashes_never_reaches_the_harness(fake_py):
    ex = _run(fake_py, FX.program("OPTIMAL:2600", extra="raise ValueError('boom')\n"))
    assert ex["returncode"] == 1 and OA.parse_harness(ex["stdout_tail"]) is None and not ex["protocol_ok"]
    assert OA.official_prediction(ex, None) == (None, "failed:exit")


def test_copt_size_limit_is_flagged(fake_py):
    ex = _run(fake_py, FX.program("SIZE_LIMIT"))
    assert ex["returncode"] == 1 and OA.copt_flags(ex) == {"size_limited": True, "no_license_notice": True}
    (s,) = ex["solve_records"]
    assert s["backend"] == "coptpy" and s["error"] and s["status"] == "UNSTARTED"


# ------------------------------------------------------------------------------------------------ harness is inert


def _solves(ex):
    return [{k: v for k, v in s.items() if k not in ("t", "seconds")} for s in ex["solve_records"] or []]


@pytest.mark.parametrize("code", [
    FX.program("OPTIMAL:2600"), FX.program("INFEASIBLE"), FX.program("OPTIMAL:2600", main_function=True),
    FX.program("OPTIMAL:1", model_var="m"), FX.program("OPTIMAL:2600", extra="raise ValueError('boom')\n"),
    FX.program("SIZE_LIMIT"), FX.program("OPTIMAL:9", extra="model.solveLP()\nmodel.solve()\n"),
    "import coptpy\nprint('no model')\n", "x = (\n",
])
def test_the_appended_harness_does_not_change_the_programs_solver_calls(fake_py, code):
    alone = _run(fake_py, code, harness=False)
    withh = _run(fake_py, code, harness=True)
    assert _solves(withh) == _solves(alone)
    assert (withh["solve_recorder"] or {}).get("n_solves") == (alone["solve_recorder"] or {}).get("n_solves")
    assert withh["returncode"] == alone["returncode"] and withh["timed_out"] == alone["timed_out"]
    assert withh["stdout_tail"].startswith(alone["stdout_tail"])      # the harness only adds lines at the end
    extra = withh["stdout_tail"][len(alone["stdout_tail"]):].splitlines()
    assert all(x.startswith(("Just print the best solution:", "No Best Solution", OA.HARNESS_MARKER, "STATUS:",
                             "FINAL_OBJECTIVE:")) for x in extra), extra
    if alone["returncode"] == 0:
        assert TEMP_NAME.sub("X", withh["stderr_tail"]) == TEMP_NAME.sub("X", alone["stderr_tail"])


def test_the_harness_source_calls_no_solver_and_defines_only_prefixed_names():
    tree = ast.parse(OA.HARNESS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"solve", "solveLP", "optimize", "setParam", "setObjective", "addConstr",
                                          "addVar", "write", "read", "reset", "dispose"}, node.func.attr
    for node in tree.body:
        targets = [node.name] if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else \
            [t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)]
        assert all(t.lower().startswith("_orgene") for t in targets), targets
    assert OA.ORLM_ADD_SCRIPT in eval(compile(ast.Expression(tree.body[0].value), "h", "eval"))  # verbatim inside


# ------------------------------------------------------------------------------------------------ official column


@pytest.mark.parametrize("pred, obj, status, raw, ok, reason", [
    ("2600.0", 2600.0, None, None, True, "match"),
    ("2600.4", 2600.0, None, None, True, "match"),
    ("2700.0", 2600.0, None, None, True, "match"),            # 100/2600 = 3.8 % after rounding
    ("2731.0", 2600.0, None, None, False, "mismatch"),        # 131/2600 = 5.04 %
    ("2730.0", 2600.0, None, None, True, "match"),            # 130/2600 = 5 % exactly
    ("2.5", 2.4, None, None, True, "match"),                   # round() halves to even: 2 vs 2
    ("3.5", 3.0, None, None, False, "mismatch"),               # 4 vs 3
    ("0.4", 0.0, None, None, True, "match"),                   # g == 0: |round(p)| <= 0.05
    ("0.6", 0.0, None, None, False, "mismatch"),
    ("-105", -100.0, None, None, True, "match"),
    ("No Best Solution", None, "infeasible", None, True, "no_best_solution_match"),
    ("12.0", None, "infeasible", None, False, "no_best_solution_mismatch"),
    ("No Best Solution", None, None, "No Best Solution", True, "no_best_solution_match"),
    ("No Best Solution", 5.0, None, None, False, "no_best_solution_predicted"),
    (None, 5.0, None, None, False, "no_prediction"),
    ("nan", 5.0, None, None, False, "prediction_not_numeric"),
    ("1e400", 5.0, None, None, False, "prediction_not_numeric"),
    ("abc", 5.0, None, None, False, "prediction_not_numeric"),
    ("5", None, None, "something else", False, "reference_not_numeric"),
])
def test_official_judge(pred, obj, status, raw, ok, reason):
    assert OA.official_judge(pred, obj, status, raw) == (ok, reason)


def test_official_prediction_reads_stdout_like_eval_execute():
    ok = {"returncode": 0, "timed_out": False}
    assert OA.official_prediction(None, None) == (None, "failed:no_code")
    assert OA.official_prediction(dict(ok, timed_out=True), None) == (None, "failed:timeout")
    assert OA.official_prediction(dict(ok, returncode=1, stdout_tail="Just print the best solution: 3"), None) == \
        (None, "failed:exit")
    assert OA.official_prediction(dict(ok, stdout_tail="a\nJust print the best solution: 12.5\nSTATUS: Optimal"),
                                  {"official_add_script": "ok"}) == ("12.5", "best_solution")
    assert OA.official_prediction(dict(ok, stdout_tail="No Best Solution\n"), {"official_add_script": "ok"}) == \
        ("No Best Solution", "no_best_solution")
    assert OA.official_prediction(dict(ok, stdout_tail="Just print the best solution: 1"),
                                  {"official_add_script": "AttributeError"}) == (None, "failed:add_script")
    assert OA.official_prediction(dict(ok, stdout_tail="nothing"), None) == (None, "out_of_expectation")
    # a program that exits early with status 0: the official parse still reads whatever it printed
    assert OA.official_prediction(dict(ok, stdout_tail="No Best Solution"), None) == ("No Best Solution",
                                                                                      "no_best_solution")


# ------------------------------------------------------------------------------------------------ backend


@pytest.fixture
def fls():
    s = FakeLlamaServer(answer_for=lambda p: FX.answer(FX.program()))
    yield s
    s.close()


def test_completion_backend_sends_the_raw_prompt_and_every_option(fls):
    b = LC.LlamaCppCompletionBackend("orlm-llama3-8b-f16", host=fls.url, retry_sleep=0, digest="a" * 64)
    prompt = OA.orlm_prompt("Maximise x.")
    rec = b.call([{"role": "user", "content": prompt}], _opts())
    (body,) = fls.completions()
    assert body["prompt"] == prompt and "messages" not in body and body["stream"] is False
    assert {k: body[k] for k in _opts()} == _opts() and body["cache_prompt"] is False and body["stop"] == ["</s>"]
    assert missing_call_fields(rec) == [] and rec["request_sha256"] == request_sha256(body)
    assert rec["done_reason"] == "stop" and rec["stop_type"] == "eos" and rec["prompt_truncated"] is False
    assert rec["prompt_eval_count"] == len(prompt.split()) and rec["eval_count"] > 0
    assert rec["settings_echo_mismatch"] == [] and rec["settings_echo_missing"] == []
    assert rec["content"] == FX.answer(FX.program()) and rec["digest"] == "a" * 64
    ident = b.identity()
    assert ident["backend"] == "llamacpp_completion" and ident["model_file"] == GGUF_NAME
    assert ident["total_slots"] == 1 and ident["n_ctx"] == 8192 and ident["build_info"].startswith("b10621")
    assert not PA.find_absolute_paths(json.dumps(rec)) and not PA.find_absolute_paths(json.dumps(ident))


def test_completion_backend_maps_stop_types_and_flags_truncation(fls):
    b = LC.LlamaCppCompletionBackend("orlm-llama3-8b-f16", host=fls.url, retry_sleep=0)
    fls.stop_type, fls.truncated = "limit", True
    rec = b.call([{"role": "user", "content": "p"}], _opts())
    assert rec["done_reason"] == "length" and rec["stop_type"] == "limit" and rec["prompt_truncated"] is True
    fls.stop_type = "word"
    assert b.call([{"role": "user", "content": "p"}], _opts())["done_reason"] == "stop"


def test_completion_backend_reports_settings_the_server_did_not_apply(fls):
    b = LC.LlamaCppCompletionBackend("orlm-llama3-8b-f16", host=fls.url, retry_sleep=0)
    fls.echo_override = {"top_k": 40, "top_p": 0.9999999}      # 32-bit float echo of 1.0 is not a difference
    rec = b.call([{"role": "user", "content": "p"}], _opts())
    assert rec["settings_echo_mismatch"] == ["top_k"]
    fls.echo_override = {}
    o = dict(_opts(), top_p=0.95)
    fls.echo_override = {"top_p": 0.949999988079071}
    assert b.call([{"role": "user", "content": "p"}], o)["settings_echo_mismatch"] == []


def test_completion_backend_refuses_before_sending(fls):
    b = LC.LlamaCppCompletionBackend("orlm-llama3-8b-f16", host=fls.url, retry_sleep=0)
    u = [{"role": "user", "content": "p"}]
    for msgs in ([{"role": "system", "content": "s"}] + u, [{"role": "system", "content": "p"}], u + u):
        with pytest.raises(OptionsError):
            b.call(msgs, _opts())
    for k in LC.COMPLETION_REQUIRED_OPTS:
        with pytest.raises(OptionsError):
            b.call(u, {x: v for x, v in _opts().items() if x != k})
    for bad in (dict(_opts(), cache_prompt="false"), dict(_opts(), stop="</s>"), dict(_opts(), n_predict=1.5),
                dict(_opts(), max_tokens=10), dict(_opts(), temperature=float("nan"))):
        with pytest.raises(OptionsError):
            b.call(u, bad)
    with pytest.raises(OptionsError):
        b.call(u, _opts(), fmt="json")
    e = _entry()
    with pytest.raises(RegistryMismatch):
        b.call(u, dict(_opts(), n_predict=8192), guard=registry_guard(e, backend=b))
    assert fls.completions() == []


def test_make_backend_and_registry_spec_agree():
    assert make_backend("llamacpp_completion", "m", host="http://127.0.0.1:9").kind == "llamacpp_completion"
    spec = MR.BACKENDS["llamacpp_completion"]
    assert tuple(spec["required"]) == LC.COMPLETION_REQUIRED_OPTS
    assert set(spec["int"]) == set(LC.COMPLETION_INT_OPTS) and set(spec["float"]) == set(LC.COMPLETION_FLOAT_OPTS)
    assert set(spec["bool"]) == set(LC.COMPLETION_BOOL_OPTS) and set(spec["other"]) == set(LC.COMPLETION_OTHER_OPTS)


# ------------------------------------------------------------------------------------------------ registry entry


def test_committed_anchor_entry_is_a_pending_greedy_draft():
    reg = MR.read(REG_PATH)
    assert MR.validate(reg) == []
    e = reg["entries"][ENTRY_ID]
    anchor = reg["anchors"]["orlm"]
    assert e["backend"] == "llamacpp_completion" and OA.entry_is_pending(e) and e["status"] == "pending"
    # one pending marker for the whole registry: the purpose no longer carries it
    assert not str(e["purpose"]).upper().startswith("PENDING") and "PENDING" not in anchor["run_settings"]
    assert OA.entry_is_pending(dict(e, status=None)) is False and OA.entry_is_pending(
        {k: v for k, v in e.items() if k != "status"}) is False
    assert e["digest"] == anchor["gguf"]["sha256"] and e["identity"]["gguf_file"] == anchor["gguf"]["file"] == GGUF_NAME
    o = e["opts"]
    assert o["temperature"] == 0 and o["top_k"] == 0 and o["top_p"] == 1 and o["min_p"] == 0 and o["typical_p"] == 1
    assert o["repeat_penalty"] == 1 and o["presence_penalty"] == 0 and o["frequency_penalty"] == 0
    assert o["dry_multiplier"] == 0 and o["xtc_probability"] == 0 and o["mirostat"] == 0
    assert o["cache_prompt"] is False and o["stop"] == ["</s>"] and o["seed"] == 1 and e["seed_rule"] == "base+k"
    s = e["identity"]["server"]
    assert set(OA.SERVER_KEYS) <= set(s) and s["ctx_size"] == anchor["ollama"]["modelfile_params"]["num_ctx"] == 8192
    assert s["parallel"] == 1 and s["cache_type_k"] == s["cache_type_v"] == "f16" and s["cache_ram_mib"] == 0
    assert s["context_shift"] is False and s["cache_reuse"] == 0
    assert e["identity"]["llama_cpp_build"] == reg["baselines"]["llama_cpp"]["build"]
    assert ENTRY_ID in anchor["run_settings"]
    # the runners' guard and the registry's own comparison accept exactly these settings
    b = LC.LlamaCppCompletionBackend(e["model"], host="http://127.0.0.1:9", digest=e["digest"])
    b._identity = {"digest": e["digest"]}
    sent = b.sent_opts(b.build_body([{"role": "user", "content": "x"}], o))
    registry_guard(e, backend=b)(sent)
    assert MR.compare_sent(e, sent, backend_kind=b.kind, model=e["model"], digest=e["digest"]) == []
    for bad in (dict(o, n_predict=-1), dict(o, cache_prompt=True), dict(o, stop=["</s>", "<|eot_id|>"])):
        with pytest.raises(RegistryMismatch):
            registry_guard(e, backend=b)(b.sent_opts(b.build_body([{"role": "user", "content": "x"}], bad)))


def test_server_command_line_comes_from_the_entry():
    argv = OA.server_argv(_entry(), "/tmp/x/" + GGUF_NAME, binary="llama-server", port=8123)
    s = " ".join(argv)
    for frag in ("-m /tmp/x/" + GGUF_NAME, "--alias orlm-llama3-8b-f16", "--port 8123", "-c 8192", "-np 1", "-ctk f16",
                 "-ctv f16", "-fa off", "-ngl all", "-b 2048", "-ub 512", "--no-context-shift", "--cache-ram 0",
                 "--cache-reuse 0", "--no-webui", "--offline"):
        assert frag in s, frag
    bad = copy.deepcopy(_entry())
    del bad["identity"]["server"]["cache_type_k"]
    with pytest.raises(SystemExit):
        OA.server_argv(bad, GGUF_NAME)


# ------------------------------------------------------------------------------------------------ solve recorder


def test_recorder_records_a_model_class_from_the_compiled_coptcore_module(monkeypatch, tmp_path):
    """coptpy 8.0.7's Model has __module__ == "coptcore"; the recorder keyed only by "coptpy" missed every solve."""
    fake = types.ModuleType("coptpy")

    class COPT:
        OPTIMAL = 1
    fake.COPT = COPT
    monkeypatch.setitem(sys.modules, "coptpy", fake)

    class _Bound:
        __name__ = "solve"

        def __init__(self, m):
            self.__self__ = m

        def __call__(self):
            self.__self__.status, self.__self__.objval = 1, 4.0

    class Model:
        __module__ = "coptcore"
        solve = property(lambda self: _Bound(self))
        status, objval = 0, 0.0

        def getAttr(self, name):
            return {"Cols": 1, "Rows": 1, "ObjSense": 1}[name]

    src = "m = Model()\nm.solve()\n"
    results = {}
    for label, c_methods in (("fixed", SR.C_SOLVE_METHODS), ("old", {("coptpy", "Model"): ("solve", "solveLP")})):
        path = tmp_path / f"{label}.jsonl"
        rec = SR.Recorder(str(path), c_methods=c_methods)
        if rec.start() is not None:
            pytest.skip("no free sys.monitoring tool id in this process")
        try:
            code = compile(src, f"fake_prog_{label}.py", "exec")
            rec.watch_prog(code)
            exec(code, {"__name__": "fake_prog", "Model": Model})
        finally:
            rec.stop()
            rec.out.close()
        from orgene.execute import read_solve_log
        results[label] = read_solve_log(str(path))[0]
    (s,) = results["fixed"]
    assert s["backend"] == "coptpy" and s["status"] == "OPTIMAL" and s["objective"] == 4.0
    assert results["old"] == []    # the negative control: the key the recorder had before E17


def test_recorder_records_an_unbound_compiled_method_on_a_coptcore_model(tmp_path):
    """The call shape of real coptpy 8.0.7 (read-only import): Model.solve is a compiled method descriptor with no
    __self__, so `model.solve()` reaches the recorder as the unbound method with the model as its first argument, and
    type(model).__module__ == "coptcore". Stand-in: a deque subclass named Model in module coptcore, whose C method
    `clear` plays `solve` (E17 verification)."""
    import collections
    Model = type("Model", (collections.deque,), {"__module__": "coptcore"})
    assert not hasattr(Model.clear, "__self__")
    src = "m = Model([1])\nm.clear()\nn = Model()\nn.clear()\n"
    results = {}
    for label, key in (("coptcore", ("coptcore", "Model")), ("coptpy_only", ("coptpy", "Model"))):
        path = tmp_path / f"{label}.jsonl"
        rec = SR.Recorder(str(path), c_methods={key: ("clear",)})
        if rec.start() is not None:
            pytest.skip("no free sys.monitoring tool id in this process")
        try:
            code = compile(src, f"fake_prog_{label}.py", "exec")
            rec.watch_prog(code)
            exec(code, {"__name__": "fake_prog", "Model": Model})
        finally:
            rec.stop()
            rec.out.close()
        from orgene.execute import read_solve_log
        results[label] = read_solve_log(str(path))[0]
    solves = results["coptcore"]
    assert [(s["backend"], s["entry"], s["problem_ordinal"]) for s in solves] == [
        ("coptpy", "Model.clear", 1), ("coptpy", "Model.clear", 2)]
    assert results["coptpy_only"] == []


# ------------------------------------------------------------------------------------------------ the stages


TOY_CASES = [
    ("toy-001", "Plan A: maximise profit.", 2600.0, None, FX.answer(FX.program("OPTIMAL:2600"))),
    ("toy-002", "Plan B: maximise profit.", 2601.0, None, FX.answer(FX.program("OPTIMAL:2600"))),
    ("toy-003", "Plan C: no code.", 100.0, None, "I cannot write code for this."),
    ("toy-004", "Plan D: crash.", 5000.0, None, FX.answer(FX.program("OPTIMAL:5000", extra="raise ValueError('x')\n"))),
    ("toy-005", "Plan E: infeasible.", None, "infeasible", FX.answer(FX.program("INFEASIBLE"))),
    ("toy-006", "Plan F: unclosed.", 380.0, None, FX.answer(FX.program("OPTIMAL:380"), closing=None)),
]


def _cases_file(tmp_path):
    p = tmp_path / "toy.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"_header": True, "source": "toy", "n": len(TOY_CASES)}) + "\n")
        for cid, text, obj, st, _ in TOY_CASES:
            raw = "infeasible" if st else str(obj)
            f.write(json.dumps({"case_id": cid, "source": "toy", "text": text,
                                "reference": {"objective": obj, "raw": raw, "status": st}}) + "\n")
    return str(p)


def _answer_for(prompt):
    for cid, text, _, _, ans in TOY_CASES:
        if text in prompt:
            return ans
    return "no"


def _gguf(tmp_path, content=b"not really a gguf"):
    d = tmp_path / "models"
    d.mkdir(exist_ok=True)
    p = d / GGUF_NAME
    p.write_bytes(content)
    return str(p), hashlib.sha256(content).hexdigest()


def _registry(tmp_path, digest, **changes):
    """The committed registry with the entry's digest set to the toy GGUF's; changes {"a/b/c": value} (None removes)."""
    reg = MR.read(REG_PATH)
    reg["entries"][ENTRY_ID]["digest"] = digest
    for path, value in changes.items():
        obj = reg
        keys = path.split("/")
        for k in keys[:-1]:
            obj = obj[k]
        if value is None:
            obj.pop(keys[-1], None)
        else:
            obj[keys[-1]] = value
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(reg), encoding="utf-8")
    return str(p)


def _stages(tmp_path, fake_py, server, extra_generate=(), registry=None):
    cases = _cases_file(tmp_path)
    run = str(tmp_path / "run")
    gguf, digest = _gguf(tmp_path)
    reg = registry or _registry(tmp_path, digest)
    assert OA.main(["requests", "--cases", cases, "--run", run]) == 0
    rc = OA.main(["generate", "--run", run, "--registry", reg, "--gguf", gguf, "--host", server.url, "--allow-pending",
                  "--retry-sleep", "0", *extra_generate])
    return cases, run, reg, rc


def test_all_stages_on_toy_cases(tmp_path, fake_py):
    srv = FakeLlamaServer(answer_for=_answer_for)
    try:
        cases, run, reg, rc = _stages(tmp_path, fake_py, srv)
    finally:
        srv.close()
    assert rc == 0 and len(srv.completions()) == len(TOY_CASES)
    assert OA.main(["execute", "--run", run, "--python", fake_py, "--registry", reg]) == 0
    assert OA.main(["score", "--run", run, "--cases", cases]) == 0
    rows = {r["case_id"]: r for r in (json.loads(x) for x in open(os.path.join(run, "results.ORLM.jsonl")))}
    # main columns: the scoring function of every configuration
    assert rows["toy-001"]["correct"] and rows["toy-001"]["correct_orlm_official"]
    assert not rows["toy-002"]["correct"] and rows["toy-002"]["correct_orlm_official"]   # 1e-4 vs rounded 5 %
    assert not rows["toy-003"]["correct"] and not rows["toy-003"]["correct_orlm_official"]
    assert rows["toy-003"]["orlm_official_state"] == "failed:no_code"
    assert not rows["toy-004"]["correct"] and rows["toy-004"]["orlm_official_state"] == "failed:exit"
    assert rows["toy-005"]["correct"] and rows["toy-005"]["status"] == "Infeasible"
    assert rows["toy-005"]["correct_orlm_official"] and rows["toy-005"]["orlm_official_prediction"] == "No Best Solution"
    assert rows["toy-006"]["correct"]                        # unclosed block: the dropped last char was a newline
    assert rows["toy-001"]["correct_tol"] == {"1e-06": True, "0.0001": True, "0.01": True}
    assert rows["toy-001"]["verified_correct"] is True and rows["toy-001"]["misreport"]["consistent"] is True
    m = json.load(open(os.path.join(run, "metrics.ORLM.json")))
    assert m["n"] == 6 and m["n_correct"] == 3 and m["condition"] == "ORLM"
    assert m["orlm"]["official"]["n_correct"] == 4 and m["orlm"]["official"]["n_correct_original_ref"] == 4
    ex = m["orlm"]["execution"]
    assert ex["n_code"] == 5 and ex["extraction_failures"] == {"no_python_block": 1} and ex["n_block_unclosed"] == 1
    assert ex["harness_targets"] == {"model": 4} and ex["n_harness_missing"] == 1
    assert m["misreport"]["any_misreport"] == 0
    final = {v["case_id"]: v for v in (json.loads(x) for x in open(os.path.join(run, "final.ORLM.jsonl")))}
    assert final["toy-003"]["orlm"]["extraction"]["reason"] == "no_python_block" and final["toy-003"]["exec"] is None
    assert final["toy-006"]["orlm"]["extraction"]["block_closed"] is False
    cfg = json.load(open(os.path.join(run, "run_config.json")))
    g = cfg["stages"]["generate"]
    assert g["registry"]["entry_id"] == ENTRY_ID and g["entry_pending"] and g["launch_settings_verified"] is False
    assert cfg["stages"]["execute"]["coptpy"] == "8.0.7" and cfg["stages"]["execute"]["timeout_s"] == 60
    gcfg = json.load(open(os.path.join(run, "gen.ORLM", "config.json")))
    assert gcfg["backend"] == "llamacpp_completion" and gcfg["opts"]["cache_prompt"] is False
    assert not MR.verify_run_config(MR.read(reg), gcfg)
    for root, _, files in os.walk(run):
        for fn in files:
            text = open(os.path.join(root, fn), encoding="utf-8", errors="replace").read()
            assert not re.search("/" + "Users" + "/", text), fn
    assert not os.path.exists(os.path.join(run, "freeze_gate.jsonl"))      # dev toy cases: no gate needed


def test_a_pending_entry_needs_allow_pending_and_is_never_used_for_sealed_cases(tmp_path):
    srv = FakeLlamaServer(answer_for=_answer_for)
    try:
        cases = _cases_file(tmp_path)
        run = str(tmp_path / "run")
        gguf, digest = _gguf(tmp_path)
        reg = _registry(tmp_path, digest)
        OA.main(["requests", "--cases", cases, "--run", run])
        with pytest.raises(SystemExit, match=r"pending \(status\).*--allow-pending"):
            OA.main(["generate", "--run", run, "--registry", reg, "--gguf", gguf, "--host", srv.url])
        cfg = json.load(open(os.path.join(run, "run_config.json")))
        cfg["split"] = "test"                                  # as if the requests were for sealed cases
        json.dump(cfg, open(os.path.join(run, "run_config.json"), "w"))
        with pytest.raises(SystemExit, match=r"pending \(status\).*sealed"):
            OA.main(["generate", "--run", run, "--registry", reg, "--gguf", gguf, "--host", srv.url, "--allow-pending"])
        # a purpose that still reads "PENDING" is not a marker; removing the status key decides the entry
        decided = _registry(tmp_path, digest, **{f"entries/{ENTRY_ID}/status": None,
                                                 f"entries/{ENTRY_ID}/purpose": "PENDING in words only."})
        with pytest.raises(SystemExit, match="--launch"):
            OA.main(["generate", "--run", run, "--registry", decided, "--gguf", gguf, "--host", srv.url])
        with pytest.raises(SystemExit, match="test gate"):     # launch requested: the freeze gate refuses next
            OA.main(["generate", "--run", run, "--registry", decided, "--gguf", gguf, "--launch", "--llama-server",
                     "/nonexistent/llama-server"])
    finally:
        srv.close()
    assert srv.completions() == []


def test_sealed_requests_are_refused_by_the_test_gate(tmp_path):
    split = tmp_path / "split"
    split.mkdir()
    (split / "test_ids.json").write_text(json.dumps([c[0] for c in TOY_CASES]))
    with pytest.raises(SystemExit, match="test gate"):
        OA.main(["requests", "--cases", _cases_file(tmp_path), "--split-dir", str(split), "--split", "test",
                 "--run", str(tmp_path / "run")])
    assert not os.path.exists(tmp_path / "run" / "requests.ORLM.jsonl")


def test_gguf_and_server_identity_are_checked_before_any_call(tmp_path):
    srv = FakeLlamaServer(answer_for=_answer_for)
    try:
        cases = _cases_file(tmp_path)
        run = str(tmp_path / "run")
        gguf, digest = _gguf(tmp_path)
        OA.main(["requests", "--cases", cases, "--run", run])
        base = ["generate", "--run", run, "--host", srv.url, "--allow-pending", "--gguf", gguf]
        with pytest.raises(SystemExit, match="differs from the registry entry's digest"):
            OA.main(base + ["--registry", _registry(tmp_path, "0" * 64)])
        other = tmp_path / "other.gguf"
        other.write_bytes(b"x")
        with pytest.raises(SystemExit, match="registry names"):
            OA.main(["generate", "--run", run, "--host", srv.url, "--allow-pending", "--gguf", str(other),
                     "--registry", _registry(tmp_path, digest)])
        srv.n_ctx = 4096
        with pytest.raises(SystemExit, match="context"):
            OA.main(base + ["--registry", _registry(tmp_path, digest)])
    finally:
        srv.close()
    assert srv.completions() == []


def test_settings_the_server_did_not_apply_fail_the_generate_stage(tmp_path, fake_py):
    srv = FakeLlamaServer(answer_for=_answer_for)
    srv.echo_override = {"repeat_penalty": 1.1}
    try:
        _, run, _, rc = _stages(tmp_path, fake_py, srv)
    finally:
        srv.close()
    assert rc == 4
    cfg = json.load(open(os.path.join(run, "run_config.json")))
    assert cfg["stages"]["generate"]["summary"]["n_settings_echo_mismatch"] == len(TOY_CASES)


def test_execute_refuses_another_coptpy_version(tmp_path, fake_py):
    srv = FakeLlamaServer(answer_for=_answer_for)
    try:
        _, run, reg, rc = _stages(tmp_path, fake_py, srv)
    finally:
        srv.close()
    reg2 = _registry(tmp_path, json.load(open(reg))["entries"][ENTRY_ID]["digest"], **{"baselines/packages/coptpy": "9.9.9"})
    with pytest.raises(SystemExit, match="coptpy"):
        OA.main(["execute", "--run", run, "--python", fake_py, "--registry", reg2])
    assert not os.path.exists(os.path.join(run, "final.ORLM.jsonl"))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_launch_starts_the_server_with_the_entry_settings_and_stops_it(tmp_path, fake_py, monkeypatch):
    wrapper = tmp_path / "llama-server"
    wrapper.write_text(f"#!/bin/sh\nexec {FX.PY} {os.path.join(HERE, 'fake_llama_server.py')} \"$@\"\n")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("FAKE_LLAMA_ARGV_FILE", str(argv_file))
    monkeypatch.setenv("FAKE_LLAMA_ANSWER", FX.answer(FX.program("OPTIMAL:2600")))
    port = _free_port()
    ollama = _OllamaPs({"models": [{"name": "some-model:latest"}]})   # an Ollama that holds a model
    try:
        cases = _cases_file(tmp_path)
        run = str(tmp_path / "run")
        gguf, digest = _gguf(tmp_path)
        reg = _registry(tmp_path, digest)
        OA.main(["requests", "--cases", cases, "--run", run, "--limit", "2"])
        gen = ["generate", "--run", run, "--registry", reg, "--gguf", gguf, "--launch", "--llama-server", str(wrapper),
               "--port", str(port), "--allow-pending", "--server-wait", "60", "--retry-sleep", "0"]
        with pytest.raises(SystemExit, match="Ollama holds 1 model"):
            OA.main(gen + ["--ollama-host", ollama.url])
        assert not argv_file.exists()                       # nothing was started
        ollama.ps = {"models": []}
        assert OA.main(gen + ["--ollama-host", ollama.url]) == 0
    finally:
        ollama.close()
    argv = json.load(open(argv_file))
    assert argv[argv.index("-c") + 1] == "8192" and argv[argv.index("-ctk") + 1] == "f16" and "--no-context-shift" in argv
    cfg = json.load(open(os.path.join(run, "run_config.json")))
    g = cfg["stages"]["generate"]
    assert g["server_launched_by_adapter"] and g["launch_settings_verified"] and g["summary"]["n_ok"] == 2
    assert g["launch"]["argv"][2] == "<outside-root>/" + GGUF_NAME        # the model path is not recorded
    assert os.path.exists(os.path.join(run, "gen.ORLM", "llama_server.log"))
    with pytest.raises(OSError):                                          # the server was stopped
        socket.create_connection(("127.0.0.1", port), timeout=2).close()


def test_launch_refuses_a_port_where_a_server_already_answers(tmp_path):
    srv = FakeLlamaServer()
    try:
        with pytest.raises(SystemExit, match="already answers"):
            OA.LlamaServer(["/nonexistent/llama-server"], srv.url, str(tmp_path / "log")).__enter__()
    finally:
        srv.close()


class _OllamaPs:
    """A minimal stand-in for Ollama's /api/ps."""

    def __init__(self, ps):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading
        self.ps = ps
        me = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                data = json.dumps(me.ps).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


# ------------------------------------------------------------------------------------------------ optional: real coptpy


@pytest.mark.skipif(not (os.environ.get("ORGENE_COPT_TESTS") == "1" and os.environ.get("ORGENE_BASELINES_PY")),
                    reason="real coptpy only with ORGENE_COPT_TESTS=1 and ORGENE_BASELINES_PY (COPT use pending)")
def test_real_coptpy_program_under_the_harness_and_recorder():
    code = ("import coptpy as cp\nfrom coptpy import COPT\nenv = cp.Envr()\nmodel = env.createModel('t')\n"
            "x = model.addVar(lb=0, name='x')\ny = model.addVar(lb=0, name='y')\n"
            "model.addConstr(2*x + y <= 100)\nmodel.addConstr(x + y <= 80)\n"
            "model.setObjective(40*x + 30*y, sense=COPT.MAXIMIZE)\nmodel.setParam('Logging', 0)\nmodel.solve()\n")
    py = os.environ["ORGENE_BASELINES_PY"]
    ex = run_program(OA.build_program(code), timeout=120, python=py)
    assert ex["exec_ok"] and ex["status"] == "Optimal" and abs(ex["objective"] - 2600) < 1e-6, ex["stderr_tail"]
    (s,) = ex["solve_records"]
    assert s["backend"] == "coptpy" and s["status"] == "OPTIMAL" and abs(s["objective"] - 2600) < 1e-6
    assert MIS.misreport(ex)["consistent"] is True
    assert OA.official_prediction(ex, OA.parse_harness(ex["stdout_tail"]))[0] == "2600.0"
    alone = run_program(code, timeout=120, python=py)
    assert _solves(alone) == _solves(ex)

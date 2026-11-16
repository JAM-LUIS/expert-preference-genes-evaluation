"""E23 post-run audit tests using invented records only.

No benchmark files, models, tokenizer processes, HTTP, SSH or solver are used.
The synthetic token counts are supplied observations, not claims about a model.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


_MODULE_PATH = Path(__file__).resolve().parents[1] / "run_e23_dev_acceptance.py"
_SPEC = importlib.util.spec_from_file_location("e23_dev_acceptance_under_test", _MODULE_PATH)
_AUDITOR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_AUDITOR)
audit_units = _AUDITOR.audit_units
AcceptanceError = _AUDITOR.AcceptanceError

CONDITIONS = ("C0", "C1", "C2", "C3", "C3E", "C3L")
GENES_PATH = "genes/genes.it0.approved.jsonl"
LEXICON_PATH = "genes/activation_lexicon.v2.json"
PREDICATE_PATH = "runtime/orgene/predicates_it0.py"
STAMP = "2026-09-30T00:00:00+00:00"
MODEL = _AUDITOR.MODEL
DIGEST = _AUDITOR.DIGEST
OPTS = {"temperature": 0.0, "top_k": 40, "top_p": 0.9, "seed": 1,
        "num_ctx": 32768, "num_predict": 6000, "think": "low", "keep_alive": 0}


def text_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def obj_sha(obj):
    return text_sha(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))


def request_sha(messages, opts):
    # Ollama's canonical request excludes stream and keep_alive.
    body = {"model": MODEL, "messages": messages, "think": opts["think"],
            "options": {k: v for k, v in opts.items() if k not in ("think", "keep_alive")}}
    return obj_sha(body)


def config(cond):
    repairing = cond in ("C3", "C3L", "C3E")
    return {"id": cond, "prompt": "C0" if cond in ("C3L", "C3E") else cond,
            "round0": "reuse:C0" if cond in ("C3L", "C3E") else "own",
            "validator": "gene" if repairing else "observe",
            "gene_scope": cond if cond in ("C3L", "C3E") else "C3",
            "activation": "per_problem" if cond in ("C3", "C3L") else "all",
            "repair": "generic" if cond == "C3E" else "gene" if repairing else "none",
            "closing": "spec_and_program" if cond in ("C2", "C3") else "program",
            "max_rounds": 2 if repairing else 0, "num_predict": 6000, "num_ctx": 32768,
            "variant": None, "pipeline": "standard", "token_cap": None}


def make_call(messages, tokenizer, opts=None, content=None):
    opts = copy.deepcopy(opts or OPTS)
    content = content or "```python\nprint('STATUS: Optimal')\nprint('FINAL_OBJECTIVE: 1')\n```"
    thinking = "Invented plan."
    local = {"schema": "orgene.tokens.v1", "tokenizer_sha256": obj_sha(tokenizer),
             "content_by_message": [10 for _ in messages], "content_total": 10 * len(messages),
             "rendered_prompt": 80, "completion": 20, "completion_thinking": 4,
             "think": "low", "current_date": "2026-09-29", "history_think_stripped": False}
    return {"call_schema": "orgene.r1.call.v1", "backend": "ollama", "model": MODEL,
            "digest": DIGEST, "seed": opts["seed"], "sent_opts": opts,
            "request_sha256": request_sha(messages, opts), "messages_sha256": obj_sha(messages),
            "n_messages": len(messages), "format": None, "request_adjustments": [],
            "started_at": STAMP, "finished_at": STAMP, "wall_seconds": 1.0, "seconds": 1.0,
            "attempts": [{"ok": True, "seconds": 1.0}], "ok": True, "done_reason": "stop",
            "prompt_eval_count": 80, "eval_count": 24, "content": content,
            "content_sha256": text_sha(content), "thinking": thinking,
            "thinking_sha256": text_sha(thinking), "local_tokens": local,
            "local_tokens_counter": "OllamaCounter", "local_tokens_error": None,
            "total_duration_ns": 1000000000, "load_duration_ns": 100000000,
            "prompt_eval_duration_ns": 100000000, "eval_duration_ns": 800000000}


def validated(case, cond, rnd, call, exec_ok=True):
    return {"case_id": case, "repeat": 0, "condition": cond, "round": rnd,
            "request_id": f"{case}.{cond}.rep0" + (f".repair{rnd}" if rnd else ""),
            "gen_ok": True, "done_reason": "stop", "in_tokens": call["prompt_eval_count"],
            "out_tokens": call["eval_count"], "local_tokens": copy.deepcopy(call["local_tokens"]),
            "has_spec": cond in ("C2", "C3"), "has_code": True, "code": "print('synthetic')",
            "spec": {} if cond in ("C2", "C3") else None,
            "exec": {"exec_ok": exec_ok, "protocol_ok": exec_ok, "status": "Optimal" if exec_ok else None,
                     "objective": 1.0 if exec_ok else None, "seconds": 0.1},
            "issues": [], "hard_failed_genes": [], "soft_failed_genes": [], "decision": "accepted",
            "repair_applied_genes": [], "repair_applications": {},
            "max_rounds": config(cond)["max_rounds"], "validated_at": STAMP}


def finalize(unit):
    calls = [ce for rnd in unit["rounds"] for ce in rnd["calls"]]
    unit["tokens"] = {
        "prompt": sum(ce["call"]["prompt_eval_count"] for ce in calls),
        "completion": sum(ce["call"]["eval_count"] for ce in calls),
        "n_calls": len(calls), "n_calls_reused": sum(ce["reused"] for ce in calls),
        "local": {"rendered_prompt": sum(ce["call"]["local_tokens"]["rendered_prompt"] for ce in calls),
                  "completion": sum(ce["call"]["local_tokens"]["completion"] for ce in calls),
                  "n_calls_missing": 0}}
    unit["tokens"]["total"] = unit["tokens"]["prompt"] + unit["tokens"]["completion"]
    final = copy.deepcopy(unit["rounds"][-1]["validated"])
    final["rounds"] = [{"round": r["round"], "request_id": r["validated"]["request_id"],
                        "in_tokens": r["validated"]["in_tokens"], "out_tokens": r["validated"]["out_tokens"],
                        "hard_failed_genes": r["validated"]["hard_failed_genes"], "soft_failed_genes": [],
                        "exec_ok": r["validated"]["exec"]["exec_ok"], "decision": r["validated"]["decision"],
                        "repair_applied_genes": r["validated"]["repair_applied_genes"]}
                       for r in unit["rounds"]]
    final["provisional"] = False
    unit["final_row"] = final


def make_bundle(ids, conditions=CONDITIONS):
    approved = {GENES_PATH: text_sha("approved synthetic genes"),
                LEXICON_PATH: text_sha("approved synthetic lexicon"),
                PREDICATE_PATH: text_sha("approved synthetic predicates")}
    entry = {"backend": "ollama", "model": MODEL, "digest": DIGEST,
             "opts": copy.deepcopy(OPTS), "seed_rule": "base+k", "status": "pending"}
    model = {k: entry[k] for k in ("backend", "model", "digest")}
    registry = {"path": "configs/model_registry.json", "entry_id": "gptoss-20b.main",
                "entry_sha256": obj_sha(entry)}
    tokenizer = {"backend": "ollama", "model": MODEL, "manifest_sha256": entry["digest"],
                 "weights_sha256": text_sha("invented weights"), "template_sha256": text_sha("invented template"),
                 "model_family": "gptoss", "renderer": "gptoss-harmony", "strip_history_think": False,
                 "tokenizer": {"kind": "tiktoken", "encoding": "o200k_harmony", "encoding_file": "o200k_base",
                               "encoding_sha256": text_sha("invented tokenizer"), "version": "synthetic"}}
    setup = {"gene_store": {"path": GENES_PATH, "file_sha256": approved[GENES_PATH]},
             "lexicon": {"path": LEXICON_PATH, "sha256": approved[LEXICON_PATH]},
             "model": copy.deepcopy(model), "model_registry": registry,
             "opts": {k: v for k, v in OPTS.items() if k != "seed"}, "seed_base": 1,
             "c1_matching": {"match_mode": "tokens", "tokenizer": "api", "report": "synthetic-c1-report.json"},
             "local_tokens_counter": "OllamaCounter", "local_tokenizer_sha256": obj_sha(tokenizer),
             "round0_run": "experiments/synthetic-dev", "exec_timeout": 60}
    configs = {cond: config(cond) for cond in conditions}
    units = []
    for case in ids:
        c0_messages = [{"role": "system", "content": "Invented C0 system."},
                       {"role": "user", "content": f"Invented problem {case}."}]
        c0_call = make_call(c0_messages, tokenizer)
        for cond in conditions:
            reused = cond in ("C3L", "C3E")
            messages = copy.deepcopy(c0_messages)
            if cond not in ("C0", "C3L", "C3E"):
                messages[0]["content"] = f"Invented {cond} system."
            call = copy.deepcopy(c0_call) if reused else make_call(messages, tokenizer)
            uid = f"{case}.{cond}.r0"
            v = validated(case, cond, 0, call)
            ce = {"stage": "round0", "round": 0, "request_id": v["request_id"],
                  "messages": messages, "meta": {"config_id": cond}, "call": call, "reused": reused}
            src = {"unit_id": f"{case}.C0.r0", "config_id": "C0", "run": setup["round0_run"],
                   "request_sha256": c0_call["request_sha256"], "content_sha256": c0_call["content_sha256"],
                   "call_sha256": obj_sha(c0_call)} if reused else None
            unit = {"schema_version": "orgene.r1.unit.v1", "unit_id": uid, "case_id": case,
                    "config_id": cond, "repeat": 0, "run_id": "synthetic-e23", "source": "invented",
                    "status": "complete", "stop_reason": "accepted" if config(cond)["repair"] != "none" else "observe_only",
                    "error": None, "pipeline": "standard", "config": copy.deepcopy(configs[cond]),
                    "setup_sha256": obj_sha(setup), "model": copy.deepcopy(model),
                    "model_registry": copy.deepcopy(registry), "opts": copy.deepcopy(OPTS),
                    "local_tokenizer": copy.deepcopy(tokenizer), "features_sha256": text_sha(case),
                    "activation": {"gene_scope": configs[cond]["gene_scope"], "mode": configs[cond]["activation"],
                                   "impl": "synthetic", "active_genes": [], "gene_set_digest": obj_sha([]), "trace": []},
                    "inapplicable_genes": [], "c1_matching": None,
                    "round0": {"source": configs[cond]["round0"], "reused_from": src},
                    "rounds": [{"round": 0, "calls": [ce], "validated": v,
                                "repair_text": None, "repair_applied_genes": []}],
                    "pending_calls": [], "applications": {}, "token_cap": None, "budget_stop": None,
                    "exec_timeout_s": 60, "context_check": {"checked": 0, "unchecked": 0},
                    "context_exceeded": None, "started_at": STAMP, "finished_at": STAMP,
                    "code_sha256": {PREDICATE_PATH: approved[PREDICATE_PATH]}}
            if cond == "C1":
                unit["c1_matching"] = {"match_mode": "tokens", "tokenizer": "api", "report": "synthetic-c1-report.json",
                                       "report_sha256": text_sha("synthetic C1 report"), "target": 10,
                                       "identity_sha256": text_sha("synthetic o200k matching identity"),
                                       "sha256": text_sha(messages[0]["content"]), "variant": None}
            finalize(unit)
            units.append(unit)
    return {"units": units, "setup": setup, "entry": entry, "configs": configs,
            "approved_hashes": approved, "expected_ids": list(ids), "conditions": list(conditions)}


def selected(bundle, cond="C3"):
    return next(u for u in bundle["units"] if u["config_id"] == cond)


def reseal_setup(bundle):
    for u in bundle["units"]:
        u["setup_sha256"] = obj_sha(bundle["setup"])


def add_repair(bundle, cond="C3"):
    u = selected(bundle, cond)
    first = u["rounds"][0]
    first["validated"].update(decision="repair_requested", hard_failed_genes=["invented.gene"],
                              repair_applied_genes=["invented.gene"])
    first["repair_text"] = "Repair the invented program."
    first["repair_applied_genes"] = ["invented.gene"]
    appended = [{"role": "assistant", "content": first["calls"][0]["call"]["content"]},
                {"role": "user", "content": first["repair_text"]}]
    messages = copy.deepcopy(first["calls"][0]["messages"]) + appended
    call = make_call(messages, u["local_tokenizer"], content="```python\nprint('synthetic repair')\n```")
    v = validated(u["case_id"], cond, 1, call)
    ce = {"stage": "repair1", "round": 1, "request_id": v["request_id"], "messages_appended": appended,
          "meta": {"round": 1, "orig_repeat": 0}, "call": call, "reused": False}
    u["rounds"].append({"round": 1, "calls": [ce], "validated": v, "repair_text": None, "repair_applied_genes": []})
    u["context_check"] = {"checked": 1, "unchecked": 0}
    finalize(u)
    return u


@pytest.fixture
def dev_bundle():
    return make_bundle([f"invented-dev-{i:02d}" for i in range(20)])


def test_author_smoke_c0_is_a_single_complete_generation():
    bundle = make_bundle(["invented-author-smoke"], ["C0"])
    summary = audit_units(**bundle)
    assert isinstance(summary, dict) and summary
    assert bundle["units"][0]["tokens"]["n_calls"] == 1
    assert bundle["units"][0]["tokens"]["n_calls_reused"] == 0


def test_complete_dev20_six_conditions_passes(dev_bundle):
    assert len(dev_bundle["units"]) == 120
    entry_before = copy.deepcopy(dev_bundle["entry"])
    summary = audit_units(**dev_bundle)
    assert summary["state"] == "passed" and summary["units"] == 120 and summary["cases"] == 20
    assert summary["cp1"]["executed"] == summary["cp1"]["denominator"] == 20
    assert summary["cp1"]["rate"] == 1.0 and summary["cp1"]["gate"] is False
    assert summary["registry_pending_preserved"] is True and dev_bundle["entry"] == entry_before
    # C3L/C3E each reuse twenty calls. Only the eighty own calls are physical model cost.
    totals = summary["tokens_actual_calls_only"]
    assert totals == {"server_prompt": 80 * 80, "server_completion_including_reasoning": 80 * 24,
                      "local_content_completion": 80 * 20, "local_thinking_completion": 80 * 4,
                      "actual_calls": 80}


def test_repair_reconstructs_full_messages_and_passes(dev_bundle):
    add_repair(dev_bundle)
    assert isinstance(audit_units(**dev_bundle), dict)


def test_cp1_execution_rate_is_diagnostic_not_a_pass_gate(dev_bundle):
    for u in dev_bundle["units"]:
        if u["config_id"] == "C0":
            u["rounds"][0]["validated"]["exec"].update(exec_ok=False, protocol_ok=False, status=None, objective=None)
            finalize(u)
    summary = audit_units(**dev_bundle)  # Even 0/20 must remain an honest diagnostic.
    assert summary["state"] == "passed"
    assert summary["cp1"]["definition"] == "C0 final_row.exec.exec_ok"
    assert summary["cp1"]["executed"] == 0 and summary["cp1"]["denominator"] == 20
    assert summary["cp1"]["rate"] == 0.0 and summary["cp1"]["gate"] is False


def test_c1_api_request_can_reuse_the_matching_qwen_prompt(dev_bundle):
    # RequestsC1 may select its qwen prompt when a separate C1-api variant is unnecessary.
    selected(dev_bundle, "C1")["c1_matching"]["tokenizer"] = "qwen"
    assert audit_units(**dev_bundle)["state"] == "passed"


@pytest.mark.parametrize("bad", ["missing", "extra", "duplicate", "case", "condition", "repeat", "unit_id", "schema"])
def test_exact_120_unit_identity_is_required(dev_bundle, bad):
    units = dev_bundle["units"]
    if bad == "missing":
        units.pop()
    elif bad in ("extra", "duplicate"):
        extra = copy.deepcopy(units[0])
        if bad == "extra":
            extra.update(case_id="invented-extra", unit_id="invented-extra.C0.r0")
        units.append(extra)
    else:
        key, value = {"case": ("case_id", "invented-unknown"), "condition": ("config_id", "C2E"),
                      "repeat": ("repeat", 1), "unit_id": ("unit_id", "wrong.C0.r0"),
                      "schema": ("schema_version", "wrong.schema")}[bad]
        units[0][key] = value
    with pytest.raises(AcceptanceError):
        audit_units(**dev_bundle)


@pytest.mark.parametrize("field,value", [
    ("status", "running"), ("status", "incomplete"), ("final_row", None),
    ("pending_calls", [{"invented": True}]), ("setup_sha256", "0" * 64),
    ("model", {"backend": "ollama", "model": MODEL, "digest": "0" * 64}),
    ("model_registry", {"path": "configs/model_registry.json", "entry_id": "other", "entry_sha256": "0" * 64}),
])
def test_invalid_unit_metadata_is_refused(dev_bundle, field, value):
    selected(dev_bundle)[field] = value
    with pytest.raises(AcceptanceError):
        audit_units(**dev_bundle)


@pytest.mark.parametrize("identity", ["genes", "lexicon", "predicate"])
def test_self_consistent_unapproved_inputs_are_refused(dev_bundle, identity):
    if identity == "genes":
        dev_bundle["setup"]["gene_store"]["file_sha256"] = text_sha("unapproved genes")
        reseal_setup(dev_bundle)
    elif identity == "lexicon":
        dev_bundle["setup"]["lexicon"]["sha256"] = text_sha("unapproved lexicon")
        reseal_setup(dev_bundle)
    else:
        for u in dev_bundle["units"]:
            u["code_sha256"][PREDICATE_PATH] = text_sha("unapproved predicates")
    with pytest.raises(AcceptanceError):
        audit_units(**dev_bundle)


@pytest.mark.parametrize("key,value", [("seed", 2), ("seed", True), ("think", True), ("think", "medium"),
                                      ("temperature", 0.5), ("num_ctx", 16384), ("num_predict", 1),
                                      ("keep_alive", 60), ("top_k", 20), ("top_p", 0.95)])
def test_every_repair_call_must_keep_registered_options(dev_bundle, key, value):
    u = add_repair(dev_bundle)
    u["rounds"][1]["calls"][0]["call"]["sent_opts"][key] = value
    with pytest.raises(AcceptanceError):
        audit_units(**dev_bundle)


@pytest.mark.parametrize("bad", ["content", "thinking", "messages", "request_hash", "digest", "seed_field",
                                 "missing_tokens", "negative_tokens", "bool_tokens", "missing_local", "missing_think_tokens",
                                 "local_think", "local_date", "local_prompt", "timestamp", "total", "n_calls", "local_total"])
def test_call_hashes_identity_and_token_observations_are_checked(dev_bundle, bad):
    u = selected(dev_bundle)
    ce = u["rounds"][0]["calls"][0]
    call = ce["call"]
    if bad == "content":
        call["content"] += "tampered"
    elif bad == "thinking":
        call["thinking"] += "tampered"
    elif bad == "messages":
        ce["messages"][0]["content"] += "tampered"
    elif bad in ("request_hash", "digest", "seed_field"):
        key = {"request_hash": "request_sha256", "digest": "digest", "seed_field": "seed"}[bad]
        call[key] = 2 if bad == "seed_field" else "0" * 64
    elif bad == "missing_tokens":
        call["eval_count"] = None
    elif bad == "negative_tokens":
        call["prompt_eval_count"] = -1
    elif bad == "bool_tokens":
        call["eval_count"] = True
    elif bad == "missing_local":
        call["local_tokens"] = None
    elif bad == "missing_think_tokens":
        del call["local_tokens"]["completion_thinking"]
    elif bad in ("local_think", "local_date", "local_prompt"):
        key, value = {"local_think": ("think", "high"), "local_date": ("current_date", "2030-01-01"),
                      "local_prompt": ("rendered_prompt", 79)}[bad]
        call["local_tokens"][key] = value
    elif bad == "timestamp":
        call["finished_at"] = None
    elif bad == "local_total":
        u["tokens"]["local"]["completion"] += 1
    else:
        u["tokens"][bad] += 1
    with pytest.raises(AcceptanceError):
        audit_units(**dev_bundle)


@pytest.mark.parametrize("bad", ["source", "source_case", "source_repeat", "source_hash", "not_reused",
                                 "copied_call", "c0_reused", "repair_reused"])
def test_c0_round0_reuse_is_exact_and_auditable(dev_bundle, bad):
    u = selected(dev_bundle, "C3L")
    if bad == "source":
        u["round0"]["source"] = "own"
    elif bad in ("source_case", "source_repeat"):
        u["round0"]["reused_from"]["unit_id"] = "other.C0.r0" if bad == "source_case" else f"{u['case_id']}.C0.r1"
    elif bad == "source_hash":
        u["round0"]["reused_from"]["call_sha256"] = "0" * 64
    elif bad == "not_reused":
        u["rounds"][0]["calls"][0]["reused"] = False
    elif bad == "copied_call":
        u["rounds"][0]["calls"][0]["call"]["wall_seconds"] = 2.0
    elif bad == "c0_reused":
        selected(dev_bundle, "C0")["rounds"][0]["calls"][0]["reused"] = True
    else:
        add_repair(dev_bundle)["rounds"][1]["calls"][0]["reused"] = True
    with pytest.raises(AcceptanceError):
        audit_units(**dev_bundle)


@pytest.mark.parametrize("bad", ["chars", "setup_qwen", "missing", "prompt_hash", "report_path", "report_hash", "target",
                                 "config", "round_gap", "too_many_rounds"])
def test_c1_configuration_and_round_protocol_are_preserved(dev_bundle, bad):
    if bad in ("chars", "setup_qwen", "missing", "prompt_hash", "report_path", "report_hash", "target"):
        u = selected(dev_bundle, "C1")
        if bad == "missing":
            u["c1_matching"] = None
        elif bad == "setup_qwen":
            dev_bundle["setup"]["c1_matching"]["tokenizer"] = "qwen"
            reseal_setup(dev_bundle)
        elif bad == "prompt_hash":
            u["c1_matching"]["sha256"] = "0" * 64
        elif bad == "report_path":
            u["c1_matching"]["report"] = "different-synthetic-report.json"
        elif bad == "report_hash":
            u["c1_matching"]["report_sha256"] = None
        elif bad == "target":
            u["c1_matching"]["target"] = 0
        else:
            u["c1_matching"]["match_mode"] = bad
    else:
        u = selected(dev_bundle)
        if bad == "config":
            u["config"]["num_predict"] = 10
        elif bad == "round_gap":
            add_repair(dev_bundle)["rounds"][1]["round"] = 2
        else:
            extra = copy.deepcopy(u["rounds"][0])
            u["rounds"] = [dict(copy.deepcopy(extra), round=i) for i in range(4)]
    with pytest.raises(AcceptanceError):
        audit_units(**dev_bundle)


@pytest.mark.parametrize("bad", ["final_exec", "final_case", "validated_case", "validated_round", "call_round", "call_stage"])
def test_final_result_and_round_metadata_are_consistent(dev_bundle, bad):
    u = selected(dev_bundle)
    if bad == "final_exec":
        u["final_row"]["exec"]["exec_ok"] = False
    elif bad == "final_case":
        u["final_row"]["case_id"] = "invented-another"
    elif bad == "validated_case":
        u["rounds"][0]["validated"]["case_id"] = "invented-another"
        finalize(u)
    elif bad == "validated_round":
        u["rounds"][0]["validated"]["round"] = 1
        finalize(u)
    elif bad == "call_round":
        u["rounds"][0]["calls"][0]["round"] = 1
    else:
        u["rounds"][0]["calls"][0]["stage"] = "repair1"
    with pytest.raises(AcceptanceError):
        audit_units(**dev_bundle)

#!/usr/bin/env python3
"""Prepare one author-written C0 smoke and audit E23 development records offline.

This tool never calls a model. The prepared command uses the ordinary unit runner,
registry and token checks. Full dev20 is audit-only: final-gene approval, a current
o200k C1 matching report and a separately fixed development roster are prerequisites.
No correctness threshold is used to accept engineering records (CP1 is diagnostic).
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from orgene.backends.base import canonical_json, request_sha256, content_sha256
from orgene.backends.ollama import OllamaBackend
from orgene import configs as CF
from orgene import pipeline as P

ENTRY_ID = "gptoss-20b.main"
CONDITIONS = ("C0", "C1", "C2", "C3", "C3E", "C3L")
MODEL = "gpt-oss-20b-date20260929:latest"
DIGEST = "05290e9c52a55a67c3f6e9cec3f625de0e37af63ef9a0e154085aba08dd4283a"
OPTS = {"temperature": 0.0, "top_k": 40, "top_p": 0.9, "seed": 1,
        "num_ctx": 32768, "num_predict": 6000, "think": "low", "keep_alive": 0}
APPROVED = {
    "genes/genes.it0.approved.jsonl": "21edf3b23d8771c27bf369ee3f1dbcd1685c60df5ea2e69017459e9ba76e7cf0",
    "genes/activation_lexicon.v2.json": "2df6c5badce9b0e700eea7a2e82d02c6b0ce797109af0c427352138c9e419636",
    "runtime/orgene/predicates_it0.py": "f2b18cc734a3e95d4e6d84093658aa8dea03e791ee2a377820bb083fda572989",
}


class AcceptanceError(ValueError):
    pass


def sha_obj(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise AcceptanceError(message)


def integer(value):
    return type(value) is int and value >= 0


def same_opts(actual, expected):
    return actual == expected and all(type(actual.get(k)) is int for k in
                                     ("seed", "top_k", "num_ctx", "num_predict", "keep_alive"))


def messages_at(unit, rnd, index=0):
    record = unit["rounds"][rnd]["calls"][index]
    if "messages" in record:
        return record["messages"]
    require(rnd > 0 and "messages_appended" in record, "missing recorded messages")
    return messages_at(unit, rnd - 1, -1) + record["messages_appended"]


def audit_units(units, setup, entry, configs, approved_hashes, expected_ids, conditions):
    """Pure audit over synthetic or development records; never opens case files."""
    ids = list(expected_ids)
    require(ids and len(set(ids)) == len(ids), "roster contains duplicate or no IDs")
    require(set(conditions) <= set(CONDITIONS) and len(set(conditions)) == len(conditions), "invalid conditions")
    require(set(conditions) == {"C0"} or set(conditions) == set(CONDITIONS), "only C0 smoke or all six conditions")
    require(entry["backend"] == "ollama" and entry["model"] == MODEL and entry["digest"] == DIGEST,
            "wrong registered model/digest")
    require(same_opts(entry["opts"], OPTS), "registered budget differs from approved smoke")
    gene = setup.get("gene_store") or {}
    lexicon = setup.get("lexicon") or {}
    require(gene.get("path") in approved_hashes and gene.get("file_sha256") == approved_hashes[gene["path"]],
            "gene library is not the approved artifact")
    require(lexicon.get("path") in approved_hashes and lexicon.get("sha256") == approved_hashes[lexicon["path"]],
            "lexicon is not the approved artifact")
    require(setup.get("model") == {k: entry[k] for k in ("backend", "model", "digest")}, "setup model mismatch")
    require(setup.get("seed_base") == 1 and setup.get("opts") == {k: v for k, v in entry["opts"].items() if k != "seed"},
            "setup options mismatch")
    expected_registry = {"entry_id": ENTRY_ID, "entry_sha256": sha_obj(entry)}
    require(all((setup.get("model_registry") or {}).get(k) == v for k, v in expected_registry.items()), "setup registry mismatch")
    expected_keys = {(c, cfg, 0) for c in ids for cfg in conditions}
    by_key = {}
    for u in units:
        require(u.get("schema_version") == "orgene.r1.unit.v1", "unexpected unit schema")
        key = (u.get("case_id"), u.get("config_id"), u.get("repeat"))
        require(type(key[2]) is int and key in expected_keys and key not in by_key, "extra/duplicate/unexpected unit")
        require(u.get("unit_id") == f"{key[0]}.{key[1]}.r0", "unit ID mismatch")
        by_key[key] = u
    require(set(by_key) == expected_keys, "incomplete condition pairing")
    totals = {"server_prompt": 0, "server_completion_including_reasoning": 0,
              "local_content_completion": 0, "local_thinking_completion": 0, "actual_calls": 0}
    done_reasons = {}
    for key, u in by_key.items():
        uid, cfg = u["unit_id"], configs[key[1]]
        require(u.get("status") == "complete" and u.get("final_row") is not None and not u.get("pending_calls"),
                f"{uid}: incomplete execution")
        require(u.get("config") == cfg and u.get("setup_sha256") == sha_obj(setup), f"{uid}: config/setup mismatch")
        require(u.get("model") == setup["model"] and same_opts(u.get("opts") or {}, entry["opts"]), f"{uid}: model/options mismatch")
        require(u.get("model_registry") == setup["model_registry"], f"{uid}: registry mismatch")
        require(u.get("local_tokenizer") and sha_obj(u["local_tokenizer"]) == setup.get("local_tokenizer_sha256"),
                f"{uid}: missing or changed tokenizer")
        for path, sha in approved_hashes.items():
            if path.startswith("runtime/"):
                require(u.get("code_sha256", {}).get(path) == sha, f"{uid}: approved predicate hash missing")
        rounds = u.get("rounds") or []
        require(1 <= len(rounds) <= cfg["max_rounds"] + 1 <= 3 and
                [r.get("round") for r in rounds] == list(range(len(rounds))), f"{uid}: invalid rounds")
        prompt = completion = local_prompt = local_completion = count = reused_count = 0
        rebuilt_final = None
        for rnd, record in enumerate(rounds):
            require(len(record.get("calls") or []) == 1, f"{uid}: expected one call per standard round")
            ce = record["calls"][0]
            call = ce["call"]
            require(ce.get("round") == rnd and ce.get("stage") == ("round0" if rnd == 0 else f"repair{rnd}"),
                    f"{uid}: call round/stage mismatch")
            validated = record.get("validated") or {}
            require(all(validated.get(k) == v for k, v in {"round": rnd, "case_id": key[0], "condition": key[1],
                                                         "repeat": 0, "gen_ok": True}.items()),
                    f"{uid}: validated identity mismatch")
            require(validated.get("done_reason") == call.get("done_reason") and
                    validated.get("out_tokens") == call.get("eval_count") and
                    validated.get("in_tokens") == call.get("prompt_eval_count") and
                    validated.get("local_tokens") == call.get("local_tokens"), f"{uid}: validated call differs")
            rebuilt_final = P.final_entry(validated, rebuilt_final)
            require(call.get("ok") is True and call.get("model") == entry["model"] and
                    call.get("digest") == entry["digest"] and call.get("backend") == "ollama", f"{uid}: bad call/model")
            require(same_opts(call.get("sent_opts") or {}, entry["opts"]) and type(call.get("seed")) is int and
                    call["seed"] == 1, f"{uid}: call options mismatch")
            require(call.get("content_sha256") == content_sha256(call.get("content")), f"{uid}: content hash mismatch")
            require(call.get("thinking_sha256") == content_sha256(call.get("thinking")), f"{uid}: thinking hash mismatch")
            messages = messages_at(u, rnd)
            require(call.get("messages_sha256") == sha_obj(messages), f"{uid}: messages hash mismatch")
            body = OllamaBackend(entry["model"]).build_body(messages, entry["opts"])
            require(call.get("request_sha256") == request_sha256(body), f"{uid}: request hash mismatch")
            require(call.get("started_at") and call.get("finished_at") and call["started_at"] <= call["finished_at"],
                    f"{uid}: missing/invalid generation timestamps")
            for field in ("prompt_eval_count", "eval_count"):
                require(integer(call.get(field)), f"{uid}: missing/invalid server token count")
            lt = call.get("local_tokens") or {}
            require(lt.get("think") == "low" and lt.get("current_date") == "2026-09-29", f"{uid}: tokenizer think/date mismatch")
            for field in ("rendered_prompt", "completion", "completion_thinking"):
                require(integer(lt.get(field)), f"{uid}: missing/invalid local token count")
            require(lt["rendered_prompt"] == call["prompt_eval_count"], f"{uid}: server/local prompt disagreement")
            if call.get("thinking"):
                require(lt["completion_thinking"] > 0, f"{uid}: reasoning tokens missing")
            require(type(ce.get("reused")) is bool and (rnd == 0 or not ce["reused"]), f"{uid}: invalid repair reuse")
            prompt += call["prompt_eval_count"]
            completion += call["eval_count"]
            local_prompt += lt["rendered_prompt"]
            local_completion += lt["completion"]
            count += 1
            reused_count += int(ce["reused"])
            if not ce["reused"]:
                totals["server_prompt"] += call["prompt_eval_count"]
                totals["server_completion_including_reasoning"] += call["eval_count"]
                totals["local_content_completion"] += lt["completion"]
                totals["local_thinking_completion"] += lt["completion_thinking"]
                totals["actual_calls"] += 1
                reason = call.get("done_reason")
                done_reasons[reason] = done_reasons.get(reason, 0) + 1
        require(u.get("tokens") == {"prompt": prompt, "completion": completion, "total": prompt + completion,
                                   "n_calls": count, "n_calls_reused": reused_count,
                                   "local": {"rendered_prompt": local_prompt, "completion": local_completion, "n_calls_missing": 0}},
                f"{uid}: token aggregate mismatch")
        require(u["final_row"] == rebuilt_final, f"{uid}: final row differs from validated rounds")
        r0, c0 = u["round0"], rounds[0]["calls"][0]
        if key[1] in ("C3L", "C3E"):
            src = by_key[(key[0], "C0", 0)]
            src_call = src["rounds"][0]["calls"][0]["call"]
            require(r0["source"] == "reuse:C0" and c0["reused"] and c0["call"] == src_call, f"{uid}: C0 call differs")
            pointer = r0.get("reused_from") or {}
            want = {"unit_id": src["unit_id"], "config_id": "C0", "request_sha256": src_call["request_sha256"],
                    "content_sha256": src_call["content_sha256"], "call_sha256": sha_obj(src_call),
                    "run": setup["round0_run"]}
            require(pointer == want, f"{uid}: C0 source pointer mismatch")
        else:
            require(r0["source"] == "own" and r0.get("reused_from") is None and not c0["reused"], f"{uid}: unexpected reuse")
        if key[1] == "C1":
            cm = u.get("c1_matching") or {}
            require(setup.get("c1_matching", {}).get("match_mode") == "tokens" and
                    setup["c1_matching"].get("tokenizer") == "api" and cm.get("match_mode") == "tokens",
                    f"{uid}: C1 must request o200k matching")
            require(cm.get("report") == setup["c1_matching"].get("report") and cm.get("report_sha256") and
                    isinstance(cm.get("target"), (int, float)) and not isinstance(cm.get("target"), bool) and cm["target"] > 0,
                    f"{uid}: incomplete C1 matching record")
            require(cm.get("sha256") == content_sha256(messages_at(u, 0)[0]["content"]), f"{uid}: C1 prompt mismatch")
    c0s = [by_key[(c, "C0", 0)] for c in ids]
    executions = sum(bool((u["final_row"].get("exec") or {}).get("exec_ok")) for u in c0s)
    return {"state": "passed", "units": len(units), "cases": len(ids), "conditions": list(conditions),
            "roster_sha256": sha_obj(ids), "registry_pending_preserved": entry.get("status") == "pending",
            "cp1": {"definition": "C0 final_row.exec.exec_ok", "executed": executions, "denominator": len(ids),
                    "rate": executions / len(ids), "historical_reference_rate": 0.9, "gate": False},
            "tokens_actual_calls_only": totals, "done_reasons_actual_calls_only": done_reasons}


def verify_approval(root=ROOT):
    manifest = json.loads((root / "configs/gene_iteration.it0.json").read_text())
    require(manifest["runtime_sha256"] == APPROVED, "approval manifest changed")
    for path, sha in APPROVED.items():
        require(sha_file(root / path) == sha, f"approved artifact changed: {path}")
    return manifest


def prepare_smoke(campaign):
    from orgene import data as D
    require(Path(campaign).name == campaign and "dev" in campaign and "test" not in campaign, "use a new dev basename")
    manifest = verify_approval()
    run = ROOT / "experiments" / campaign
    run.mkdir(parents=True, exist_ok=False)
    cases = run / "cases.smoke.jsonl"
    D.build_cases("smoke", str(ROOT / "data/smoke/smoke_raw.jsonl"), str(cases))
    roster = {"mode": "smoke", "case_ids": ["smoke-0001"], "source": "author-written CC0 smoke",
              "raw_sha256": sha_file(ROOT / "data/smoke/smoke_raw.jsonl")}
    (run / "roster.json").write_text(json.dumps(roster, indent=2) + "\n")
    cmd = [sys.executable, "runtime/unit_runner.py", "--run", str((run / "smoke").relative_to(ROOT)),
           "--cases", str(cases.relative_to(ROOT)), "--split", "dev", "--limit", "1", "--cond", "C0",
           "--genes", manifest["genes"], "--lexicon", manifest["lexicon"], "--registry-entry", ENTRY_ID,
           "--call-timeout", "1800", "--max-attempts", "1", "--local-tokens", "on", "--export-validated"]
    plan = {"mode": "smoke_only", "command": cmd, "generation_calls": 1, "num_predict": 6000,
            "max_call_seconds": 1800, "next": "audit before the separate one-output-token server comparison",
            "dev20_state": "not_started; final gene/current o200k report/fixed roster prerequisites"}
    (run / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return plan


def audit_run(run, roster_path, export_request=None):
    verify_approval()
    roster = json.loads(Path(roster_path).read_text())
    mode, ids = roster.get("mode"), roster.get("case_ids") or []
    require(mode in ("smoke", "dev20"), "audit only smoke/development")
    if mode == "smoke":
        require(ids == ["smoke-0001"] and roster.get("raw_sha256") == sha_file(ROOT / "data/smoke/smoke_raw.jsonl"),
                "smoke roster provenance mismatch")
    else:
        require(len(ids) == 20 and len(set(ids)) == 20, "dev20 means twenty total cases")
        # The whitelist contains only IDs and hashes. No benchmark cases/answers are opened here.
        dev_files = roster.get("development_id_files") or {}
        require(dev_files, "a fixed, hashed dev whitelist is required")
        allowed = set()
        for path, sha in dev_files.items():
            require(Path(path).name == "dev_ids.json", "only development ID files are allowed")
            require(sha_file(ROOT / path) == sha, "development whitelist hash mismatch")
            allowed.update(json.loads((ROOT / path).read_text()))
        require(set(ids) <= allowed, "roster not within development whitelist")
    run = Path(run)
    require("test" not in run.name and "test" not in run.parent.name, "refuse test run directory")
    run_config = json.loads((run / "run_config.json").read_text())
    require(run_config.get("split") == "dev", "run is not development")
    setup = json.loads((run / "units/setup.json").read_text())["setup"]
    units = [json.loads(p.read_text()) for p in sorted((run / "units").glob("*.json")) if p.name != "setup.json"]
    entry = json.loads((ROOT / "configs/model_registry.json").read_text())["entries"][ENTRY_ID]
    configs = CF.load_registry(str(ROOT / "configs/r1_configs.json"))["configs"]
    report = audit_units(units, setup, entry, configs, APPROVED, ids, ("C0",) if mode == "smoke" else CONDITIONS)
    if mode == "dev20":
        from orgene import c1match as M, genes as G, conditions as C
        lex = ROOT / "genes/activation_lexicon.v2.json"
        store = G.load_store(str(ROOT / "genes/genes.it0.approved.jsonl"), lexicon=str(lex))
        rc = M.RequestsC1(CF.load_registry(), [configs["C1"]], store,
                          str(ROOT / "genes/genes.it0.approved.jsonl"), str(ROOT / "conditions"), 0.05,
                          sha_file(lex), match_mode="tokens", report_path=setup["c1_matching"]["report"],
                          tokenizer="api", local_tokens="auto", lexicon=str(lex))
        # Replays template/target and checks current gene, lexicon, tokenizer and C3 dev prompt hashes.
        for u in units:
            if u["config_id"] == "C1":
                ce = u["rounds"][0]["calls"][0]
                rc.kwargs(configs["C1"])
                req = {"messages": messages_at(u, 0), "meta": ce["meta"]}
                rc.record(configs["C1"], [req], {})
                wanted = dict({k: rc.run_info()[k] for k in ("match_mode", "tokenizer", "report", "report_sha256")},
                              **rc.by_config["C1"])
                require(u["c1_matching"] == wanted, "C1 matching record differs from current replay")
        report["c1_current_report_replayed"] = True
    if export_request:
        require(mode == "smoke" and len(units) == 1, "request export is restricted to the author smoke")
        ce = units[0]["rounds"][0]["calls"][0]
        req = {"request_id": "smoke-0001.C0", "case_id": "smoke-0001", "condition": "C0", "messages": ce["messages"]}
        Path(export_request).write_text(json.dumps(req) + "\n")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare-smoke")
    prep.add_argument("--campaign", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--run", required=True)
    audit.add_argument("--roster", required=True)
    audit.add_argument("--export-request")
    audit.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.action == "prepare-smoke":
        out = prepare_smoke(a.campaign)
    else:
        try:
            out = audit_run(a.run, a.roster, a.export_request)
        except Exception as exc:
            out = {"state": "failed", "error": f"{type(exc).__name__}: {exc}"}
            Path(a.out).write_text(json.dumps(out, indent=2) + "\n")
            print(json.dumps(out))
            return 1
        Path(a.out).write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Execution timeouts and re-execution of a finished run under another timeout (E22). No model call.

Timeouts come from the model registry (configs/model_registry.json, block `execution`, E19): timeout_s (60, the main
setting for every run) and timeout_s_engineering_cases (600, reported in addition for the engineering-source cases).
Both results come from the same model outputs: the run is generated and validated once at timeout_s; this module
then re-validates the same outputs at the other timeout into a new run directory.

Replay rule (the batch path: validated.<cond>.round<r>.jsonl, gen.<cond>.r0 / gen.<cond>.repair<r>):
- round 0 is re-executed and re-checked at the new timeout; repair requests are rebuilt from those results;
- round r >= 1 uses the original output of a unit only when the rebuilt repair request is byte-identical to the one
  the original run sent (same request id, same messages). A unit whose rebuilt request differs, or that has no
  original output for it, is "diverged": it keeps its last validated round, marked provisional, and is listed;
- a unit accepted earlier under the new timeout (for example a program that timed out at 60 s and finishes within
  600 s) stops there, and the original later rounds are not used.
The new directory holds run_config.json (with a `reexec` block), the round files and reexec.json (counts and the
diverged units); score it with `orgene_cli.py score` like any run.
"""
import json
import os
import shutil

from . import pipeline as P
from .conditions import read_jsonl, write_jsonl
from .paths import ROOT, rel

REGISTRY = os.path.join(ROOT, "configs", "model_registry.json")
DEFAULT_TIMEOUT_S = 60  # v5 execute.run_program; used only when the registry has no execution block


def execution_timeouts(registry_path=None):
    """{"timeout_s": main timeout, "timeout_s_engineering_cases": the second timeout of the engineering cases}."""
    path = registry_path or REGISTRY
    ex = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            ex = json.load(f).get("execution") or {}
    main = ex.get("timeout_s", DEFAULT_TIMEOUT_S)
    eng = ex.get("timeout_s_engineering_cases")
    for k, v in (("timeout_s", main), ("timeout_s_engineering_cases", eng)):
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 1):
            raise ValueError(f"execution.{k} must be a positive integer")
    return {"timeout_s": main, "timeout_s_engineering_cases": eng}


def _req_path(run_dir, cond, rnd):
    return os.path.join(run_dir, f"requests.{cond}.jsonl" if rnd == 0 else f"requests.{cond}.repair{rnd}.jsonl")


def _gen_dir(run_dir, cond, rnd):
    return os.path.join(run_dir, f"gen.{cond}.r0" if rnd == 0 else f"gen.{cond}.repair{rnd}")


def reexecute(run_dir, out_dir, cond, cases_by_id, genes_path, timeout, act=True, max_rounds=2, python=None,
              validate_kw=None):
    """Re-validate the outputs of `run_dir` (configuration `cond`) at `timeout` seconds into `out_dir`.

    Returns the summary written to out_dir/reexec.json. out_dir must not exist yet (nothing is overwritten)."""
    if os.path.exists(out_dir):
        raise FileExistsError(f"{rel(out_dir)} exists; re-execution never overwrites a directory")
    if not os.path.exists(_req_path(run_dir, cond, 0)):
        raise FileNotFoundError(f"no requests.{cond}.jsonl in {rel(run_dir)}")
    os.makedirs(out_dir)
    cfg_path = os.path.join(run_dir, "run_config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else {}
    cfg["reexec"] = {"source_run": rel(run_dir), "condition": cond, "timeout_s": timeout, "max_rounds": max_rounds,
                     "rule": "same model outputs; round r >= 1 reused only when the rebuilt repair request is identical",
                     "created_at": P.now_iso()}
    with open(os.path.join(out_dir, "run_config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    shutil.copyfile(_req_path(run_dir, cond, 0), _req_path(out_dir, cond, 0))
    kw = dict(validate_kw or {})
    summary = {"source_run": rel(run_dir), "condition": cond, "timeout_s": timeout, "rounds": [], "diverged": []}
    rnd = 0
    gen = _gen_dir(run_dir, cond, 0)
    while True:
        res = P.validate_round(out_dir, cond, rnd, gen, cases_by_id, genes_path, timeout=timeout, act=act,
                               max_rounds=max_rounds, python=python, **kw)
        summary["rounds"].append({"round": rnd, "n_validated": res["n_validated"],
                                  "n_repair_requested": res["n_repair_requested"]})
        nxt = rnd + 1
        new_req = _req_path(out_dir, cond, nxt)
        if not os.path.exists(new_req):
            break
        orig_req = _req_path(run_dir, cond, nxt)
        orig = {r["request_id"]: r for r in read_jsonl(orig_req)} if os.path.exists(orig_req) else {}
        outputs = {}
        og = _gen_dir(run_dir, cond, nxt)
        for rec in (P.read_gen_outputs(og) if os.path.isdir(os.path.join(og, "outputs")) else []):
            outputs[rec.get("request_id")] = rec
        keep = []
        for r in read_jsonl(new_req):
            o = orig.get(r["request_id"])
            if o is not None and o.get("messages") == r.get("messages") and r["request_id"] in outputs:
                keep.append(outputs[r["request_id"]])
            else:
                summary["diverged"].append({"case_id": r["case_id"], "round": nxt, "request_id": r["request_id"],
                                            "reason": "no original output" if o is None or r["request_id"] not in outputs
                                            else "repair request differs"})
        if not keep:
            break
        gen = os.path.join(out_dir, f"gen.{cond}.repair{nxt}")
        os.makedirs(os.path.join(gen, "outputs"))
        for i, rec in enumerate(sorted(keep, key=lambda x: x["request_id"])):
            with open(os.path.join(gen, "outputs", f"{i:05d}.json"), "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False)
        rnd = nxt
    final = read_jsonl(os.path.join(out_dir, f"final.{cond}.jsonl"))
    summary["n_units"] = len(final)
    summary["n_timed_out_final"] = sum(1 for v in final if (v.get("exec") or {}).get("timed_out"))
    summary["n_provisional"] = sum(1 for v in final if v.get("provisional"))
    summary["n_diverged"] = len(summary["diverged"])
    with open(os.path.join(out_dir, "reexec.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return summary


def compare_timeouts(run_a, run_b, cond):
    """Per-unit comparison of two runs of the same outputs (for example 60 s and 600 s): which units changed their
    timed-out flag, exec_ok or reported objective. Reads final.<cond>.jsonl of both; ids and flags only."""
    a = {(v["case_id"], v["repeat"]): v for v in read_jsonl(os.path.join(run_a, f"final.{cond}.jsonl"))}
    b = {(v["case_id"], v["repeat"]): v for v in read_jsonl(os.path.join(run_b, f"final.{cond}.jsonl"))}
    rows = []
    for k in sorted(set(a) | set(b)):
        ea, eb = (a.get(k) or {}).get("exec") or {}, (b.get(k) or {}).get("exec") or {}
        rows.append({"case_id": k[0], "repeat": k[1],
                     "timed_out": [ea.get("timed_out"), eb.get("timed_out")],
                     "exec_ok": [ea.get("exec_ok"), eb.get("exec_ok")],
                     "objective": [ea.get("objective"), eb.get("objective")],
                     "rounds": [len((a.get(k) or {}).get("rounds", [])), len((b.get(k) or {}).get("rounds", []))]})
    return rows


def write_rows(path, rows):
    write_jsonl(path, rows)

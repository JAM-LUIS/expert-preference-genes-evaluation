"""End-to-end self-test without a model: canned outputs -> validate -> repair request -> validate -> score -> report.

Batch path: simulates a runner output directory for smoke-001 under C3 with three units:
  r0: correct spec + program                       -> accepted, correct
  r1: reversed objective sense (LpMinimize)        -> hard failure, repair requested; canned repair fixes it
  r2: no program at all                            -> hard failure, repair requested; canned repair still broken -> stays wrong
Also runs C0 with the correct program only (no repair path) to exercise the observe-only mode.
Unit executor (E06): the same smoke case as (case, configuration) units through a canned backend (no server):
C0 observes, C3L shares C0's round 0 and repairs a runtime error, C3 repairs the reversed sense; the three final
files score as expected.
"""
import json
import os
import shutil
import tempfile

from . import configs as CF
from . import data as D
from . import features as F
from . import genes as G
from . import pipeline as P
from .conditions import build_requests, read_jsonl, write_jsonl

GOOD_SPEC = {
    "problem_type": "LP",
    "decision_variables": [{"name": "a", "domain": "continuous", "lower": 0, "upper": None, "meaning": "units of A"},
                           {"name": "b", "domain": "continuous", "lower": 0, "upper": None, "meaning": "units of B"}],
    "objective": {"sense": "max", "expression": "40*a + 30*b", "meaning": "total profit"},
    "constraints": [{"name": "machining", "expression": "2*a + b <= 100", "source_sentence": "at most 100 hours of machining"},
                    {"name": "assembly", "expression": "a + b <= 80", "source_sentence": "at most 80 hours of assembly"}],
    "assumptions": ["fractional production allowed"],
}

GOOD_CODE = """import pulp
prob = pulp.LpProblem("mix", pulp.LpMaximize)
a = pulp.LpVariable("a", lowBound=0)
b = pulp.LpVariable("b", lowBound=0)
prob += 40 * a + 30 * b
prob += 2 * a + b <= 100, "machining"
prob += a + b <= 80, "assembly"
prob.solve(pulp.PULP_CBC_CMD(msg=0))
print("STATUS:", pulp.LpStatus[prob.status])
print("FINAL_OBJECTIVE:", pulp.value(prob.objective))
"""


def _answer(spec, code):
    return "```json\n" + json.dumps(spec, indent=1) + "\n```\n\n```python\n" + code + "```\n"


def _write_gen(gen_dir, records):
    os.makedirs(os.path.join(gen_dir, "outputs"), exist_ok=True)
    for r in records:
        with open(os.path.join(gen_dir, "outputs", f"{r['request_id']}.r{r['repeat']}.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, indent=1)


RUNTIME_ERROR_CODE = GOOD_CODE.replace("prob += a + b <= 80", "prob += a + b <= float('80 h')")


def _unit_selftest(run, case, cases_by_id, genes_path, cond_dir, root):
    """E06: the smoke case as (case, configuration) units through a canned backend (no server, no model)."""
    from . import unit_exec as U
    from .backends.canned import CannedBackend
    script = {  # (system prompt asks for a spec?, round) -> answer
        (False, 0): "```python\n" + RUNTIME_ERROR_CODE + "```",          # C0 round 0, shared by C3L
        (False, 1): "```python\n" + GOOD_CODE + "```",                   # C3L repair
        (True, 0): _answer(GOOD_SPEC, GOOD_CODE.replace("LpMaximize", "LpMinimize")),  # C3 round 0: reversed sense
        (True, 1): _answer(GOOD_SPEC, GOOD_CODE),                         # C3 repair
    }

    def answer(messages, body):
        spec = "JSON" in messages[0]["content"] and "specification" in messages[0]["content"].lower()
        return script[(spec, sum(1 for m in messages if m["role"] == "assistant"))]
    backend = CannedBackend(answer=answer)
    ctx = U.build_context(run, configs_path=os.path.join(root, "configs", "r1_configs.json"), genes_path=genes_path,
                          cond_dir=cond_dir, opts={"temperature": 0.0, "top_k": 20, "top_p": 0.95, "seed": 1,
                                                   "num_ctx": 32768, "num_predict": 6000, "think": False,
                                                   "keep_alive": 0})
    reg = ctx.registry
    recs = {cid: U.run_unit(case, CF.get_config(reg, cid), 0, backend, ctx) for cid in ("C0", "C3L", "C3")}
    for cid, r in recs.items():
        print(f"[selftest] unit {r['unit_id']}: {r['status']} {r['stop_reason']} calls={r['tokens']['n_calls']} "
              f"reused={r['tokens']['n_calls_reused']}")
    ok = all(r["status"] == U.COMPLETE for r in recs.values())
    ok &= recs["C0"]["stop_reason"] == "observe_only" and recs["C0"]["tokens"]["n_calls"] == 1
    ok &= recs["C3L"]["round0"]["reused_from"]["unit_id"] == recs["C0"]["unit_id"]
    ok &= recs["C3L"]["rounds"][0]["calls"][0]["call"]["content_sha256"] == \
        recs["C0"]["rounds"][0]["calls"][0]["call"]["content_sha256"]
    ok &= len(backend.sent) == 4  # C0 round 0, C3L repair 1, C3 round 0 and repair 1; C3L round 0 is C0's
    ok &= [r["stop_reason"] for r in (recs["C3L"], recs["C3"])] == ["accepted", "accepted"]
    acc = {cid: P.score_condition(run, cid, cases_by_id)["accuracy"] for cid in recs}
    print("[selftest] unit accuracy:", json.dumps(acc))
    ok &= acc == {"C0": 0.0, "C3L": 1.0, "C3": 1.0}
    return bool(ok)


def run_selftest(root, genes_path, cond_dir, keep=False):
    tmp = tempfile.mkdtemp(prefix="orgene_selftest_")
    ok_all = True
    try:
        cases_path = os.path.join(tmp, "smoke.jsonl")
        D.build_cases("smoke", os.path.join(root, "data", "smoke", "smoke_raw.jsonl"), cases_path)
        cases = D.load_cases(cases_path)
        cases_by_id = {c["case_id"]: c for c in cases}
        case = cases[0]
        reg = CF.load_registry(os.path.join(root, "configs", "r1_configs.json"))
        lex = F.load_lexicon(None)
        store = G.load_store(genes_path, lexicon=lex)
        feats = {c["case_id"]: F.extract_features(c["text"], lex) for c in cases}  # per-problem activation (E04)
        run = os.path.join(tmp, "run")
        os.makedirs(run)
        for cond in ("C3", "C0"):
            write_jsonl(os.path.join(run, f"requests.{cond}.jsonl"),
                        build_requests([case], CF.get_config(reg, cond), store, "selftest", features_by_case=feats,
                                       registry_ids=CF.all_ids(reg), cond_dir=cond_dir))
        bad_code = GOOD_CODE.replace("LpMaximize", "LpMinimize")
        bad_spec = dict(GOOD_SPEC)
        recs = []
        for k, content in enumerate([_answer(GOOD_SPEC, GOOD_CODE), _answer(bad_spec, bad_code), "I cannot solve this."]):
            recs.append({"request_id": f"{case['case_id']}.C3", "case_id": case["case_id"], "condition": "C3", "repeat": k,
                         "ok": True, "content": content, "eval_count": 300 + k, "prompt_eval_count": 900,
                         "total_duration_ns": 5e9, "meta": {"round": 0}})
        _write_gen(os.path.join(run, "gen.C3.r0"), recs)
        r0 = P.validate_round(run, "C3", 0, os.path.join(run, "gen.C3.r0"), cases_by_id, genes_path, act=True)
        print("[selftest] C3 round0:", json.dumps(r0))
        ok_all &= r0["n_validated"] == 3 and r0["n_repair_requested"] == 2
        reps = read_jsonl(r0["repair_requests_path"])
        ok_all &= all(m["role"] in ("system", "user", "assistant") for r in reps for m in r["messages"]) and len(reps) == 2
        rep_recs = []
        for r in reps:
            k = r["meta"]["orig_repeat"]
            content = _answer(GOOD_SPEC, GOOD_CODE) if k == 1 else "Still no program, sorry."
            rep_recs.append({"request_id": r["request_id"], "case_id": r["case_id"], "condition": "C3", "repeat": 0, "ok": True,
                             "content": content, "eval_count": 250, "prompt_eval_count": 1500, "total_duration_ns": 4e9, "meta": r["meta"]})
        _write_gen(os.path.join(run, "gen.C3.repair1"), rep_recs)
        r1 = P.validate_round(run, "C3", 1, os.path.join(run, "gen.C3.repair1"), cases_by_id, genes_path, act=True)
        print("[selftest] C3 round1:", json.dumps(r1))
        # C0: only the good program, observe-only
        _write_gen(os.path.join(run, "gen.C0.r0"), [{"request_id": f"{case['case_id']}.C0", "case_id": case["case_id"], "condition": "C0",
                                                      "repeat": 0, "ok": True, "content": "```python\n" + GOOD_CODE + "```",
                                                      "eval_count": 200, "prompt_eval_count": 400, "total_duration_ns": 3e9, "meta": {"round": 0}}])
        from .cli import batch_validate_kwargs  # observe-only: every C3-scope gene recorded, spec genes not applicable
        c0 = P.validate_round(run, "C0", 0, os.path.join(run, "gen.C0.r0"), cases_by_id, genes_path, act=False,
                              max_rounds=0, **batch_validate_kwargs(CF.get_config(reg, "C0"), reg, store))
        print("[selftest] C0 round0:", json.dumps(c0))
        m3 = P.score_condition(run, "C3", cases_by_id)
        m0 = P.score_condition(run, "C0", cases_by_id)
        print("[selftest] C3 metrics:", json.dumps({k: m3[k] for k in ("n", "exec_rate", "accuracy", "n_correct", "repaired_cases", "mean_calls")}))
        print("[selftest] C0 metrics:", json.dumps({k: m0[k] for k in ("n", "exec_rate", "accuracy", "n_correct")}))
        rows3 = {r["repeat"]: r for r in read_jsonl(os.path.join(run, "results.C3.jsonl"))}
        ok_all &= rows3[0]["correct"] and rows3[1]["correct"] and (not rows3[2]["correct"])
        ok_all &= rows3[1]["repair_rounds_used"] == 1 and rows3[1]["n_calls"] == 2 and rows3[0]["n_calls"] == 1
        ok_all &= m0["accuracy"] == 1.0
        v0 = read_jsonl(os.path.join(run, "validated.C0.round0.jsonl"))[0]
        ok_all &= len(v0["issues"]) == len(G.activate(store, condition="C3", mode="all")[0]) and not v0["hard_failed_genes"]
        print(P.report(run))
        ok_all &= _unit_selftest(os.path.join(tmp, "units_run"), case, cases_by_id, genes_path, cond_dir, root)
        print("[selftest]", "PASS" if ok_all else "FAIL", f"(run dir: {run})")
        return bool(ok_all)
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)

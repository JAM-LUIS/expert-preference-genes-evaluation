"""E06: the (case, configuration) unit executor and shared round 0 (engineering plan 3.6).

No model is called. A canned backend (orgene/backends/canned.py) answers by request: in script mode from the table
below (case text, whether the system prompt asks for a spec, round), in replay mode only from the sha256 of requests
it has seen, so two paths that must send identical requests can be compared. Fixtures are self-made two-product
problems; no benchmark text is read. Programs run with the fixed interpreter; each distinct program runs once per
module (memoised run_program), and the validation clock is fixed, so records of two paths can be compared byte for
byte.
"""
import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import cli  # noqa: E402
from orgene import configs as CF  # noqa: E402
from orgene import genes as G  # noqa: E402
from orgene import ladder as L  # noqa: E402
from orgene import paths as PA  # noqa: E402
from orgene import pipeline as P  # noqa: E402
from orgene import runner as RN  # noqa: E402
from orgene import unit_exec as U  # noqa: E402
from orgene.backends.base import REQUIRED_CALL_FIELDS, canonical_json, request_sha256  # noqa: E402
from orgene.backends.canned import CANNED_DIGEST, CannedBackend  # noqa: E402
from orgene.conditions import read_jsonl, write_jsonl  # noqa: E402

REUSE_SCRIPT = os.path.join(ROOT, "analysis", "reuse_c0_as_c3l.py")
UNIT_RUNNER = os.path.join(RUNTIME, "unit_runner.py")
OPTS = {"temperature": 0.0, "top_k": 20, "top_p": 0.95, "seed": 1, "num_ctx": 32768, "num_predict": 6000,
        "think": False, "keep_alive": 0}
CLOCK = "2026-01-01T00:00:00+00:00"

# ------------------------------------------------------------------------------------------ self-made cases, answers

TEXT = ("{name} makes products A and B. Each unit of A earns 40 and each unit of B earns 30. A unit of A needs 2 hours "
        "of machining and 1 hour of assembly; a unit of B needs 1 hour of each. At most 100 hours of machining and 80 "
        "hours of assembly are available. Fractional amounts are allowed. Maximise the total earnings.")
NAMES = {"u-a": "Workshop Alder", "u-b": "Workshop Birch", "u-c": "Workshop Cedar", "u-d": "Workshop Dogwood",
         "u-e": "Workshop Elm"}
CASES = [{"case_id": cid, "source": "toy", "text": TEXT.format(name=n),
          "reference": {"objective": 2600.0, "raw": "2600", "status": None}} for cid, n in NAMES.items()]
CASES_BY_ID = {c["case_id"]: c for c in CASES}
BY_TEXT = {("Problem:\n" + c["text"].strip() + "\n"): c["case_id"] for c in CASES}

HEAD = ("import pulp\nprob = pulp.LpProblem('mix', pulp.LpMaximize)\na = pulp.LpVariable('a', lowBound=0)\n"
        "b = pulp.LpVariable('b', lowBound=0)\nprob += 40 * a + 30 * b\n")
SOLVE = "prob.solve(pulp.PULP_CBC_CMD(msg=0))\nprint('STATUS:', pulp.LpStatus[prob.status])\n"
REPORT = "print('FINAL_OBJECTIVE:', pulp.value(prob.objective))\n"
GOOD = HEAD + "prob += 2 * a + b <= 100\nprob += a + b <= 80\n" + SOLVE + REPORT
ERR1 = HEAD + "hours = float('100 h')\nprob += 2 * a + b <= hours\nprob += a + b <= 80\n" + SOLVE + REPORT
ERR2 = HEAD + "prob += 2 * a + b <= 100\nprob += a + b <= 80 / 0\n" + SOLVE + REPORT
INFEASIBLE = HEAD + "prob += 2 * a + b <= 100\nprob += a + b >= 100 + 80\n" + SOLVE + REPORT
LITERAL = HEAD + "prob += 2 * a + b <= 100\nprob += a + b <= 80\n" + SOLVE + "print('FINAL_OBJECTIVE:', 2600)\n"
SPEC = {"problem_type": "LP",
        "decision_variables": [{"name": "a", "domain": "continuous", "lower": 0, "upper": None, "meaning": "units of A"},
                               {"name": "b", "domain": "continuous", "lower": 0, "upper": None, "meaning": "units of B"}],
        "objective": {"sense": "max", "expression": "40*a + 30*b", "meaning": "earnings"},
        "constraints": [{"name": "machining", "expression": "2*a + b <= 100", "source_sentence": "100 hours"},
                        {"name": "assembly", "expression": "a + b <= 80", "source_sentence": "80 hours"}],
        "assumptions": ["fractional amounts allowed"]}
# case -> program per round (the last one repeats)
SCRIPT = {
    "u-a": [GOOD],                             # accepted at round 0
    "u-b": [ERR1, ERR2, GOOD],                 # fails twice, repaired in round 2
    "u-c": [INFEASIBLE, INFEASIBLE, INFEASIBLE],  # status repaired once; no application left afterwards
    "u-d": [LITERAL, ERR1, GOOD],              # fixing the protocol breaks the run, then fixed
    "u-e": [ERR1, ERR1, ERR1],                 # never runs: rounds exhausted
}
EXPECT = {"u-a": ("accepted", 1), "u-b": ("accepted", 3), "u-c": ("no_repair_left", 2), "u-d": ("accepted", 3),
          "u-e": ("rounds_exhausted", 3)}


def fenced(code):
    return "```python\n" + code + "```\n"


def asks_for_spec(messages):
    return "JSON specification" in messages[0]["content"]


def answer(messages, body=None):
    case_id = BY_TEXT[messages[1]["content"]]
    rnd = sum(1 for m in messages if m["role"] == "assistant")
    seq = SCRIPT[case_id]
    code = seq[min(rnd, len(seq) - 1)]
    if asks_for_spec(messages):
        return "```json\n" + json.dumps(SPEC, indent=1) + "\n```\n\n" + fenced(code)
    return fenced(code)


def script_backend(**kw):
    return CannedBackend(answer=answer, **kw)


@pytest.fixture(scope="module", autouse=True)
def memo_exec_and_clock():
    """Each distinct program runs once; later executions get a copy of that result (so two paths see the same exec
    dict, temp directory names included). The validation clock is fixed."""
    cache, real = {}, P.run_program

    def memo(code, timeout=60, python=None, workdir=None, record_solves=True):
        key = (code, timeout, record_solves)
        if key not in cache:
            cache[key] = real(code, timeout=timeout, python=python, workdir=workdir, record_solves=record_solves)
        return copy.deepcopy(cache[key])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(P, "run_program", memo)
        mp.setattr(P, "now_iso", lambda: CLOCK)
        yield cache


@pytest.fixture(scope="module")
def reg():
    return CF.load_registry()


def cfg(reg, cid, **change):
    c = copy.deepcopy(CF.get_config(reg, cid))
    c.update(change)
    return c


def ctx_for(run, **kw):
    kw.setdefault("opts", OPTS)
    return U.build_context(str(run), **kw)


def run_all(ctx, backend, cids, cases=CASES, repeat=0, reg_=None):
    reg_ = reg_ or ctx.registry
    return {(c["case_id"], cid): U.run_unit(c, CF.get_config(reg_, cid), repeat, backend, ctx) for cid in cids for c in cases}


def final_bytes(run, cid):
    with open(os.path.join(run, f"final.{cid}.jsonl"), "rb") as f:
        return f.read()


# ------------------------------------------------------------------------------------------ the batch path, for comparison


def write_cases(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"_header": True, "source": "toy", "n": len(CASES)}) + "\n")
        for c in CASES:
            f.write(json.dumps(c) + "\n")
    return path


def batch_run(run, cid, cases_path, backend, reg, c1=("--c1-match-mode", "chars")):
    """What runtime/run_condition.sh does, with the runner (orgene.runner) on the replay backend. `c1`: the C1 options of
    `requests` (E11); the default is the v5 character rule, which the unit path gets with c1_match_mode="chars"."""
    c = CF.get_config(reg, cid)
    cli.main(["requests", "--run", run, "--cases", cases_path, "--cond", cid, *c1])
    src = CF.reuse_source(c)
    if src:
        p = subprocess.run([sys.executable, REUSE_SCRIPT, "--c0-run", run, "--c3l-run", run, "--src-cond", src,
                            "--dst-cond", cid], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
    else:
        req = os.path.join(run, f"requests.{cid}.jsonl")
        assert RN.run_batch(backend, RN.load_requests(req), os.path.join(run, f"gen.{cid}.r0"), OPTS,
                            requests_path=req, argv=[], code_files=()) == 0
    cli.main(["validate", "--run", run, "--cases", cases_path, "--cond", cid, "--round", "0"])
    for r in range(1, c["max_rounds"] + 1):
        req = os.path.join(run, f"requests.{cid}.repair{r}.jsonl")
        if not os.path.exists(req):
            break
        assert RN.run_batch(backend, RN.load_requests(req), os.path.join(run, f"gen.{cid}.repair{r}"), OPTS,
                            requests_path=req, argv=[], code_files=()) == 0
        cli.main(["validate", "--run", run, "--cases", cases_path, "--cond", cid, "--round", str(r)])


PATH_CONFIGS = ("C0", "C1", "C2", "C3", "C3L", "C3E", "C2E", "C3L-ALL")


@pytest.fixture(scope="module")
def both_paths(tmp_path_factory, reg):
    base = tmp_path_factory.mktemp("e06_paths")
    units_run, batch_run_dir = str(base / "units"), str(base / "batch")
    os.makedirs(batch_run_dir)
    cases_path = write_cases(str(base / "toy.jsonl"))
    script = script_backend()
    ctx = ctx_for(units_run, c1_match_mode="chars")  # the batch path below builds C1 with --c1-match-mode chars
    recs = run_all(ctx, script, PATH_CONFIGS)
    replay = CannedBackend(table=script.table)
    for cid in PATH_CONFIGS:
        batch_run(batch_run_dir, cid, cases_path, replay, reg)
    return {"units": units_run, "batch": batch_run_dir, "script": script, "replay": replay, "recs": recs, "ctx": ctx}


# ------------------------------------------------------------------------------------------ shared validate_one


@pytest.mark.parametrize("cid", PATH_CONFIGS)
def test_batch_and_unit_paths_write_byte_identical_final(both_paths, cid):
    """validate_one is shared: the batch path (runner + validate_round + reuse script) and the unit executor write the
    same final.<config>.jsonl, byte for byte, for the same canned answers."""
    assert final_bytes(both_paths["units"], cid) == final_bytes(both_paths["batch"], cid)
    # and the validated records of every round (the batch path writes them in runner-output order)
    U.export_validated(both_paths["units"], cid)
    for p in sorted(os.listdir(both_paths["batch"])):
        if p.startswith(f"validated.{cid}.round"):
            a = sorted(read_jsonl(os.path.join(both_paths["batch"], p)), key=lambda v: v["case_id"])
            b = read_jsonl(os.path.join(both_paths["units"], p))
            assert a == b, p


def test_both_paths_sent_exactly_the_same_requests(both_paths):
    """The replay backend answers only requests the unit path sent: no miss, and the same set of request hashes (the
    unit path's shared round 0 of C3L, C3E, C3L-ALL and C2E is no request at all; neither is the batch path's)."""
    assert both_paths["replay"].misses == []
    assert sorted(both_paths["replay"].sent) == sorted(both_paths["script"].sent)
    n_calls = sum(r["tokens"]["n_calls"] - r["tokens"]["n_calls_reused"] for r in both_paths["recs"].values())
    assert n_calls == len(both_paths["script"].sent)


def test_final_rows_score_unchanged(both_paths):
    for cid in ("C3L", "C3E"):
        m = P.score_condition(both_paths["units"], cid, CASES_BY_ID)
        rows = {r["case_id"]: r for r in read_jsonl(os.path.join(both_paths["units"], f"results.{cid}.jsonl"))}
        assert {c: r["n_calls"] for c, r in rows.items()} == {c: n for c, (_, n) in EXPECT.items()}
        assert {c for c, r in rows.items() if r["correct"]} == {"u-a", "u-b", "u-d"}
        assert m["n"] == 5 and "misreport" in m and rows["u-a"]["verified_correct"] is True


# ------------------------------------------------------------------------------------------ observe, repair, stop


def test_c0_observes_and_never_repairs(both_paths):
    r = both_paths["recs"][("u-e", "C0")]
    assert r["status"] == "complete" and r["stop_reason"] == "observe_only" and r["tokens"]["n_calls"] == 1
    v = r["rounds"][0]["validated"]
    assert v["decision"] == "accepted" and v["max_rounds"] == 0 and r["rounds"][0]["repair_text"] is None
    # every gene of scope C3 is recorded; the four spec genes are not applicable to an answer without a spec
    assert len(v["issues"]) == len(G.activate(G.load_store(both_paths["ctx"].genes_path), condition="C3",
                                              mode="all")[0])
    na = sorted(i["geneId"] for i in v["issues"] if i["detail"] == P.NOT_APPLICABLE)
    assert na == r["inapplicable_genes"] == ["orgene.artifact.spec_present", "orgene.constraints.implemented",
                                             "orgene.objective.sense_consistent", "orgene.variables.domain_consistent"]
    assert all(i["ok"] is None for i in v["issues"] if i["geneId"] in na)
    assert "orgene.execution.runs" in v["hard_failed_genes"]  # recorded, not repaired
    assert r["final_row"]["provisional"] is False
    # C2 asks for a spec: every gene applies
    r2 = both_paths["recs"][("u-e", "C2")]
    assert r2["inapplicable_genes"] == [] and not any(i["detail"] == P.NOT_APPLICABLE
                                                      for i in r2["rounds"][0]["validated"]["issues"])


@pytest.mark.parametrize("cid", ["C3L", "C3E", "C3", "C2E", "C3L-ALL"])
def test_repairs_run_and_stop_as_expected(both_paths, cid):
    """Same failure sequences, same stops, for gene repair and the generic template alike (maxApplications: the run
    gene twice, the status gene once)."""
    got = {c: (r["stop_reason"], r["tokens"]["n_calls"]) for (c, x), r in both_paths["recs"].items() if x == cid}
    assert got == EXPECT
    e = both_paths["recs"][("u-e", cid)]
    runs, status = "orgene.execution.runs", "orgene.solution.status_optimal_or_justified"
    assert [runs in r["repair_applied_genes"] for r in e["rounds"]] == [True, True, False]
    assert [status in r["repair_applied_genes"] for r in e["rounds"]] == [True, False, False]
    assert e["applications"] == {runs: 2, status: 1}
    assert [r["validated"]["decision"] for r in e["rounds"]] == ["repair_requested", "repair_requested", "accepted"]


@pytest.mark.parametrize("cid", ["C3E", "C2E"])
def test_generic_repair_messages_are_template_only(both_paths, cid):
    for (c, x), r in both_paths["recs"].items():
        if x != cid:
            continue
        for rd in r["rounds"]:
            if rd["repair_text"]:
                assert G.generic_message_violations(rd["repair_text"], exec_result=rd["validated"]["exec"],
                                                    closing=r["config"]["closing"]) == [], (c, rd["round"])


def test_repair_requests_rebuild_to_the_recorded_hashes(both_paths):
    """unit_messages() rebuilds every call's messages (round 0 whole, later calls from their appended pair); the request
    rebuilt from them hashes to what was sent."""
    b = both_paths["script"]
    for r in both_paths["recs"].values():
        for rd in r["rounds"]:
            for i, entry in enumerate(rd["calls"]):
                msgs = U.unit_messages(r, rd["round"], i)
                assert request_sha256(b.build_body(msgs, r["opts"])) == entry["call"]["request_sha256"]
                if rd["round"] > 0:
                    assert entry["request_id"] == f"{r['case_id']}.{r['config_id']}.rep0.repair{rd['round']}"


def test_unit_records_carry_the_interface_fields(both_paths):
    need = ("schema_version", "unit_id", "case_id", "config_id", "repeat", "status", "stop_reason", "error", "pipeline",
            "config", "setup_sha256", "model", "model_registry", "opts", "features_sha256", "activation",
            "inapplicable_genes", "round0", "rounds", "applications", "tokens", "token_cap", "budget_stop", "timing",
            "final_row", "schedule", "started_at", "finished_at", "code_sha256", "exec_timeout_s", "context_check",
            "context_exceeded")
    for r in both_paths["recs"].values():
        assert not [k for k in need if k not in r], r["unit_id"]
        for rd in r["rounds"]:
            for e in rd["calls"]:
                assert not [k for k in REQUIRED_CALL_FIELDS if k not in e["call"]]
        # the only host paths are the random execution directories inside exec (E12's capture; see E06 notes)
        text = G.scrub_exec_paths(json.dumps(r))
        assert not PA.find_absolute_paths(text)
        assert r["tokens"]["total"] == sum((e["call"]["prompt_eval_count"] or 0) + (e["call"]["eval_count"] or 0)
                                           for rd in r["rounds"] for e in rd["calls"])


def test_unit_records_are_compact_json(both_paths):
    """Unit records are written without indentation (one line); the content is unchanged."""
    d = os.path.join(both_paths["units"], "units")
    names = [n for n in os.listdir(d) if n.endswith(".json") and n != U.SETUP_FILE]
    assert len(names) == len(both_paths["recs"])
    for n in names:
        text = open(os.path.join(d, n), encoding="utf-8").read()
        assert text == json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":")) + "\n", n


def test_context_is_unchecked_without_a_local_counter(both_paths):
    """No local counter on the backend: repair calls are made, and counted as not checked (never as fitting)."""
    for (c, cid), r in both_paths["recs"].items():
        n_repairs = sum(1 for rd in r["rounds"] if rd["round"] > 0)
        assert r["context_check"]["unchecked"] == n_repairs and r["context_check"]["checked"] == 0, (c, cid)
        assert r["context_exceeded"] is None and r["exec_timeout_s"] == 60


# ------------------------------------------------------------------------------------------ shared round 0


def test_c3l_takes_c0_round0_with_its_own_request_meta(both_paths):
    for c in CASES:
        c0, c3l = both_paths["recs"][(c["case_id"], "C0")], both_paths["recs"][(c["case_id"], "C3L")]
        e0, e1 = c0["rounds"][0]["calls"][0], c3l["rounds"][0]["calls"][0]
        assert e1["reused"] is True and c3l["tokens"]["n_calls_reused"] == 1
        assert e1["call"]["content_sha256"] == e0["call"]["content_sha256"]
        assert c3l["round0"]["reused_from"]["unit_id"] == c0["unit_id"]
        assert c3l["round0"]["reused_from"]["request_sha256"] == e0["call"]["request_sha256"]
        # E03 item 5: the meta is C3L's own request's (config id, gene scope, 13 genes), not C0's (17 genes)
        assert e1["meta"]["config_id"] == "C3L" and e1["meta"]["gene_scope"] == "C3L"
        assert len(e1["meta"]["active_genes"]) == len(c3l["activation"]["active_genes"]) == 13
        assert len(e0["meta"]["active_genes"]) == 17
        # round 0 counts for the method's cost
        assert c3l["final_row"]["rounds"][0]["out_tokens"] == c0["final_row"]["rounds"][0]["out_tokens"]


def test_c2e_takes_c2_round0(both_paths):
    for c in CASES:
        c2, c2e = both_paths["recs"][(c["case_id"], "C2")], both_paths["recs"][(c["case_id"], "C2E")]
        assert c2e["round0"]["reused_from"]["config_id"] == "C2"
        assert c2e["rounds"][0]["calls"][0]["call"]["content_sha256"] == c2["rounds"][0]["calls"][0]["call"]["content_sha256"]
        for rd in c2e["rounds"]:
            if rd["repair_text"]:
                assert rd["repair_text"].endswith(G.GENERIC_CLOSING["spec_and_program"])


def _one_c0(tmp_path, case=None):
    case = case or CASES[1]
    run = tmp_path / "run"
    ctx = ctx_for(run)
    b = script_backend()
    U.run_unit(case, CF.get_config(ctx.registry, "C0"), 0, b, ctx)
    return run, ctx, b, case


def _edit_unit(run, uid, fn):
    p = os.path.join(run, "units", uid + ".json")
    u = json.load(open(p, encoding="utf-8"))
    fn(u)
    json.dump(u, open(p, "w", encoding="utf-8"))


@pytest.mark.parametrize("damage", ["content", "status", "missing", "messages"])
def test_reuse_refuses_a_source_that_does_not_hold(tmp_path, damage):
    run, ctx, b, case = _one_c0(tmp_path)
    uid = U.unit_id(case["case_id"], "C0", 0)
    if damage == "content":      # the answer was changed after generation
        _edit_unit(run, uid, lambda u: u["rounds"][0]["calls"][0]["call"].update(content="```python\nprint(1)\n```"))
    elif damage == "status":
        _edit_unit(run, uid, lambda u: u.update(status="incomplete"))
    elif damage == "missing":
        os.remove(os.path.join(run, "units", uid + ".json"))
    elif damage == "messages":   # the source answered another system prompt
        def other(u):
            e = u["rounds"][0]["calls"][0]
            e["messages"][0]["content"] += "\nAlso be brief."
            e["call"]["messages_sha256"] = hashlib.sha256(canonical_json(e["messages"])).hexdigest()
        _edit_unit(run, uid, other)
    n_sent = len(b.sent)
    with pytest.raises(U.ReuseError):
        U.run_unit(case, CF.get_config(ctx.registry, "C3L"), 0, b, ctx)
    assert len(b.sent) == n_sent
    assert not os.path.exists(os.path.join(run, "units", U.unit_id(case["case_id"], "C3L", 0) + ".json"))
    assert not os.path.exists(os.path.join(run, "final.C3L.jsonl"))


def test_reuse_refuses_a_source_generated_with_other_settings(tmp_path):
    """A round 0 generated with another seed (or model) is another request: refused (source in another run dir)."""
    case = CASES[0]
    src_run = tmp_path / "src"
    sctx = ctx_for(src_run, opts=dict(OPTS, seed=7))
    U.run_unit(case, CF.get_config(sctx.registry, "C0"), 0, script_backend(), sctx)
    ctx = ctx_for(tmp_path / "run", round0_run_dir=str(src_run))
    with pytest.raises(U.ReuseError, match="another request"):
        U.run_unit(case, CF.get_config(ctx.registry, "C3L"), 0, script_backend(), ctx)
    other = CannedBackend(model="canned:2", answer=answer)
    ctx2 = ctx_for(tmp_path / "run2", round0_run_dir=str(src_run), opts=dict(OPTS, seed=7))
    with pytest.raises(U.ReuseError, match="another request"):
        U.run_unit(case, CF.get_config(ctx2.registry, "C3L"), 0, other, ctx2)


def test_variance_repeats_reuse_their_own_repeat(tmp_path):
    ctx = ctx_for(tmp_path / "run", opts=dict(OPTS, temperature=0.7))
    b = script_backend()
    case = CASES[1]
    recs = {(cid, k): U.run_unit(case, CF.get_config(ctx.registry, cid), k, b, ctx)
            for k in (0, 1) for cid in ("C0", "C3L")}
    for k in (0, 1):
        c3l = recs[("C3L", k)]
        assert c3l["round0"]["reused_from"]["unit_id"] == U.unit_id(case["case_id"], "C0", k)
        assert all(e["call"]["seed"] == 1 + k for rd in c3l["rounds"] for e in rd["calls"])
    r0 = recs[("C0", 0)]["rounds"][0]["calls"][0]["call"]["request_sha256"]
    r1 = recs[("C0", 1)]["rounds"][0]["calls"][0]["call"]["request_sha256"]
    assert r0 != r1 and recs[("C3L", 1)]["round0"]["reused_from"]["request_sha256"] == r1


# ------------------------------------------------------------------------------------------ resume and failures


def test_complete_units_are_skipped(tmp_path):
    run = tmp_path / "run"
    ctx = ctx_for(run)
    b = script_backend()
    first = U.run_unit(CASES[1], CF.get_config(ctx.registry, "C3"), 0, b, ctx)
    n = len(b.sent)
    assert n == 3
    before = final_bytes(run, "C3")
    again = U.run_unit(CASES[1], CF.get_config(ctx.registry, "C3"), 0, b, ctx)
    assert len(b.sent) == n and json.dumps(again, sort_keys=True) == json.dumps(first, sort_keys=True)
    assert final_bytes(run, "C3") == before
    # a lost final row (crash between the unit file and the final file) is restored from the unit record
    os.remove(os.path.join(run, "final.C3.jsonl"))
    U.run_unit(CASES[1], CF.get_config(ctx.registry, "C3"), 0, b, ctx)
    assert final_bytes(run, "C3") == before and len(b.sent) == n


def test_half_finished_units_run_again_from_round0(tmp_path):
    run = tmp_path / "run"
    ctx = ctx_for(run)

    def interrupted(messages, body=None):
        if sum(1 for m in messages if m["role"] == "assistant"):
            raise KeyboardInterrupt  # the process dies during the repair call
        return answer(messages)
    with pytest.raises(KeyboardInterrupt):
        U.run_unit(CASES[1], CF.get_config(ctx.registry, "C3"), 0, CannedBackend(answer=interrupted), ctx)
    half = json.load(open(os.path.join(run, "units", "u-b.C3.r0.json"), encoding="utf-8"))
    assert half["status"] == "running" and len(half["rounds"]) == 1
    assert not os.path.exists(os.path.join(run, "final.C3.jsonl"))
    b = script_backend()
    rec = U.run_unit(CASES[1], CF.get_config(ctx.registry, "C3"), 0, b, ctx)
    assert rec["status"] == "complete" and len(b.sent) == 3  # round 0 generated again, then two repairs
    assert [r["case_id"] for r in read_jsonl(os.path.join(run, "final.C3.jsonl"))] == ["u-b"]


class _RaisingBackend(CannedBackend):
    """call() itself raises on the n-th call (a connection error, a bug in a client library, ...)."""

    def __init__(self, raise_on, **kw):
        super().__init__(answer=answer, **kw)
        self.raise_on, self.n = raise_on, 0

    def call(self, messages, opts, **kw):
        self.n += 1
        if self.n == self.raise_on:
            raise ConnectionResetError("peer reset the connection")
        return super().call(messages, opts, **kw)


@pytest.mark.parametrize("how", ["raises", "fails"])
def test_backend_failure_marks_the_unit_incomplete_and_writes_no_final(tmp_path, how):
    run = tmp_path / "run"
    ctx = ctx_for(run)
    good = script_backend()
    U.run_unit(CASES[0], CF.get_config(ctx.registry, "C3"), 0, good, ctx)  # another unit of the same config: complete
    if how == "raises":
        bad = _RaisingBackend(2)
    else:  # every attempt of the repair call fails; the backend returns ok=False after its retries
        bad = CannedBackend(answer=answer, max_attempts=2,
                            fail=lambda body: "HTTP 500" if len(body["messages"]) > 2 else None)
    rec = U.run_unit(CASES[1], CF.get_config(ctx.registry, "C3"), 0, bad, ctx)
    assert rec["status"] == "incomplete" and rec["final_row"] is None
    assert rec["error"]["kind"] == ("backend_exception" if how == "raises" else "call_failed")
    assert rec["error"]["stage"] == "repair1" and len(rec["rounds"]) == 1
    assert [r["case_id"] for r in read_jsonl(os.path.join(run, "final.C3.jsonl"))] == ["u-a"]
    if how == "fails":
        assert rec["pending_calls"][0]["call"]["ok"] is False and len(rec["pending_calls"][0]["call"]["attempts"]) == 2
    rec2 = U.run_unit(CASES[1], CF.get_config(ctx.registry, "C3"), 0, script_backend(), ctx)
    assert rec2["status"] == "complete"
    assert [r["case_id"] for r in read_jsonl(os.path.join(run, "final.C3.jsonl"))] == ["u-a", "u-b"]


def test_setup_changes_are_refused(tmp_path):
    run = tmp_path / "run"
    U.run_unit(CASES[0], CF.get_config(ctx_for(run).registry, "C0"), 0, script_backend(), ctx_for(run))
    for kw in ({"opts": dict(OPTS, temperature=0.7)}, {"timeout": 30}, {"lexicon": None}):
        ctx = ctx_for(run, **kw)
        with pytest.raises(U.UnitRefused, match="set up differently"):
            U.run_unit(CASES[1], CF.get_config(ctx.registry, "C0"), 0, script_backend(), ctx)


# ------------------------------------------------------------------------------------------ token cap


def test_token_cap_stops_repairs(tmp_path, reg):
    free = U.run_unit(CASES[1], cfg(reg, "C3"), 0, script_backend(), ctx_for(tmp_path / "free"))
    t = [e["call"]["prompt_eval_count"] + e["call"]["eval_count"] for rd in free["rounds"] for e in rd["calls"]]
    assert len(t) == 3 and free["budget_stop"] is None and free["stop_reason"] == "accepted"
    for cap, n_calls, stop_round in ((1, 1, 0), (t[0] + 1, 2, 1), (t[0] + t[1] + 1, 3, None)):
        rec = U.run_unit(CASES[1], cfg(reg, "C3", token_cap=cap), 0, script_backend(), ctx_for(tmp_path / f"cap{cap}"))
        assert rec["tokens"]["n_calls"] == n_calls, cap
        if stop_round is None:
            assert rec["stop_reason"] == "accepted" and rec["budget_stop"] is None
            continue
        assert rec["stop_reason"] == "token_cap" and rec["budget_stop"]["round"] == stop_round
        assert rec["budget_stop"]["tokens_used"] >= cap and rec["token_cap"] == cap
        row = rec["final_row"]
        assert row["decision"] == "accepted" and row["provisional"] is False and row["hard_failed_genes"]
        assert len(row["rounds"]) == n_calls
    # a unit that passes needs no repair: the cap is not a stop reason there
    ok = U.run_unit(CASES[0], cfg(reg, "C3", token_cap=1), 0, script_backend(), ctx_for(tmp_path / "ok"))
    assert ok["stop_reason"] == "accepted" and ok["budget_stop"] is None


def test_token_cap_counts_a_shared_round0(tmp_path, reg):
    run = tmp_path / "run"
    ctx = ctx_for(run)
    b = script_backend()
    U.run_unit(CASES[1], cfg(reg, "C0"), 0, b, ctx)
    # C3L with a cap below round 0's tokens: round 0 is reused (not generated) and already spends the budget
    c = cfg(reg, "C3L", token_cap=1)
    ctx2 = ctx_for(tmp_path / "run2", round0_run_dir=str(run))
    rec = U.run_unit(CASES[1], c, 0, b, ctx2)
    assert rec["tokens"]["n_calls"] == 1 and rec["tokens"]["n_calls_reused"] == 1 and rec["stop_reason"] == "token_cap"


# ------------------------------------------------------------------------------------------ context window


class _GrowingCounter:
    """Rendered prompt = 100 + 14000 tokens per earlier answer: with num_predict 6000 and num_ctx 32768, round 0 and
    the first repair fit, the second repair (prompt 28100 + 6000 = 34100) does not."""

    def identity(self):
        return {"backend": "ollama", "model": "canned:1", "renderer": "growing"}

    def count_prompt(self, messages, think):
        return 100 + 14000 * sum(1 for m in messages if m["role"] == "assistant"), {"history_think_stripped": 0}

    def local_tokens(self, messages, completion, think=None, thinking=None):
        return {"rendered_prompt": self.count_prompt(messages, think)[0], "completion": len(completion or "") // 4}


RUNS_GENE = "orgene.execution.runs"


@pytest.mark.parametrize("cid", ["C3", "C3L", "C3E"])
def test_context_overflow_stops_only_that_unit(tmp_path, reg, cid):
    """E22 engineering cases: a repair request whose local prompt count + num_predict exceeds num_ctx is not sent; the
    unit (only this one) stops with its last answer as the result, counted like a failed repair, and the record says
    which round, the local prompt tokens, num_predict and num_ctx. The run goes on."""
    run = tmp_path / "run"
    ctx = ctx_for(run)
    b = script_backend()
    U.attach_local_counter(b, counter=_GrowingCounter(), counter_id="test:Growing")
    recs = {}
    for c in CASES[:2]:
        if CF.reuse_source(cfg(reg, cid)):
            U.run_unit(c, cfg(reg, "C0"), 0, b, ctx)
        recs[c["case_id"]] = U.run_unit(c, cfg(reg, cid), 0, b, ctx)
    ok, rec = recs["u-a"], recs["u-b"]  # u-a passes at round 0; u-b fails twice (ERR1, ERR2)
    assert ok["status"] == "complete" and ok["stop_reason"] == "accepted" and ok["context_exceeded"] is None
    assert rec["status"] == "complete" and rec["stop_reason"] == "context_exceeded" and rec["error"] is None
    assert rec["tokens"]["n_calls"] == 2 and len(rec["rounds"]) == 2 and rec["pending_calls"] == []
    assert not any(e["request_id"].endswith("repair2") for rd in rec["rounds"] for e in rd["calls"])
    want = {"round": 2, "request_id": f"u-b.{cid}.rep0.repair2", "local_prompt_tokens": 28100, "num_predict": 6000,
            "num_ctx": 32768, "prompt_plus_predict": 34100, "local_tokens_counter": "test:Growing"}
    assert rec["context_exceeded"] == want
    assert rec["context_check"]["checked"] == 2 and rec["context_check"]["unchecked"] == 0
    assert rec["context_check"]["max_prompt_plus_predict"] == 34100
    assert rec["applications"].get(RUNS_GENE) == 1  # the repair that was not sent applied nothing
    row = rec["final_row"]
    assert row["context_exceeded"] == want and row["round"] == 1 and row["decision"] == "accepted"
    assert row["provisional"] is False and row["repair_applied_genes"] == [] and RUNS_GENE in row["hard_failed_genes"]
    assert [r["decision"] for r in row["rounds"]] == ["repair_requested", "accepted"]
    # separately countable: final rows, the conflict table, the score (a failed repair: the answer does not run)
    rows = read_jsonl(os.path.join(run, f"final.{cid}.jsonl"))
    assert [r["case_id"] for r in rows if r.get("context_exceeded")] == ["u-b"]
    assert L.convergence(row) == "context_exceeded"
    assert L.conflict_summary(rows)["convergence"].get("context_exceeded") == 1
    P.score_condition(str(run), cid, CASES_BY_ID)
    res = {r["case_id"]: r for r in read_jsonl(os.path.join(run, f"results.{cid}.jsonl"))}
    assert res["u-b"]["correct"] is False and res["u-b"]["n_calls"] == 2 and res["u-a"]["correct"] is True
    # ladder: at most one repair round keeps the row; round 0 alone is an ordinary cut
    assert U.derive_ladder(rec, 1)["final_row"] == dict(row, max_rounds=1)
    assert "context_exceeded" not in U.derive_ladder(rec, 0)["final_row"]


def test_context_overflow_inside_generate_is_never_sent(tmp_path, reg, monkeypatch):
    """A pipeline function that does not call context_overflow() (here the ORA stand-in) still never sends an
    overflowing call: generate() checks it, and the unit ends incomplete with error kind context_exceeded."""
    ans = _install_fake_ora(monkeypatch)
    b = CannedBackend(answer=ans)
    U.attach_local_counter(b, counter=_GrowingCounter(), counter_id="test:Growing")
    rec = U.run_unit(CASES[1], cfg(reg, "ORA"), 0, b, ctx_for(tmp_path / "run"))
    assert rec["status"] == "incomplete" and rec["final_row"] is None
    assert rec["error"]["kind"] == "context_exceeded" and rec["error"]["round"] == 2
    assert len(b.sent) == 3  # formulate, code, repair 1; repair 2 was not sent
    assert rec["context_exceeded"]["round"] == 2 and rec["context_exceeded"]["local_prompt_tokens"] == 28100
    assert not os.path.exists(os.path.join(tmp_path, "run", "final.ORA.jsonl")) or \
        read_jsonl(os.path.join(tmp_path, "run", "final.ORA.jsonl")) == []


def test_context_check_uses_the_sent_settings(tmp_path, reg):
    """num_ctx and num_predict come from the settings the unit sends (the model registry entry)."""
    regp = _model_registry(tmp_path, opts=dict(OPTS, num_ctx=40000))
    ctx = U.build_context(str(tmp_path / "run"), model_registry=regp, entry_id="canned.main")
    b = script_backend()
    U.attach_local_counter(b, counter=_GrowingCounter(), counter_id="test:Growing")
    rec = U.run_unit(CASES[1], cfg(reg, "C3", num_ctx=40000), 0, b, ctx)
    assert rec["stop_reason"] == "accepted" and rec["tokens"]["n_calls"] == 3  # 34100 <= 40000
    assert rec["context_check"] == {"rule": U.CONTEXT_RULE, "num_ctx": 40000, "num_predict": 6000, "checked": 2,
                                    "unchecked": 0, "max_prompt_plus_predict": 34100}


# ------------------------------------------------------------------------------------------ ladder


@pytest.mark.parametrize("cid", ["C3L", "C3E"])
@pytest.mark.parametrize("k", [0, 1])
def test_ladder_cut_equals_a_unit_run_with_that_cap(tmp_path, reg, cid, k):
    src_run = tmp_path / "src"
    sctx = ctx_for(src_run)
    b = script_backend()
    two = {}
    for c in CASES:
        U.run_unit(c, cfg(reg, "C0"), 0, b, sctx)
        two[c["case_id"]] = U.run_unit(c, cfg(reg, cid), 0, b, sctx)
    kctx = ctx_for(tmp_path / f"k{k}", round0_run_dir=str(src_run))
    for c in CASES:
        capped = U.run_unit(c, cfg(reg, cid, max_rounds=k), 0, b, kctx)
        cut = U.derive_ladder(two[c["case_id"]], k)
        assert cut["final_row"] == capped["final_row"], c["case_id"]
        assert cut["cost"]["n_calls"] == capped["tokens"]["n_calls"]
        assert cut["cost"]["total"] == capped["tokens"]["total"]


def test_ladder_script_reads_an_exported_unit_run(both_paths, tmp_path):
    """export_validated + ladder.derive_run (analysis/derive_repair_ladder.py) give the same cut as derive_ladder."""
    run = both_paths["units"]
    U.export_validated(run, "C3L")
    L.derive_run(run, "C3L", 1, str(tmp_path / "ladder1"))
    rows = {r["case_id"]: r for r in read_jsonl(str(tmp_path / "ladder1" / "final.C3L.jsonl"))}
    for c in CASES:
        assert rows[c["case_id"]] == U.derive_ladder(both_paths["recs"][(c["case_id"], "C3L")], 1)["final_row"]


def test_rebuild_final_matches_the_incremental_file(both_paths, tmp_path):
    import shutil
    run = str(tmp_path / "copy")
    shutil.copytree(both_paths["units"], run)
    for cid in PATH_CONFIGS:
        before = final_bytes(run, cid)
        os.remove(os.path.join(run, f"final.{cid}.jsonl"))
        assert U.rebuild_final(run, cid) == len(CASES)
        assert final_bytes(run, cid) == before


# ------------------------------------------------------------------------------------------ activation, registry, setup


def test_per_problem_activation_needs_features(tmp_path, reg):
    ctx = ctx_for(tmp_path / "run", lexicon=None)
    with pytest.raises(U.UnitRefused, match="per_problem needs the problem features"):
        U.run_unit(CASES[0], cfg(reg, "C3"), 0, script_backend(), ctx)
    assert not os.path.exists(os.path.join(tmp_path, "run", "units", "u-a.C3.r0.json"))
    rec = U.run_unit(CASES[0], cfg(reg, "C0"), 0, script_backend(), ctx)  # activation all: no features needed
    assert rec["status"] == "complete" and rec["features_sha256"] is None


def test_per_problem_rules_decide_the_genes_of_both_prompt_and_checks(tmp_path, reg):
    """With a gene rule on a problem feature, the genes a unit validates with are the ones its request was built with,
    per case; the all-active ablation (C3L-ALL) ignores the rule."""
    genes = tmp_path / "genes.jsonl"
    rows = [json.loads(line) for line in open(os.path.join(ROOT, "genes", "genes.r1.jsonl"), encoding="utf-8")
            if line.strip() and not line.startswith("#")]
    for g in rows:
        if g["geneId"] == "orgene.numeric.bigm_bounded":
            g["activation"] = {"rule": {"feature": "binary_terms", "op": "==", "value": True}, "rationale": "test"}
    genes.write_text("".join(json.dumps(g) + "\n" for g in rows), encoding="utf-8")
    yes = dict(CASES[0], case_id="u-y", text=CASES[0]["text"] + " Decide yes or no for an optional overtime shift.")
    BY_TEXT["Problem:\n" + yes["text"].strip() + "\n"] = "u-a"
    ctx = ctx_for(tmp_path / "run", genes_path=str(genes))
    b = script_backend()
    ids = {}
    for case in (CASES[0], yes):
        for cid in ("C0", "C3L", "C3L-ALL", "C3"):
            r = U.run_unit(case, cfg(reg, cid), 0, b, ctx)
            got = [g["geneId"] for g in r["activation"]["active_genes"]]
            assert got == [g["geneId"] for g in r["rounds"][0]["calls"][0]["meta"]["active_genes"]]
            assert [i["geneId"] for i in r["rounds"][0]["validated"]["issues"]] and \
                set(i["geneId"] for i in r["rounds"][0]["validated"]["issues"]) - {"orgene.execution.runs"} <= set(got)
            ids[(case["case_id"], cid)] = got
    assert "orgene.numeric.bigm_bounded" not in ids[("u-a", "C3L")] and "orgene.numeric.bigm_bounded" in ids[("u-y", "C3L")]
    assert "orgene.numeric.bigm_bounded" in ids[("u-a", "C3L-ALL")]
    assert "orgene.numeric.bigm_bounded" not in ids[("u-a", "C3")] and "orgene.numeric.bigm_bounded" in ids[("u-y", "C3")]


def _model_registry(tmp_path, execution=None, **change):
    entry = {"backend": "ollama", "model": "canned:1", "digest": CANNED_DIGEST, "seed_rule": "base+k",
             "opts": dict(OPTS)}
    entry.update(change)
    p = tmp_path / "model_registry.json"
    doc = {"entries": {"canned.main": entry}}
    if execution is not None:
        doc["execution"] = execution
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(p)


def test_model_registry_entry_fixes_what_every_call_sends(tmp_path, reg):
    regp = _model_registry(tmp_path)
    ctx = U.build_context(str(tmp_path / "run"), model_registry=regp, entry_id="canned.main")
    b = script_backend()
    rec = U.run_unit(CASES[1], cfg(reg, "C3"), 0, b, ctx)
    assert rec["model_registry"]["entry_id"] == "canned.main" and rec["status"] == "complete"
    assert all(e["call"]["sent_opts"] == dict(OPTS) for rd in rec["rounds"] for e in rd["calls"])
    # the configuration's generation limits must be the entry's
    with pytest.raises(U.UnitRefused, match="num_predict"):
        U.run_unit(CASES[0], cfg(reg, "C3", num_predict=4000), 0, b, ctx)
    # an entry for another model digest: refused before anything is sent
    ctx2 = U.build_context(str(tmp_path / "run2"), model_registry=_model_registry(tmp_path, digest="0" * 64),
                           entry_id="canned.main")
    b2 = script_backend()
    with pytest.raises(U.UnitRefused, match="refused before sending"):
        U.run_unit(CASES[0], cfg(reg, "C0"), 0, b2, ctx2)
    assert b2.sent == []


def test_exec_timeout_comes_from_the_model_registry(tmp_path, reg, monkeypatch):
    """The execution timeout is the model registry's execution.timeout_s unless given explicitly; it is what
    run_program gets, and it is recorded in units/setup.json and in every unit record (exec_timeout_s)."""
    seen, real = [], P.run_program

    def spy(code, timeout=60, **kw):
        seen.append(timeout)
        return real(code, timeout=timeout, **kw)
    monkeypatch.setattr(P, "run_program", spy)
    regp = _model_registry(tmp_path, execution={"timeout_s": 45})
    ctx = U.build_context(str(tmp_path / "run"), model_registry=regp, entry_id="canned.main")
    assert ctx.timeout == 45
    rec = U.run_unit(CASES[1], cfg(reg, "C3"), 0, script_backend(), ctx)
    assert rec["exec_timeout_s"] == 45 and seen and set(seen) == {45}
    setup = json.load(open(os.path.join(tmp_path, "run", "units", U.SETUP_FILE), encoding="utf-8"))["setup"]
    assert setup["exec_timeout"] == 45
    assert U.build_context(str(tmp_path / "x"), model_registry=regp, entry_id="canned.main", timeout=600).timeout == 600
    assert ctx_for(tmp_path / "y").timeout == U.execution_timeout() == 60  # the repository's registry
    assert U.execution_timeout(str(tmp_path / "absent.json")) == U.DEFAULT_EXEC_TIMEOUT_S
    for bad in (0, "60", True, 1.5):
        with pytest.raises(U.UnitRefused, match="timeout_s"):
            U.build_context(str(tmp_path / "z"), model_registry=_model_registry(tmp_path, execution={"timeout_s": bad}),
                            entry_id="canned.main")


def test_context_needs_either_an_entry_or_explicit_opts(tmp_path):
    with pytest.raises(U.UnitRefused):
        U.build_context(str(tmp_path / "run"))


# ------------------------------------------------------------------------------------------ pipelines (E15's seam)


def test_ora_is_refused_until_its_module_exists(tmp_path, reg):
    ctx = ctx_for(tmp_path / "run")
    with pytest.raises(U.PipelineNotImplemented, match="agent_baseline.run_ora"):
        U.run_unit(CASES[0], cfg(reg, "ORA"), 0, script_backend(), ctx)
    with pytest.raises(U.PipelineNotImplemented):
        U.check_pipelines([cfg(reg, "C0"), cfg(reg, "ORA")])
    assert not os.path.exists(os.path.join(tmp_path, "run"))


def _install_fake_ora(monkeypatch):
    """A stand-in for E15's module: run_ora(u) with a formulate call and a code call in round 0, then the generic
    repair template through the UnitRun hooks. Returns the canned answer function it needs."""
    def run_ora(u):
        case = u.case
        sys_msg = {"role": "system", "content": "Write the mathematical model in words."}
        user = {"role": "user", "content": "Problem:\n" + case["text"].strip() + "\n"}
        u.generate([sys_msg, user], request_id=f"{case['case_id']}.ORA.formulate", stage="formulate", rnd=0)
        code_msgs = [{"role": "system", "content": "You write PuLP programs."}, user]
        rid = f"{case['case_id']}.ORA"
        call = u.generate(code_msgs, request_id=rid, stage="code", rnd=0)
        rnd = 0
        while True:
            v, text, applied = u.check(call, rnd, rid)
            u.add_round(v, text, applied)
            if not text:
                return U.stop_reason(u, v, rnd)
            rnd += 1
            appended = [{"role": "assistant", "content": call["content"]}, {"role": "user", "content": text}]
            code_msgs = code_msgs + appended
            rid = f"{case['case_id']}.ORA.rep{u.k}.repair{rnd}"
            call = u.generate(code_msgs, request_id=rid, stage=f"repair{rnd}", rnd=rnd, appended=appended)

    mod = types.ModuleType("orgene.fake_ora")
    mod.run_ora = run_ora
    monkeypatch.setitem(sys.modules, "orgene.fake_ora", mod)
    monkeypatch.setitem(U.PIPELINE_IMPLS, "ora", ("fake_ora", "run_ora"))

    def ans(messages, body=None):
        if messages[0]["content"].startswith("Write the mathematical model"):
            return "Maximise 40a + 30b subject to 2a + b <= 100 and a + b <= 80."
        return answer(messages)
    return ans


def test_pipeline_hooks_carry_a_two_stage_baseline(tmp_path, reg, monkeypatch):
    """What E15 plugs in: a module with run_ora(u). Here a stand-in with a formulate call and a code call in round 0,
    then the generic repair template, bounded by max_rounds and the token cap, all through the UnitRun hooks."""
    ans = _install_fake_ora(monkeypatch)
    rec = U.run_unit(CASES[1], cfg(reg, "ORA"), 0, CannedBackend(answer=ans), ctx_for(tmp_path / "run"))
    assert rec["status"] == "complete" and rec["stop_reason"] == "accepted"
    assert [e["stage"] for e in rec["rounds"][0]["calls"]] == ["formulate", "code"]
    assert rec["tokens"]["n_calls"] == 4 and len(rec["final_row"]["rounds"]) == 3
    for rd in rec["rounds"]:
        if rd["repair_text"]:
            assert G.generic_message_violations(rd["repair_text"], rd["validated"]["exec"], "program") == []
    capped = U.run_unit(CASES[1], cfg(reg, "ORA", token_cap=1), 0, CannedBackend(answer=ans),
                        ctx_for(tmp_path / "cap"))
    assert capped["stop_reason"] == "token_cap" and capped["tokens"]["n_calls"] == 2


# ------------------------------------------------------------------------------------------ batch path, observe mode


def test_batch_validate_observes_c0_with_every_gene(both_paths):
    v = read_jsonl(os.path.join(both_paths["batch"], "validated.C0.round0.jsonl"))
    assert all(len(x["issues"]) == 17 for x in v)
    assert all(x["decision"] == "accepted" for x in v)
    assert {x["case_id"] for x in v if "orgene.execution.runs" in x["hard_failed_genes"]} == {"u-b", "u-e"}


# ------------------------------------------------------------------------------------------ before a batch, command line


def test_preflight_registry_check_runs_the_quick_check():
    seen = []

    def ok(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "[registry] check against live (read-only) quick: OK\n", "")

    def bad(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "[registry] MISMATCH entries.x.digest\n[registry] check: FAIL\n", "")
    U.preflight_registry_check("qwen3-8b.main", runner=ok)
    assert seen[0][-4:] == ["check", "--quick", "--entry", "qwen3-8b.main"]
    with pytest.raises(U.UnitRefused, match="registry check failed"):
        U.preflight_registry_check("qwen3-8b.main", runner=bad)


class _Counter:
    """A local token counter with the tokcount shape (render, local_tokens, identity)."""

    def __init__(self, refuse_text=None, fail_on_completion=None):
        self.refuse_text, self.fail_on_completion = refuse_text, fail_on_completion

    def identity(self):
        return {"backend": "ollama", "model": "canned:1", "renderer": "test"}

    def render(self, messages, think):
        from orgene.tokcount import TokenizerError
        if self.refuse_text and any(self.refuse_text in m["content"] for m in messages):
            raise TokenizerError("cannot render")
        return "|".join(m["content"] for m in messages), {"history_think_stripped": 0}

    def local_tokens(self, messages, completion, think=None, thinking=None):
        if self.fail_on_completion and self.fail_on_completion in (completion or ""):
            raise RuntimeError("tokenizer crashed")
        return {"rendered_prompt": len(self.render(messages, think)[0]) // 4, "completion": len(completion) // 4}


def test_local_counter_is_attached_and_every_request_rendered_first(tmp_path, reg):
    ctx = ctx_for(tmp_path / "run")
    b = script_backend()
    U.attach_local_counter(b, counter=_Counter(), counter_id="test:Counter")
    units = U.default_order(CASES[:2], [cfg(reg, "C3L"), cfg(reg, "C0")])
    assert [(c["case_id"], x["id"]) for c, x, _ in units] == [("u-a", "C0"), ("u-b", "C0"), ("u-a", "C3L"),
                                                              ("u-b", "C3L")]
    assert U.precheck_render(ctx, b, units) == 4
    rec = U.run_unit(CASES[1], cfg(reg, "C3"), 0, b, ctx)
    assert rec["tokens"]["local"]["n_calls_missing"] == 0 and rec["tokens"]["local"]["rendered_prompt"] > 0
    assert rec["local_tokenizer"]["renderer"] == "test"
    b2 = script_backend()
    U.attach_local_counter(b2, counter=_Counter(refuse_text="Workshop Birch"))
    with pytest.raises(U.UnitRefused, match="u-b.C0"):
        U.precheck_render(ctx_for(tmp_path / "run2"), b2, units)
    b3 = script_backend()
    U.attach_local_counter(b3, counter=_Counter(fail_on_completion="80 / 0"))
    rec3 = U.run_unit(CASES[1], cfg(reg, "C3"), 0, b3, ctx_for(tmp_path / "run3"))
    assert rec3["status"] == "complete" and rec3["tokens"]["local"]["n_calls_missing"] == 1


class _FakeOllama:
    """/api/version, /api/tags, /api/show and /api/chat; chat answers come from the canned script."""

    def __init__(self, model="canned:1", digest=CANNED_DIGEST):
        self.chats = 0
        fo = self

        class H(BaseHTTPRequestHandler):
            def _send(self, obj):
                data = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/version":
                    return self._send({"version": "0.33.0"})
                return self._send({"models": [{"name": model, "model": model, "digest": digest, "size": 1}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if self.path == "/api/show":
                    return self._send({"capabilities": ["completion"], "parameters": "", "template": "{{ .Prompt }}"})
                fo.chats += 1
                content = answer(body["messages"])
                self._send({"model": model, "message": {"role": "assistant", "content": content}, "done": True,
                            "done_reason": "stop", "prompt_eval_count": 100, "eval_count": 50,
                            "total_duration": 2_000_000_000})

            def log_message(self, *a):
                pass
        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


def _split_dir(tmp_path, dev, test):
    d = tmp_path / "split"
    d.mkdir()
    (d / "dev_ids.json").write_text(json.dumps(dev), encoding="utf-8")
    (d / "test_ids.json").write_text(json.dumps(test), encoding="utf-8")
    return str(d)


def test_cli_runs_units_against_an_ollama_server(tmp_path, monkeypatch):
    from orgene import freeze as FZ
    gates, real_gate = [], FZ.gate_stage

    def gate(stage, **kw):
        gates.append((stage, kw))
        return real_gate(stage, **kw)
    monkeypatch.setattr(FZ, "gate_stage", gate)
    fake = _FakeOllama()
    try:
        run = str(tmp_path / "run")
        cases = write_cases(str(tmp_path / "toy.jsonl"))
        split = _split_dir(tmp_path, ["u-a", "u-b"], ["u-c", "u-d", "u-e"])
        argv = ["--run", run, "--cases", cases, "--split-dir", split, "--split", "dev", "--cond", "C3E", "C0",
                "--registry", _model_registry(tmp_path, execution={"timeout_s": 45}), "--registry-entry", "canned.main",
                "--host", fake.url, "--no-registry-check", "--local-tokens", "off", "--export-validated"]
        assert U.main(argv) == 0
        assert fake.chats == 1 + 1 + 2  # C0 u-a, u-b; C3E repairs of u-b (its round 0 is C0's)
        # one gate check per process, with every input that decides what is sent or checked (E21)
        assert [g[0] for g in gates] == ["execute"]
        ins = {os.path.basename(p) for p in gates[0][1]["inputs"]}
        assert {"toy.jsonl", "genes.r1.jsonl", "r1_configs.json", "activation_lexicon.v1.json", "model_registry.json",
                "base_system.md", "C0_direct.md", "C3_orgene.md"} <= ins
        units = U.load_units(run)
        assert sorted(u["unit_id"] for u in units) == ["u-a.C0.r0", "u-a.C3E.r0", "u-b.C0.r0", "u-b.C3E.r0"]
        assert all(u["status"] == "complete" for u in units)
        assert {u["exec_timeout_s"] for u in units} == {45}  # no --timeout: the registry's execution.timeout_s
        assert [u["schedule"]["index"] for u in sorted(units, key=lambda u: u["schedule"]["index"])] == [0, 1, 2, 3]
        rc = json.load(open(os.path.join(run, "run_config.json"), encoding="utf-8"))
        assert rc["split"] == "dev" and rc["unit_executor"]["cases"] == ["u-a", "u-b"]
        assert os.path.exists(os.path.join(run, "validated.C3E.round1.jsonl"))
        assert not os.path.exists(os.path.join(run, "freeze_gate.jsonl"))  # dev: no gate record
        assert U.main(argv) == 0 and fake.chats == 4  # everything complete: nothing is sent again
    finally:
        fake.close()


@pytest.mark.parametrize("sealed", ["test", "eng_holdout"])
def test_cli_refuses_the_test_split_without_a_freeze(tmp_path, sealed, monkeypatch):
    from orgene import data as D
    run = str(tmp_path / "run")
    cases = write_cases(str(tmp_path / "toy.jsonl"))
    split = _split_dir(tmp_path, ["u-a", "u-b"], ["u-c", "u-d", "u-e"])
    with open(os.path.join(split, "eng_holdout_ids.json"), "w", encoding="utf-8") as f:
        json.dump(["u-c"], f)
    def forbidden_case_load(*args, **kwargs):
        raise AssertionError("sealed case contents were loaded before the freeze gate")
    monkeypatch.setattr(D, "load_cases", forbidden_case_load)
    monkeypatch.setattr(D, "load_case_ids", forbidden_case_load)
    with pytest.raises(SystemExit, match="refused by the test gate"):
        U.main(["--run", run, "--cases", cases, "--split-dir", split, "--split", sealed, "--cond", "C0",
                "--registry", _model_registry(tmp_path), "--registry-entry", "canned.main", "--host", "http://127.0.0.1:9",
                "--no-registry-check", "--local-tokens", "off"])
    assert not os.path.exists(run)


@pytest.mark.parametrize("label", [None, "dev"])
def test_default_runner_gates_id_metadata_before_deserializing_case_objects(tmp_path, monkeypatch, label):
    from orgene import data as D
    from orgene import freeze as FZ
    # The payload deliberately is not valid JSON: identity discovery must not parse it.
    cases = tmp_path / "protected.jsonl"
    cases.write_text('{"case_id": "u-c", "text": PROTECTED, "reference": UNPARSEABLE}\n')
    monkeypatch.setattr(FZ, "sealed_ids", lambda root=None: {"u-c"})
    def forbidden_case_load(*args, **kwargs):
        raise AssertionError("protected content was loaded before the gate")
    monkeypatch.setattr(D, "load_cases", forbidden_case_load)
    argv = ["--run", str(tmp_path / "run"), "--cases", str(cases), "--cond", "C0",
            "--registry-entry", "canned.main", "--no-registry-check", "--local-tokens", "off"]
    if label is not None:
        argv += ["--split", label]
    with pytest.raises(SystemExit, match="refused by the test gate"):
        U.main(argv)


def test_identity_scan_handles_reordering_escaped_text_and_only_parses_selected_payload(tmp_path):
    from orgene import data as D
    path = tmp_path / "identities.jsonl"
    selected = {"text": 'quoted "case_id": "decoy"', "reference": {"objective": 1}, "case_id": "u-a"}
    path.write_text(json.dumps(selected) + '\n{"reference": UNPARSEABLE, "case_id":"u-c", "text":PROTECTED}\n')
    assert D.load_case_ids(str(path)) == ["u-a", "u-c"]
    assert D.load_cases(str(path), {"u-a"}, metadata_only_filter=True) == [selected]


def test_cli_refuses_a_pipeline_without_implementation_before_anything(tmp_path):
    run = str(tmp_path / "run")
    with pytest.raises(SystemExit, match="not implemented"):
        U.main(["--run", run, "--cases", write_cases(str(tmp_path / "toy.jsonl")), "--cond", "C0", "ORA",
                "--registry-entry", "canned.main", "--no-registry-check"])
    assert not os.path.exists(run)


def test_sealed_cases_need_the_freeze_gate_in_this_process(tmp_path, reg, monkeypatch):
    """run_unit itself refuses a sealed case (test / eng_holdout id) unless the entry point passed the E21 gate."""
    from orgene import freeze as FZ
    monkeypatch.setattr(FZ, "sealed_ids", lambda root=None: {"u-a"})
    ctx = ctx_for(tmp_path / "run")
    b = script_backend()
    with pytest.raises(U.UnitRefused, match="sealed case"):
        U.run_unit(CASES[0], cfg(reg, "C0"), 0, b, ctx)
    assert b.sent == [] and not os.path.exists(os.path.join(tmp_path, "run"))
    assert U.run_unit(CASES[1], cfg(reg, "C0"), 0, b, ctx)["status"] == "complete"  # not sealed
    ctx.gate = {"stage": "execute", "manifest": "FREEZE_MANIFEST.json"}  # what freeze.gate_stage returns on a pass
    assert U.run_unit(CASES[0], cfg(reg, "C0"), 0, b, ctx)["status"] == "complete"


def test_unit_runner_script_shows_usage():
    p = subprocess.run([sys.executable, UNIT_RUNNER, "--help"], capture_output=True, text=True)
    assert p.returncode == 0 and "--registry-entry" in p.stdout


# ------------------------------------------------------------------------------------------ C1 length matching (E11)
# The unit path builds C1 through the same c1match.RequestsC1 as `orgene_cli.py requests`: token-matched from the C1
# matching report by default, the v5 character rule only when asked for. The report here is made the way
# `orgene_cli.py c1-match` makes it, over the real dev ids with self-made statements (ids only: the working library has
# no activation rules, so the dev C3 prompts do not depend on the statements) and a stand-in tokenizer, on a copy of
# conditions/ whose C1 pool is the proposed R1 pool (the working pool carries gene wording, so its report is not ok).


class _StandInTokenizer:
    """characters / 3: deterministic, and not the character measure of the v5 rule."""

    def __init__(self, divisor=3):
        self.divisor = divisor
        self.identity_sha256 = hashlib.sha256(f"stand-in tokenizer /{divisor}".encode()).hexdigest()

    def identity(self):
        return {"backend": "stand-in", "divisor": self.divisor}

    def count(self, text):
        return len(text) // self.divisor

    def counts(self, texts):
        return [self.count(t) for t in texts]


def _c1_world(tmp_path, reg):
    import shutil
    from orgene import c1match as C1M
    from orgene import features as F
    cond = os.path.join(str(tmp_path), "cond_r1")
    shutil.copytree(os.path.join(ROOT, "conditions"), cond, ignore=shutil.ignore_patterns("variants", "drafts", "ora"))
    shutil.copy(os.path.join(ROOT, "conditions", "drafts", "C1_pool_r1.draft.md"),
                os.path.join(cond, "C1_generic_expert_pool.md"))
    genes = os.path.join(ROOT, "genes", "genes.r1.jsonl")
    store = G.load_store(genes)
    tok = _StandInTokenizer()
    ids, info = C1M.dev_set_ids()
    cases = [{"case_id": c, "source": "toy", "text": f"Toy statement {i} with yes or no choices."}
             for i, c in enumerate(ids)]
    rep = C1M.build_report(store, genes, reg, cases, info, F.load_lexicon(),
                           {"qwen": C1M.TokenMeasure(tok, "qwen"), "api": None}, cond_dir=cond, variants=[])
    assert rep["ok"], rep["variants"]["base"].get("errors")
    path = os.path.join(str(tmp_path), "c1_report.json")
    C1M.write_report(rep, path)
    return {"cond": cond, "report": path, "rep": rep, "tok": tok, "make": lambda which, **kw: tok,
            "c1_sha": rep["variants"]["base"]["tokenizers"]["qwen"]["c1"]["sha256"]}


def _sha_path(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_unit_and_batch_paths_build_the_same_token_matched_c1(tmp_path, reg, monkeypatch):
    """Default mode "tokens" on both paths: the C1 prompt is the report's, the requests are identical, the final rows
    are byte-identical; the unit record and units/setup.json say how C1 was matched."""
    from orgene import c1match as C1M
    w = _c1_world(tmp_path, reg)
    monkeypatch.setattr(C1M, "MAKE_COUNTER", w["make"])  # the batch path's `requests`
    units_run, batch_dir = str(tmp_path / "units"), str(tmp_path / "batch")
    os.makedirs(batch_dir)
    cases_path = write_cases(str(tmp_path / "toy.jsonl"))
    script = script_backend()
    ctx = ctx_for(units_run, cond_dir=w["cond"], c1_report=w["report"], c1_make_counter=w["make"])
    recs = run_all(ctx, script, ["C1"])
    replay = CannedBackend(table=script.table)
    batch_run(batch_dir, "C1", cases_path, replay, reg, c1=("--c1-report", w["report"], "--cond-dir", w["cond"]))
    assert replay.misses == [] and sorted(replay.sent) == sorted(script.sent) and len(script.sent) == len(CASES)
    assert final_bytes(units_run, "C1") == final_bytes(batch_dir, "C1")
    assert {r["meta"]["system_prompt_sha256"] for r in read_jsonl(os.path.join(batch_dir, "requests.C1.jsonl"))} \
        == {w["c1_sha"]}
    for r in recs.values():
        meta = r["rounds"][0]["calls"][0]["meta"]
        assert meta["system_prompt_sha256"] == w["c1_sha"]
        assert meta["c1_match"]["measure"] == "tokens:qwen" and meta["c1_match"]["select"] == "closest"
        m = r["c1_matching"]
        assert m["match_mode"] == "tokens" and m["tokenizer"] == "qwen" and m["sha256"] == w["c1_sha"]
        assert m["report_sha256"] == _sha_path(w["report"]) and m["identity_sha256"] == w["tok"].identity_sha256
    setup = json.load(open(os.path.join(units_run, "units", "setup.json"), encoding="utf-8"))["setup"]
    assert setup["c1_matching"] == {"match_mode": "tokens", "tokenizer": "qwen", "report": PA.rel(w["report"])}
    # configurations that are not C1 record no matching
    rec = U.run_unit(CASES[0], cfg(reg, "C0"), 0, script, ctx)
    assert rec["c1_matching"] is None


def test_token_matched_c1_is_refused_without_a_current_report(tmp_path, reg):
    from orgene import c1match as C1M
    w = _c1_world(tmp_path, reg)
    c1, b = cfg(reg, "C1"), script_backend()

    def refused(name, match, **kw):
        kw.setdefault("c1_make_counter", w["make"])
        ctx = ctx_for(tmp_path / name, cond_dir=w["cond"], **kw)
        with pytest.raises(U.UnitRefused, match=match):
            U.run_unit(CASES[0], c1, 0, b, ctx)
        assert not os.path.exists(os.path.join(tmp_path, name, "units", "u-a.C1.r0.json"))

    refused("r1", "no C1 matching report", c1_report=str(tmp_path / "none.json"))
    t = json.load(open(w["report"], encoding="utf-8"))
    t["variants"]["base"]["tokenizers"]["qwen"]["c1"]["sha256"] = "0" * 64
    C1M.write_report(t, str(tmp_path / "tampered.json"))
    refused("r2", "replayed C1 prompt is not the one in the matching report", c1_report=str(tmp_path / "tampered.json"))
    refused("r3", "not the one the C1 matching report was made with", c1_report=w["report"],
            c1_make_counter=lambda which, **kw: _StandInTokenizer(divisor=4))
    bad = dict(t, ok=False)
    C1M.write_report(bad, str(tmp_path / "bad.json"))
    refused("r4", "is not ok", c1_report=str(tmp_path / "bad.json"))
    assert b.sent == []
    # "chars" needs no report: the v5 rule
    ctx = ctx_for(tmp_path / "r5", cond_dir=w["cond"], c1_report=str(tmp_path / "none.json"), c1_match_mode="chars")
    rec = U.run_unit(CASES[0], c1, 0, b, ctx)
    assert rec["status"] == "complete" and rec["c1_matching"]["match_mode"] == "chars"
    assert rec["rounds"][0]["calls"][0]["meta"]["c1_match"]["measure"] == "chars"
    # a run directory set up with one C1 matching refuses the other
    ctx = ctx_for(tmp_path / "r5", cond_dir=w["cond"], c1_report=w["report"], c1_make_counter=w["make"])
    with pytest.raises(U.UnitRefused, match=r"set up differently \(c1_matching\)"):
        U.run_unit(CASES[1], c1, 0, b, ctx)


def test_cli_gate_inputs_include_the_c1_report_of_a_token_matched_c1(tmp_path, monkeypatch):
    """Under the test gate the C1 matching report is a frozen input when the run builds a token-matched C1; the
    optional contract frames of the rewrites are template inputs too (E11 x R1-D17)."""
    from orgene import c1match as C1M
    from orgene import freeze as FZ
    seen = []

    def gate(stage, **kw):
        seen.append(kw["inputs"])
        raise FZ.GateRefused("stop here")
    monkeypatch.setattr(FZ, "gate_stage", gate)
    base = ["--run", str(tmp_path / "run"), "--cases", write_cases(str(tmp_path / "toy.jsonl")),
            "--registry-entry", "canned.main", "--no-registry-check"]
    for extra, want in ((["--cond", "C1"], True), (["--cond", "C0", "C1", "--c1-match-mode", "chars"], False),
                        (["--cond", "C0"], False)):
        with pytest.raises(SystemExit, match="stop here"):
            U.main(base + extra)
        assert (C1M.DEFAULT_REPORT in seen[-1]) is want, extra
    with pytest.raises(SystemExit, match="stop here"):
        U.main(base + ["--cond", "C1", "--c1-report", str(tmp_path / "r.json")])
    assert str(tmp_path / "r.json") in seen[-1] and C1M.DEFAULT_REPORT not in seen[-1]
    frames = [p for p in seen[-1] if os.path.basename(p) == "C3_contract_frame.json"]
    variants = os.path.join(ROOT, "conditions", "variants")
    assert sorted(frames) == sorted(os.path.join(variants, v, "C3_contract_frame.json") for v in os.listdir(variants)
                                    if os.path.isfile(os.path.join(variants, v, "C3_contract_frame.json")))
    assert not os.path.exists(tmp_path / "run")

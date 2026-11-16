"""E05: repair ladder (every repairing configuration runs to at most 2 rounds; lower points are cut from the same run),
C2 + generic repair (C2E), maxApplications bookkeeping shared by C3E and C3L, and the whitelist of the generic
repair message.

Fixtures are self-made two-product problems; no benchmark text is used. Programs run with the fixed interpreter
(env.orgene_python()); no model is called: a fake runner answers every request from a canned table.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import conditions as C  # noqa: E402
from orgene import env as E  # noqa: E402
from orgene import genes as G  # noqa: E402
from orgene import ladder as L  # noqa: E402
from orgene import pipeline as P  # noqa: E402
from orgene.conditions import read_jsonl, write_jsonl  # noqa: E402
from orgene.execute import run_program  # noqa: E402

STORE = os.path.join(ROOT, "genes", "genes.r1.jsonl")
COND_DIR = os.path.join(ROOT, "conditions")
REGISTRY = os.path.join(ROOT, "configs", "r1_configs.json")
PY = E.orgene_python()

# Request building: the per-condition builder of v5 (build_system_prompts + build_requests), or, once the configuration
# registry (E03) replaces it, build_requests(cases, config, store, run_id).
OLD_BUILDER = hasattr(C, "build_system_prompts")
needs_old_builder = pytest.mark.skipif(not OLD_BUILDER, reason="per-condition prompt table replaced by the registry")


def make_requests(cases, cond, run_id="e05"):
    if OLD_BUILDER:
        prompts, info = C.build_system_prompts(COND_DIR, STORE)
        return C.build_requests(cases, cond, prompts, info, run_id)
    from orgene import configs as CF
    reg = CF.load_registry(REGISTRY)
    return C.build_requests(cases, CF.get_config(reg, cond), G.load_store(STORE), run_id)


def gene_ids(meta):
    return {g["geneId"] if isinstance(g, dict) else g for g in meta.get("active_genes") or []}

C3E_GENE_IDS = {
    "orgene.artifact.code_present",
    "orgene.boundary.solve_before_report",
    "orgene.boundary.status_reported",
    "orgene.execution.runs",
    "orgene.solution.status_optimal_or_justified",
}
RUNS = "orgene.execution.runs"
STATUS = "orgene.solution.status_optimal_or_justified"
SOLVE_FIRST = "orgene.boundary.solve_before_report"
REPORTED = "orgene.boundary.status_reported"
CODE = "orgene.artifact.code_present"

# The generic template, written out a second time so that an edit to genes.py cannot pass unnoticed.
TEMPLATE_LINES = {
    "Your program did not finish within the time limit.",
    "Your program failed to run. stderr:",
    "Your program did not produce the two required output lines.",
    "Your program must call .solve() and then print exactly two final lines:",
    "STATUS: <pulp.LpStatus[prob.status]>",
    "FINAL_OBJECTIVE: <the objective value as a plain number>",
    "",
    "Fix it and return the complete corrected Python program in a single ```python block. "
    "Do not explain; do not omit any part.",
    "Fix it and return the complete corrected answer in the same format (the JSON spec block followed by the full "
    "Python program). Do not explain; do not omit any part.",
}
STATUS_LINE = re.compile(r"^The solver reported status: (.*)\.$")
# Recorded when the generic template was frozen for R1 (E05). Changing the template means a new hash here and a
# DECISIONS entry; the freeze manifest records the same value.
GENERIC_TEMPLATE_SHA256 = "ddb95169c40091c83210c5217a29a8bbf124d55f71fdaa392178d70fc6e41dcb"


def issue(gid, pred, detail="failed", ok=False, severity="hard", phase="post_exec"):
    return {"geneId": gid, "version": "1.0.0", "predicateId": pred, "severity": severity, "phase": phase,
            "ok": ok, "detail": detail}


I_RUNS = issue(RUNS, "predicate.executes.v1", "runtime error: ValueError: could not convert string to float: '100 h'")
I_STATUS = issue(STATUS, "predicate.status_optimal_or_justified.v1",
                 "solver status infeasible: re-check constraint directions, bounds, and data; "
                 "state in assumptions if the instance is truly infeasible")
I_SOLVE_FIRST = issue(SOLVE_FIRST, "predicate.solve_before_report.v1",
                      "FINAL_OBJECTIVE appears to print a literal number instead of the solver value", phase="pre_exec")
I_REPORTED = issue(REPORTED, "predicate.status_reported.v1", "program does not print solver STATUS via pulp.LpStatus",
                   phase="pre_exec")
I_CODE = issue(CODE, "predicate.code_present.v1", "no python program using pulp found", phase="pre_exec")

EX_ERR = {"exec_ok": False, "timed_out": False, "status": None,
          "stderr_tail": "Traceback (most recent call last):\n  File \"prog.py\", line 5, in <module>\n"
                         "ValueError: could not convert string to float: '100 h'\n"}
EX_INFEASIBLE = {"exec_ok": True, "timed_out": False, "status": "Infeasible", "stderr_tail": ""}
EX_TIMEOUT = {"exec_ok": False, "timed_out": True, "status": None, "stderr_tail": ""}
EX_SILENT = {"exec_ok": True, "timed_out": False, "status": None, "stderr_tail": ""}

# (name, issues, exec_result): failure mixes a generic message has to cover
MIXES = [
    ("runtime_error", [I_RUNS, issue(STATUS, "predicate.status_optimal_or_justified.v1", "no STATUS reported")], EX_ERR),
    ("infeasible", [I_STATUS], EX_INFEASIBLE),
    ("timeout", [I_RUNS], EX_TIMEOUT),
    ("no_output", [I_RUNS], EX_SILENT),
    ("literal_objective", [I_SOLVE_FIRST], EX_INFEASIBLE),
    ("no_status_print", [I_REPORTED, I_STATUS], EX_SILENT),
    ("no_program", [I_CODE, issue(RUNS, "predicate.executes.v1", "no program to execute")], None),
    ("everything", [I_CODE, I_SOLVE_FIRST, I_REPORTED, I_RUNS, I_STATUS], EX_ERR),
]


@pytest.fixture(scope="module")
def store():
    return G.load_store(STORE)


def active_for(store, cond):
    return G.activate(store, condition=G.gene_scope(cond))[0]


def strip_generic(msg):
    """The lines of a generic message outside its stderr block, with the status value replaced by a placeholder."""
    lines = msg.split("\n")
    out, i = [], 0
    while i < len(lines):
        if lines[i] == "Your program failed to run. stderr:":
            assert lines[i + 1] == "```", msg
            end = max(j for j in range(i + 2, len(lines)) if lines[j] == "```")
            out.append(lines[i])
            i = end + 1
            continue
        m = STATUS_LINE.match(lines[i])
        out.append("The solver reported status: <STATUS>." if m else lines[i])
        i += 1
    return out


# --------------------------------------------------------------- profiles, C3P / NO_REPAIR removed


def test_repair_profiles_and_round_cap():
    assert G.MAX_REPAIR_ROUNDS == 2
    assert set(G.REPAIR_PROFILES) == {"C3", "C3L", "C3E", "C2E"}
    assert {c: p["repair"] for c, p in G.REPAIR_PROFILES.items()} == {
        "C3": "gene", "C3L": "gene", "C3E": "generic", "C2E": "generic"}
    assert {c: p["closing"] for c, p in G.REPAIR_PROFILES.items()} == {
        "C3": "spec_and_program", "C3L": "program", "C3E": "program", "C2E": "spec_and_program"}
    assert G.gene_scope("C2E") == "C3E" and G.gene_scope("C3L") == "C3L" and G.gene_scope("C0") == "C0"
    if hasattr(C, "VALIDATED_CONDITIONS"):
        assert set(C.VALIDATED_CONDITIONS) == set(G.REPAIR_PROFILES)
    with pytest.raises(ValueError):
        G.repair_profile("C0")


@pytest.mark.skipif(not os.path.exists(REGISTRY), reason="configuration registry (E03) not present")
def test_repair_profiles_agree_with_the_configuration_registry():
    """Once the registry exists, every repairing configuration it shares with REPAIR_PROFILES must agree on scope,
    repair mode, closing and round cap."""
    reg = json.load(open(REGISTRY, encoding="utf-8"))
    for c in reg["configs"]:
        if c["id"] in G.REPAIR_PROFILES:
            p = G.REPAIR_PROFILES[c["id"]]
            assert (c["gene_scope"], c["repair"], c["closing"]) == (p["gene_scope"], p["repair"], p["closing"]), c["id"]
            assert c["max_rounds"] == G.MAX_REPAIR_ROUNDS, c["id"]
        elif c.get("repair") not in (None, "none"):
            assert c["max_rounds"] == G.MAX_REPAIR_ROUNDS, c["id"]


def test_c3p_and_no_repair_are_gone():
    assert "C3P" not in getattr(C, "CONDITIONS", ())
    if OLD_BUILDER:
        prompts, info = C.build_system_prompts(COND_DIR, STORE)
        assert "C3P" not in prompts and "C3P" not in info["system_prompt_sha256"]
    sh = open(os.path.join(RUNTIME, "run_condition.sh"), encoding="utf-8").read()
    assert "NO_REPAIR" not in sh and "--no-repair" not in sh
    assert 'if [ "$COND" = "C3" ]' not in sh, "the repair loop must not be limited to C3"
    assert not os.path.exists(os.path.join(ROOT, "analysis", "derive_repair_ladder.sh")), \
        "the ladder is cut from the run (derive_repair_ladder.py), not re-executed"


# --------------------------------------------------------------- C2E


def test_c2e_validates_with_the_c3e_gene_set(store):
    a_c2e, a_c3e = active_for(store, "C2E"), active_for(store, "C3E")
    assert {g["geneId"] for g in a_c2e} == C3E_GENE_IDS
    assert G.store_digest(a_c2e) == G.store_digest(a_c3e)


@needs_old_builder
def test_c2e_prompt_is_c2_in_the_prompt_table():
    prompts, info = C.build_system_prompts(COND_DIR, STORE)
    assert prompts["C2E"] == prompts["C2"] and info["c2e_prompt_equals_c2"] is True
    assert prompts["C2E"] != prompts["C3E"]
    assert info["system_prompt_sha256"]["C2E"] == info["system_prompt_sha256"]["C2"]


def test_c2e_requests_are_c2_requests_with_the_c3e_gene_set():
    case = {"case_id": "e05-x", "source": "smoke", "text": "maximise 2a subject to a <= 3."}
    c2e = make_requests([case], "C2E", "run")[0]
    c2 = make_requests([case], "C2", "run")[0]
    c3e = make_requests([case], "C3E", "run")[0]
    assert c2e["messages"] == c2["messages"], "C2E round 0 is C2's round 0"
    assert c2e["messages"] != c3e["messages"]
    assert c2e["meta"]["contract_sha256"] is None
    assert gene_ids(c2e["meta"]) == C3E_GENE_IDS
    # the message itself carries no configuration or case identity
    body = json.dumps(c2e["messages"])
    assert "C2E" not in body and "e05-x" not in body


def test_closing_lines_per_configuration(store):
    issues = [I_RUNS]
    msgs = {c: G.repair_turn(active_for(store, c), issues, {}, exec_result=EX_ERR, condition=c)[0]
            for c in ("C3", "C3L", "C3E", "C2E")}
    last = {c: m.split("\n")[-1] for c, m in msgs.items()}
    assert "JSON spec block" in last["C2E"] and "python program" in last["C2E"].lower()
    assert "spec" not in last["C3E"].lower() and "```python" in last["C3E"]
    assert "spec" not in msgs["C3L"].lower(), "C3L never asked for a spec"
    assert "JSON spec block" in last["C3"]
    assert last["C2E"] == G.GENERIC_CLOSING["spec_and_program"] and last["C3E"] == G.GENERIC_CLOSING["program"]
    assert msgs["C2E"].split("\n")[:-1] == msgs["C3E"].split("\n")[:-1], "C2E and C3E differ only in the closing"


# --------------------------------------------------------------- whitelist of the generic message


@pytest.mark.parametrize("cond", ["C3E", "C2E"])
@pytest.mark.parametrize("name,issues,ex", MIXES, ids=[m[0] for m in MIXES])
def test_generic_message_is_template_lines_only(store, cond, name, issues, ex):
    msg, applied = G.repair_turn(active_for(store, cond), issues, {}, exec_result=ex, condition=cond)
    assert msg and applied
    bad = [ln for ln in strip_generic(msg) if ln not in TEMPLATE_LINES and ln != "The solver reported status: <STATUS>."]
    assert not bad, bad
    closing = G.REPAIR_PROFILES[cond]["closing"]
    assert G.generic_message_violations(msg, exec_result=ex or {}, closing=closing) == []


def test_template_copy_in_this_test_matches_the_code():
    lines = set(TEMPLATE_LINES) | {G.GENERIC_STATUS}
    assert G.generic_whitelist() == lines


def test_generic_template_hash_is_pinned():
    assert G.generic_template_sha256() == GENERIC_TEMPLATE_SHA256


@pytest.mark.parametrize("cond", ["C3E", "C2E"])
def test_generic_message_contains_no_gene_wording(store, cond):
    texts = []
    for g in store:
        texts += [g["repair"]["instruction"], g["preference"]["statement"], g["preference"].get("rationale", "")]
        for k in ("required", "forbidden", "checks"):
            texts += g["contract"].get(k, [])
    texts = [t for t in texts if t and t.strip()]
    for name, issues, ex in MIXES:
        msg, _ = G.repair_turn(active_for(store, cond), issues, {}, exec_result=ex, condition=cond)
        for t in texts:
            assert t not in msg, (name, t[:60])
        for i in issues:  # predicate details carry modelling advice and must never be forwarded
            if i["detail"] not in ("failed",):
                assert i["detail"] not in msg, (name, i["detail"][:60])
        for hint in ("re-check constraint directions", "state in assumptions", "Fix:", "[orgene."):
            assert hint not in msg, (name, hint)


def test_whitelist_check_catches_non_template_text(store):
    ex = EX_INFEASIBLE
    good, _ = G.repair_turn(active_for(store, "C3E"), [I_STATUS], {}, exec_result=ex, condition="C3E")
    assert G.generic_message_violations(good, exec_result=ex, closing="program") == []
    # the gene-directed message for the same failure is not a generic message
    c3l, _ = G.repair_turn(active_for(store, "C3L"), [I_STATUS], {}, exec_result=ex, condition="C3L")
    assert G.generic_message_violations(c3l)
    # one injected line of modelling advice
    lines = good.split("\n")
    injected = "\n".join(lines[:1] + ["Re-check constraint directions, bounds, and data."] + lines[1:])
    assert G.generic_message_violations(injected)
    # a status value that is not the reported one
    assert G.generic_message_violations(good.replace("Infeasible", "Optimal"), exec_result=ex)
    # the closing of another configuration
    assert G.generic_message_violations(good, closing="spec_and_program")
    # stderr block that is not the program's stderr
    err, _ = G.repair_turn(active_for(store, "C3E"), [I_RUNS], {}, exec_result=EX_ERR, condition="C3E")
    assert G.generic_message_violations(err, exec_result=EX_ERR) == []
    tampered = err.replace("ValueError", "ValueError\nHint: use lpSum over the arcs")
    assert G.generic_message_violations(tampered, exec_result=EX_ERR)


def test_generic_mode_refuses_modelling_genes(store):
    a_l = active_for(store, "C3L")
    with pytest.raises(ValueError):
        G.repair_turn(a_l, [I_RUNS], {}, exec_result=EX_ERR, condition="C3L", repair="generic", closing="program")
    with pytest.raises(ValueError):
        G.check_generic_scope(a_l)
    G.check_generic_scope(active_for(store, "C3E"))


# --------------------------------------------------------------- v5 behaviour kept for the first application


def legacy_c3e_repair_message(issues, exec_result):
    """v5's C3E message (genes.py before E05), verbatim: it never read `applications`."""
    ex = exec_result or {}
    lines, applied = [], []
    for i in G.hard_failures(issues):
        gid = i["geneId"]
        applied.append(gid)
        if gid in ("orgene.execution.runs", "orgene.artifact.code_present"):
            tail = (ex.get("stderr_tail") or "").strip()
            if ex.get("timed_out"):
                lines.append("Your program did not finish within the time limit.")
            elif tail:
                lines.append("Your program failed to run. stderr:\n```\n" + tail[-1200:] + "\n```")
            else:
                lines.append("Your program did not produce the two required output lines.")
        elif gid == "orgene.solution.status_optimal_or_justified":
            lines.append(f"The solver reported status: {ex.get('status') or 'unknown'}.")
        elif gid in ("orgene.boundary.solve_before_report", "orgene.boundary.status_reported"):
            lines.append("Your program must call .solve() and then print exactly two final lines:\n"
                         "STATUS: <pulp.LpStatus[prob.status]>\nFINAL_OBJECTIVE: <the objective value as a plain number>")
    if not lines:
        return None, []
    seen, uniq = set(), []
    for t in lines:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return "\n".join(uniq + ["", "Fix it and return the complete corrected Python program in a single ```python block. "
                                 "Do not explain; do not omit any part."]), applied


_NEW_REPAIR_TURN = G.repair_turn


def legacy_repair_turn(active, issues, applications, exec_result=None, condition="C3", repair=None, closing=None):
    if condition == "C3E":
        return legacy_c3e_repair_message(issues, exec_result)
    return _NEW_REPAIR_TURN(active, issues, applications, exec_result=exec_result, condition=condition,
                            repair=repair, closing=closing)


@pytest.mark.parametrize("name,issues,ex", MIXES, ids=[m[0] for m in MIXES])
def test_first_application_is_byte_identical_to_v5(store, name, issues, ex):
    new = G.repair_turn(active_for(store, "C3E"), issues, {}, exec_result=ex, condition="C3E")
    assert new == legacy_c3e_repair_message(issues, ex)


# --------------------------------------------------------------- symmetry of the bookkeeping (C3E vs C3L)

# (name, issues seen in every validation round, exec result); the same failure repeats in rounds 0, 1 and 2
SEQUENCES = [
    ("infeasible_twice", [I_STATUS], EX_INFEASIBLE),
    ("runtime_error_every_round", [I_RUNS, issue(STATUS, "predicate.status_optimal_or_justified.v1",
                                                  "no STATUS reported")], EX_ERR),
    ("literal_objective_twice", [I_SOLVE_FIRST], EX_INFEASIBLE),
]


def symmetry_violations(repair_turn, store):
    """Run each failure sequence through C3E and C3L for rounds 0..MAX_REPAIR_ROUNDS; list every round in which
    one side asks for a repair of a gene the other side does not."""
    a_e, a_l = active_for(store, "C3E"), active_for(store, "C3L")
    problems, trace = [], {}
    for name, issues, ex in SEQUENCES:
        apps = {"C3E": {}, "C3L": {}}
        for rnd in range(G.MAX_REPAIR_ROUNDS + 1):
            got = {}
            for cond, act in (("C3E", a_e), ("C3L", a_l)):
                if rnd < G.MAX_REPAIR_ROUNDS:
                    msg, applied = repair_turn(act, issues, apps[cond], exec_result=ex, condition=cond)
                else:
                    msg, applied = None, []  # the run stops at the cap
                got[cond] = sorted(applied) if msg else []
                for gid in applied:
                    apps[cond][gid] = apps[cond].get(gid, 0) + 1
            trace[(name, rnd)] = got
            if got["C3E"] != got["C3L"]:
                problems.append((name, rnd, got))
    return problems, trace


def test_c3e_and_c3l_share_the_maxapplications_bookkeeping(store):
    problems, trace = symmetry_violations(G.repair_turn, store)
    assert problems == []
    # a non-Optimal status is repaired once on both sides (maxApplications 1) ...
    assert trace[("infeasible_twice", 0)] == {"C3E": [STATUS], "C3L": [STATUS]}
    assert trace[("infeasible_twice", 1)] == {"C3E": [], "C3L": []}
    # ... a failed run twice on both sides (execution.runs has maxApplications 2)
    assert RUNS in trace[("runtime_error_every_round", 0)]["C3E"]
    assert trace[("runtime_error_every_round", 1)] == {"C3E": [RUNS], "C3L": [RUNS]}


def test_symmetry_check_fails_on_the_v5_c3e_implementation(store):
    """Negative control: with v5's C3E message swapped back in, the same check must fail."""
    problems, trace = symmetry_violations(legacy_repair_turn, store)
    assert problems, "the symmetry check did not detect the v5 asymmetry"
    assert trace[("infeasible_twice", 1)] == {"C3E": [STATUS], "C3L": []}


def test_runs_gene_budget_in_the_store_is_two_and_the_rest_one(store):
    budgets = {g["geneId"]: int(g["repair"]["maxApplications"]) for g in active_for(store, "C3E")}
    assert budgets[RUNS] == 2 and all(v == 1 for k, v in budgets.items() if k != RUNS), budgets


# --------------------------------------------------------------- random exec paths never reach a repair message


FAILING = ("import pulp\nprob = pulp.LpProblem('p', pulp.LpMaximize)\nx = pulp.LpVariable('x', lowBound=0)\n"
           "prob += 3 * x\nlimit = float('4 h')\nprob += x <= limit\nprob.solve(pulp.PULP_CBC_CMD(msg=0))\n"
           "print('STATUS:', pulp.LpStatus[prob.status])\nprint('FINAL_OBJECTIVE:', pulp.value(prob.objective))\n")


def test_repair_messages_do_not_depend_on_the_temporary_exec_dir(store):
    r1, r2 = run_program(FAILING, timeout=60, python=PY), run_program(FAILING, timeout=60, python=PY)
    # run_program records no temporary directory any more (E12, wave2): the traceback names prog.py only
    assert not r1["exec_ok"] and 'File "prog.py"' in r1["stderr_tail"] and "orgene_exec_" not in r1["stderr_tail"]
    assert r1["stderr_tail"] == r2["stderr_tail"]
    # a record written before that (the random directory still in stderr_tail) gives the same repair message
    tmp_dir = "/" + "var" + "/" + "folders" + "/ab/cd/T/orgene_exec_k3j2x9/"
    raw = dict(r2, stderr_tail=r2["stderr_tail"].replace('File "prog.py"', 'File "' + tmp_dir + 'prog.py"'))
    assert "orgene_exec_" in raw["stderr_tail"]
    for cond in ("C3E", "C2E", "C3L", "C3"):
        act = active_for(store, cond)
        msgs = []
        for r in (r1, raw):
            ctx = {"case": {"text": "maximise 3x with x at most 4"}, "spec": None, "code": FAILING, "exec": r}
            issues = G.validate(act, ctx, "pre_exec") + G.validate(act, ctx, "post_exec")
            msgs.append(G.repair_turn(act, issues, {}, exec_result=r, condition=cond)[0])
        assert msgs[0] == msgs[1], cond
        assert "orgene_exec_" not in msgs[0] and 'File "prog.py"' in msgs[0], cond
        if cond in ("C3E", "C2E"):
            assert G.generic_message_violations(msgs[0], exec_result=r1,
                                                closing=G.REPAIR_PROFILES[cond]["closing"]) == []


# --------------------------------------------------------------- pipeline runs with a fake runner

CASE_TEXT = ("A shop makes products A and B. Each unit of A earns 40 and each unit of B earns 30. A unit of A needs "
             "2 hours of machining and 1 hour of assembly; a unit of B needs 1 hour of each. At most 100 hours of "
             "machining and 80 hours of assembly are available. Fractional amounts are allowed. Maximise the total "
             "earnings.")
HEAD = ("import pulp\nprob = pulp.LpProblem('mix', pulp.LpMaximize)\na = pulp.LpVariable('a', lowBound=0)\n"
        "b = pulp.LpVariable('b', lowBound=0)\nprob += 40 * a + 30 * b\n")
SOLVE = "prob.solve(pulp.PULP_CBC_CMD(msg=0))\nprint('STATUS:', pulp.LpStatus[prob.status])\n"
REPORT = "print('FINAL_OBJECTIVE:', pulp.value(prob.objective))\n"
GOOD = HEAD + "prob += 2 * a + b <= 100\nprob += a + b <= 80\n" + SOLVE + REPORT
ERR1 = HEAD + "hours = float('100 h')\nprob += 2 * a + b <= hours\nprob += a + b <= 80\n" + SOLVE + REPORT
ERR2 = HEAD + "prob += 2 * a + b <= 100\nprob += a + b <= 80 / 0\n" + SOLVE + REPORT
INFEASIBLE = HEAD + "prob += 2 * a + b <= 100\nprob += a + b >= 100 + 80\n" + SOLVE + REPORT
LITERAL = HEAD + "prob += 2 * a + b <= 100\nprob += a + b <= 80\n" + SOLVE + "print('FINAL_OBJECTIVE:', 2600)\n"


def fenced(code):
    return "```python\n" + code + "```\n"


# case -> answer per round (the fake runner answers round r with the r-th entry, or the last one)
SCRIPT = {
    "e05-a": [GOOD],                       # accepted at round 0
    "e05-b": [ERR1, ERR2, GOOD],           # fails twice, repaired in round 2
    "e05-c": [INFEASIBLE, INFEASIBLE, INFEASIBLE],  # status repaired once; no application left afterwards
    "e05-d": [LITERAL, ERR1, GOOD],        # fixing the protocol breaks the run: two conflict events
    "e05-e": [ERR1, ERR1, ERR1],           # never runs: rounds exhausted
}
CASES = [{"case_id": cid, "source": "e05", "text": CASE_TEXT,
          "reference": {"objective": 2600.0, "raw": "2600", "status": None}} for cid in SCRIPT]
CASES_BY_ID = {c["case_id"]: c for c in CASES}


def canned(request):
    seq = SCRIPT[request["case_id"]]
    rnd = int((request.get("meta") or {}).get("round", 0))
    return fenced(seq[min(rnd, len(seq) - 1)])


def fake_runner(req_path, gen_dir, seen=None):
    """Answer every request of a request file from SCRIPT, in the runner's output format."""
    os.makedirs(os.path.join(gen_dir, "outputs"), exist_ok=True)
    for r in read_jsonl(req_path):
        content = canned(r)
        req_sha = hashlib.sha256(json.dumps(r["messages"], sort_keys=True).encode("utf-8")).hexdigest()
        if seen is not None:
            seen.append((r["request_id"], req_sha))
        rec = {"request_id": r["request_id"], "case_id": r["case_id"], "condition": r["condition"], "meta": r["meta"],
               "repeat": 0, "seed": 1, "ok": True, "done_reason": "stop",
               "prompt_eval_count": sum(len(m["content"]) for m in r["messages"]) // 4,
               "eval_count": len(content) // 4, "total_duration_ns": 2e9, "content": content,
               "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
        with open(os.path.join(gen_dir, "outputs", f"{r['request_id']}.r0.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1)


def drive(run, cond, max_rounds, cases=CASES):
    """What run_condition.sh does, with the fake runner in place of Ollama."""
    os.makedirs(run, exist_ok=True)
    write_jsonl(os.path.join(run, f"requests.{cond}.jsonl"), make_requests(cases, cond))
    seen = []
    fake_runner(os.path.join(run, f"requests.{cond}.jsonl"), os.path.join(run, f"gen.{cond}.r0"), seen)
    by_id = {c["case_id"]: c for c in cases}
    P.validate_round(run, cond, 0, os.path.join(run, f"gen.{cond}.r0"), by_id, STORE, act=True,
                     max_rounds=max_rounds, python=PY)
    for r in range(1, max_rounds + 1):
        req = os.path.join(run, f"requests.{cond}.repair{r}.jsonl")
        if not os.path.exists(req):
            break
        fake_runner(req, os.path.join(run, f"gen.{cond}.repair{r}"), seen)
        P.validate_round(run, cond, r, os.path.join(run, f"gen.{cond}.repair{r}"), by_id, STORE, act=True,
                         max_rounds=max_rounds, python=PY)
    P.score_condition(run, cond, by_id)
    return seen


_EXEC_DIR = re.compile(r"""[^\s"'<>\\]*orgene_exec_[^\s"'/<>\\]+/""")


def norm(obj):
    """Drop wall-clock fields and the random exec directory, which differ between two executions of one program.
    (Its own pattern, so that the comparison does not rest on the scrubbing under test.) `t` is the solve recorder's
    time since program start in exec.solve_records (E12)."""
    txt = _EXEC_DIR.sub("", json.dumps(obj, sort_keys=True))
    txt = re.sub(r'"(validated_at|seconds|exec_seconds|scored_at|t)": [^,}\]]+', r'"\1": null', txt)
    return json.loads(txt)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    base = tmp_path_factory.mktemp("e05_runs")
    out = {}
    for cond in ("C3E", "C3L"):
        for mr in (2, 1, 0):
            d = str(base / f"{cond}-mr{mr}")
            out[(cond, mr, "seen")] = drive(d, cond, mr)
            out[(cond, mr)] = d
    return out


def by_case(rows):
    return {r["case_id"]: r for r in rows}


@pytest.mark.parametrize("cond", ["C3E", "C3L"])
def test_c3e_and_c3l_calls_per_unit_match_on_the_same_failures(runs, cond):
    rows = by_case(read_jsonl(os.path.join(runs[(cond, 2)], f"results.{cond}.jsonl")))
    assert {c: r["n_calls"] for c, r in rows.items()} == {"e05-a": 1, "e05-b": 3, "e05-c": 2, "e05-d": 3, "e05-e": 3}
    final = by_case(read_jsonl(os.path.join(runs[(cond, 2)], f"final.{cond}.jsonl")))
    # execution.runs is repaired in round 0 and again in round 1; the status gene only once
    e_rounds = final["e05-e"]["rounds"]
    assert RUNS in e_rounds[0]["repair_applied_genes"] and RUNS in e_rounds[1]["repair_applied_genes"]
    assert STATUS in e_rounds[0]["repair_applied_genes"] and STATUS not in e_rounds[1]["repair_applied_genes"]
    c_rounds = final["e05-c"]["rounds"]
    assert c_rounds[0]["repair_applied_genes"] == [STATUS]
    assert c_rounds[1]["decision"] == "accepted" and c_rounds[1]["hard_failed_genes"] == [STATUS]


def test_c3e_and_c3l_apply_the_same_genes_round_by_round(runs):
    fe = by_case(read_jsonl(os.path.join(runs[("C3E", 2)], "final.C3E.jsonl")))
    fl = by_case(read_jsonl(os.path.join(runs[("C3L", 2)], "final.C3L.jsonl")))
    for cid in SCRIPT:
        ae = [sorted(r["repair_applied_genes"]) for r in fe[cid]["rounds"]]
        al = [sorted(r["repair_applied_genes"]) for r in fl[cid]["rounds"]]
        assert ae == al, cid


def test_pipeline_with_v5_c3e_repairs_a_status_twice(tmp_path, monkeypatch):
    """Negative control at pipeline level: v5's C3E message asks again for the infeasible unit."""
    monkeypatch.setattr(G, "repair_turn", legacy_repair_turn)
    run = str(tmp_path / "legacy")
    drive(run, "C3E", 2, cases=[CASES_BY_ID["e05-c"]])
    row = read_jsonl(os.path.join(run, "results.C3E.jsonl"))[0]
    assert row["n_calls"] == 3, "v5's C3E repaired the non-Optimal status in round 1 as well"


@pytest.mark.parametrize("cond", ["C3E", "C3L"])
def test_generic_messages_sent_by_the_pipeline_are_template_only(runs, cond):
    run = runs[(cond, 2)]
    validated = L.read_validated(run, cond)
    for r in (1, 2):
        for req in read_jsonl(os.path.join(run, f"requests.{cond}.repair{r}.jsonl")):
            msg = req["messages"][-1]["content"]
            prev = validated[r - 1][(req["case_id"], 0)]
            viol = G.generic_message_violations(msg, exec_result=prev["exec"] or {}, closing="program")
            if cond == "C3E":
                assert viol == [], (req["request_id"], viol)
            else:
                assert viol, "C3L sends gene-directed messages"


# --------------------------------------------------------------- the ladder is cut from the same run


@pytest.mark.parametrize("cond", ["C3E", "C3L"])
@pytest.mark.parametrize("k", [0, 1, 2])
def test_ladder_cut_equals_a_run_with_that_cap(runs, cond, k):
    src = runs[(cond, 2)]
    final2 = L.read_final(src, cond)
    cut, n_cut = L.derive_final(final2, L.read_validated(src, cond), k)
    direct = L.read_final(runs[(cond, k)], cond)
    assert norm(cut) == norm(direct)
    assert n_cut == {0: 4, 1: 3, 2: 0}[k]
    assert all(r["max_rounds"] == k for r in cut)


@pytest.mark.parametrize("cond", ["C3E", "C3L"])
def test_ladder_cut_scores_like_a_run_with_that_cap(runs, cond, tmp_path):
    src = runs[(cond, 2)]
    man = L.derive_run(src, cond, 1, str(tmp_path / "cut1"))
    assert man["n_cut_at_k"] == 3 and man["source_max_rounds"] == 2 and man["max_repair_rounds"] == 1
    P.score_condition(str(tmp_path / "cut1"), cond, CASES_BY_ID)
    got = norm(read_jsonl(str(tmp_path / "cut1" / f"results.{cond}.jsonl")))
    want = norm(read_jsonl(os.path.join(runs[(cond, 1)], f"results.{cond}.jsonl")))
    assert got == want
    rows = by_case(got)
    assert rows["e05-b"]["n_calls"] == 2 and rows["e05-b"]["correct"] is False
    assert rows["e05-d"]["n_calls"] == 2 and rows["e05-a"]["n_calls"] == 1
    m_cut = json.load(open(tmp_path / "cut1" / f"metrics.{cond}.json"))
    m_dir = json.load(open(os.path.join(runs[(cond, 1)], f"metrics.{cond}.json")))
    assert norm(m_cut) == norm(m_dir)


@pytest.mark.parametrize("cond", ["C3E", "C3L"])
def test_lower_caps_send_exactly_the_same_requests(runs, cond):
    """The round-k requests do not depend on the cap: a run capped at 1 sends a subset of the capped-at-2 requests."""
    s2 = set(runs[(cond, 2, "seen")])
    s1 = set(runs[(cond, 1, "seen")])
    s0 = set(runs[(cond, 0, "seen")])
    assert s0 <= s1 <= s2 and len(s0) == 5 and len(s1) == 9 and len(s2) == 12
    a = open(os.path.join(runs[(cond, 2)], f"requests.{cond}.repair1.jsonl"), "rb").read()
    b = open(os.path.join(runs[(cond, 1)], f"requests.{cond}.repair1.jsonl"), "rb").read()
    assert a == b
    assert not os.path.exists(os.path.join(runs[(cond, 1)], f"requests.{cond}.repair2.jsonl"))
    assert not os.path.exists(os.path.join(runs[(cond, 0)], f"requests.{cond}.repair1.jsonl"))


def test_ladder_refuses_to_cut_above_the_cap_or_in_place(runs):
    src = runs[("C3E", 1)]
    with pytest.raises(ValueError):
        L.derive_final(L.read_final(src, "C3E"), L.read_validated(src, "C3E"), 2)
    with pytest.raises(ValueError):
        L.derive_run(src, "C3E", 0, src)


def test_derive_repair_ladder_script(runs, tmp_path):
    run = str(tmp_path / "C3L-run")
    shutil.copytree(runs[("C3L", 2)], run)
    cases = tmp_path / "cases.jsonl"
    write_jsonl(str(cases), CASES)
    p = subprocess.run([PY, os.path.join(ROOT, "analysis", "derive_repair_ladder.py"), "--run", run,
                        "--cases", str(cases), "--cond", "C3L"], capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    for k in (0, 1):
        got = norm(read_jsonl(os.path.join(f"{run}-r{k}", "results.C3L.jsonl")))
        want = norm(read_jsonl(os.path.join(runs[("C3L", k)], "results.C3L.jsonl")))
        assert got == want, k
    conf = json.load(open(os.path.join(run, "conflicts.C3L.json")))
    assert conf["n_conflict_events"] == 2
    assert conf["convergence"] == {"clean_round0": 1, "converged": 2, "no_repair_left": 1, "rounds_exhausted": 1}


# --------------------------------------------------------------- conflict accounting


def test_conflicts_in_the_pipeline_run(runs):
    s = L.conflict_summary(L.read_final(runs[("C3E", 2)], "C3E"))
    assert s["n_conflict_events"] == 2 and s["n_units_with_conflict"] == 1
    assert set(s["conflict_pairs"]) == {f"{SOLVE_FIRST} -> {RUNS} (hard)", f"{SOLVE_FIRST} -> {STATUS} (hard)"}
    ev = s["events"][0]
    assert ev["case_id"] == "e05-d" and ev["round"] == 1 and ev["fixed_was_targeted"] is True
    assert {(u["case_id"], u["status"]) for u in s["not_converged"]} == {
        ("e05-c", "no_repair_left"), ("e05-e", "rounds_exhausted")}


def _row(cid, rounds, final_hard, max_rounds=2, provisional=False):
    return {"case_id": cid, "repeat": 0, "max_rounds": max_rounds, "provisional": provisional,
            "hard_failed_genes": final_hard,
            "rounds": [{"round": i, "hard_failed_genes": h, "soft_failed_genes": s, "repair_applied_genes": a}
                       for i, (h, s, a) in enumerate(rounds)]}


def test_conflict_events_positive_and_negative():
    rows = [
        # g fixed, h newly hard, k newly soft: two events
        _row("x1", [(["g"], [], ["g"]), (["h"], ["k"], [])], ["h"]),
        # g fixed, nothing new: no event
        _row("x2", [(["g"], [], ["g"]), ([], [], [])], []),
        # h failed before and still fails: not new, so no event
        _row("x3", [(["g", "h"], [], ["g", "h"]), (["h"], [], ["h"]), (["h"], [], [])], ["h"]),
        # a soft warning that stays is not new either
        _row("x4", [(["g"], ["k"], ["g"]), ([], ["k"], [])], []),
    ]
    ev = L.conflict_events(rows)
    assert [(e["case_id"], e["fixed"], e["new"], e["new_severity"]) for e in ev] == [
        ("x1", "g", "h", "hard"), ("x1", "g", "k", "soft")]
    s = L.conflict_summary(rows)
    assert s["convergence"] == {"converged": 2, "no_repair_left": 1, "rounds_exhausted": 1}
    assert {u["case_id"] for u in s["not_converged"]} == {"x1", "x3"}


def test_convergence_labels():
    assert L.convergence(_row("a", [([], [], [])], [])) == "clean_round0"
    assert L.convergence(_row("a", [(["g"], [], ["g"]), ([], [], [])], [])) == "converged"
    assert L.convergence(_row("a", [(["g"], [], ["g"]), (["g"], [], [])], ["g"])) == "no_repair_left"
    assert L.convergence(_row("a", [(["g"], [], ["g"])] * 3, ["g"])) == "rounds_exhausted"
    assert L.convergence(_row("a", [(["g"], [], ["g"])], ["g"], provisional=True)) == "incomplete"


# --------------------------------------------------------------- re-validation, reuse script, run_condition.sh


def test_revalidating_a_round_does_not_duplicate_it(tmp_path):
    run = str(tmp_path / "rv")
    drive(run, "C3E", 2, cases=[CASES_BY_ID["e05-a"], CASES_BY_ID["e05-c"]])
    before = by_case(read_jsonl(os.path.join(run, "final.C3E.jsonl")))
    for r, gen in ((0, "gen.C3E.r0"), (1, "gen.C3E.repair1")):
        P.validate_round(run, "C3E", r, os.path.join(run, gen), CASES_BY_ID, STORE, act=True, max_rounds=2, python=PY)
    after = by_case(read_jsonl(os.path.join(run, "final.C3E.jsonl")))
    assert [x["round"] for x in after["e05-c"]["rounds"]] == [0, 1]
    assert norm(after) == norm(before)


def _reuse(src_run, dst_run, src, dst, extra=()):
    return subprocess.run([PY, os.path.join(ROOT, "analysis", "reuse_c0_as_c3l.py"), "--c0-run", src_run,
                           "--c3l-run", dst_run, "--src-cond", src, "--dst-cond", dst, *extra],
                          capture_output=True, text=True, timeout=60)


def _write_runner_config(gen_dir, model="qwen3:8b", num_ctx=32768, num_predict=6000, temperature=0.0, repeat=1,
                         key="opts"):
    """The fields of the runner's config.json that the reuse check reads. The R1 runner (E08) writes the settings
    under "opts"; key="options" gives v5's layout. test_backends.py runs the reuse check on a real runner config."""
    with open(os.path.join(gen_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"identity": {"model": model}, "repeat": repeat,
                   key: {"temperature": temperature, "num_ctx": num_ctx, "num_predict": num_predict}}, f)


EXPECT = ["--expect-model", "qwen3:8b", "--expect-num-ctx", "32768", "--expect-num-predict", "6000",
          "--expect-temperature", "0", "--expect-repeat", "1"]


def test_round0_reuse_checks_the_source_generation_settings(tmp_path):
    """run_condition.sh passes its own settings: a round 0 generated with another context size, num_predict, model,
    temperature or repeat count is not reused, and neither is one whose settings cannot be read."""
    src_run, dst_run = str(tmp_path / "c0"), str(tmp_path / "c3l")
    os.makedirs(src_run)
    os.makedirs(dst_run)
    cases = [CASES_BY_ID["e05-c"]]
    write_jsonl(os.path.join(src_run, "requests.C0.jsonl"), make_requests(cases, "C0"))
    write_jsonl(os.path.join(dst_run, "requests.C3L.jsonl"), make_requests(cases, "C3L"))
    gen = os.path.join(src_run, "gen.C0.r0")
    fake_runner(os.path.join(src_run, "requests.C0.jsonl"), gen)
    dst_gen = os.path.join(dst_run, "gen.C3L.r0")
    p = _reuse(src_run, dst_run, "C0", "C3L", EXPECT)
    assert p.returncode != 0 and "cannot be checked" in p.stderr, p.stderr
    for bad, field in (({"num_ctx": 16384}, "num_ctx"), ({"num_predict": 4000}, "num_predict"),
                       ({"model": "other:8b"}, "model"), ({"temperature": 0.7}, "temperature"),
                       ({"repeat": 5}, "repeat")):
        _write_runner_config(gen, **bad)
        p = _reuse(src_run, dst_run, "C0", "C3L", EXPECT)
        assert p.returncode != 0 and f"{field}: source" in p.stderr, (field, p.stderr)
        assert not os.path.exists(dst_gen), field
    for key in ("options", "opts"):  # v5's layout, then the R1 runner's (E08)
        _write_runner_config(gen, key=key)
        p = _reuse(src_run, dst_run, "C0", "C3L", EXPECT)
        assert p.returncode == 0 and "5 checked" in p.stdout, (key, p.stderr)
    assert os.path.exists(os.path.join(dst_gen, "outputs", "e05-c.C3L.r0.json"))


def test_run_condition_uses_one_context_size_and_checks_the_reused_round0():
    sh = open(os.path.join(RUNTIME, "run_condition.sh"), encoding="utf-8").read()
    assert re.search(r'^NUM_CTX="\$\{NUM_CTX:-32768\}"$', sh, re.M), "default practice 1: num_ctx 32768 everywhere"
    for flag, var in (("--expect-model", "MODEL"), ("--expect-num-ctx", "NUM_CTX"),
                      ("--expect-num-predict", "NUM_PREDICT"), ("--expect-temperature", "TEMP"),
                      ("--expect-repeat", "REPEAT"), ("--expect-registry-entry", "REGISTRY_ENTRY")):
        assert f'{flag} "${var}"' in sh, flag


def test_round0_reuse_checks_the_registry_entry(tmp_path):
    """With --expect-registry-entry the source generation must have run under the same model registry entry, in the
    version the registry holds now (entry sha256 as the runner records it)."""
    from orgene.runner import load_registry_entry
    reg_path = os.path.join(ROOT, "configs", "model_registry.json")
    sha_main = load_registry_entry(reg_path, "qwen3-8b.main")[1]["entry_sha256"]
    src_run, dst_run = str(tmp_path / "c0"), str(tmp_path / "c3l")
    os.makedirs(src_run)
    os.makedirs(dst_run)
    cases = [CASES_BY_ID["e05-c"]]
    write_jsonl(os.path.join(src_run, "requests.C0.jsonl"), make_requests(cases, "C0"))
    write_jsonl(os.path.join(dst_run, "requests.C3L.jsonl"), make_requests(cases, "C3L"))
    gen = os.path.join(src_run, "gen.C0.r0")
    fake_runner(os.path.join(src_run, "requests.C0.jsonl"), gen)
    expect = EXPECT + ["--expect-registry-entry", "qwen3-8b.main"]

    def with_registry(reg):
        _write_runner_config(gen)
        cfg = json.load(open(os.path.join(gen, "config.json")))
        cfg["registry"] = reg
        json.dump(cfg, open(os.path.join(gen, "config.json"), "w"))

    for reg, why in ((None, "registry_entry: source None"),
                     ({"path": "configs/model_registry.json", "entry_id": "qwen3-8b.r0-v5", "entry_sha256": "0" * 64},
                      "registry_entry: source 'qwen3-8b.r0-v5'"),
                     ({"path": "configs/model_registry.json", "entry_id": "qwen3-8b.main", "entry_sha256": "0" * 64},
                      "another version of it")):
        with_registry(reg)
        p = _reuse(src_run, dst_run, "C0", "C3L", expect)
        assert p.returncode != 0 and why in p.stderr, (why, p.stderr)
        assert not os.path.exists(os.path.join(dst_run, "gen.C3L.r0"))
    with_registry({"path": "configs/model_registry.json", "entry_id": "qwen3-8b.main", "entry_sha256": sha_main})
    p = _reuse(src_run, dst_run, "C0", "C3L", expect)
    assert p.returncode == 0 and "6 checked" in p.stdout, p.stderr


def test_round0_reuse_c2_to_c2e_and_refusal_of_a_wrong_source(tmp_path):
    src_run, dst_run = str(tmp_path / "c2"), str(tmp_path / "c2e")
    os.makedirs(src_run)
    os.makedirs(dst_run)
    cases = [CASES_BY_ID["e05-c"]]
    for run, cond in ((src_run, "C2"), (src_run, "C0"), (dst_run, "C2E")):
        write_jsonl(os.path.join(run, f"requests.{cond}.jsonl"), make_requests(cases, cond))
    fake_runner(os.path.join(src_run, "requests.C2.jsonl"), os.path.join(src_run, "gen.C2.r0"))
    fake_runner(os.path.join(src_run, "requests.C0.jsonl"), os.path.join(src_run, "gen.C0.r0"))
    bad = _reuse(src_run, dst_run, "C0", "C2E")
    assert bad.returncode != 0 and "different messages" in (bad.stdout + bad.stderr)
    assert not os.path.exists(os.path.join(dst_run, "gen.C2E.r0"))
    ok = _reuse(src_run, dst_run, "C2", "C2E")
    assert ok.returncode == 0, ok.stderr
    src_rec = json.load(open(os.path.join(src_run, "gen.C2.r0", "outputs", "e05-c.C2.r0.json")))
    dst_rec = json.load(open(os.path.join(dst_run, "gen.C2E.r0", "outputs", "e05-c.C2E.r0.json")))
    assert dst_rec["content"] == src_rec["content"] and dst_rec["request_id"] == "e05-c.C2E"
    # C2E then validates with the C3E genes and asks for spec + program in the generic template
    P.validate_round(dst_run, "C2E", 0, os.path.join(dst_run, "gen.C2E.r0"), CASES_BY_ID, STORE, act=True,
                     max_rounds=2, python=PY)
    rep = read_jsonl(os.path.join(dst_run, "requests.C2E.repair1.jsonl"))
    assert len(rep) == 1 and rep[0]["meta"]["repaired_genes"] == [STATUS]
    msg = rep[0]["messages"][-1]["content"]
    v0 = read_jsonl(os.path.join(dst_run, "validated.C2E.round0.jsonl"))[0]
    assert G.generic_message_violations(msg, exec_result=v0["exec"], closing="spec_and_program") == []
    assert rep[0]["messages"][:2] == make_requests(cases, "C2")[0]["messages"]


def _run_condition(args, env_extra):
    env = {k: v for k, v in os.environ.items() if k not in ("MAX_ROUNDS", "ROUND0_FROM")}
    env.update(env_extra)
    return subprocess.run(["bash", os.path.join(RUNTIME, "run_condition.sh"), *args], capture_output=True, text=True,
                          timeout=120, env=env)


def test_run_condition_refuses_another_round_cap(tmp_path):
    p = _run_condition([str(tmp_path / "x"), "C3L", "cases.jsonl"], {"MAX_ROUNDS": "1"})
    assert p.returncode != 0 and "fixed at 2" in p.stderr


def test_run_condition_needs_the_round0_source_for_reusing_configs(tmp_path):
    for cond, src in (("C3L", "C0"), ("C3E", "C0"), ("C2E", "C2")):
        p = _run_condition([str(tmp_path / "x"), cond, "cases.jsonl"], {})
        assert p.returncode != 0 and f"round 0 of {src}" in p.stderr, (cond, p.stderr)

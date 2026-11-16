"""Positive/negative examples for the genes derived from dev failures (2026-09-06).

`positive` = the predicate must FIRE (the code has the defect the gene is about).
`negative` = the predicate must PASS (correct code that must not be flagged).
Every example is a minimal, general program; none reproduces a dev case verbatim.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, RUNTIME)

from orgene import genes as G  # noqa: E402

HEAD = "import pulp\nprob = pulp.LpProblem('p', pulp.LpMinimize)\n"
TAIL = "\nprob.solve(pulp.PULP_CBC_CMD(msg=0))\nprint('STATUS:', pulp.LpStatus[prob.status])\nprint('FINAL_OBJECTIVE:', pulp.value(prob.objective))\n"


def run(predicate_id, code, spec=None, case=None, params=None):
    ctx = {"code": HEAD + code + TAIL, "spec": spec, "case": case or {}, "exec": {}}
    return G.PREDICATES[predicate_id](ctx, params or {})


# --------------------------------------------------------------- tuple_key_indexing

TUPLE_KEY_BAD = [
    # LpVariable.dicts over a generator of tuples, then two subscripts
    "N = [1, 2, 3]\n"
    "x = pulp.LpVariable.dicts('x', ((i, j) for i in N for j in N if i != j), lowBound=0)\n"
    "prob += pulp.lpSum([x[i][j] for i in N for j in N if i != j])\n",
    # dict comprehension with tuple keys, then two subscripts
    "N = ['a', 'b']\n"
    "y = {(i, j): pulp.LpVariable(f'y_{i}_{j}', lowBound=0) for i in N for j in N}\n"
    "prob += pulp.lpSum([y[i][j] for i in N for j in N])\n",
    # dict literal with tuple keys read with two subscripts
    "c = {(1, 2): 5, (2, 1): 7}\n"
    "z = pulp.LpVariable('z', lowBound=0)\n"
    "prob += c[1][2] * z\n",
]

TUPLE_KEY_OK = [
    # tuple keys read with a tuple key
    "N = [1, 2, 3]\n"
    "x = pulp.LpVariable.dicts('x', ((i, j) for i in N for j in N if i != j), lowBound=0)\n"
    "prob += pulp.lpSum([x[i, j] for i in N for j in N if i != j])\n",
    # genuinely nested mapping read with two subscripts
    "N = [1, 2]\n"
    "x = {i: {j: pulp.LpVariable(f'x_{i}_{j}', lowBound=0) for j in N} for i in N}\n"
    "prob += pulp.lpSum([x[i][j] for i in N for j in N])\n",
    # plain scalar variables
    "a = pulp.LpVariable('a', lowBound=0)\nb = pulp.LpVariable('b', lowBound=0)\nprob += 2 * a + 3 * b\n",
]


@pytest.mark.parametrize("code", TUPLE_KEY_BAD)
def test_tuple_key_indexing_fires(code):
    ok, detail = run("predicate.tuple_key_indexing.v1", code)
    assert not ok and "d[i, j]" in detail


@pytest.mark.parametrize("code", TUPLE_KEY_OK)
def test_tuple_key_indexing_passes(code):
    ok, _ = run("predicate.tuple_key_indexing.v1", code)
    assert ok


# --------------------------------------------------------------- sparse_index_guard

SPARSE_BAD = [
    # dict built only on existing arcs, read over the full product
    "N = [0, 1, 2]\n"
    "cap = {(0, 1): 4, (1, 2): 5}\n"
    "f = {}\n"
    "for i in N:\n"
    "    for j in N:\n"
    "        if (i, j) in cap:\n"
    "            f[(i, j)] = pulp.LpVariable(f'f_{i}_{j}', lowBound=0)\n"
    "prob += pulp.lpSum([f[(i, j)] for i in N for j in N])\n",
    # dict comprehension with a non-diagonal filter, read unguarded
    "N = [0, 1, 2, 3]\n"
    "d = {(i, j): 1 for i in N for j in N if i < j}\n"
    "v = pulp.LpVariable('v', lowBound=0)\n"
    "prob += pulp.lpSum([d[(i, j)] * v for i in N for j in N])\n",
    # literal table missing arbitrary pairs, read over the full product
    "N = [1, 2, 3]\n"
    "c = {(1, 2): 3, (1, 3): 4, (2, 3): 5, (3, 1): 6}\n"
    "v = pulp.LpVariable('v', lowBound=0)\n"
    "prob += pulp.lpSum([c[(i, j)] * v for i in N for j in N])\n",
]

SPARSE_OK = [
    # sparse dict, read with a membership guard
    "N = [0, 1, 2]\n"
    "cap = {(0, 1): 4, (1, 2): 5}\n"
    "f = {}\n"
    "for i in N:\n"
    "    for j in N:\n"
    "        if (i, j) in cap:\n"
    "            f[(i, j)] = pulp.LpVariable(f'f_{i}_{j}', lowBound=0)\n"
    "prob += pulp.lpSum([f[(i, j)] for i in N for j in N if (i, j) in f])\n",
    # full product minus the diagonal, read with an i != j guard
    "N = [1, 2, 3, 4]\n"
    "c = {(i, j): i + j for i in N for j in N if i != j}\n"
    "v = pulp.LpVariable('v', lowBound=0)\n"
    "prob += pulp.lpSum([c[(i, j)] * v for i in N for j in N if i != j])\n",
    # dense table
    "N = [1, 2]\n"
    "c = {(1, 1): 1, (1, 2): 2, (2, 1): 3, (2, 2): 4}\n"
    "v = pulp.LpVariable('v', lowBound=0)\n"
    "prob += pulp.lpSum([c[(i, j)] * v for i in N for j in N])\n",
]


@pytest.mark.parametrize("code", SPARSE_BAD)
def test_sparse_index_guard_fires(code):
    ok, detail = run("predicate.sparse_index_guard.v1", code)
    assert not ok and "subset of index pairs" in detail


@pytest.mark.parametrize("code", SPARSE_OK)
def test_sparse_index_guard_passes(code):
    ok, _ = run("predicate.sparse_index_guard.v1", code)
    assert ok


# --------------------------------------------------------------- pulp_api_exists

API_BAD = [
    "r = pulp.LpVariable('r', lowBound=0)\nprob += pulp.pi * r\n",
    "a = pulp.LpVariable('a', lowBound=0)\nb = pulp.LpVariable('b', lowBound=0)\nprob += pulp.lpProduct([a, b])\n",
    "x = pulp.LpVariable('x', lowBound=0)\ny = pulp.LpVariable('y', lowBound=0)\nprob += pulp.lpNorm([x, y])\n",
]

API_OK = [
    "x = pulp.LpVariable('x', lowBound=0)\nprob += pulp.lpSum([x])\n",
    "x = pulp.LpVariable('x', lowBound=0)\ny = pulp.LpVariable('y', lowBound=0)\nprob += pulp.lpDot([1, 2], [x, y])\n",
    "x = pulp.LpVariable('x', cat='Binary')\nprob += 3 * x\nprob += pulp.LpConstraint(x, sense=pulp.LpConstraintLE, rhs=1)\n",
]


@pytest.mark.parametrize("code", API_BAD)
def test_pulp_api_exists_fires(code):
    ok, detail = run("predicate.pulp_api_exists.v1", code)
    assert not ok and "do not exist" in detail


@pytest.mark.parametrize("code", API_OK)
def test_pulp_api_exists_passes(code):
    ok, _ = run("predicate.pulp_api_exists.v1", code)
    assert ok


# --------------------------------------------------------------- linear_expressions_only

LINEAR_BAD = [
    # division by a variable expression (a ratio requirement written directly)
    "a = pulp.LpVariable('a', lowBound=0)\nb = pulp.LpVariable('b', lowBound=0)\n"
    "prob += a\nprob += (86 * a + 92 * b) / (a + b) >= 89\n",
    # python min/max on a variable (a tiered price written directly)
    "q = pulp.LpVariable('q', lowBound=0)\nprob += 10 * min(q, 500) + 8 * max(0, q - 500)\n",
    # product of two variable expressions
    "x = pulp.LpVariable('x', lowBound=0)\ny = pulp.LpVariable('y', lowBound=0)\nprob += x * y\n",
]

LINEAR_OK = [
    # the same ratio, cross-multiplied
    "a = pulp.LpVariable('a', lowBound=0)\nb = pulp.LpVariable('b', lowBound=0)\n"
    "prob += a\nprob += 86 * a + 92 * b >= 89 * (a + b)\n",
    # the same tiered price, one variable per tier
    "q1 = pulp.LpVariable('q1', lowBound=0, upBound=500)\nq2 = pulp.LpVariable('q2', lowBound=0, upBound=500)\n"
    "prob += 10 * q1 + 8 * q2\n",
    # an indicator binary with a data-derived big-M
    "x = pulp.LpVariable('x', lowBound=0)\nb = pulp.LpVariable('b', cat='Binary')\n"
    "prob += x\nprob += x <= 1200 * b\n",
]


@pytest.mark.parametrize("code", LINEAR_BAD)
def test_linear_expressions_only_fires(code):
    ok, detail = run("predicate.linear_expressions_only.v1", code)
    assert not ok and "not linear" in detail


@pytest.mark.parametrize("code", LINEAR_OK)
def test_linear_expressions_only_passes(code):
    ok, _ = run("predicate.linear_expressions_only.v1", code)
    assert ok


# --------------------------------------------------------------- objective_aggregates_variables

AGG_BAD = [
    # throughput objective set to one arc while the constraints range over the index set
    "N = [0, 1, 2, 3]\n"
    "f = {(i, j): pulp.LpVariable(f'f_{i}_{j}', lowBound=0) for i in N for j in N}\n"
    "prob += f[(0, 3)]\n"
    "for k in [1, 2]:\n"
    "    prob += pulp.lpSum([f[(i, k)] for i in N]) == pulp.lpSum([f[(k, j)] for j in N])\n",
    # list-of-lists variables, objective on a single cell
    "n = 4\n"
    "f = [[pulp.LpVariable(f'f_{i}_{j}', lowBound=0) for j in range(n)] for i in range(n)]\n"
    "prob += f[0][3]\n"
    "for k in range(1, 3):\n"
    "    prob += pulp.lpSum([f[i][k] for i in range(n)]) == pulp.lpSum([f[k][j] for j in range(n)])\n",
    # single element of a dict family
    "K = ['a', 'b', 'c']\n"
    "z = pulp.LpVariable.dicts('z', K, lowBound=0)\n"
    "prob += z['a']\n"
    "prob += pulp.lpSum([z[k] for k in K]) <= 10\n",
]

AGG_OK = [
    # the same network, objective aggregated over the source's arcs
    "N = [0, 1, 2, 3]\n"
    "f = {(i, j): pulp.LpVariable(f'f_{i}_{j}', lowBound=0) for i in N for j in N}\n"
    "prob += pulp.lpSum([f[(0, j)] for j in N]) - pulp.lpSum([f[(i, 0)] for i in N])\n"
    "for k in [1, 2]:\n"
    "    prob += pulp.lpSum([f[(i, k)] for i in N]) == pulp.lpSum([f[(k, j)] for j in N])\n",
    # explicit weighted sum over several elements of one family
    "v = pulp.LpVariable.dicts('v', [1, 2, 3, 4, 5, 6], lowBound=0)\n"
    "prob += 10 * v[1] + 4 * v[2] + 1 * v[3] + 7 * v[4] + 6 * v[5] + 8 * v[6]\n"
    "prob += pulp.lpSum([v[i] for i in [1, 2, 3, 4, 5, 6]]) >= 1\n",
    # scalar model
    "a = pulp.LpVariable('a', lowBound=0)\nb = pulp.LpVariable('b', lowBound=0)\n"
    "prob += 2 * a + 3 * b\nprob += a + b >= 4\n",
]


@pytest.mark.parametrize("code", AGG_BAD)
def test_objective_aggregates_fires(code):
    ok, detail = run("predicate.objective_aggregates_variables.v1", code)
    assert not ok and "single element" in detail


@pytest.mark.parametrize("code", AGG_OK)
def test_objective_aggregates_passes(code):
    ok, _ = run("predicate.objective_aggregates_variables.v1", code)
    assert ok


# --------------------------------------------------------------- binary_cardinality_linked

CARD_BAD = [
    # counted binaries, only a lower link -> the count cannot bind
    "a = pulp.LpVariable('a', lowBound=0)\nb = pulp.LpVariable('b', lowBound=0)\n"
    "ua = pulp.LpVariable('ua', cat='Binary')\nub = pulp.LpVariable('ub', cat='Binary')\n"
    "prob += a + b\nprob += ua + ub == 1\nprob += a >= 0.1 * ua\nprob += b >= 0.1 * ub\n",
    # counted binaries with no link at all
    "u1 = pulp.LpVariable('u1', cat='Binary')\nu2 = pulp.LpVariable('u2', cat='Binary')\n"
    "x = pulp.LpVariable('x', lowBound=0)\n"
    "prob += x\nprob += u1 + u2 <= 1\nprob += x >= 5\n",
    # three counted binaries, none of them bounding anything
    "y1 = pulp.LpVariable('y1', cat='Binary')\ny2 = pulp.LpVariable('y2', cat='Binary')\n"
    "y3 = pulp.LpVariable('y3', cat='Binary')\nq = pulp.LpVariable('q', lowBound=0)\n"
    "prob += q\nprob += y1 + y2 + y3 >= 2\nprob += q >= 1\n",
]

CARD_OK = [
    # counted binaries that do bound their quantities
    "a = pulp.LpVariable('a', lowBound=0)\nb = pulp.LpVariable('b', lowBound=0)\n"
    "ua = pulp.LpVariable('ua', cat='Binary')\nub = pulp.LpVariable('ub', cat='Binary')\n"
    "prob += a + b\nprob += ua + ub == 1\nprob += a <= 120 * ua\nprob += b <= 120 * ub\n",
    # facility-location shape: binary used for capacity linking, no cardinality constraint
    "y = pulp.LpVariable('y', cat='Binary')\nx = pulp.LpVariable('x', lowBound=0)\n"
    "prob += 1000 * y + 3 * x\nprob += x <= 1500 * y\n",
    # no binaries at all
    "a = pulp.LpVariable('a', lowBound=0)\nprob += a\nprob += a >= 2\n",
]


@pytest.mark.parametrize("code", CARD_BAD)
def test_binary_cardinality_linked_fires(code):
    ok, detail = run("predicate.binary_cardinality_linked.v1", code)
    assert not ok and "cardinality" in detail


@pytest.mark.parametrize("code", CARD_OK)
def test_binary_cardinality_linked_passes(code):
    ok, _ = run("predicate.binary_cardinality_linked.v1", code)
    assert ok


# --------------------------------------------------------------- store integrity

def test_store_loads_and_new_genes_are_well_formed():
    store = os.path.join(os.path.dirname(RUNTIME), "genes", "genes.r1.jsonl")
    genes = G.load_store(store)
    active, _ = G.activate(genes, "C3")
    assert len(active) <= 25, "active gene budget is 25"
    prompt_only = [g for g in active if g["validation"]["mode"] != "executable"]
    assert len(prompt_only) * 2 <= len(active), "prompt_only genes must not exceed half the store"
    derived = [g for g in active if g["audit"]["sourceType"] == "dev_failure_derived"]
    assert derived, "expected dev-derived genes"
    for g in derived:
        assert len(g["audit"]["devCaseIds"]) >= 3, f"{g['geneId']} needs >= 3 triggering dev cases"
        assert g["validation"]["predicateId"] in G.PREDICATES
        assert g["repair"]["instruction"].strip()


# --------------------------------------------------------------- C3L (lite condition, 2026-09-07)

C3L_GENE_IDS = {
    "orgene.artifact.code_present",
    "orgene.boundary.solve_before_report",
    "orgene.boundary.status_reported",
    "orgene.execution.runs",
    "orgene.solution.status_optimal_or_justified",
    "orgene.code.tuple_key_indexing",
    "orgene.code.sparse_index_guard",
    "orgene.code.pulp_api_exists",
    "orgene.model.linear_expressions_only",
    "orgene.objective.aggregates_declared_variables",
    "orgene.model.binary_cardinality_linked",
    "orgene.data.no_invented_numbers",
    "orgene.numeric.bigm_bounded",
}
SPEC_ONLY_GENE_IDS = {
    "orgene.artifact.spec_present",
    "orgene.objective.sense_consistent",
    "orgene.variables.domain_consistent",
    "orgene.constraints.implemented",
}

ROOT = os.path.dirname(RUNTIME)
STORE = os.path.join(ROOT, "genes", "genes.r1.jsonl")
COND_DIR = os.path.join(ROOT, "conditions")


def test_c3l_activation_set_is_the_thirteen_code_and_execution_genes():
    active, _ = G.activate(G.load_store(STORE), condition="C3L")
    ids = {g["geneId"] for g in active}
    assert ids == C3L_GENE_IDS, sorted(ids ^ C3L_GENE_IDS)
    assert len(active) == 13
    assert not (ids & SPEC_ONLY_GENE_IDS), "spec-dependent genes must stay out of C3L"


_CASE = {"case_id": "x-0001", "source": "smoke", "text": "maximise 2a subject to a <= 3."}


def _prompts(*config_ids):
    """(text, meta) per configuration from the registry-driven builder (E03), for one self-made case."""
    from orgene import configs as CF
    from orgene.conditions import build_prompt
    reg, store = CF.load_registry(), G.load_store(STORE)
    return {cid: build_prompt(CF.get_config(reg, cid), _CASE, store, cond_dir=COND_DIR) for cid in config_ids}


def test_c3l_prompt_is_byte_identical_to_c0():
    p = _prompts("C0", "C3L", "C3")
    assert p["C3L"][0] == p["C0"][0]
    assert p["C3L"][1]["system_prompt_sha256"] == p["C0"][1]["system_prompt_sha256"]
    assert p["C3L"][1]["contract_in_prompt"] is False
    # and it must NOT be the C3 prompt
    assert p["C3L"][0] != p["C3"][0]


def test_c3l_requests_carry_no_contract_but_their_own_gene_set():
    from orgene import configs as CF
    from orgene.conditions import build_request
    reg, store = CF.load_registry(), G.load_store(STORE)
    case = _CASE
    c3l = build_request(CF.get_config(reg, "C3L"), case, store, "run", cond_dir=COND_DIR)
    c3 = build_request(CF.get_config(reg, "C3"), case, store, "run", cond_dir=COND_DIR)
    assert c3l["meta"]["contract_sha256"] is None, "C3L compiles no contract into its prompt"
    assert len(c3l["meta"]["active_genes"]) == 13
    assert c3["meta"]["contract_sha256"] is not None
    assert len(c3["meta"]["active_genes"]) == 17


def test_c3l_repair_closing_instruction_never_mentions_a_spec():
    active, _ = G.activate(G.load_store(STORE), condition="C3L")
    issues = [{"geneId": "orgene.execution.runs", "version": "1.0.0", "predicateId": "predicate.executes.v1",
               "severity": "hard", "phase": "post_exec", "ok": False, "detail": "runtime error: KeyError"}]
    msg, applied = G.repair_turn(active, issues, {}, exec_result=None, condition="C3L")
    assert applied == ["orgene.execution.runs"]
    low = msg.lower()
    assert "```python" in msg
    assert "json spec" not in low and "spec block" not in low
    # the C3 wording, by contrast, does ask for the spec
    active_c3, _ = G.activate(G.load_store(STORE), condition="C3")
    msg_c3, _ = G.repair_turn(active_c3, issues, {}, exec_result=None, condition="C3")
    assert "json spec" in msg_c3.lower()


# --------------------------------------------------------------- C3E (execution-only baseline, 2026-09-07)

C3E_GENE_IDS = {
    "orgene.artifact.code_present",
    "orgene.boundary.solve_before_report",
    "orgene.boundary.status_reported",
    "orgene.execution.runs",
    "orgene.solution.status_optimal_or_justified",
}


def test_c3e_activation_set_has_no_ast_or_modelling_genes():
    active, _ = G.activate(G.load_store(STORE), condition="C3E")
    ids = {g["geneId"] for g in active}
    assert ids == C3E_GENE_IDS, sorted(ids ^ C3E_GENE_IDS)
    # none of the dev-derived AST/modelling genes may be active in the execution-only baseline
    forbidden = {
        "orgene.code.tuple_key_indexing", "orgene.code.sparse_index_guard", "orgene.code.pulp_api_exists",
        "orgene.model.linear_expressions_only", "orgene.objective.aggregates_declared_variables",
        "orgene.model.binary_cardinality_linked", "orgene.data.no_invented_numbers", "orgene.numeric.bigm_bounded",
    }
    assert not (ids & forbidden), sorted(ids & forbidden)


def test_c3e_prompt_is_byte_identical_to_c0():
    p = _prompts("C0", "C3L", "C3E")
    assert p["C3E"][0] == p["C0"][0] == p["C3L"][0]
    assert p["C3E"][1]["system_prompt_sha256"] == p["C0"][1]["system_prompt_sha256"]


def _all_gene_wording(store_path):
    """Every sentence the gene store could contribute to a repair message."""
    import json
    out = []
    with open(store_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            g = json.loads(line)
            out.append(g["repair"]["instruction"])
            out.append(g["preference"]["statement"])
            out.extend(g["contract"].get("required", []))
            out.extend(g["contract"].get("forbidden", []))
            out.extend(g["contract"].get("checks", []))
    return [t for t in out if t and t.strip()]


def test_c3e_repair_message_contains_no_gene_wording():
    active, _ = G.activate(G.load_store(STORE), condition="C3E")
    issues = [
        {"geneId": "orgene.execution.runs", "version": "1.0.0", "predicateId": "predicate.executes.v1",
         "severity": "hard", "phase": "post_exec", "ok": False, "detail": "runtime error: KeyError: 'A'"},
        {"geneId": "orgene.solution.status_optimal_or_justified", "version": "1.0.0",
         "predicateId": "predicate.status_optimal_or_justified.v1", "severity": "hard", "phase": "post_exec",
         "ok": False,
         "detail": "solver status infeasible: re-check constraint directions, bounds, and data; "
                   "state in assumptions if the instance is truly infeasible"},
    ]
    exec_res = {"status": "Infeasible", "stderr_tail": "KeyError: 'A'", "exec_ok": False}
    msg, applied = G.repair_turn(active, issues, {}, exec_result=exec_res, condition="C3E")
    assert msg and set(applied) == {"orgene.execution.runs", "orgene.solution.status_optimal_or_justified"}
    # the fixed template, and nothing else
    assert "The solver reported status: Infeasible." in msg
    assert "```python" in msg
    # no gene wording at all
    for text in _all_gene_wording(STORE):
        assert text not in msg, f"gene wording leaked into the C3E repair message: {text[:70]}"
    # and specifically none of the modelling advice carried by the predicate details
    for hint in ("re-check constraint directions", "state in assumptions", "lpSum", "big-M", "linearize",
                 "tuple key", "index set", "aggregate"):
        assert hint.lower() not in msg.lower(), hint


def test_c3e_repair_message_differs_from_c3l_for_the_same_failure():
    issues = [{"geneId": "orgene.execution.runs", "version": "1.0.0", "predicateId": "predicate.executes.v1",
               "severity": "hard", "phase": "post_exec", "ok": False, "detail": "runtime error: KeyError: 'A'"}]
    exec_res = {"status": None, "stderr_tail": "KeyError: 'A'", "exec_ok": False}
    store = G.load_store(STORE)
    a_e, _ = G.activate(store, condition="C3E")
    a_l, _ = G.activate(store, condition="C3L")
    m_e, _ = G.repair_turn(a_e, issues, {}, exec_result=exec_res, condition="C3E")
    m_l, _ = G.repair_turn(a_l, issues, {}, exec_result=exec_res, condition="C3L")
    assert m_e != m_l
    assert "Fix:" not in m_e, "C3E must not carry the gene's Fix: instruction"
    assert "Fix:" in m_l

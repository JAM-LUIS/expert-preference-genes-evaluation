"""D12 (2026-10-03): checklist repair (C3T, C3A) and rules in the prompt (C0R-E). Self-made examples only."""
import itertools
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))
from orgene import conditions as C, configs as CF, features as F, genes as G, unit_exec as U
from orgene.backends.canned import CannedBackend

GENES = ROOT / "genes/genes.it1.jsonl"
LEX = ROOT / "genes/activation_lexicon.v2.json"
STORE = G.load_store(GENES, lexicon=LEX)
BY_ID = {g["geneId"]: g for g in STORE}
C3L = [g for g in STORE if "C3L" in g["scope"]["conditions"]]
T = C.load_templates()
CHECKLIST = C.review_checklist(T)
E_IDS = sorted(g["geneId"] for g in C3L if G._in_generic_scope(g))
M_IDS = sorted(g["geneId"] for g in C3L if not G._in_generic_scope(g) and g["validation"]["severity"] == "hard")
S_IDS = sorted(g["geneId"] for g in C3L if g["validation"]["severity"] == "soft")
EXEC = {"stderr_tail": "Traceback (most recent call last):\nKeyError: 'a'", "status": None}


def issue(gid, ok=False):
    g = BY_ID[gid]
    return {"geneId": gid, "version": g["version"], "predicateId": g["validation"]["predicateId"],
            "severity": g["validation"]["severity"], "phase": g["validation"].get("phase", "pre_exec"), "ok": ok,
            "detail": f"detail of {gid}"}


def both(issues, applications=None, exec_result=EXEC):
    a = dict(applications or {})
    gene = G.repair_turn(C3L, issues, a, exec_result=exec_result, repair="gene", closing="program")
    chk = G.repair_turn(C3L, issues, a, exec_result=exec_result, repair="gene_generic", closing="program",
                        checklist=CHECKLIST)
    return gene, chk


def test_scope_partition_and_checklist_file():
    assert len(E_IDS) == 5 and M_IDS and S_IDS
    assert not set(S_IDS) & set(E_IDS)  # no soft gene in the generic-repair scope: C3T shows no warning at all
    # the registered text (four bullets, pinned by digest); since the R1 C1 pool of 2026-10-05 it is no longer a pool prefix
    assert T["files"]["review_checklist"]["sha256"] == C.CHECKLIST_SHA256 and C.CHECKLIST_BULLETS == 4
    assert [l[:2] for l in CHECKLIST.splitlines()] == ["- "] * 4
    block = len(G.CHECKLIST_HEAD) + 1 + len(CHECKLIST) + 1
    assert 0.9 * 572 <= block <= 1.1 * 572  # it1 dev median of the omitted gene text: 572 characters


@pytest.mark.parametrize("ids", [(e,) for e in ("orgene.execution.runs", "orgene.solution.status_optimal_or_justified")]
                         + [("orgene.execution.runs", "orgene.boundary.status_reported")])
def test_generic_scope_failures_only_equal_gene_repair(ids):
    (g_text, g_app), (c_text, c_app) = both([issue(i) for i in ids] + [issue(M_IDS[0], ok=True)])
    assert g_text == c_text and g_app == c_app and g_text


def test_other_gene_text_never_appears():
    m, s = M_IDS[0], S_IDS[0]
    (g_text, g_app), (c_text, c_app) = both([issue("orgene.execution.runs"), issue(m), issue(s)])
    assert g_app == c_app and set(g_app) == {"orgene.execution.runs", m}
    assert G.CHECKLIST_HEAD in c_text and CHECKLIST in c_text
    for gid in M_IDS + S_IDS:
        assert gid not in c_text and f"detail of {gid}" not in c_text
        assert BY_ID[gid]["repair"]["instruction"] not in c_text
    assert "(warning)" not in c_text and "(warning)" in g_text
    assert "[orgene.execution.runs] detail of orgene.execution.runs" in c_text
    assert c_text.endswith(G.GENE_CLOSING["program"]) and "KeyError" in c_text


def test_only_other_genes_fail_gives_checklist_without_review_header():
    (_, g_app), (c_text, c_app) = both([issue(M_IDS[0]), issue(M_IDS[1])], exec_result=None)
    assert c_app == g_app == [M_IDS[0], M_IDS[1]]
    assert c_text.startswith(G.CHECKLIST_HEAD) and "Automatic review" not in c_text


def test_trigger_and_bookkeeping_equal_gene_repair():
    pool = ["orgene.execution.runs", "orgene.solution.status_optimal_or_justified", M_IDS[0], M_IDS[1], S_IDS[0]]
    for r in range(len(pool) + 1):
        for ids in itertools.combinations(pool, r):
            for apps in ({}, {M_IDS[0]: 1}, {i: 1 for i in pool}):
                (g_text, g_app), (c_text, c_app) = both([issue(i) for i in ids], apps)
                assert (g_text is None) == (c_text is None) and g_app == c_app, (ids, apps)


def test_forced_review():
    ok = [issue("orgene.execution.runs", ok=True), issue(S_IDS[0])]
    kw = dict(repair="gene_generic", closing="program", checklist=CHECKLIST)
    assert G.repair_turn(C3L, ok, {}, **kw) == (None, [])
    text, applied = G.repair_turn(C3L, ok, {}, force=True, **kw)
    assert applied == [] and text == "\n".join([G.REVIEW_HEAD, CHECKLIST, "", G.REVIEW_CLOSING])
    assert S_IDS[0] not in text
    # a hard failure takes the ordinary path even when force is set
    hard = [issue(M_IDS[0])]
    assert G.repair_turn(C3L, hard, {}, force=True, **kw) == G.repair_turn(C3L, hard, {}, **kw)
    with pytest.raises(ValueError):
        G.repair_turn(C3L, hard, {}, repair="gene_generic", closing="program")


def _reg(**over):
    base = json.loads((ROOT / "configs/r1_configs.json").read_text())
    for c in base["configs"]:
        if c["id"] in over:
            c.update(over[c["id"]])
    return base


def test_registry_entries_and_rules():
    reg = CF.load_registry()
    t, a, r = (reg["configs"][k] for k in ("C3T", "C3A", "C0R-E"))
    l, e = reg["configs"]["C3L"], reg["configs"]["C3E"]
    same = ("prompt", "round0", "validator", "gene_scope", "activation", "closing", "max_rounds", "num_predict", "num_ctx")
    assert all(t[k] == l[k] == a[k] for k in same) and t["repair"] == a["repair"] == "gene_generic"
    assert a["force_review"] is True and t["force_review"] is False and l["force_review"] is False
    assert all(r[k] == e[k] for k in ("validator", "gene_scope", "activation", "repair", "closing", "max_rounds"))
    assert r["prompt"] == "C0R" and r["round0"] == "own" and r["contract_scope"] == "C3L"
    for bad in ({"C3T": {"gene_scope": "C3E"}}, {"C3L": {"force_review": True}}, {"C3L": {"contract_scope": "C3L"}},
                {"C0R-E": {"contract_scope": None}}, {"C0R-E": {"contract_scope": "C3"}}):
        with pytest.raises(CF.RegistryError):
            CF.parse_registry(_reg(**bad))


def test_c0r_prompt():
    reg = CF.load_registry()
    lex = F.load_lexicon(LEX)
    case = {"case_id": "d12-toy", "source": "toy", "text": "Choose a quantity x between 0 and 1. Maximize x."}
    ctx_feats = F.extract_features(case["text"], lex)
    text, meta = C.build_prompt(reg["configs"]["C0R-E"], case, STORE, features=ctx_feats)
    c0, _ = C.build_prompt(reg["configs"]["C0"], case, STORE, features=ctx_feats)
    _, l_meta = C.build_prompt(reg["configs"]["C3L"], case, STORE, features=ctx_feats)
    assert text.startswith(C._base(T)) and text.rstrip().endswith("Return only the program.")
    assert "JSON specification" not in text and "```json" not in text
    assert meta["contract_in_prompt"] and meta["contract_scope"] == "C3L"
    assert meta["contract_genes"] == l_meta["active_genes"]          # the rules C3L checks this problem with
    assert sorted(g["geneId"] for g in meta["active_genes"]) == E_IDS  # the validator's scope stays C3E
    assert "Before answering, check your program for:" in text and "checked automatically" not in text
    assert "orgene." not in text and len(text) > len(c0)


CODE_ZERO = ("import pulp\np = pulp.LpProblem('toy', pulp.LpMaximize)\n"
             "x = pulp.LpVariable('x', lowBound=0, upBound=1)\n"
             "p += x\np += x == 0\np.solve(pulp.PULP_CBC_CMD(msg=0))\n"
             "print('STATUS:', pulp.LpStatus[p.status])\nprint('FINAL_OBJECTIVE:', pulp.value(p.objective))\n")
CODE_GOOD = CODE_ZERO.replace("p += x == 0\n", "")
OPTS = dict(temperature=0.0, top_k=20, top_p=.95, seed=1, num_ctx=32768, num_predict=6000, think=False, keep_alive=0)
CASE = {"case_id": "d12-toy", "source": "toy", "text": "Choose a nonnegative continuous quantity x, at most 1. Maximize x.",
        "reference": {"objective": 1.0, "raw": "1", "status": None}}


def _run(tmp_path, code, ids):
    backend = CannedBackend(answer=lambda messages, body: "```python\n" + code + "```\n")
    ctx = U.build_context(str(tmp_path), genes_path=str(GENES), lexicon=str(LEX), opts=OPTS, python=sys.executable)
    return {cid: U.run_unit(CASE, CF.get_config(ctx.registry, cid), 0, backend, ctx) for cid in ids}


def test_units_zero_optimum(tmp_path):
    # only a gene outside the generic-repair scope fails (zero optimum): C3L, C3T and C3A repair, C3E does not
    r = _run(tmp_path, CODE_ZERO, ("C0", "C3E", "C3L", "C3T", "C3A"))
    assert len(r["C3E"]["rounds"]) == 1
    for cid in ("C3L", "C3T", "C3A"):
        assert r[cid]["status"] == "complete" and len(r[cid]["rounds"]) > 1
        assert r[cid]["round0"]["reused_from"]["unit_id"] == r["C0"]["unit_id"]
    l0, t0, a0 = (r[c]["rounds"][0] for c in ("C3L", "C3T", "C3A"))
    assert l0["validated"]["hard_failed_genes"] == t0["validated"]["hard_failed_genes"]
    assert l0["repair_applied_genes"] == t0["repair_applied_genes"] == a0["repair_applied_genes"]
    assert t0["repair_text"] == a0["repair_text"] and t0["repair_text"].startswith(G.CHECKLIST_HEAD)
    assert "nontrivial_optimum" in l0["repair_text"] and "orgene." not in t0["repair_text"]
    assert len(r["C3L"]["rounds"]) == len(r["C3T"]["rounds"])


def test_units_correct_program(tmp_path):
    # nothing fails: only C3A sends a (forced) review round, and only one
    r = _run(tmp_path, CODE_GOOD, ("C0", "C3L", "C3T", "C3A"))
    assert len(r["C3L"]["rounds"]) == len(r["C3T"]["rounds"]) == 1
    a = r["C3A"]["rounds"]
    assert len(a) == 2 and a[0]["repair_applied_genes"] == [] and a[0]["repair_text"].startswith(G.REVIEW_HEAD)
    assert r["C3A"]["applications"] == {} and r["C3A"]["final_row"]["decision"] == "accepted"


def test_units_c0r(tmp_path):
    r = _run(tmp_path, CODE_GOOD, ("C0", "C0R-E"))
    u = r["C0R-E"]
    assert u["status"] == "complete" and u["round0"]["source"] == "own" and len(u["rounds"]) == 1
    assert "Modeling contract" in json.dumps(u["rounds"][0]["calls"][0]) and "Modeling contract" not in json.dumps(
        r["C0"]["rounds"][0]["calls"][0])

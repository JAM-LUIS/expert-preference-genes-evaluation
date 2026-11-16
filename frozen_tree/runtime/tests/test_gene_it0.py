"""Approved iteration-0 integration; fixtures are author-approved synthetic examples."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))
from orgene import genes as G, features as F, unit_exec as U, configs as CF
from orgene.backends.canned import CannedBackend

FIX = Path(__file__).parent / "fixtures"
GENES = ROOT / "genes/genes.it0.approved.jsonl"
LEX = ROOT / "genes/activation_lexicon.v2.json"
EXAMPLES = json.loads((FIX / "gene_it0_examples.json").read_text())


@pytest.mark.parametrize("t", EXAMPLES)
def test_approved_predicate_example(t):
    ctx = {"case": {"case_id": "self-made", "text": t.get("text", "")},
           "spec": t.get("spec"), "code": t.get("code"), "exec": t.get("exec")}
    ok, detail = G.PREDICATES[t["predicateId"]](ctx, t.get("params") or {})
    assert bool(ok) is t["expect_ok"], detail
    assert "analysis skipped" not in detail


def test_complete_library_and_manifest():
    store = G.load_store(GENES, lexicon=LEX)
    seed = G.load_store(ROOT / "genes/genes.r1.jsonl")
    assert len(store) == len({g["geneId"] for g in store}) == 21
    by_id = {g["geneId"]: g for g in store}
    assert sum(by_id[g["geneId"]] == g for g in seed) == 7
    assert len(set(by_id) - {g["geneId"] for g in seed}) == 4
    manifest = json.loads((ROOT / "configs/gene_iteration.it0.json").read_text())
    current = json.loads((ROOT / "configs/gene_iteration.it1.json").read_text())["runtime_sha256"]
    for name, expected in manifest["runtime_sha256"].items():
        # it1 (2026-10-03) changed model-facing detail text in the predicate module only; that file is now
        # pinned by the it1 manifest. The it0 library and lexicon stay pinned by the it0 manifest.
        if name.startswith("runtime/"):
            expected = current[name]
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    assert "predicates_it0.py" in U.CODE_FILES


def test_approved_activation_examples():
    lex = F.load_lexicon(LEX)
    store = G.load_store(GENES, lexicon=lex)
    examples = F.load_examples(FIX / "gene_it0_activation.json")
    assert F.check_activation_examples(store, examples, lex) == []


def test_mounted_library_shared_round0_and_repair_budget(tmp_path):
    # A new G1 failure: a solved zero objective. It must route through gene
    # repair only; the generic execution control sees a successful execution.
    case = {"case_id": "it0-toy", "source": "toy", "text":
            "Choose a nonnegative continuous quantity x, at most 1. Maximize x.",
            "reference": {"objective": 1.0, "raw": "1", "status": None}}
    code = ("import pulp\np = pulp.LpProblem('toy', pulp.LpMaximize)\n"
            "x = pulp.LpVariable('x', lowBound=0, upBound=1)\n"
            "p += x\np += x == 0\np.solve(pulp.PULP_CBC_CMD(msg=0))\n"
            "print('STATUS:', pulp.LpStatus[p.status])\nprint('FINAL_OBJECTIVE:', pulp.value(p.objective))\n")
    backend = CannedBackend(answer=lambda messages, body: "```python\n" + code + "```\n")
    opts = dict(temperature=0.0, top_k=20, top_p=.95, seed=1, num_ctx=32768,
                num_predict=6000, think=False, keep_alive=0)
    ctx = U.build_context(str(tmp_path), genes_path=str(GENES), lexicon=str(LEX),
                          opts=opts, python=sys.executable)
    records = {cid: U.run_unit(case, CF.get_config(ctx.registry, cid), 0, backend, ctx)
               for cid in ("C0", "C3L", "C3E")}
    for cid in ("C3L", "C3E"):
        r = records[cid]
        assert r["status"] == "complete"
        assert len(r["rounds"]) <= 3
        assert r["round0"]["reused_from"]["unit_id"] == records["C0"]["unit_id"]
    assert len(records["C3L"]["rounds"]) > 1
    assert len(records["C3E"]["rounds"]) == 1
    assert "optimum_not_trivial_zero" in json.dumps(records["C3L"])

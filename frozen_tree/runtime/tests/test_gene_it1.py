"""Iteration 1 (2026-10-03): text-only changes from the isolated clause review; predicate logic unchanged."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))
from orgene import genes as G

FIX = Path(__file__).parent / "fixtures"
LEX = ROOT / "genes/activation_lexicon.v2.json"
IT0 = ROOT / "genes/genes.it0.approved.jsonl"
IT1 = ROOT / "genes/genes.it1.jsonl"
FIXED = ("scope", "targets", "validation")
REMOVED = ("per price/quantity tier", "allowed value or tier", "net flow out of the source", "throughput",
           "assigning an item to itself", "trivial assignment")


def test_it1_manifest_hashes():
    manifest = json.loads((ROOT / "configs/gene_iteration.it1.json").read_text())
    for name, expected in manifest["runtime_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected


def test_it1_changes_text_only():
    a = {g["geneId"]: g for g in G.load_store(IT0, lexicon=LEX)}
    b = {g["geneId"]: g for g in G.load_store(IT1, lexicon=LEX)}
    assert set(a) == set(b) and len(b) == 21
    changed = set()
    for gid in a:
        for k in FIXED:
            assert a[gid].get(k) == b[gid].get(k), (gid, k)
        assert a[gid]["preference"].get("priority") == b[gid]["preference"].get("priority")
        assert {k: v for k, v in a[gid]["repair"].items() if k != "instruction"} == \
               {k: v for k, v in b[gid]["repair"].items() if k != "instruction"}
        if a[gid] != b[gid]:
            changed.add(gid)
            assert a[gid]["version"] != b[gid]["version"], gid
            assert f"{gid}@{a[gid]['version']}" in b[gid]["lifecycle"]["supersedes"]
        else:
            assert a[gid]["version"] == b[gid]["version"]
    assert len(changed) == 10


def test_predicate_truth_values_unchanged_and_details_scrubbed():
    examples = json.loads((FIX / "gene_it0_examples.json").read_text())
    for t in examples:
        ctx = {"case": {"case_id": "self-made", "text": t.get("text", "")},
               "spec": t.get("spec"), "code": t.get("code"), "exec": t.get("exec")}
        ok, detail = G.PREDICATES[t["predicateId"]](ctx, t.get("params") or {})
        assert bool(ok) is t["expect_ok"], detail
        assert not any(p in detail for p in REMOVED), (t["predicateId"], detail)


def test_it1_model_facing_text_scrubbed():
    for g in G.load_store(IT1, lexicon=LEX):
        text = json.dumps({k: g.get(k) for k in ("preference", "contract", "repair")}, ensure_ascii=False)
        assert not any(p in text for p in REMOVED), g["geneId"]

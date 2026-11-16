"""Regression against the v5 gene library 1.0 kept in releases/v1.0/ (gene library, conditions/, schema/).

R1 code on the v1.0 inputs must reproduce the hashes recorded when v1.0 was frozen: gene library file, compiled C3
contract, the C3 / C3L / C3E activation digests and the C0-C3 system prompts. releases/v1.0/ is not part of the
anonymous repository (it keeps the v5 originals), so every test here is skipped when the directory is absent.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from orgene import genes as G  # noqa: E402

RELEASE = os.path.join(ROOT, "releases", "v1.0")
V1_GENES = os.path.join(RELEASE, "genes.v3.jsonl")
V1_COND = os.path.join(RELEASE, "conditions")
R1_GENES = os.path.join(ROOT, "genes", "genes.r1.jsonl")
R1_COND = os.path.join(ROOT, "conditions")

pytestmark = pytest.mark.skipif(not os.path.exists(V1_GENES),
                                reason="releases/v1.0 is not in the anonymous repository (v5 originals)")


@pytest.fixture(scope="module")
def anchors():
    import anchor_hashes as A
    return A, A.gene_side(V1_GENES, V1_COND), A.gene_side(R1_GENES, R1_COND)


def test_v1_anchor_hashes_are_reproduced(anchors):
    A, v1, _ = anchors
    bad = [r for r in A.check_release(v1) if not r["ok"]]
    assert not bad, bad


def test_v1_schema_copy_is_the_working_schema():
    name = "optimization_model_spec.v3.schema.json"
    a = open(os.path.join(RELEASE, "schema", name), "rb").read()
    b = open(os.path.join(ROOT, "schema", name), "rb").read()
    assert a == b, "schema v3 is unchanged in R1 (D4 option (1))"


def test_working_library_keeps_prompts_and_contract_of_v1(anchors):
    """The R1 working library changes audit text only, so everything compiled into a prompt is unchanged."""
    _, v1, r1 = anchors
    assert r1["contract_sha256"] == v1["contract_sha256"]
    assert r1["contract_chars"] == v1["contract_chars"]
    assert r1["system_prompt_sha256"] == v1["system_prompt_sha256"]
    assert r1["n_active"] == v1["n_active"]
    assert r1["activation_digest"]["C3E"] == v1["activation_digest"]["C3E"], "no C3E gene changed"


def _load(path):
    return {g["geneId"]: g for g in G.load_store(path)}


def _vtuple(v):
    return tuple(int(x) for x in v.split("."))


def test_changed_genes_have_a_higher_version():
    """Store version rule: a geneId whose record differs from the previous release must carry a higher version."""
    v1, r1 = _load(V1_GENES), _load(R1_GENES)
    assert set(r1) >= set(v1), sorted(set(v1) - set(r1))
    bumped = []
    for gid, g in v1.items():
        a = {k: v for k, v in g.items() if k != "version"}
        b = {k: v for k, v in r1[gid].items() if k != "version"}
        if a != b:
            assert _vtuple(r1[gid]["version"]) > _vtuple(g["version"]), gid
            bumped.append(gid)
        else:
            assert r1[gid]["version"] == g["version"], f"{gid}: version changed without a content change"
    assert bumped == ["orgene.objective.aggregates_declared_variables"], bumped


def test_working_library_differs_from_v1_only_in_audit_text():
    v1, r1 = _load(V1_GENES), _load(R1_GENES)
    for gid, g in v1.items():
        for k in g:
            if k in ("version", "audit"):
                continue
            assert json.dumps(g[k], sort_keys=True) == json.dumps(r1[gid][k], sort_keys=True), (gid, k)
        assert g["audit"]["devCaseIds"] == r1[gid]["audit"]["devCaseIds"], gid
        assert g["audit"]["sourceType"] == r1[gid]["audit"]["sourceType"], gid

"""E20a script paths on toy data: strata.py, tost.py, holm.py (CLI), shared_round0.py. Toy ids and self-made values
only; the real pre-registration file is read (its pending items are exercised the way dev and test analyses use them)."""
import argparse
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))
sys.path.insert(0, os.path.join(ROOT, "analysis", "r1"))

import common as CM  # noqa: E402
import paired as PA  # noqa: E402
import prereg as PR  # noqa: E402
import registry as RG  # noqa: E402
import shared_round0 as SR  # noqa: E402
import strata as ST  # noqa: E402
import tost as TO  # noqa: E402
import holm as HO  # noqa: E402
from prereg_draft import draft_doc, draft_file  # noqa: E402

M_IDS = [f"toy_m-{i:04d}" for i in range(1, 13)]
I_IDS = [f"toy_i-{i:04d}" for i in range(1, 9)]              # toy cases filed under the benchmark name "industryor"
PY = sys.executable


def _row(label, cid, bench, correct, repaired=0, sha=None, split="dev", tokens=100):
    r = {k: None for k in RG.MATRIX_FIELDS}
    r.update({"model": "toy-model", "label": label, "config": label.split("@")[0], "benchmark": bench, "split": split,
              "case_id": cid, "repeat": 0, "correct": correct, "exec_ok": True, "status": "Optimal", "objective": 1.0,
              "out_tokens": tokens, "repair_rounds_used": repaired, "n_calls": 1 + repaired,
              "round0_content_sha256": sha})
    return r


def _matrix(split="dev"):
    """C0 (round 0), C3L@2 and C3E@2 sharing it: C3L repairs 6 cases into right answers, C3E 2."""
    rows = []
    ids = [(c, "toy_m") for c in M_IDS] + [(c, "industryor") for c in I_IDS]
    for n, (cid, b) in enumerate(ids):
        r0 = n % 2 == 0
        sha = f"sha-{cid}"
        rows.append(_row("C0", cid, b, r0, sha=sha, split=split))
        fix_l = (not r0) and n in (1, 3, 5, 7, 13, 15)
        fix_e = (not r0) and n in (1, 13)
        rows.append(_row("C3L@2", cid, b, r0 or fix_l, repaired=0 if r0 else 1, sha=sha, split=split))
        rows.append(_row("C3E@2", cid, b, r0 or fix_e, repaired=0 if r0 else 1, sha=sha, split=split))
    return RG.Matrix(rows, {"data": CM.DATA_LABELS[split], "analysis_set": None, "registry": None, "superseded": None,
                            "runs": [], "freeze_gate": None})


def _aset(split="dev", reference="r1"):
    by = {"toy_m": sorted(M_IDS), "industryor": sorted(I_IDS)}
    ids = sorted(M_IDS + I_IDS)
    return {"name": "toyset", "split": split, "reference": reference, "n": len(ids), "sha256": "0" * 64, "ids": ids,
            "by_benchmark": by, "pending": []}


def _ns(**kw):
    base = dict(a="C3L@2", b="C3E@2", registry=None, superseded=None, prereg=None, set=None, incl_0905=False,
                allow_pending=False, outcome="correct", models=None, n_boot=300, seed=1, out=None, margin=None,
                scope="pooled", round0_label="C0", round0_check="sha", mde_n="pooled=20,toy_m=12,industryor=8",
                mde_set="main", by=["benchmark"], scale_feature=None, scale_file=ST.SCALE_FILE,
                industryor_cases="data/cases/industryor.jsonl", no_bootstrap=False)
    base.update(kw)
    return argparse.Namespace(**base)


# ------------------------------------------------------------------ strata


def test_strata_by_benchmark_scale_difficulty_type(tmp_path):
    root = str(tmp_path)
    feats = {c: {"strata": {"n_numeric_literals": i % 3}} for i, c in enumerate(M_IDS + I_IDS)}
    feats[M_IDS[0]] = {"strata": {"n_numeric_literals": None}}
    os.makedirs(os.path.join(root, "data/features"))
    json.dump({"features": feats, "cutpoints": {"toy_m": {"n_numeric_literals": [10, 20]}}},
              open(os.path.join(root, ST.SCALE_FILE), "w"))
    os.makedirs(os.path.join(root, "data/cases"))
    with open(os.path.join(root, "data/cases/industryor.jsonl"), "w") as f:
        f.write(json.dumps({"_header": True}) + "\n")
        for i, c in enumerate(I_IDS[:-1]):
            f.write(json.dumps({"case_id": c, "extra": {"difficulty": ["Easy", "Medium", "Hard"][i % 3]}}) + "\n")
    os.makedirs(os.path.join(root, "data/labels"))
    json.dump({"status": "final", "labels": {c: {"effective_type": "LP" if i < 4 else "MILP"} for i, c in enumerate(I_IDS)}},
              open(os.path.join(root, "data/labels/industryor_type.json"), "w"))
    doc = ST.run(_ns(by=["benchmark", "scale", "difficulty", "type"]),
                 matrix=_matrix(), aset=_aset(), prereg=PR.load(), root=root)
    assert doc["data"] == "DEV" and "strata_scale_feature" not in doc["prereg"]["pending_used"]
    res = doc["results"]
    assert {r["stratum"]: r["n"] for r in res["benchmark"]} == {"industryor": 8, "toy_m": 12}
    assert {r["stratum"]: r["n"] for r in res["scale"]} == {"T1": 6, "T2": 7, "T3": 6, "missing": 1}
    assert {r["stratum"]: r["n"] for r in res["difficulty"]} == {"Easy": 3, "Hard": 2, "Medium": 2, "missing": 1, "n/a": 12}
    assert {r["stratum"]: r["n"] for r in res["type"]} == {"LP": 4, "MILP": 4, "n/a": 12}
    # the benchmark strata equal paired.compare per benchmark
    pc = {r["scope"]: r for r in PA.compare(_matrix(), "C3L@2", "C3E@2", "toy-model", bench_of=RG.bench_map(_aset()),
                                            n_boot=300)}
    for r in res["benchmark"]:
        assert (r["wins"], r["losses"], r["diff"]) == (pc[r["stratum"]]["wins"], pc[r["stratum"]]["losses"],
                                                       pc[r["stratum"]]["diff"])
    # the scale feature is fixed (n_numeric_literals): another feature cannot be passed in its place
    with pytest.raises(Exception, match="cannot be overridden"):
        ST.run(_ns(by=["scale"], scale_feature="n_tokens"), matrix=_matrix(), aset=_aset(), prereg=PR.load(), root=root)


def test_strata_type_drops_linear_unresolved(tmp_path):
    path = str(tmp_path / "industryor_type.json")
    labels = {c: {"type": "LP", "effective_type": "LP"} for c in I_IDS}
    labels[I_IDS[0]] = {"type": "LINEAR_UNRESOLVED", "effective_type": None}
    json.dump({"status": "final", "labels": labels}, open(path, "w"))
    bench_of = {c: "toy_m" for c in M_IDS} | {c: "industryor" for c in I_IDS}
    out, src = ST.type_strata(sorted(bench_of), bench_of, path)
    assert I_IDS[0] not in out and src["n_linear_unresolved_dropped"] == 1
    assert sorted(set(out.values())) == ["LP", "n/a"] and len(out) == len(bench_of) - 1


# ------------------------------------------------------------------ TOST


def test_tost_run_dev_uses_an_explicit_margin_and_test_refuses_the_pending_one(tmp_path):
    draft = draft_file(tmp_path)
    doc = TO.run(_ns(a="C3L@2", b="C3E@2", margin=0.3), matrix=_matrix(), aset=_aset(), prereg=PR.load(draft))
    (r,) = doc["results"]
    assert doc["data"] == "DEV" and doc["prereg"]["pending_used"]["tost_margin"] == 0.3
    assert r["score"]["b"] == 4 and r["score"]["c"] == 0 and r["n"] == 20
    assert r["methods_agree"] is not None and "score 90% CI" in TO.render_md(doc)
    with pytest.raises(PR.PendingItem, match="no proposal"):
        TO.run(_ns(margin=None), matrix=_matrix(), aset=_aset(), prereg=PR.load(draft))
    with pytest.raises(PR.PendingItem):
        TO.run(_ns(margin=0.3), matrix=_matrix("test"), aset=_aset("test"), prereg=PR.load(draft))
    # the registered margin (0.05, fixed on 2026-10-03) is used as it is and cannot be overridden
    fixed = TO.run(_ns(a="C3L@2", b="C3E@2", margin=None), matrix=_matrix(), aset=_aset(), prereg=PR.load())
    assert fixed["margin"] == 0.05 and "tost_margin" not in fixed["prereg"]["pending_used"]
    with pytest.raises(CM.AnalysisError, match="cannot be overridden"):
        TO.run(_ns(a="C3L@2", b="C3E@2", margin=0.3), matrix=_matrix(), aset=_aset(), prereg=PR.load())


# ------------------------------------------------------------------ shared round 0


def test_shared_round0_run_with_sha_identity_and_design_mde():
    doc = SR.run(_ns(), matrix=_matrix(), aset=_aset(), prereg=PR.load())
    (r,) = doc["results"]
    assert r["round0_identity"]["mode"] == "sha" and r["round0_identity"]["n_units"] == 20
    pooled = [t for t in r["tests"] if t["scope"] == "pooled"][0]
    assert (pooled["wins"], pooled["losses"]) == (4, 0)
    d = r["decomposition"]["summary"]
    assert d["both_repaired"]["n"] == 10 and d["both_repaired"]["a_only_right"] == 4
    assert d["neither_repaired"]["n"] == 10 and r["decomposition"]["n_unrepaired_outcome_mismatch"] == 0
    assert {(x["scope"], x["n"]) for x in doc["mde"]["rows"]} == {("pooled", 20), ("toy_m", 12), ("industryor", 8)}
    # C3E with another round 0 on one case: refused
    m = _matrix()
    for row in m.rows:
        if row["label"] == "C3E@2" and row["case_id"] == M_IDS[2]:
            row["round0_content_sha256"] = "other"
    with pytest.raises(SR.SharedRound0Error, match="differs on 1 of 20"):
        SR.run(_ns(), matrix=m, aset=_aset(), prereg=PR.load())


def test_shared_round0_default_mde_n_comes_from_the_main_set_sizes():
    doc = SR.run(_ns(mde_n=None, allow_pending=True), matrix=_matrix(), aset=_aset(), prereg=PR.load())
    main = RG.resolve_set("main", allow_pending=True)
    ns = {x["scope"]: x["n"] for x in doc["mde"]["rows"]}
    assert ns["pooled"] == main["n"] and doc["mde"]["n_source"].startswith("analysis set main (sizes only)")


# ------------------------------------------------------------------ Holm CLI over paired outputs


def test_holm_cli_dev_proposals_and_skipped_families(tmp_path):
    doc = PA.run(_ns(), matrix=_matrix(), aset=dict(_aset(), name="main"), prereg=PR.load())
    # re-label the toy comparison as the pre-registered primary one
    for r in doc["results"]:
        r["model"] = "qwen3:8b"
    p = tmp_path / "paired.DEV.json"
    p.write_text(json.dumps(doc))
    out = tmp_path / "holm.json"
    draft = draft_file(tmp_path)
    cp = subprocess.run([PY, "-B", os.path.join(ROOT, "analysis/r1/holm.py"), "--paired", str(p), "--allow-pending",
                         "--prereg", draft, "--out", str(out)], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert cp.returncode == 0, cp.stderr
    h = json.load(open(tmp_path / "holm.DEV.json"))
    assert [f["family"] for f in h["families"]] == ["primary"] and h["skipped_families"] == ["controls", "ladder"]
    assert h["families"][0]["results"][0]["p"] == [r for r in doc["results"] if r["scope"] == "pooled"][0]["mcnemar_exact_p"]
    # without --allow-pending the pending families are refused
    cp = subprocess.run([PY, "-B", os.path.join(ROOT, "analysis/r1/holm.py"), "--paired", str(p), "--prereg", draft],
                        capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert cp.returncode == 2 and "pending" in cp.stderr
    # the registered families (fixed on 2026-10-03): a dev analysis still skips the families it has no rows for, and
    # reports the gated test H2 only when its rows exist
    cp = subprocess.run([PY, "-B", os.path.join(ROOT, "analysis/r1/holm.py"), "--paired", str(p), "--allow-pending",
                         "--out", str(tmp_path / "holm_fixed.json")], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert cp.returncode == 0, cp.stderr
    hf = json.load(open(tmp_path / "holm_fixed.DEV.json"))
    assert [f["family"] for f in hf["families"]] == ["primary"] and hf["gated"] == []


def test_holm_cli_test_data_never_skips_a_family(tmp_path):
    """With fixed families, a TEST analysis corrects every family: --allow-pending does not let it skip the families
    whose results are missing (dev only)."""
    doc = PA.run(_ns(), matrix=_matrix(), aset=dict(_aset(), name="main"), prereg=PR.load())
    for r in doc["results"]:
        r["model"] = "qwen3:8b"
    doc["data"] = "TEST"
    p = tmp_path / "paired.TEST.json"
    p.write_text(json.dumps(doc))
    pre = draft_doc()
    fam = pre["items"]["holm_families"]
    fam.update(status="fixed", value=fam["proposal"], basis="toy decision")
    gt = pre["items"]["gated_tests"]
    gt.update(status="fixed", value=gt["proposal"], basis="toy decision")
    pf = tmp_path / "prereg.json"
    pf.write_text(json.dumps(pre))
    base = [PY, "-B", os.path.join(ROOT, "analysis/r1/holm.py"), "--paired", str(p), "--prereg", str(pf)]
    for extra in ([], ["--allow-pending"]):
        cp = subprocess.run(base + extra, capture_output=True, text=True, timeout=60, cwd=ROOT)
        assert cp.returncode == 2 and "all of its members" in cp.stderr, (extra, cp.stdout, cp.stderr)
    # the same file labelled DEV with --allow-pending skips the incomplete families
    doc["data"] = "DEV"
    p.write_text(json.dumps(doc))
    cp = subprocess.run(base + ["--allow-pending"], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert cp.returncode == 0 and "## primary" in cp.stdout and "## ladder" not in cp.stdout, cp.stderr


def _gate_setup(p_gate, p_h2, diff_h2=0.05):
    fams = [{"family": "primary", "results": [{"name": "C3L_vs_C3E", "reject": p_gate <= 0.05}]}]
    comp = {"id": "C3L1_vs_C3T1", "a": "C3L@1", "b": "C3T@1", "model": "m", "outcome": "correct", "analysis_set": "main",
            "scope": "pooled"}
    idx = {HO._key(comp): ({"mcnemar_exact_p": p_h2, "diff": diff_h2, "ci": [0.0, 0.1]}, "TEST")}
    return [{"id": "H2", "gate": "C3L_vs_C3E", "alpha": 0.05, "comparison": comp}], fams, idx


def test_gated_test_is_read_only_when_its_gate_is_rejected():
    (g,) = HO.gated_results(*_gate_setup(0.01, 0.03))
    assert g["tested"] and g["reject"] and g["p"] == 0.03 and g["reading"] == "confirmatory"
    (g,) = HO.gated_results(*_gate_setup(0.01, 0.20))
    assert g["tested"] and not g["reject"]
    (g,) = HO.gated_results(*_gate_setup(0.01, 0.03, diff_h2=-0.05))      # the direction is fixed
    assert g["tested"] and not g["reject"]
    (g,) = HO.gated_results(*_gate_setup(0.30, 0.001))                     # gate not rejected: an estimate only
    assert not g["tested"] and not g["reject"] and g["p"] is None and g["diff"] == 0.05 and "estimate only" in g["reading"]
    gated, fams, idx = _gate_setup(0.01, 0.03)
    with pytest.raises(CM.AnalysisError, match="no paired result"):
        HO.gated_results(gated, fams, {})
    with pytest.raises(CM.AnalysisError, match="has no result"):
        HO.gated_results(gated, [], idx)

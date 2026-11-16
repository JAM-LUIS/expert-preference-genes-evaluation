"""D12 mechanism analysis (analysis/r1/mechanism.py) on toy data: toy ids, self-made outcomes and unit records."""
import json
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))
sys.path.insert(0, os.path.join(ROOT, "analysis", "r1"))

import common as CM  # noqa: E402
import mechanism as ME  # noqa: E402
import registry as RG  # noqa: E402
from orgene import genes as G  # noqa: E402

RUNS, STAT = "orgene.execution.runs", "orgene.solution.status_optimal_or_justified"       # generic-repair scope
TUP, AGG, ZERO = "orgene.code.tuple_key_indexing", "orgene.objective.aggregates_declared_variables", \
    "orgene.solution.nontrivial_optimum"
PRED = {g["geneId"]: g["validation"]["predicateId"] for g in G.load_store(os.path.join(ROOT, "genes/genes.it1.jsonl"),
                                                                        lexicon=os.path.join(ROOT, "genes/activation_lexicon.v2.json"))}
CLASSES, _ = ME.load_classes()
BOOT = {"n_boot": 400, "seed": 1, "ci_level": 0.95}
# case: (round-0 correct, hard failures at round 0, soft, final correct under E, T, L, A)
PLAN = {
    "toy-01": (1, [], [], 1, 1, 1, 1), "toy-02": (1, [], [], 1, 1, 1, 0),          # N; forced review breaks toy-02
    "toy-03": (0, [], [], 0, 0, 0, 1),                                               # N, wrong and unflagged; A fixes it
    "toy-04": (0, [RUNS], [], 1, 1, 1, 1), "toy-05": (0, [STAT], [], 0, 1, 1, 1),    # P
    "toy-06": (0, [RUNS, TUP], [], 0, 1, 1, 1), "toy-07": (0, [RUNS, AGG], [], 0, 0, 1, 0),   # X
    "toy-08": (0, [AGG], [], 0, 0, 1, 0), "toy-09": (0, [TUP], [], 0, 1, 1, 1),      # M
    "toy-10": (1, [AGG], [], 1, 1, 0, 1),                                            # M, false alarm, L breaks it
    "toy-11": (0, [ZERO], [], 0, 0, 1, 0), "toy-12": (0, [ZERO], [], 0, 0, 0, 0),    # M, heuristic only
}
IDS = sorted(PLAN)
BENCH = {c: "toy" for c in IDS}


def _row(label, cid, correct, repaired):
    r = {k: None for k in RG.MATRIX_FIELDS}
    r.update({"model": "toy-model", "label": label, "config": label.split("@")[0], "benchmark": "toy", "split": "dev",
              "case_id": cid, "repeat": 0, "correct": bool(correct), "exec_ok": True, "repair_rounds_used": int(repaired),
              "n_calls": 1 + int(repaired), "round0_content_sha256": f"sha-{cid}", "out_tokens": 10})
    return r


@pytest.fixture()
def toy(tmp_path):
    rows = []
    for cid, (r0, hard, soft, e, t, l, a) in PLAN.items():
        rows.append(_row("C0", cid, r0, 0))
        rows.append(_row("C3E@1", cid, e, any(g in (RUNS, STAT) for g in hard)))
        rows.append(_row("C3T@1", cid, t, bool(hard)))
        rows.append(_row("C3L@1", cid, l, bool(hard)))
        rows.append(_row("C3A@1", cid, a, True))
        issues = [{"geneId": g, "predicateId": PRED[g], "severity": "hard", "ok": False} for g in hard]
        u = {"schema_version": RG.UNIT_SCHEMA, "case_id": cid, "config_id": "C3L", "repeat": 0,
             "rounds": [{"round": 0, "validated": {"issues": issues, "hard_failed_genes": hard, "soft_failed_genes": soft},
                         "repair_applied_genes": hard}]}
        p = tmp_path / "experiments/run-l/units" / f"{cid}.C3L.r0.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(u))
    m = RG.Matrix(rows, {"data": CM.DATA_LABELS["dev"], "analysis_set": None, "registry": None, "superseded": None,
                         "runs": [], "freeze_gate": None})
    reg = types.SimpleNamespace(runs=[{"model": "toy-model", "label": "C3L@1", "config": "C3L", "benchmark": "toy",
                                       "path": "experiments/run-l"}])
    return m, reg, str(tmp_path)


def _run(toy, labels=None, families=None):
    m, reg, root = toy
    labels = labels or {"l": "C3L@1", "e": "C3E@1", "t": "C3T@1", "a": "C3A@1"}
    return ME.analyse(m, reg, "toy-model", labels, "C0", BENCH, CLASSES, BOOT, families=families, root=root)


def test_strata_come_from_round0_checks_only(toy):
    r = _run(toy)
    assert r["strata_counts"] == {"N": 3, "P": 2, "X": 2, "M": 5}
    assert ME.stratum_of({"hard": [STAT], "generic": [STAT]}) == "P"   # the status gene is in the generic-repair scope


def test_nested_decomposition_is_additive(toy):
    r = _run(toy)
    c = r["comparisons"]
    le, te, lt = (c[k]["pooled"] for k in ("L_vs_E", "T_vs_E", "L_vs_T"))
    assert (le["wins"], le["losses"]) == (6, 1) and (te["wins"], te["losses"]) == (3, 0) and (lt["wins"], lt["losses"]) == (3, 1)
    d = r["decomposition"]
    assert d["additive"] and abs(d["total_L_minus_E"] - d["detection_T_minus_E"] - d["prescription_L_minus_T"]) < 2e-4
    # same resamples: the interval ends need not add up, but every stratum where the labels cannot differ is exactly 0
    for name in ("L_vs_E", "T_vs_E", "L_vs_T"):
        assert c[name]["by_stratum"]["N"]["diff"] == 0 and c[name]["by_stratum"]["N"]["wins"] == 0
    assert c["A_vs_T"]["by_stratum"]["N"]["wins"] == 1 and c["A_vs_T"]["by_stratum"]["N"]["losses"] == 1
    assert all(c["A_vs_T"]["by_stratum"][s]["diff"] == 0 for s in ("P", "X", "M"))


def test_detection_and_repair_rates_satisfy_the_identity(toy):
    r = _run(toy)["rates"]
    e, l, a = r["C3E@1"], r["C3L@1"], r["C3A@1"]
    assert (e["n_wrong0"], e["detected"], e["repaired_ok"], e["false_alarms"], e["broken"]) == (9, 4, 1, 0, 0)
    assert (l["detected"], l["repaired_ok"], l["false_alarms"], l["broken"]) == (8, 7, 1, 1)
    assert (a["detected"], a["false_alarms"], a["broken"]) == (9, 3, 1)             # forced review reaches every case
    for v in (e, l, a):
        assert v["n_correct_final"] == v["n_correct0"] + v["repaired_ok"] - v["broken"]


def test_function_classes_and_conservative_bound(toy):
    r = _run(toy)
    g = r["gains_by_function_class"]
    assert g["answer_distribution_heuristic"] == {"wins": 1, "losses": 0, "single_class_wins": 1, "single_class_losses": 0}
    assert g["or_modelling"]["losses"] == 1 and g["coding_hygiene"]["wins"] == 2
    cb = r["conservative_bound"]
    assert cb["n_cases_only_heuristic_at_round0"] == 2 and cb["n_outcomes_changed"] == 1
    assert (cb["L_vs_E"]["wins"], cb["L_vs_E"]["losses"]) == (5, 1)
    det = r["detection_round0"]["by_gene"]
    assert det[AGG]["fires_on_wrong"] == 2 and det[AGG]["fires_on_correct"] == 1 and det[AGG]["function_class"] == "or_modelling"


def test_families_pending_or_grouped(toy):
    assert _run(toy)["families"]["status"] == "pending"
    fam = {"case_family": {c: ("flow" if c in ("toy-07", "toy-08", "toy-10") else "other") for c in IDS},
           "gene_source_families": {AGG: ["flow"], TUP: ["routing"], ZERO: ["routing"]}}
    g = _run(toy, families=fam)["families"]["groups"]
    assert g["same_family"]["n"] == 3 and g["same_family"]["wins"] == 2 and g["same_family"]["losses"] == 1
    assert g["seed_only"]["n"] == 2 and g["no_repair"]["n"] == 3 and g["other_family"]["n"] == 4


def test_refusals(toy):
    m, reg, root = toy
    with pytest.raises(CM.AnalysisError, match="no registered run"):
        ME.analyse(m, types.SimpleNamespace(runs=[]), "toy-model", {"l": "C3L@1", "e": "C3E@1"}, "C0", BENCH, CLASSES, BOOT, root=root)
    for r in m.rows:
        if r["label"] == "C3E@1" and r["case_id"] == "toy-01":
            r["round0_content_sha256"] = "other"
    with pytest.raises(CM.AnalysisError, match="does not share round 0"):
        _run(toy)


def test_two_label_run_and_markdown(toy):
    r = _run(toy, labels={"l": "C3L@1", "e": "C3E@1"})
    assert "decomposition" not in r and set(r["comparisons"]) == {"L_vs_E"}
    doc = {"data": "DEV", "results": [r]}
    md = ME.render_md(doc)
    assert md.startswith("# [DEV]") and "Round-0 strata" in md and "Problem families: pending." in md


def test_function_class_file_covers_the_library():
    assert set(CLASSES) == set(PRED) and set(CLASSES.values()) == set(ME.CLASSES)
    assert CLASSES[ZERO] == "answer_distribution_heuristic" and CLASSES[RUNS] == "protocol_execution"

"""E20a statistics core (analysis/r1/): McNemar, Wilson, case bootstrap, Holm, Tango score interval and TOST, shared
round 0, pre-registration file. Standard library only; self-made numbers and toy case ids, no benchmark text.

The scipy / statsmodels / matplotlib cross-checks live in test_e20a_venv.py; the last test here runs that file with the
analysis environment's interpreter when it exists (ORGENE_TOOLS_PY or <repo>/.venv-tools/bin/python)."""
import importlib.util
import json
import math
import os
import random
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))
sys.path.insert(0, os.path.join(ROOT, "analysis", "r1"))

import common as CM  # noqa: E402
import holm as HO  # noqa: E402
import paired as PA  # noqa: E402
import prereg as PR  # noqa: E402
from prereg_draft import draft_doc, draft_file  # noqa: E402
import shared_round0 as SR  # noqa: E402
import tost as TO  # noqa: E402


# ------------------------------------------------------------------ McNemar, Wilson


@pytest.mark.parametrize("b,c,expected", [
    (0, 0, 1.0),
    (5, 1, 14 / 64),            # n = 6, k = 1: 2 * (C(6,0) + C(6,1)) / 2^6
    (1, 5, 14 / 64),            # symmetric
    (13, 0, 2 / 2 ** 13),       # all discordant pairs one way
    (3, 3, 1.0),                # capped at 1
    (10, 2, 2 * (1 + 12 + 66) / 4096),
])
def test_mcnemar_exact_hand_computed(b, c, expected):
    assert PA.mcnemar_exact(b, c) == pytest.approx(expected, rel=1e-12)
    assert SR.mcnemar_exact_p(b, c) == pytest.approx(expected, rel=1e-12)


def test_wilson_matches_the_stage0_table():
    lo, hi = PA.wilson(13, 85)       # T8 table 2.2: 15.3% (9.2%-24.4%)
    assert (round(100 * lo, 1), round(100 * hi, 1)) == (9.2, 24.4)
    assert PA.wilson(0, 0) == (None, None)


# ------------------------------------------------------------------ bootstrap


def _v5_bootstrap(diff, n_boot, seed):
    """The draws of v5 analysis/paired_bootstrap.py (lines 87-93), for the comparison."""
    rng = random.Random(seed)
    n = len(diff)
    boots = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        boots.append(sum(diff[i] for i in idx) / n)
    boots.sort()
    return boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]


def test_single_stratum_bootstrap_reproduces_v5():
    rng = random.Random(7)
    diff = [rng.choice([-1.0, 0.0, 0.0, 1.0, 1.0]) for _ in range(40)]
    boots = PA.bootstrap_mean_diff([diff], 2000, 3)
    assert PA.percentile_ci(boots, 0.95) == _v5_bootstrap(diff, 2000, 3)


def test_paired_matches_the_v5_script_on_a_toy_run(tmp_path):
    """analysis/paired_bootstrap.py (the v5 script, one run directory) and paired.compare_cases agree exactly."""
    rng = random.Random(11)
    rows = {"A": [], "B": []}
    for i in range(30):
        cid = f"toy-{i:04d}"
        for lab, p in (("A", 0.6), ("B", 0.45)):
            rows[lab].append({"case_id": cid, "repeat": 0, "source": "toy", "correct": rng.random() < p})
    for lab in rows:
        (tmp_path / f"results.{lab}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows[lab]))
    out = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "analysis", "paired_bootstrap.py"), "--run",
                          str(tmp_path), "--a", "A", "--b", "B", "--n-boot", "2000", "--seed", "3"],
                         capture_output=True, text=True, timeout=120, check=True).stdout
    v5 = json.loads(out)
    pa = {r["case_id"]: float(r["correct"]) for r in rows["A"]}
    pb = {r["case_id"]: float(r["correct"]) for r in rows["B"]}
    r = PA.compare_cases(pa, pb, list(pa), {c: "toy" for c in pa}, n_boot=2000, seed=3, stratify=False)
    assert r["ci"] == v5["bootstrap_95ci"] and r["diff"] == v5["diff_A_minus_B"]
    assert [r["wins"], r["ties"], r["losses"]] == v5["win_tie_loss_repeat0"]
    assert round(r["mcnemar_exact_p"], 5) == v5["mcnemar_exact_p"]


def test_pooled_bootstrap_resamples_within_benchmark():
    # benchmark X: every case +1, benchmark Y: every case 0. Resampling within benchmark keeps 10 X and 30 Y cases in
    # every replicate, so the pooled mean is always 10/40; resampling the pooled list would let it vary.
    pa = {f"x{i}": 1.0 for i in range(10)} | {f"y{i}": 0.0 for i in range(30)}
    pb = {c: 0.0 for c in pa}
    bench = {c: ("X" if c.startswith("x") else "Y") for c in pa}
    r = PA.compare_cases(pa, pb, list(pa), bench, n_boot=500, seed=1, stratify=True)
    assert r["ci"] == [0.25, 0.25] and r["strata"] == ["X", "Y"]
    unstrat = PA.compare_cases(pa, pb, list(pa), bench, n_boot=500, seed=1, stratify=False)
    assert unstrat["ci"][0] < 0.25 < unstrat["ci"][1]


def test_repeats_are_averaged_per_case_before_testing():
    rows = [{"label": "A", "case_id": "t-1", "repeat": k, "correct": v} for k, v in enumerate([True, True, False])]
    rows += [{"label": "A", "case_id": "t-2", "repeat": 0, "correct": False}]
    means, reps = PA.per_case(rows, "correct", None)
    assert means == {"t-1": pytest.approx(2 / 3), "t-2": 0.0} and reps == {"t-1": 3, "t-2": 1}
    pb = {"t-1": 0.0, "t-2": 0.0}
    r = PA.compare_cases(means, pb, ["t-1", "t-2"], {"t-1": "B", "t-2": "B"}, n_boot=10, seed=1)
    # the case, not the repeat, is the unit: one win, one tie; non-binary so no discordance table
    assert (r["wins"], r["ties"], r["losses"], r["binary"]) == (1, 1, 0, False)
    assert r["diff"] == pytest.approx(1 / 3, abs=1e-4)


def test_missing_case_is_an_error():
    with pytest.raises(CM.AnalysisError, match="lack a value"):
        PA.compare_cases({"a": 1.0}, {"a": 0.0, "b": 1.0}, ["a", "b"], {"a": "X", "b": "X"}, n_boot=5)


def test_outcome_fields_follow_the_set_reference_kind():
    assert PA.outcome_field("correct", "r1") == ("correct", None)
    assert PA.outcome_field("correct", "original") == ("correct_original_ref", None)
    assert PA.outcome_field("correct_tol:0.01", "original") == ("correct_tol_original_ref", "0.01")
    with pytest.raises(CM.AnalysisError, match="not a correctness signal"):
        PA.outcome_field("correct", "not_a_signal")
    with pytest.raises(CM.AnalysisError, match="needs a tier"):
        PA.outcome_field("correct_tol", "r1")
    with pytest.raises(CM.AnalysisError, match="unknown outcome"):
        PA.outcome_field("objective", "r1")


# ------------------------------------------------------------------ Holm


def test_holm_textbook_example():
    # four hypotheses, p = 0.01, 0.04, 0.03, 0.005, alpha 0.05: H4 and H1 are rejected, H2 and H3 are not
    res = HO.holm([("H1", 0.01), ("H2", 0.04), ("H3", 0.03), ("H4", 0.005)], 0.05)
    assert [h["reject"] for h in res] == [True, False, False, True]
    assert [h["p_adj"] for h in res] == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert [h["rank"] for h in res] == [2, 4, 3, 1]


def test_holm_is_not_bonferroni():
    # Bonferroni (m * p = 0.033, 0.06, 0.12) rejects only a; Holm steps down and rejects all three
    res = HO.holm([("a", 0.011), ("b", 0.02), ("c", 0.04)], 0.05)
    assert [h["reject"] for h in res] == [True, True, True]
    assert [h["p_adj"] for h in res] == pytest.approx([0.033, 0.04, 0.04])


def test_holm_refuses_bad_input_and_incomplete_families():
    with pytest.raises(CM.AnalysisError):
        HO.holm([], 0.05)
    with pytest.raises(CM.AnalysisError):
        HO.holm([("x", 1.2)], 0.05)
    fam = [{"id": "F", "alpha": 0.05, "comparisons": [
        {"id": "one", "a": "A", "b": "B", "model": "m", "outcome": "correct", "analysis_set": "s", "scope": "pooled"},
        {"id": "two", "a": "A", "b": "C", "model": "m", "outcome": "correct", "analysis_set": "s", "scope": "pooled"}]}]
    doc = {"data": "DEV", "analysis_set": {"name": "s"},
           "results": [{"a": "A", "b": "B", "model": "m", "outcome": "correct", "scope": "pooled", "mcnemar_exact_p": 0.01}]}
    with pytest.raises(CM.AnalysisError, match="all of its members"):
        HO.correct_families(fam, HO.index_paired([doc]))
    doc["results"].append(dict(doc["results"][0], b="C", mcnemar_exact_p=0.2))
    out = HO.correct_families(fam, HO.index_paired([doc]))
    assert out[0]["m"] == 2 and [h["reject"] for h in out[0]["results"]] == [True, False]


# ------------------------------------------------------------------ Tango score interval, TOST


def _loglik(b, c, n, q, d):
    return b * math.log(q + d) + c * math.log(q) + (n - b - c) * math.log(1 - 2 * q - d)


def _brute_q(b, c, n, d):
    """Constrained MLE by golden-section search (independent of the closed form)."""
    lo, hi = max(0.0, -d) + 1e-12, (1 - d) / 2 - 1e-12
    g = (math.sqrt(5) - 1) / 2
    x1, x2 = hi - g * (hi - lo), lo + g * (hi - lo)
    for _ in range(300):
        if _loglik(b, c, n, x1, d) < _loglik(b, c, n, x2, d):
            lo, x1 = x1, x2
            x2 = lo + g * (hi - lo)
        else:
            hi, x2 = x2, x1
            x1 = hi - g * (hi - lo)
    return (lo + hi) / 2


@pytest.mark.parametrize("b,c,n,d", [(5, 1, 20, 0.0), (5, 1, 20, 0.1), (10, 3, 85, -0.05), (13, 2, 85, 0.2),
                                     (7, 7, 40, 0.03), (2, 9, 60, -0.15)])
def test_constrained_mle_closed_form_equals_brute_force(b, c, n, d):
    assert TO.constrained_q(b, c, n, d) == pytest.approx(_brute_q(b, c, n, d), abs=1e-7)


def test_score_statistic_at_zero_is_the_mcnemar_z():
    # Tango's statistic at delta = 0 reduces to McNemar's z = (b - c) / sqrt(b + c)
    assert TO.score_stat(5, 1, 20, 0.0) == pytest.approx(4 / math.sqrt(6), rel=1e-12)
    assert TO.score_stat(10, 13, 85, 0.0) == pytest.approx(-3 / math.sqrt(23), rel=1e-12)


def test_score_interval_solves_the_score_equation():
    b, c, n = 12, 3, 85
    lo, hi = TO.score_ci(b, c, n, 0.90)
    z = 1.6448536269514722
    assert TO.score_stat(b, c, n, lo) == pytest.approx(z, abs=1e-6)
    assert TO.score_stat(b, c, n, hi) == pytest.approx(-z, abs=1e-6)
    assert lo < (b - c) / n < hi
    # swapping A and B mirrors the interval
    lo2, hi2 = TO.score_ci(c, b, n, 0.90)
    assert (lo2, hi2) == (pytest.approx(-hi, abs=1e-9), pytest.approx(-lo, abs=1e-9))


def test_score_interval_edge_cases():
    lo, hi = TO.score_ci(0, 0, 30, 0.95)        # no discordant pair: interval around 0, inside (-1, 1)
    assert -1 < lo < 0 < hi < 1 and lo == pytest.approx(-hi, abs=1e-9)
    lo, hi = TO.score_ci(30, 0, 30, 0.95)       # every case favours A
    assert hi == pytest.approx(1.0, abs=1e-9) and 0 < lo < 1


def test_tost_verdict_matches_the_interval_and_the_margin():
    # 200 cases, 6 vs 5 discordant: the 90% score interval is about -2.2 to +3.2 points
    eq = TO.tost_score(6, 5, 200, margin=0.05, alpha=0.05)
    assert eq["equivalent"] and eq["ci_inside_margin"]
    assert eq["p"] == max(eq["p_lower"], eq["p_upper"]) < 0.05
    ne = TO.tost_score(6, 5, 200, margin=0.02, alpha=0.05)
    assert not ne["equivalent"] and not ne["ci_inside_margin"]
    # a real difference is never "equivalent" with a small margin, however many cases
    far = TO.tost_score(40, 5, 400, margin=0.05, alpha=0.05)
    assert not far["equivalent"]
    with pytest.raises(CM.AnalysisError):
        TO.tost_score(1, 1, 10, margin=0.0)
    with pytest.raises(CM.AnalysisError):
        TO.score_stat(6, 6, 10, 0.0)


# ------------------------------------------------------------------ shared round 0


def _u(case, rep=0, sha="s1", correct=True, repaired=0, **kw):
    r = {"case_id": case, "repeat": rep, "round0_content_sha256": sha, "correct": correct, "exec_ok": True,
         "status": "Optimal", "objective": 1.0, "out_tokens": 100, "repair_rounds_used": repaired}
    r.update(kw)
    return r


def test_shared_round0_sha_check_positive_and_negative():
    ua = {("t-1", 0): _u("t-1"), ("t-2", 0): _u("t-2", sha="s2")}
    ub = {("t-1", 0): _u("t-1"), ("t-2", 0): _u("t-2", sha="s2")}
    assert SR.check_identity_sha(ua, ub)["mode"] == "sha"
    ub[("t-2", 0)] = _u("t-2", sha="other")
    with pytest.raises(SR.SharedRound0Error, match="differs on 1 of 2"):
        SR.check_identity_sha(ua, ub)
    ub[("t-2", 0)] = _u("t-2", sha=None)
    with pytest.raises(SR.SharedRound0Error, match="no round-0 content sha256"):
        SR.check_identity_sha(ua, ub)


def test_shared_round0_results_check_catches_a_different_round0():
    ur = {("t-1", 0): _u("t-1", correct=False), ("t-2", 0): _u("t-2")}
    ua = {("t-1", 0): _u("t-1", correct=True, repaired=1), ("t-2", 0): _u("t-2")}
    ub = {("t-1", 0): _u("t-1", correct=False), ("t-2", 0): _u("t-2")}
    assert SR.check_identity_results(ua, ub, ur)["n_unrepaired_checked"] == 3
    ub[("t-2", 0)] = _u("t-2", out_tokens=101)          # unrepaired but not the round-0 answer
    with pytest.raises(SR.SharedRound0Error, match="differ from the round-0 label"):
        SR.check_identity_results(ua, ub, ur)
    with pytest.raises(SR.SharedRound0Error, match="needs --round0-label"):
        SR.check_identity_results(ua, ub, None)


def test_decomposition_counts():
    ur = {("t-1", 0): _u("t-1", correct=False), ("t-2", 0): _u("t-2", correct=False), ("t-3", 0): _u("t-3")}
    ua = {("t-1", 0): _u("t-1", correct=True, repaired=1), ("t-2", 0): _u("t-2", correct=True, repaired=2),
          ("t-3", 0): _u("t-3")}
    ub = {("t-1", 0): _u("t-1", correct=False, repaired=1), ("t-2", 0): _u("t-2", correct=False),
          ("t-3", 0): _u("t-3")}
    d = SR.decompose(ua, ub, ur)
    assert d["summary"]["both_repaired"] == {"n": 1, "a_only_right": 1, "b_only_right": 0}
    assert d["summary"]["only_a_repaired"] == {"n": 1, "a_only_right": 1, "b_only_right": 0}
    assert d["table"]["neither_repaired"] == {"r0=1 a=1 b=1": 1}
    assert d["n_unrepaired_outcome_mismatch"] == 0


def test_shared_round0_mde_reproduces_stage0_values():
    # T8 section 3.4 (IndustryOR n = 75, all regression rates; pooled n = 226 at p01 = 0): 10.4 11.3 12.2 13.8 15.1, 3.5
    got = [SR.mde_shared_round0(75, p)[0] for p in (0.0, 0.005, 0.01, 0.02, 0.03)]
    assert [round(100 * d, 1) for d in got] == [10.4, 11.3, 12.2, 13.8, 15.1]
    d, pw = SR.mde_shared_round0(226, 0.0)
    assert (round(d, 3), round(pw, 3)) == (0.035, 0.805)


# ------------------------------------------------------------------ pre-registration file


def test_prereg_file_is_valid_and_its_tiers_match_the_runtime():
    pr = PR.load()
    assert pr.get("primary_comparison")["a"] == "C3L@2" and pr.get("primary_comparison")["b"] == "C3E@2"
    assert pr.get("tolerance_tiers") == ["1e-06", "0.0001", "0.01"]
    # the 1D decisions of 2026-10-03 and the scale strata (2026-10-04) are fixed: nothing is pending
    assert pr.pending() == []
    assert pr.get("strata_scale_feature") == pr.get("strata_scale_cutpoints")["feature"] == "n_numeric_literals"
    assert pr.get("alpha") == 0.05 and pr.get("tost_margin") == 0.05 and pr.get("bootstrap")["n_boot"] == 10000
    fams = {f["id"]: [c["id"] for c in f["comparisons"]] for f in pr.get("holm_families")}
    assert fams["primary"] == ["C3L_vs_C3E"] and "C3L_vs_C3LALL" not in fams["controls"]
    (h2,) = pr.get("gated_tests")
    assert (h2["gate"], h2["comparison"]["a"], h2["comparison"]["b"], h2["alpha"]) == ("C3L_vs_C3E", "C3L@1", "C3T@1", 0.05)
    assert pr.get("mechanism")["labels"] == {"l": "C3L@1", "e": "C3E@1", "t": "C3T@1", "a": "C3A@1", "round0": "C0"}


def test_prereg_pending_items_refuse_test_use_and_are_recorded_for_dev(tmp_path):
    pr = PR.load(draft_file(tmp_path))
    with pytest.raises(PR.PendingItem):
        pr.get("bootstrap")
    boot = pr.get("bootstrap", allow_pending=True)
    assert boot["n_boot"] == 10000 and "bootstrap" in pr.provenance()["pending_used"]
    with pytest.raises(PR.PendingItem, match="no proposal"):
        pr.get("tost_margin", allow_pending=True)
    assert pr.get("tost_margin", allow_pending=True, override=0.05) == 0.05
    with pytest.raises(CM.AnalysisError, match="cannot be overridden"):
        pr.get("tolerance_primary", override="0.01")


def test_prereg_check_final_refuses_pending_items(tmp_path):
    """`prereg.py check --final` (the freeze step of 1D) fails while any item is pending and passes once all are
    fixed; plain `check` passes either way."""
    cli = [sys.executable, "-B", os.path.join(ROOT, "analysis", "r1", "prereg.py"), "check"]
    assert subprocess.run(cli, capture_output=True, text=True, timeout=60, cwd=ROOT).returncode == 0
    doc = json.load(open(os.path.join(ROOT, "configs", "prereg_analysis.json"), encoding="utf-8"))
    assert all(it["status"] == "fixed" for it in doc["items"].values())   # the committed file has no pending item
    f = tmp_path / "prereg_final.json"
    f.write_text(json.dumps(doc))
    p = subprocess.run(cli + ["--final", "--file", str(f)], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert p.returncode == 0 and "pending 0" in p.stdout, p.stdout + p.stderr
    # one item back to pending: refused
    doc["items"]["tost_margin"].update(status="pending", value=None)
    f.write_text(json.dumps(doc))
    p = subprocess.run(cli + ["--final", "--file", str(f)], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert p.returncode == 1 and "FAIL: pending items remain" in p.stdout and "tost_margin" in p.stdout


def test_prereg_validation_rejects_broken_documents():
    assert PR.validate(json.load(open(os.path.join(ROOT, "configs", "prereg_analysis.json"), encoding="utf-8"))) == []
    doc = draft_doc()
    assert PR.validate(doc) == []
    bad = json.loads(json.dumps(doc))
    bad["items"]["tost_margin"]["value"] = 0.05             # pending with a value
    bad["items"]["tolerance_tiers"]["value"] = ["0.0001"]   # differs from the runtime
    bad["items"]["alpha"]["status"] = "maybe"
    del bad["items"]["repeats"]
    bad["items"]["surprise"] = {"status": "fixed", "value": 1, "basis": "x"}
    fam = bad["items"]["holm_families"]["proposal"]
    fam[1]["comparisons"].append(dict(fam[0]["comparisons"][0]))   # one comparison in two families
    probs = " | ".join(PR.validate(bad))
    for frag in ("tost_margin: a pending item has value null", "tolerance_tiers", "alpha.status",
                 "item repeats is missing", "unknown item 'surprise'", "used twice"):
        assert frag in probs, frag
    # gated tests: the gate must be the single comparison of a family, and the gated comparison outside every family
    real = json.load(open(os.path.join(ROOT, "configs", "prereg_analysis.json"), encoding="utf-8"))
    g = real["items"]["gated_tests"]["value"][0]
    g["gate"] = "C3E_vs_C0"                                   # a member of the five-comparison ladder family
    assert any("not the single comparison of a Holm family" in x for x in PR.validate(real))
    g["gate"] = "C3L_vs_C3E"
    g["comparison"]["id"] = "C3L_vs_C0"
    assert any("also belongs to a Holm family" in x for x in PR.validate(real))
    real["items"]["mechanism"]["value"]["labels"].pop("t")
    assert any("mechanism.value.labels" in x for x in PR.validate(real))


# ------------------------------------------------------------------ labels


def test_data_label_refuses_mixed_splits():
    assert CM.data_label(["dev", "dev"]) == "DEV"
    assert CM.data_label(["test"]) == "TEST"
    with pytest.raises(CM.AnalysisError, match="several splits"):
        CM.data_label(["dev", "test"])
    assert CM.labelled_path("out/paired.json", "DEV") == "out/paired.DEV.json"
    assert CM.labelled_path("out/paired.DEV.json", "DEV") == "out/paired.DEV.json"
    assert CM.signed_pp(-0.1647) == "−16.5" and CM.signed_pp(0.0) == "+0.0" and CM.signed_pp(-0.00001) == "+0.0"


# ------------------------------------------------------------------ analysis environment (scipy, statsmodels, ...)


def _tools_python():
    p = os.environ.get("ORGENE_TOOLS_PY") or os.path.join(ROOT, ".venv-tools", "bin", "python")
    return p if os.path.exists(p) else None


def test_venv_cross_checks_pass_in_the_analysis_environment():
    py = _tools_python()
    if py is None:
        pytest.skip("no analysis environment (.venv-tools or ORGENE_TOOLS_PY); an anonymous clone skips this")
    if all(importlib.util.find_spec(m) for m in ("numpy", "scipy", "statsmodels", "matplotlib")):
        pytest.skip("this interpreter has the analysis packages: test_e20a_venv.py runs directly")
    p = subprocess.run([py, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        os.path.join(HERE, "test_e20a_venv.py")], capture_output=True, text=True, timeout=900, cwd=ROOT)
    tail = (p.stdout + p.stderr)[-1500:]
    assert p.returncode == 0, tail
    assert " passed" in tail and "skipped" not in tail and "failed" not in tail, tail

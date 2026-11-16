"""E20a cross-checks that need the analysis environment (.venv-tools: numpy, scipy, statsmodels, matplotlib).

Skipped under an interpreter without those packages; test_e20a_stats.py runs this file with the analysis
environment's interpreter when it exists. Synthetic data and toy case ids only."""
import math
import os
import sys

import pytest

np = pytest.importorskip("numpy")
scipy_stats = pytest.importorskip("scipy.stats")
scipy_optimize = pytest.importorskip("scipy.optimize")
pytest.importorskip("statsmodels")
pytest.importorskip("matplotlib")

from statsmodels.stats.contingency_tables import mcnemar as sm_mcnemar  # noqa: E402
from statsmodels.stats.multitest import multipletests  # noqa: E402
from statsmodels.stats.proportion import proportion_confint  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))
sys.path.insert(0, os.path.join(ROOT, "analysis", "r1"))

import common as CM  # noqa: E402
import forest as FO  # noqa: E402
import holm as HO  # noqa: E402
import length_model as LM  # noqa: E402
import paired as PA  # noqa: E402
import registry as RG  # noqa: E402
import tost as TO  # noqa: E402


# ------------------------------------------------------------------ TOST / score interval against scipy


def _scipy_score_ci(b, c, n, level):
    """Tango's interval from scratch with scipy: numeric constrained MLE (bounded 1-D optimisation) + brentq."""
    def q_of(d):
        lo, hi = max(0.0, -d) + 1e-13, (1 - d) / 2 - 1e-13
        f = lambda q: -(b * math.log(q + d) + c * math.log(q) + (n - b - c) * math.log(1 - 2 * q - d))  # noqa: E731
        return scipy_optimize.minimize_scalar(f, bounds=(lo, hi), method="bounded",
                                              options={"xatol": 1e-13, "maxiter": 5000}).x

    def T(d):
        return (b - c - n * d) / math.sqrt(n * (2 * q_of(d) + d * (1 - d)))

    z = scipy_stats.norm.ppf(1 - (1 - level) / 2)
    est = (b - c) / n
    return (scipy_optimize.brentq(lambda d: T(d) - z, -0.999, est, xtol=1e-12),
            scipy_optimize.brentq(lambda d: T(d) + z, est, 0.999, xtol=1e-12), T)


@pytest.mark.parametrize("b,c,n", [(12, 3, 85), (6, 5, 200), (2, 9, 60), (10, 0, 85), (25, 20, 226)])
def test_score_interval_and_tost_match_scipy(b, c, n):
    lo_s, hi_s, T = _scipy_score_ci(b, c, n, 0.90)
    lo, hi = TO.score_ci(b, c, n, 0.90)
    assert lo == pytest.approx(lo_s, abs=1e-6) and hi == pytest.approx(hi_s, abs=1e-6)
    r = TO.tost_score(b, c, n, margin=0.08, alpha=0.05)
    assert r["p_lower"] == pytest.approx(scipy_stats.norm.sf(T(-0.08)), abs=1e-6)
    assert r["p_upper"] == pytest.approx(scipy_stats.norm.cdf(T(0.08)), abs=1e-6)
    assert r["equivalent"] == (-0.08 < lo_s and hi_s < 0.08)


def test_mcnemar_and_wilson_match_statsmodels_and_scipy():
    for b, c in [(0, 0), (5, 1), (13, 0), (10, 13), (29, 3), (40, 38)]:
        p = PA.mcnemar_exact(b, c)
        assert p == pytest.approx(sm_mcnemar([[0, b], [c, 0]], exact=True).pvalue, abs=1e-12)
        if b + c:
            assert p == pytest.approx(scipy_stats.binomtest(b, b + c, 0.5).pvalue, abs=1e-12)
    for x, n in [(13, 85), (0, 25), (25, 25), (35, 85)]:
        lo, hi = PA.wilson(x, n)
        slo, shi = proportion_confint(x, n, alpha=0.05, method="wilson")
        assert (lo, hi) == (pytest.approx(slo, abs=1e-9), pytest.approx(shi, abs=1e-9))


def test_holm_matches_statsmodels():
    rng = np.random.default_rng(20260929)
    for m in (1, 2, 5, 12):
        for _ in range(20):
            ps = list(rng.uniform(0, 0.2, size=m))
            ours = HO.holm([(str(i), p) for i, p in enumerate(ps)], 0.05)
            rej, adj, _, _ = multipletests(ps, alpha=0.05, method="holm")
            assert [h["reject"] for h in ours] == list(rej)
            assert [h["p_adj"] for h in ours] == pytest.approx(list(adj), abs=1e-12)


# ------------------------------------------------------------------ length model


def _synthetic(n_cases, seed, beta=1.0, gamma=-0.8, reps=3):
    """Difficulty a_i per case; output length depends on the configuration and on a_i (confounding); the true
    conditional model is logit P(correct) = a_i + beta * [config B] + gamma * log(tokens)."""
    rng = np.random.default_rng(seed)
    y, X, g = [], [], []
    a = rng.normal(0, 1.5, size=n_cases)
    for i in range(n_cases):
        for cfg in (0, 1):
            for _ in range(reps):
                lt = 6 + 0.5 * cfg + 0.3 * a[i] + rng.normal(0, 0.5)
                eta = a[i] + beta * cfg + gamma * (lt - 6)
                y.append(float(rng.random() < 1 / (1 + math.exp(-eta))))
                X.append([float(cfg), lt])
                g.append(f"toy-{i:04d}")
    return y, X, g


def test_conditional_logit_recovers_known_effects_and_a_marginal_model_does_not():
    y, X, g = _synthetic(1500, seed=11)
    cl = LM.fit_conditional_logit(y, X, g, ["label[B]", "log_out_tokens"])
    assert cl["converged"]
    for term, truth in (("label[B]", 1.0), ("log_out_tokens", -0.8)):
        est = cl["params"][term]
        assert abs(est["coef"] - truth) < 4 * est["se"], (term, est)
        assert est["se"] < 0.1
    # negative control: ignoring the case (a marginal model) is confounded by difficulty and misses the length effect
    gee = LM.fit_gee(y, X, g, ["label[B]", "log_out_tokens"])
    assert abs(gee["params"]["log_out_tokens"]["coef"] - (-0.8)) > 0.5


def test_conditional_logit_refuses_a_design_without_information():
    y = [1.0] * 12
    X = [[float(i % 2), 5.0 + i / 10] for i in range(12)]
    g = [f"toy-{i // 2}" for i in range(12)]
    with pytest.raises(CM.AnalysisError, match="no information"):
        LM.fit_conditional_logit(y, X, g, ["label[B]", "log_out_tokens"])


def _pairs(spec):
    """One case per (outcome, delta) of spec: configurations A and B, outcome "B" (only B right), "A" (only A right)
    or "both"; delta = log tokens of B minus log tokens of A in that case."""
    y, X, g = [], [], []
    for i, (who, delta) in enumerate(spec):
        base = 5.0 + (i % 4) / 10
        ya, yb = {"A": (1.0, 0.0), "B": (0.0, 1.0), "both": (1.0, 1.0)}[who]
        y += [ya, yb]
        X += [[0.0, base], [1.0, base + delta]]
        g += [f"toy-{i:04d}", f"toy-{i:04d}"]
    return y, X, g


B_WINS = [("B", (-0.2, 0.0, 0.2)[i % 3]) for i in range(20)] + [("both", 0.1)] * 10
NAMES2 = ["label[B]", "log_out_tokens"]


def test_separation_is_reported_not_raised():
    # configuration B never loses: within every informative case B is right and A wrong -> no finite MLE
    cl = LM.fit_conditional_logit(*_pairs(B_WINS), NAMES2)
    assert cl["params"] is None and cl["status"] == LM.SEPARATED and not cl["converged"]
    assert cl["n_informative_strata"] == 20
    # control: two losses of B (token difference 0) -> no separating direction, a finite estimate
    ok = LM.fit_conditional_logit(*_pairs(B_WINS + [("A", 0.0)] * 2), NAMES2)
    assert ok["status"] == "ok" and ok["n_informative_strata"] == 22
    assert ok["params"]["label[B]"]["coef"] == pytest.approx(math.log(10), abs=0.05)


def test_separation_along_a_combination_of_covariates_is_found():
    # 30 cases; B is right in all but case 1, A right in every third case and in case 1. The token differences
    # (B - A) of the informative cases are -0.8 (B wins) and 0.3 (B wins, and A wins once): the direction
    # (+0.3 on the label, -1 on log tokens) separates quasi-completely, so there is no finite MLE. Newton stops at
    # finite coefficients below the size guard with a non-finite standard error; before the linear-program check this
    # case came out as status "ok" with NaN standard errors (and the JSON output then failed on NaN).
    y, X, g = [], [], []
    for i in range(30):
        for cfg in (0, 1):
            right_b = i != 1
            y.append(float(right_b) if cfg == 1 else float(i % 3 == 0 or not right_b))
            X.append([float(cfg), 5.0 + ((7 * i + 3 * cfg) % 11) / 10])
            g.append(f"toy-{i:04d}")
    cl = LM.fit_conditional_logit(y, X, g, NAMES2)
    assert cl["status"] == LM.SEPARATED and cl["params"] is None


def test_collinear_covariates_within_cases_are_not_identified():
    # the token difference is the same in every case, so label and log tokens cannot be told apart within cases
    spec = [("B", 0.1)] * 12 + [("A", 0.1)] * 4 + [("both", 0.1)] * 4
    cl = LM.fit_conditional_logit(*_pairs(spec), NAMES2)
    assert cl["status"] == LM.NOT_IDENTIFIED and cl["params"] is None


def test_length_analysis_on_a_matrix_drops_units_without_tokens_and_fills_quartiles():
    y, X, g = _synthetic(300, seed=5, reps=1)
    rows = []
    for yy, (cfg, lt), c in zip(y, X, g):
        rows.append({"model": "toy-model", "label": "B" if cfg else "A", "case_id": c, "repeat": 0,
                     "benchmark": "toy", "correct": bool(yy), "out_tokens": int(round(math.exp(lt)))})
    rows[0]["out_tokens"] = None
    m = RG.Matrix(rows, {"data": "DEV"})
    res = LM.analyse(m, ["A", "B"], "toy-model")
    assert res["n_dropped_no_tokens"] == 1 and res["primary"]["n_obs"] == 599
    assert sum(t["n"] for t in res["quartiles"]["table"]) == 599
    assert len(res["quartiles"]["cutpoints"]) == 3 and res["reference_label"] == "A"


# ------------------------------------------------------------------ forest plot


def _paired_doc(label, rows):
    return {"data": label, "analysis_set": {"name": "toy"}, "results": [
        {"a": "A", "b": "B", "model": "toy-model", "scope": s, "outcome": "correct", "diff": d, "ci": [lo, hi], "n": n}
        for s, d, lo, hi, n in rows]}


def test_forest_plot_is_deterministic_and_labelled(tmp_path):
    import json
    p1 = tmp_path / "p_main.json"
    p2 = tmp_path / "p_orig.json"
    p1.write_text(json.dumps(_paired_doc("DEV", [("pooled", 0.10, 0.03, 0.18, 55), ("toy", 0.2, 0.0, 0.4, 30)])))
    p2.write_text(json.dumps(_paired_doc("DEV", [("pooled", 0.08, 0.01, 0.16, 55)])))
    spec = {"title": "A vs B", "margin": 0.05, "rows": [
        {"setting": "main", "file": "p_main.json", "a": "A", "b": "B", "model": "toy-model", "scope": "pooled"},
        {"setting": "original reference", "file": "p_orig.json", "a": "A", "b": "B", "model": "toy-model", "scope": "pooled"}]}
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    outs = []
    for k in range(2):
        stem = str(tmp_path / f"f{k}" / "forest")
        assert FO.main(["--spec", str(tmp_path / "spec.json"), "--out", stem]) == 0
        outs.append({ext: open(f"{stem}.DEV.{ext}", "rb").read() for ext in ("svg", "pdf", "json")})
    assert outs[0] == outs[1]
    svg = outs[0]["svg"].decode("utf-8")
    assert "[DEV] A vs B" in svg and "original reference (n=55)" in svg
    assert b"CreationDate" not in outs[0]["pdf"]
    # rows of different data labels are refused
    p2.write_text(json.dumps(_paired_doc("TEST", [("pooled", 0.08, 0.01, 0.16, 55)])))
    with pytest.raises(CM.AnalysisError, match="several data labels"):
        FO.collect(spec, str(tmp_path))

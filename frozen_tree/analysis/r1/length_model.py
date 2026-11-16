#!/usr/bin/env python3
"""Does output length explain the accuracy difference? correct ~ configuration + log(output tokens) (E20a; todo A0-12).

  .venv-tools/bin/python analysis/r1/length_model.py --labels C3L@2 C3E@2 [C0 ...] [--registry ...] [--set main]
      [--outcome correct] --out length.json

Needs the analysis environment (.venv-tools: numpy, statsmodels); the runtime does not.
Observations: one per (case, label, repeat) of the analysis set; y = the outcome (0/1); x = one indicator per label
other than the first (the reference), and log(out_tokens) with out_tokens the unit's output tokens summed over all
its calls (result rows). Units with missing or non-positive out_tokens are dropped and counted.
  primary      conditional logistic regression with one stratum per case (statsmodels ConditionalLogit): the case
               effect (difficulty) is conditioned away; only cases whose outcomes differ contribute. Before fitting,
               a linear program checks for separation (e.g. one configuration never loses among the informative
               cases) and a rank check for collinearity within cases; either one is reported as "no finite
               estimate" instead of a fit, as is a fit with a diverging coefficient or a non-finite standard error
  sensitivity  GEE, binomial family, logit link, exchangeable working correlation, clusters = cases, with an
               intercept (statsmodels GEE; robust standard errors)
  quartiles    output-token quartile cut points pooled over the compared labels (statistics.quantiles n=4,
               inclusive); per label and quartile: n and accuracy
Reported: coefficients, standard errors, 95% Wald intervals, odds ratios, p-values, numbers of units, cases and
informative strata. Labelled DEV / TEST like every analysis output.
"""
import argparse
import bisect
import math
import os
import statistics
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import paired as PA  # noqa: E402
import prereg as PR  # noqa: E402
import registry as RG  # noqa: E402
from common import AnalysisError, dumps, labelled_path, md_header, rel, write_text  # noqa: E402

SCHEMA = "orgene.r1.length_model.v1"
MAX_COEF = 20.0   # |coefficient| beyond this on the logit scale = no finite estimate (separation)
NO_ESTIMATE = ("no finite estimate: the information matrix is singular or a coefficient diverges (separation, e.g. one "
               "configuration never loses among the informative cases, or too few informative cases)")
SEPARATED = ("no finite estimate: separation (linear-program check): a combination of the covariates never lowers and "
             "somewhere raises the conditional likelihood, e.g. one configuration never loses among the informative "
             "cases")
NOT_IDENTIFIED = "no finite estimate: not identified (the covariates are collinear within cases)"


def design(rows_by_label, labels, field, tier, keep_cases=None):
    """(y, X, groups, names, n_dropped) with X = [label indicators..., log_tokens]."""
    ys, xs, gs, dropped = [], [], [], 0
    names = [f"label[{l}]" for l in labels[1:]] + ["log_out_tokens"]
    for j, lab in enumerate(labels):
        for r in rows_by_label[lab]:
            if keep_cases is not None and r["case_id"] not in keep_cases:
                continue
            t = r.get("out_tokens")
            if t is None or t <= 0:
                dropped += 1
                continue
            ys.append(PA.value_of(r, field, tier))
            xs.append([1.0 if j == k + 1 else 0.0 for k in range(len(labels) - 1)] + [math.log(t)])
            gs.append(r["case_id"])
    return ys, xs, gs, names, dropped


def _summ(names, params, bse, pvalues, conf):
    out = {}
    for i, n in enumerate(names):
        out[n] = {"coef": float(params[i]), "se": float(bse[i]), "ci95": [float(conf[i][0]), float(conf[i][1])],
                  "odds_ratio": float(math.exp(params[i])), "p": float(pvalues[i])}
    return out


def pair_differences(yv, Xv, gv):
    """Rows x_i - x_j for every pair (i right, j wrong) inside one case. The conditional likelihood depends on the
    coefficients only through these differences."""
    import numpy as np
    rows = []
    for g in np.unique(gv):
        idx = np.flatnonzero(gv == g)
        ones, zeros = idx[yv[idx] == 1], idx[yv[idx] == 0]
        rows += [Xv[i] - Xv[j] for i in ones for j in zeros]
    return np.asarray(rows, float).reshape(-1, Xv.shape[1])


def mle_obstacle(yv, Xv, gv):
    """None when the conditional-logit MLE exists and is unique; otherwise NOT_IDENTIFIED or SEPARATED.
    Not identified: the pair differences do not span the coefficient space (collinear within cases).
    Separation (complete or quasi-complete; Albert and Anderson 1984, for the conditional likelihood): a direction v
    with v.d >= 0 for every pair difference d and v.d > 0 for one of them raises the likelihood without bound, so no
    finite MLE exists. Found exactly with a linear program: maximise sum(D v) subject to D v >= 0, -1 <= v <= 1."""
    import numpy as np
    from scipy.optimize import linprog
    D = pair_differences(yv, Xv, gv)
    if D.shape[0] == 0 or np.linalg.matrix_rank(D) < D.shape[1]:
        return NOT_IDENTIFIED
    lp = linprog(-D.sum(axis=0), A_ub=-D, b_ub=np.zeros(D.shape[0]), bounds=[(-1.0, 1.0)] * D.shape[1],
                 method="highs")
    if lp.status == 0 and -lp.fun > 1e-7 * max(1.0, float(np.abs(D).max())):
        return SEPARATED
    return None


def fit_conditional_logit(y, X, groups, names):
    import numpy as np
    from statsmodels.discrete.conditional_models import ConditionalLogit
    yv, Xv = np.asarray(y, float), np.asarray(X, float)
    codes = {g: i for i, g in enumerate(sorted(set(groups)))}
    gv = np.asarray([codes[g] for g in groups])
    informative = sum(1 for g in codes.values() if 0 < yv[gv == g].sum() < (gv == g).sum())
    if informative == 0:
        raise AnalysisError("no case has differing outcomes: the conditional logit has no information")
    head = {"model": "conditional logistic regression (strata = cases)", "n_obs": int(len(yv)),
            "n_strata": len(codes), "n_informative_strata": informative}
    obstacle = mle_obstacle(yv, Xv, gv)
    if obstacle:
        return dict(head, status=obstacle, converged=False, max_abs_score=None, params=None)
    with warnings.catch_warnings():
        # statsmodels warns that it drops the strata without within-case variation; they are counted above
        warnings.simplefilter("ignore")
        model = ConditionalLogit(yv, Xv, groups=gv)
        try:
            res = model.fit(method="newton", disp=False, maxiter=200)
        except np.linalg.LinAlgError:
            return dict(head, status=NO_ESTIMATE, converged=False, max_abs_score=None, params=None)
    # the results object keeps no optimiser status; convergence = the score vanishes at the estimate
    score = float(np.max(np.abs(model.score(np.asarray(res.params)))))
    params, bse = np.asarray(res.params), np.asarray(res.bse)
    if not np.all(np.isfinite(params)) or np.max(np.abs(params)) > MAX_COEF or not np.all(np.isfinite(bse)) \
            or np.any(bse <= 0):
        return dict(head, status=NO_ESTIMATE, converged=False, max_abs_score=score, params=None)
    conf = res.conf_int(0.05)
    return dict(head, status="ok" if score < 1e-3 else "not converged", max_abs_score=score, converged=score < 1e-3,
                params=_summ(names, res.params, res.bse, res.pvalues, conf))


def fit_gee(y, X, groups, names):
    import numpy as np
    import statsmodels.api as sm
    yv = np.asarray(y, float)
    Xv = sm.add_constant(np.asarray(X, float), has_constant="add")
    codes = {g: i for i, g in enumerate(sorted(set(groups)))}
    gv = np.asarray([codes[g] for g in groups])
    head = {"model": "GEE binomial logit, exchangeable, clusters = cases (robust SE)", "n_obs": int(len(yv)),
            "n_clusters": len(codes)}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            res = sm.GEE(yv, Xv, groups=gv, family=sm.families.Binomial(),
                         cov_struct=sm.cov_struct.Exchangeable()).fit(maxiter=200)
        except (np.linalg.LinAlgError, ValueError):
            return dict(head, status=NO_ESTIMATE, working_correlation=None, params=None)
    params = np.asarray(res.params)
    if not np.all(np.isfinite(params)) or np.max(np.abs(params)) > MAX_COEF or not np.all(np.isfinite(res.bse)):
        return dict(head, status=NO_ESTIMATE, working_correlation=None, params=None)
    conf = res.conf_int(0.05)
    conf = conf.tolist() if hasattr(conf, "tolist") else conf
    return dict(head, status="ok", working_correlation=float(res.cov_struct.dep_params),
                params=_summ(["intercept"] + names, res.params, res.bse, res.pvalues, conf))


def quartiles(rows_by_label, labels, field, tier, keep_cases=None):
    vals = [r["out_tokens"] for l in labels for r in rows_by_label[l]
            if (keep_cases is None or r["case_id"] in keep_cases) and r.get("out_tokens")]
    if len(vals) < 4:
        raise AnalysisError("fewer than 4 units with output tokens; no quartiles")
    cuts = statistics.quantiles(vals, n=4, method="inclusive")
    table = []
    for l in labels:
        for q in range(4):
            sel = [r for r in rows_by_label[l] if (keep_cases is None or r["case_id"] in keep_cases)
                   and r.get("out_tokens") and bisect.bisect_left(cuts, r["out_tokens"]) == q]
            k = sum(PA.value_of(r, field, tier) for r in sel)
            table.append({"label": l, "quartile": f"Q{q + 1}", "n": len(sel), "n_correct": int(k),
                          "accuracy": round(k / len(sel), 4) if sel else None})
    return {"cutpoints": [float(c) for c in cuts], "rule": "Q1 <= c1 < Q2 <= c2 < Q3 <= c3 < Q4", "table": table}


def analyse(matrix, labels, model, outcome="correct", reference_kind="r1", keep_cases=None):
    if len(labels) < 2:
        raise AnalysisError("give at least two labels")
    field, tier = PA.outcome_field(outcome, reference_kind)
    by = {l: matrix.select(model, l) for l in labels}
    y, X, g, names, dropped = design(by, labels, field, tier, keep_cases)
    return {"model_id": model, "labels": labels, "reference_label": labels[0], "outcome": outcome,
            "n_dropped_no_tokens": dropped, "primary": fit_conditional_logit(y, X, g, names),
            "sensitivity": fit_gee(y, X, g, names), "quartiles": quartiles(by, labels, field, tier, keep_cases)}


def run(args, matrix=None, aset=None, prereg=None):
    pr = prereg or PR.load(args.prereg)
    spec = pr.get("length_model")
    if matrix is None:
        reg = RG.load_registry(args.registry, superseded_path=args.superseded)
        matrix = RG.build_matrix(reg, labels=args.labels, models=args.models)
    dev = matrix.label == "DEV"
    if aset is None:
        name = RG.set_name_for(matrix.label, args.set, args.incl_0905)
        aset = RG.resolve_set(name, allow_pending=args.allow_pending and dev)
    m = RG.restrict(matrix, aset)
    keep = set(aset["ids"])
    res = [analyse(m, args.labels, model, args.outcome, aset["reference"], keep) for model in (args.models or m.models())]
    return {"schema": SCHEMA, "data": m.label, "generated_by": "analysis/r1/length_model.py", "specification": spec,
            "analysis_set": m.header["analysis_set"], "prereg": pr.provenance(),
            "inputs": {k: m.header[k] for k in ("registry", "runs", "freeze_gate")}, "results": res}


def render_md(doc):
    lines = [md_header("Output length and accuracy: correct ~ configuration + log(output tokens)", doc["data"])]
    for r in doc["results"]:
        lines += ["", f"## {r['model_id']}: {', '.join(r['labels'])} (reference {r['reference_label']})", "",
                  "| model | term | coef | 95% CI | OR | p |", "|---|---|---|---|---|---|"]
        for part in ("primary", "sensitivity"):
            if r[part]["params"] is None:
                lines.append(f"| {part} | – | {r[part]['status']} | | | |")
                continue
            for term, v in r[part]["params"].items():
                lines.append(f"| {part} | {term} | {v['coef']:.3f} | [{v['ci95'][0]:.3f}, {v['ci95'][1]:.3f}] | "
                             f"{v['odds_ratio']:.3f} | {v['p']:.4f} |")
        q = r["quartiles"]
        lines += ["", f"Quartile cut points (output tokens): {', '.join(f'{c:g}' for c in q['cutpoints'])}", "",
                  "| label | quartile | n | accuracy |", "|---|---|---|---|"]
        lines += [f"| {t['label']} | {t['quartile']} | {t['n']} | {t['accuracy']} |" for t in q["table"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", nargs="+", required=True)
    ap.add_argument("--registry", default=RG.DEFAULT_REGISTRY)
    ap.add_argument("--superseded", default=RG.DEFAULT_SUPERSEDED)
    ap.add_argument("--prereg", default=PR.DEFAULT_PATH)
    ap.add_argument("--set", default=None)
    ap.add_argument("--incl-0905", action="store_true")
    ap.add_argument("--allow-pending", action="store_true")
    ap.add_argument("--outcome", default="correct")
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    try:
        doc = run(a)
    except AnalysisError as x:
        print(f"[length_model] REFUSED: {x}", file=sys.stderr)
        return 2
    md = render_md(doc)
    if a.out:
        out = labelled_path(a.out, doc["data"])
        write_text(out, dumps(doc))
        write_text(os.path.splitext(out)[0] + ".md", md)
        print(f"[length_model] {doc['data']} -> {rel(out)}")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Equivalence test (TOST) for two paired proportions (E20a; todo B1-10).

  $PY analysis/r1/tost.py --a C3L@2 --b C3L@1 [--registry ...] [--set main] [--outcome correct]
                          [--margin D (dev only, while the pre-registered margin is pending)] --out tost.json

Primary method: the score interval of Tango (1998, Statistics in Medicine 17:891-908) for the paired difference
delta = P(A right) - P(B right). With b = cases only A gets right, c = cases only B gets right, n cases:
  T(d) = (b - c - n d) / sqrt(n (2 q(d) + d (1 - d)))
where q(d) is the maximum-likelihood estimate of P(only B right) under delta = d, the root of
  2n q^2 + (-b - c + (2n - b + c) d) q - c d (1 - d) = 0 (the non-negative one).
T is decreasing in d; the (1 - 2 alpha) interval is {d : |T(d)| <= z(1 - alpha)}, found by bisection.
TOST with margin D: p_lower = 1 - Phi(T(-D)) (H0: delta <= -D), p_upper = Phi(T(D)) (H0: delta >= D),
p = max(p_lower, p_upper); equivalence when p < alpha, which is the same as the (1 - 2 alpha) score interval lying
inside (-D, D).
Cross-check: the case bootstrap percentile (1 - 2 alpha) interval of the same difference (paired.py draws); the
output says whether both methods reach the same verdict. The score test needs one binary outcome per case: with
repeats (the variance subset) only the bootstrap is reported.
The margin comes from the pre-registered item tost_margin; a test analysis refuses while it is pending.
Standard library only (tests cross-check against scipy in the analysis environment).
"""
import argparse
import math
import os
import sys
from statistics import NormalDist

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import paired as PA  # noqa: E402
import prereg as PR  # noqa: E402
import registry as RG  # noqa: E402
from common import AnalysisError, dumps, labelled_path, md_header, rel, signed_pp, write_text  # noqa: E402

SCHEMA = "orgene.r1.tost.v1"
_N = NormalDist()


def constrained_q(b, c, n, d):
    """MLE of P(only B right) given P(only A right) - P(only B right) = d (closed form, Tango 1998)."""
    A = 2.0 * n
    B = -b - c + (2.0 * n - b + c) * d
    C = -c * d * (1.0 - d)
    disc = max(B * B - 4.0 * A * C, 0.0)
    return (-B + math.sqrt(disc)) / (2.0 * A)


def score_stat(b, c, n, d):
    """Tango's score statistic T(d); +-inf where its variance vanishes."""
    if n <= 0:
        raise AnalysisError("n must be positive")
    if b < 0 or c < 0 or b + c > n:
        raise AnalysisError("counts must satisfy 0 <= b, c and b + c <= n")
    q = constrained_q(b, c, n, d)
    var = n * (2.0 * q + d * (1.0 - d))
    num = b - c - n * d
    if var <= 1e-300:
        return 0.0 if abs(num) < 1e-12 else math.copysign(math.inf, num)
    return num / math.sqrt(var)


def _root(f, lo, hi, iters=200):
    """Bisection for f decreasing on [lo, hi] with f(lo) >= 0 >= f(hi)."""
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def score_ci(b, c, n, level):
    """Tango score interval for delta at confidence `level`."""
    z = _N.inv_cdf(1.0 - (1.0 - level) / 2.0)
    est = (b - c) / n
    eps = 1e-12
    lo_end, hi_end = -1.0 + eps, 1.0 - eps
    # lower limit: T(d) = z for d <= est; upper limit: T(d) = -z for d >= est
    lower = lo_end if score_stat(b, c, n, lo_end) <= z else _root(lambda d: score_stat(b, c, n, d) - z, lo_end, est)
    upper = hi_end if score_stat(b, c, n, hi_end) >= -z else _root(lambda d: score_stat(b, c, n, d) + z, est, hi_end)
    return max(-1.0, lower), min(1.0, upper)


def tost_score(b, c, n, margin, alpha=0.05):
    if not 0 < margin < 1:
        raise AnalysisError("the equivalence margin is a proportion in (0, 1)")
    t_low, t_up = score_stat(b, c, n, -margin), score_stat(b, c, n, margin)
    p_low = 1.0 - _N.cdf(t_low) if math.isfinite(t_low) else (0.0 if t_low > 0 else 1.0)
    p_up = _N.cdf(t_up) if math.isfinite(t_up) else (0.0 if t_up < 0 else 1.0)
    lo, hi = score_ci(b, c, n, 1.0 - 2.0 * alpha)
    p = max(p_low, p_up)
    return {"b": b, "c": c, "n": n, "estimate": (b - c) / n, "margin": margin, "alpha": alpha,
            "t_lower": t_low, "t_upper": t_up, "p_lower": p_low, "p_upper": p_up, "p": p,
            "ci": [lo, hi], "ci_level": 1.0 - 2.0 * alpha, "equivalent": p < alpha,
            "ci_inside_margin": -margin < lo and hi < margin}


def tost_bootstrap(diff_strata, margin, alpha, n_boot, seed):
    boots = PA.bootstrap_mean_diff(diff_strata, n_boot, seed)
    lo, hi = PA.percentile_ci(boots, 1.0 - 2.0 * alpha)
    return {"ci": [lo, hi], "ci_level": 1.0 - 2.0 * alpha, "n_boot": n_boot, "seed": seed,
            "equivalent": -margin < lo and hi < margin}


def tost_labels(matrix, a, b, model, margin, outcome, bench_of, reference_kind, alpha, n_boot, seed, scope="pooled"):
    field, tier = PA.outcome_field(outcome, reference_kind)
    pa, ka = PA.per_case(matrix.select(model, a), field, tier)
    pb, kb = PA.per_case(matrix.select(model, b), field, tier)
    cases = sorted(c for c, bm in bench_of.items() if scope == "pooled" or bm == scope)
    missing = [c for c in cases if c not in pa or c not in pb]
    if missing:
        raise AnalysisError(f"{len(missing)} case(s) of the analysis set lack a value in one of the two labels")
    strata = {}
    for c in cases:
        strata.setdefault(bench_of[c] if scope == "pooled" else scope, []).append(pa[c] - pb[c])
    boot = tost_bootstrap([strata[s] for s in sorted(strata)], margin, alpha, n_boot, seed)
    binary = all(pa[c] in (0.0, 1.0) and pb[c] in (0.0, 1.0) for c in cases)
    out = {"model": model, "a": a, "b": b, "outcome": outcome, "scope": scope, "n": len(cases), "bootstrap": boot,
           "max_repeats": max(max(ka[c], kb[c]) for c in cases)}
    if binary:
        bb = sum(1 for c in cases if pa[c] > pb[c])
        cc = sum(1 for c in cases if pa[c] < pb[c])
        sc = tost_score(bb, cc, len(cases), margin, alpha)
        out["score"] = sc
        out["equivalent"] = sc["equivalent"]
        out["methods_agree"] = sc["equivalent"] == boot["equivalent"]
    else:
        out["score"] = None
        out["equivalent"] = boot["equivalent"]
        out["methods_agree"] = None
        out["note"] = "several repeats per case: the score test needs one binary outcome per case; bootstrap only"
    return out


def run(args, matrix=None, aset=None, prereg=None):
    pr = prereg or PR.load(args.prereg)
    if matrix is None:
        reg = RG.load_registry(args.registry, superseded_path=args.superseded)
        matrix = RG.build_matrix(reg, labels=[args.a, args.b], models=args.models)
    dev = matrix.label == "DEV"
    margin = pr.get("tost_margin", allow_pending=dev, override=args.margin)
    tost_cfg = pr.get("tost", allow_pending=dev)
    alpha = tost_cfg.get("alpha", 0.05)
    boot = pr.get("bootstrap", allow_pending=dev)
    if aset is None:
        name = RG.set_name_for(matrix.label, args.set, args.incl_0905)
        aset = RG.resolve_set(name, allow_pending=args.allow_pending and dev)
    m = RG.restrict(matrix, aset)
    bench_of = RG.bench_map(aset)
    res = [tost_labels(m, args.a, args.b, model, margin, args.outcome, bench_of, aset["reference"], alpha,
                       args.n_boot or boot["n_boot"], boot["seed"] if args.seed is None else args.seed, args.scope)
           for model in (args.models or m.models())]
    return {"schema": SCHEMA, "data": m.label, "generated_by": "analysis/r1/tost.py", "margin": margin, "alpha": alpha,
            "analysis_set": m.header["analysis_set"], "prereg": pr.provenance(),
            "inputs": {k: m.header[k] for k in ("registry", "runs", "freeze_gate")}, "results": res}


def render_md(doc):
    lines = [md_header(f"Equivalence (TOST), margin ±{100 * doc['margin']:.1f} points, alpha {doc['alpha']}", doc["data"]),
             "| model | a vs b | scope | n | estimate (pp) | score 90% CI (pp) | TOST p | bootstrap 90% CI (pp) | equivalent | methods agree |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in doc["results"]:
        s, bt = r["score"], r["bootstrap"]
        sc = f"[{signed_pp(s['ci'][0])}, {signed_pp(s['ci'][1])}]" if s else "–"
        tp = f"{s['p']:.4f}" if s else "–"
        lines.append(f"| {r['model']} | {r['a']} vs {r['b']} | {r['scope']} | {r['n']} | "
                     f"{signed_pp(s['estimate']) if s else '–'} | {sc} | {tp} | "
                     f"[{signed_pp(bt['ci'][0])}, {signed_pp(bt['ci'][1])}] | {r['equivalent']} | {r['methods_agree']} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--registry", default=RG.DEFAULT_REGISTRY)
    ap.add_argument("--superseded", default=RG.DEFAULT_SUPERSEDED)
    ap.add_argument("--prereg", default=PR.DEFAULT_PATH)
    ap.add_argument("--set", default=None)
    ap.add_argument("--incl-0905", action="store_true")
    ap.add_argument("--allow-pending", action="store_true")
    ap.add_argument("--outcome", default="correct")
    ap.add_argument("--scope", default="pooled")
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--margin", type=float, default=None, help="dev only, while tost_margin is pending")
    ap.add_argument("--n-boot", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    try:
        doc = run(a)
    except AnalysisError as x:
        print(f"[tost] REFUSED: {x}", file=sys.stderr)
        return 2
    md = render_md(doc)
    if a.out:
        out = labelled_path(a.out, doc["data"])
        write_text(out, dumps(doc))
        write_text(os.path.splitext(out)[0] + ".md", md)
        print(f"[tost] {doc['data']}: {len(doc['results'])} rows -> {rel(out)}")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

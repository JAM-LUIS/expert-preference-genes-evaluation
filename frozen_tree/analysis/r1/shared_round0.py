#!/usr/bin/env python3
"""Two configurations that share round 0 (C3L vs C3E; C3L or C3E vs C0; C2E vs C2): identity check, paired test,
decomposition, and the minimum detectable effect under a shared round 0 (E20a; stage-0 report T8 section 3.4).

  $PY analysis/r1/shared_round0.py --a C3L@2 --b C3E@2 --round0-label C0 [--registry ...] [--set main]
      [--round0-check sha | results] [--mde-n pooled=226,mamo_complex_lp=151,industryor=75] --out shared.json

1. Identity. Default (sha): every unit (case, repeat) of A and B, and of the round-0 label when given, must carry a
   round-0 content sha256 (registry: round0_gen_dir, or the unit records) and the shas must be equal; otherwise the
   analysis stops. `--round0-check results` is the fallback for runs without stored answers (the v5 dev copies): every
   unit that A or B did not repair must have exactly the round-0 label's outcome (correct, exec_ok, status, objective,
   output tokens), and the output says that the content sha256 was not checked.
2. Paired test: exact McNemar and the case bootstrap CI (paired.py), per benchmark and pooled.
3. Decomposition: units by repair pattern (both repaired / only A / only B / neither) x outcome triple
   (round 0, A final, B final), from the round-0 label (required for the triple). Units that neither configuration
   repaired must keep the round-0 outcome; a mismatch is counted and reported.
4. MDE under a shared round 0 (T8 scripts/dev_discordance_mde.py, ported unchanged): with the regression rate p01
   (right -> wrong after repair) fixed, the smallest delta = p10 - p01 with exact McNemar power >= 0.80 on a 0.001
   grid, psi = 2 p01 + delta. n = the size of the analysis set per benchmark and pooled (the main set for the test
   design), or --mde-n.
Standard library only.
"""
import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import paired as PA  # noqa: E402
import prereg as PR  # noqa: E402
import registry as RG  # noqa: E402
from common import AnalysisError, dumps, labelled_path, md_header, p4, rel, signed_pp, write_text  # noqa: E402

SCHEMA = "orgene.r1.shared_round0.v1"
RESULT_FIELDS = ("correct", "exec_ok", "status", "objective", "out_tokens")
PATTERNS = ("both_repaired", "only_a_repaired", "only_b_repaired", "neither_repaired")


class SharedRound0Error(AnalysisError):
    """The two configurations do not share round 0."""


# ------------------------------------------------------------------ MDE (ported from T8 dev_discordance_mde.py)


def mcnemar_exact_p(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


_REJ = {}


def reject_table(D, alpha):
    if (D, alpha) not in _REJ:
        _REJ[(D, alpha)] = [mcnemar_exact_p(b, D - b) <= alpha and b > D - b for b in range(D + 1)]
    return _REJ[(D, alpha)]


def binom_pmf_row(n, p):
    if p <= 0:
        return [1.0] + [0.0] * n
    if p >= 1:
        return [0.0] * n + [1.0]
    lp, lq = math.log(p), math.log1p(-p)
    return [math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * lp + (n - k) * lq)
            for k in range(n + 1)]


def exact_power(n, psi, delta, alpha=0.05):
    """Power of the two-sided exact McNemar test (effect in the hypothesised direction), by full enumeration."""
    if delta > psi + 1e-12 or psi <= 0:
        return None
    pi = min(1.0, (psi + delta) / (2 * psi))
    pD = binom_pmf_row(n, min(psi, 1.0))
    pw = 0.0
    for D in range(n + 1):
        if pD[D] < 1e-15:
            continue
        rej = reject_table(D, alpha)
        pb = binom_pmf_row(D, pi)
        pw += pD[D] * sum(pb[b] for b in range(D + 1) if rej[b])
    return pw


def mde_shared_round0(n, p01, alpha=0.05, power=0.80, step=0.001):
    """Smallest delta with exact power >= power when psi = 2 * p01 + delta (regression rate p01 fixed)."""
    d = step
    while d <= 1 - 2 * p01:
        pw = exact_power(n, 2 * p01 + d, d, alpha)
        if pw is not None and pw >= power:
            return d, pw
        d = round(d + step, 6)
    return None, None


def mde_table(n_by_scope, p01_grid, alpha=0.05, power=0.80, step=0.001):
    rows = []
    for p01 in p01_grid:
        for scope, n in n_by_scope.items():
            d, pw = mde_shared_round0(n, p01, alpha, power, step)
            rows.append({"p01_regression_rate": p01, "scope": scope, "n": n,
                         "mde": round(d, 4) if d else None, "implied_psi": round(2 * p01 + d, 4) if d else None,
                         "power_at_mde": round(pw, 3) if pw else None})
    return rows


# ------------------------------------------------------------------ identity check


def _units(rows):
    return {(r["case_id"], r["repeat"]): r for r in rows}


def check_identity_sha(ua, ub, ur=None):
    keys = sorted(set(ua) | set(ub) | (set(ur) if ur else set()))
    missing = [k for k in keys if k not in ua or k not in ub or (ur is not None and k not in ur)]
    if missing:
        raise SharedRound0Error(f"{len(missing)} unit(s) are not in every label (first: {missing[:3]})")
    no_sha = [k for k in keys if not ua[k].get("round0_content_sha256") or not ub[k].get("round0_content_sha256")
              or (ur is not None and not ur[k].get("round0_content_sha256"))]
    if no_sha:
        raise SharedRound0Error(f"{len(no_sha)} unit(s) have no round-0 content sha256 (register round0_gen_dir, or "
                                "use --round0-check results for runs without stored answers)")
    diff = [k for k in keys if ua[k]["round0_content_sha256"] != ub[k]["round0_content_sha256"]
            or (ur is not None and ur[k]["round0_content_sha256"] != ua[k]["round0_content_sha256"])]
    if diff:
        raise SharedRound0Error(f"round 0 differs on {len(diff)} of {len(keys)} unit(s) (first: {diff[:3]}); these "
                                "configurations do not share round 0")
    return {"mode": "sha", "n_units": len(keys), "verified": "round-0 content sha256 equal on every unit"}


def check_identity_results(ua, ub, ur):
    if ur is None:
        raise SharedRound0Error("--round0-check results needs --round0-label (the configuration whose answers are the "
                                "shared round 0)")
    keys = sorted(set(ua) | set(ub) | set(ur))
    missing = [k for k in keys if k not in ua or k not in ub or k not in ur]
    if missing:
        raise SharedRound0Error(f"{len(missing)} unit(s) are not in every label (first: {missing[:3]})")
    bad = []
    n_checked = 0
    for k in keys:
        for u in (ua[k], ub[k]):
            if (u.get("repair_rounds_used") or 0) == 0:
                n_checked += 1
                if any(u.get(f) != ur[k].get(f) for f in RESULT_FIELDS):
                    bad.append(k)
    if bad:
        raise SharedRound0Error(f"{len(bad)} unrepaired unit(s) differ from the round-0 label's outcome "
                                f"(first: {bad[:3]}); these configurations do not share round 0")
    return {"mode": "results", "n_units": len(keys), "n_unrepaired_checked": n_checked,
            "verified": "results-consistent: every unrepaired unit has the round-0 outcome; the round-0 content "
                        "sha256 was NOT checked (not available for these runs)"}


# ------------------------------------------------------------------ decomposition


def decompose(ua, ub, ur):
    table = {p: {} for p in PATTERNS}
    mismatch = 0
    for k in sorted(ua):
        a, b = ua[k], ub[k]
        ra, rb = (a.get("repair_rounds_used") or 0) > 0, (b.get("repair_rounds_used") or 0) > 0
        pat = PATTERNS[0] if ra and rb else PATTERNS[1] if ra else PATTERNS[2] if rb else PATTERNS[3]
        r0 = int(bool(ur[k]["correct"])) if ur is not None else None
        tri = f"r0={'-' if r0 is None else r0} a={int(bool(a['correct']))} b={int(bool(b['correct']))}"
        table[pat][tri] = table[pat].get(tri, 0) + 1
        if pat == "neither_repaired" and r0 is not None and not (int(a["correct"]) == int(b["correct"]) == r0):
            mismatch += 1
    summary = {}
    for p in PATTERNS:
        t = table[p]
        summary[p] = {"n": sum(t.values()),
                      "a_only_right": sum(v for k, v in t.items() if "a=1 b=0" in k),
                      "b_only_right": sum(v for k, v in t.items() if "a=0 b=1" in k)}
    return {"table": {p: dict(sorted(t.items())) for p, t in table.items()}, "summary": summary,
            "n_unrepaired_outcome_mismatch": mismatch}


# ------------------------------------------------------------------ run


def parse_mde_n(text):
    out = {}
    for part in (text or "").split(","):
        if part.strip():
            k, _, v = part.partition("=")
            out[k.strip()] = int(v)
    return out


def analyse(matrix, a, b, model, round0_label=None, check="sha", bench_of=None, reference_kind="r1",
            n_boot=10000, seed=1, level=0.95):
    ra, rb = matrix.select(model, a), matrix.select(model, b)
    ur = _units(matrix.select(model, round0_label)) if round0_label else None
    ua, ub = _units(ra), _units(rb)
    if bench_of is not None:
        keep = set(bench_of)
        ua = {k: v for k, v in ua.items() if k[0] in keep}
        ub = {k: v for k, v in ub.items() if k[0] in keep}
        ur = {k: v for k, v in ur.items() if k[0] in keep} if ur is not None else None
    ident = check_identity_sha(ua, ub, ur) if check == "sha" else check_identity_results(ua, ub, ur)
    tests = PA.compare(matrix, a, b, model, "correct", bench_of, reference_kind, n_boot, seed, level)
    for t in tests:
        t.pop("_exact", None)
    return {"model": model, "a": a, "b": b, "round0_label": round0_label, "round0_identity": ident,
            "tests": tests, "decomposition": decompose(ua, ub, ur)}


def run(args, matrix=None, aset=None, prereg=None):
    pr = prereg or PR.load(args.prereg)
    labels = [args.a, args.b] + ([args.round0_label] if args.round0_label else [])
    if matrix is None:
        reg = RG.load_registry(args.registry, superseded_path=args.superseded)
        matrix = RG.build_matrix(reg, labels=labels, models=args.models)
    dev = matrix.label == "DEV"
    boot = pr.get("bootstrap", allow_pending=dev)
    mde_cfg = pr.get("shared_round0_mde", allow_pending=dev)
    if aset is None:
        name = RG.set_name_for(matrix.label, args.set, args.incl_0905)
        aset = RG.resolve_set(name, allow_pending=args.allow_pending and dev)
    m = RG.restrict(matrix, aset)
    bench_of = RG.bench_map(aset)
    res = [analyse(m, args.a, args.b, model, args.round0_label, args.round0_check, bench_of, aset["reference"],
                   args.n_boot or boot["n_boot"], boot["seed"] if args.seed is None else args.seed,
                   boot.get("ci_level", 0.95))
           for model in (args.models or m.models())]
    n_by = parse_mde_n(args.mde_n)
    n_source = "command line (--mde-n)"
    if not n_by:
        # the MDE is for the design: n = the main analysis set of the test split (sizes only)
        design = RG.resolve_set(args.mde_set, allow_pending=args.allow_pending and dev)
        n_by = {b: len(v) for b, v in sorted(design["by_benchmark"].items())}
        if len(n_by) > 1:
            n_by = dict({"pooled": design["n"]}, **n_by)
        n_source = f"analysis set {design['name']} (sizes only)" + (f"; pending {design['pending']}" if design["pending"] else "")
    mde = mde_table(n_by, mde_cfg["p01_grid"], mde_cfg["alpha"], mde_cfg["power"], mde_cfg.get("step", 0.001))
    return {"schema": SCHEMA, "data": m.label, "generated_by": "analysis/r1/shared_round0.py",
            "analysis_set": m.header["analysis_set"], "prereg": pr.provenance(),
            "inputs": {k: m.header[k] for k in ("registry", "runs", "freeze_gate")}, "results": res,
            "mde": {"method": "T8 scripts/dev_discordance_mde.py (shared round 0; exact McNemar power by enumeration)",
                    "n_source": n_source, "alpha": mde_cfg["alpha"], "power": mde_cfg["power"], "rows": mde}}


def render_md(doc):
    lines = [md_header("Shared round 0: identity, paired test, decomposition, MDE", doc["data"])]
    for r in doc["results"]:
        lines += ["", f"## {r['model']}: {r['a']} vs {r['b']} (round 0 = {r['round0_label'] or 'not given'})", "",
                  f"Round-0 identity ({r['round0_identity']['mode']}): {r['round0_identity']['verified']}.", "",
                  "| scope | n | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |", "|---|---|---|---|---|---|"]
        for t in r["tests"]:
            lines.append(f"| {t['scope']} | {t['n']} | {signed_pp(t['diff'])} | [{signed_pp(t['ci'][0])}, "
                         f"{signed_pp(t['ci'][1])}] | {t['wins']}/{t['ties']}/{t['losses']} | {p4(t['mcnemar_exact_p'])} |")
        lines += ["", "| repair pattern | n | A only right | B only right | outcome triples (r0, A, B) |", "|---|---|---|---|---|"]
        for p in PATTERNS:
            s = r["decomposition"]["summary"][p]
            trip = "; ".join(f"{k}: {v}" for k, v in r["decomposition"]["table"][p].items())
            lines.append(f"| {p} | {s['n']} | {s['a_only_right']} | {s['b_only_right']} | {trip} |")
    lines += ["", f"## MDE under a shared round 0 ({doc['mde']['n_source']})", "",
              "| p01 | scope | n | MDE (pp) | power |", "|---|---|---|---|---|"]
    for row in doc["mde"]["rows"]:
        mde = "not attainable" if row["mde"] is None else f"{100 * row['mde']:.1f}"
        lines.append(f"| {row['p01_regression_rate']} | {row['scope']} | {row['n']} | {mde} | {row['power_at_mde']} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--round0-label", default=None)
    ap.add_argument("--round0-check", choices=["sha", "results"], default="sha")
    ap.add_argument("--registry", default=RG.DEFAULT_REGISTRY)
    ap.add_argument("--superseded", default=RG.DEFAULT_SUPERSEDED)
    ap.add_argument("--prereg", default=PR.DEFAULT_PATH)
    ap.add_argument("--set", default=None)
    ap.add_argument("--incl-0905", action="store_true")
    ap.add_argument("--allow-pending", action="store_true")
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--mde-n", default=None, help="scope=n,...; default: sizes of --mde-set")
    ap.add_argument("--mde-set", default="main", help="analysis set whose sizes give the MDE's n (default main)")
    ap.add_argument("--n-boot", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    try:
        doc = run(a)
    except AnalysisError as x:
        print(f"[shared_round0] REFUSED: {x}", file=sys.stderr)
        return 2
    md = render_md(doc)
    if a.out:
        out = labelled_path(a.out, doc["data"])
        write_text(out, dumps(doc))
        write_text(os.path.splitext(out)[0] + ".md", md)
        print(f"[shared_round0] {doc['data']} -> {rel(out)}")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""End-to-end regression of the analysis core: reproduce the stage-0 report T8, tables 2.1 and 2.2 (and the pooled
execution line after table 2.2, and table 3.4), from the v5 dev results copied into reference/v5_dev_results (E20a).

  $PY analysis/r1/t8_repro.py [--fixture reference/v5_dev_results] [--skip-mde] [--out t8_repro.json]

Dev data only (85 dev cases: MAMO 60 + IndustryOR 25; qwen3:8b; 12 v5 run labels). The path through the code is
the one every analysis takes: registry.json -> registry.build_matrix (hash, split and membership checks) ->
analysis set dev_all85 (runtime/orgene/analysis_sets.py) -> paired.compare / per-label summaries. Checks:
  metrics      per label and benchmark, accuracy and execution rate equal the pipeline's own metrics.<C>.json
  per_case     correct / exec per case and label equal T8's dev_per_case_matrix.csv
  table_2_1    every cell: accuracy and execution rate with counts (pooled, MAMO, IndustryOR), mean output tokens,
               mean calls
  table_2_2    every row: A-only / B-only counts, discordance with its Wilson 95% interval, difference, exact McNemar
               p, and the per-benchmark cells
  exec_line    the pooled execution-rate comparisons printed after table 2.2
  table_3_4    MDE under a shared round 0 for the T8 test sizes (226 / 151 / 75); --skip-mde skips it (slow part)
The expected cells are copied verbatim from the report (t8_expected.json, with the report's sha256); each cell is
compared at the precision the report prints. Exit code 0 when every cell matches, 1 otherwise.
"""
import argparse
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import paired as PA  # noqa: E402
import registry as RG  # noqa: E402
import shared_round0 as SR  # noqa: E402
from common import ROOT, AnalysisError, dumps, labelled_path, md_header, rel, resolve, write_text  # noqa: E402

SCHEMA = "orgene.r1.t8_repro.v1"
FIXTURE = "reference/v5_dev_results"
DEV_SET = "dev_all85"
BENCHES = ("mamo_complex_lp", "industryor")
T8_TEST_N = {"pooled": 226, "mamo_complex_lp": 151, "industryor": 75}   # T8 section 3.1 (SPLIT_LOCK n_test)

_PCT_COUNT = re.compile(r"^([\d.]+)%（(\d+)/(\d+)）$")
_PCT = re.compile(r"^([\d.]+)%$")
_PAIR_LABEL = re.compile(r"^(\S+) 对 (\S+)")
_BENCH_CELL = re.compile(r"^(\d+)/(\d+)(?:，([\d.]+)%，([+−][\d.]+))?$")
_PSI = re.compile(r"^([\d.]+)%（([\d.]+)%–([\d.]+)%）$")
_EXEC = re.compile(r"([A-Za-z0-9_]+) 对 ([A-Za-z0-9_]+) 为 (\d+) / (\d+)（ψ ([\d.]+)%，([+−][\d.]+)）")


def _clean(s):
    return s.replace("**", "").strip()


# T8's display convention: its scripts rounded proportions to 4 decimals and p-values to 5 decimals (CSV tables),
# and the report printed those rounded values with one decimal (percent) or four decimals (p). The numbers compared
# here are computed unrounded; only the printing follows the report. Printing the unrounded values directly would
# differ in the last digit in three cells (two p-values ending in 5 at the fifth decimal, one Wilson bound).


def _pct(k, n):
    return f"{100.0 * round(k / n, 4):.1f}"


def _pctx(x):
    return f"{100.0 * round(x, 4):.1f}"


def _pp(x):
    return PA.signed_pp(round(x, 4))


def _p(p):
    return "<0.0001" if p < 0.0001 else f"{round(p, 5):.4f}"


class Checker:
    def __init__(self):
        self.checks = []

    def eq(self, table, row, cell, expected, got):
        ok = str(expected) == str(got)
        self.checks.append({"table": table, "row": row, "cell": cell, "expected": str(expected), "got": str(got),
                            "ok": ok})
        return ok

    def summary(self):
        by = {}
        for c in self.checks:
            t = by.setdefault(c["table"], {"n": 0, "mismatches": 0})
            t["n"] += 1
            t["mismatches"] += not c["ok"]
        return by


def load(root=None, fixture=FIXTURE):
    root = root or ROOT
    reg = RG.load_registry(os.path.join(fixture, "registry.json"), root=root)
    m = RG.build_matrix(reg, root)
    if m.label != "DEV":
        raise AnalysisError("the T8 fixture must be dev data")
    aset = RG.resolve_set(DEV_SET, root=root)
    return reg, RG.restrict(m, aset), aset


def label_summary(m, label, model="qwen3:8b"):
    rows = m.select(model, label)
    out = {}
    for scope in ("pooled",) + BENCHES:
        rs = [r for r in rows if scope == "pooled" or r["benchmark"] == scope]
        n = len(rs)
        out[scope] = {"n": n, "k": sum(r["correct"] for r in rs), "e": sum(r["exec_ok"] for r in rs),
                      "out": sum(r["out_tokens"] or 0 for r in rs) / n, "calls": sum(r["n_calls"] or 1 for r in rs) / n}
    return out


def check_metrics(ck, reg, m, root):
    for e in reg.runs:
        mp = os.path.join(resolve(e["path"], root), f"metrics.{e['config']}.json")
        met = json.load(open(mp, encoding="utf-8"))
        rows = [r for r in m.select(e["model"], e["label"]) if r["benchmark"] == e["benchmark"]]
        n = len(rows)
        acc = sum(r["correct"] for r in rows) / n
        ex = sum(r["exec_ok"] for r in rows) / n
        ck.eq("metrics", f"{e['label']}/{e['benchmark']}", "accuracy", round(met["accuracy"], 3), round(acc, 3))
        ck.eq("metrics", f"{e['label']}/{e['benchmark']}", "exec_rate", round(met["exec_rate"], 3), round(ex, 3))


def check_per_case(ck, m, fixture_dir):
    path = os.path.join(fixture_dir, "t8_dev_per_case_matrix.csv")
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    labels = sorted({k[:-len("_correct")] for k in rows[0] if k.endswith("_correct")})
    got = {(r["label"], r["case_id"]): r for r in m.rows}
    n_ok = n = 0
    for row in rows:
        for l in labels:
            g = got.get((l, row["case_id"]))
            for fld, key in (("correct", f"{l}_correct"), ("exec_ok", f"{l}_exec")):
                n += 1
                n_ok += g is not None and int(bool(g[fld])) == int(row[key])
    ck.eq("per_case", "all labels", "cells equal", n, n_ok)
    ck.eq("per_case", "all labels", "cases", len(rows), len({r["case_id"] for r in m.rows}))


def check_table_2_1(ck, m, exp):
    for row in exp["table_2_1"]["rows"]:
        label = re.sub(r"（.*?）", "", _clean(row[0])).strip()
        s = label_summary(m, label)
        p, mm, io = s["pooled"], s["mamo_complex_lp"], s["industryor"]
        ck.eq("2.1", label, "pooled accuracy", row[1], f"{_pct(p['k'], p['n'])}%（{p['k']}/{p['n']}）")
        ck.eq("2.1", label, "pooled exec rate", row[2], f"{_pct(p['e'], p['n'])}%（{p['e']}/{p['n']}）")
        ck.eq("2.1", label, "MAMO accuracy / exec", row[3],
              f"{_pct(mm['k'], mm['n'])}%（{mm['k']}/{mm['n']}） / {_pct(mm['e'], mm['n'])}%")
        ck.eq("2.1", label, "IndustryOR accuracy / exec", row[4],
              f"{_pct(io['k'], io['n'])}%（{io['k']}/{io['n']}） / {_pct(io['e'], io['n'])}%")
        ck.eq("2.1", label, "mean output tokens", float(row[5]), round(p["out"], 1))
        ck.eq("2.1", label, "mean calls", float(row[6]), round(p["calls"], 3))


def _pair_cells(r):
    return r["a_only_right"], r["b_only_right"]


def check_table_2_2(ck, m, bench_of, exp):
    for row in exp["table_2_2"]["rows"]:
        lab = _PAIR_LABEL.match(_clean(row[0]))
        a, b = lab.group(1), re.sub(r"（.*$", "", lab.group(2))
        res = {r["scope"]: r for r in PA.compare(m, a, b, "qwen3:8b", "correct", bench_of, n_boot=1)}
        p = res["pooled"]
        name = f"{a} vs {b}"
        ck.eq("2.2", name, "A only / B only", _clean(row[1]), f"{p['a_only_right']} / {p['b_only_right']}")
        n = p["n"]
        lo, hi = PA.wilson(p["a_only_right"] + p["b_only_right"], n)
        ck.eq("2.2", name, "discordance (Wilson 95%)", _clean(row[2]),
              f"{_pct(p['a_only_right'] + p['b_only_right'], n)}%（{_pctx(lo)}%–{_pctx(hi)}%）")
        ck.eq("2.2", name, "difference", _clean(row[3]), _pp((p["a_only_right"] - p["b_only_right"]) / n))
        ck.eq("2.2", name, "exact McNemar p", _clean(row[4]), _p(p["mcnemar_exact_p"]))
        for col, scope in ((5, "mamo_complex_lp"), (6, "industryor")):
            want = _BENCH_CELL.match(_clean(row[col]))
            r = res[scope]
            b10, b01, nn = r["a_only_right"], r["b_only_right"], r["n"]
            if want.group(3) is None:       # the report prints only the counts when both are 0
                ck.eq("2.2", name, f"{scope} counts", _clean(row[col]), f"{b10}/{b01}")
            else:
                ck.eq("2.2", name, f"{scope} counts, discordance, difference", _clean(row[col]),
                      f"{b10}/{b01}，{_pct(b10 + b01, nn)}%，{_pp((b10 - b01) / nn)}")


def check_exec_line(ck, m, bench_of, exp):
    for a, b, x10, x01, psi, diff in _EXEC.findall(exp["exec_pooled_line"]):
        p = {r["scope"]: r for r in PA.compare(m, a, b, "qwen3:8b", "exec_ok", bench_of, n_boot=1)}["pooled"]
        n = p["n"]
        ck.eq("exec_line", f"{a} vs {b}", "exec A only / B only, discordance, difference",
              f"{x10} / {x01}（ψ {psi}%，{diff}）",
              f"{p['a_only_right']} / {p['b_only_right']}（ψ {_pct(p['a_only_right'] + p['b_only_right'], n)}%，"
              f"{_pp((p['a_only_right'] - p['b_only_right']) / n)}）")


def _p01(label):
    s = _clean(label)
    if s.startswith("0（"):
        return 0.0
    return float(s.rstrip("%")) / 100.0


def check_table_3_4(ck, exp, fixture_dir):
    head = exp["table_3_4"]["header"]
    scopes = ["pooled", "mamo_complex_lp", "industryor"]
    if len(head) != 4:
        raise AnalysisError("table 3.4 of the expected file has an unexpected layout")
    got = {}
    for row in exp["table_3_4"]["rows"]:
        p01 = _p01(row[0])
        for col, scope in zip(row[1:], scopes):
            d, pw = SR.mde_shared_round0(T8_TEST_N[scope], p01)
            got[(p01, scope)] = (d, pw)
            ck.eq("3.4", f"p01={p01}", scope, _clean(col), f"{100 * d:.1f}")
    # unrounded values of T8's CSV (mde on the 0.001 grid, power at the mde)
    with open(os.path.join(fixture_dir, "t8_mde_shared_round0.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d, pw = got[(float(r["p01_regression_rate"]), r["scope"])]
            ck.eq("3.4_csv", f"p01={r['p01_regression_rate']}", f"{r['scope']} mde, power",
                  f"{float(r['mde_exact_mcnemar'])}, {float(r['exact_power_at_mde'])}", f"{round(d, 4)}, {round(pw, 3)}")


def reproduce(root=None, fixture=FIXTURE, skip_mde=False):
    root = root or ROOT
    fixture_dir = resolve(fixture, root)
    exp = json.load(open(os.path.join(fixture_dir, "t8_expected.json"), encoding="utf-8"))
    reg, m, aset = load(root, fixture)
    bench_of = RG.bench_map(aset)
    ck = Checker()
    check_metrics(ck, reg, m, root)
    check_per_case(ck, m, fixture_dir)
    check_table_2_1(ck, m, exp)
    check_table_2_2(ck, m, bench_of, exp)
    check_exec_line(ck, m, bench_of, exp)
    if not skip_mde:
        check_table_3_4(ck, exp, fixture_dir)
    summ = ck.summary()
    return {"schema": SCHEMA, "data": m.label, "generated_by": "analysis/r1/t8_repro.py",
            "expected_source": {"file": rel(os.path.join(fixture_dir, "t8_expected.json"), root),
                                "report_sha256": exp.get("source_sha256")},
            "analysis_set": m.header["analysis_set"], "registry": m.header["registry"],
            "n_labels": len(m.groups()), "n_rows": len(m.rows), "summary": summ,
            "all_match": all(c["ok"] for c in ck.checks), "checks": ck.checks}


def render_md(doc):
    lines = [md_header("Reproduction of the stage-0 report T8, tables 2.1 and 2.2 (and 3.4)", doc["data"]),
             f"Analysis set {doc['analysis_set']['name']} ({doc['analysis_set']['n']} dev cases), {doc['n_labels']} labels, "
             f"{doc['n_rows']} rows. All cells match: **{doc['all_match']}**.", "",
             "| check | cells | mismatches |", "|---|---|---|"]
    lines += [f"| {t} | {v['n']} | {v['mismatches']} |" for t, v in doc["summary"].items()]
    bad = [c for c in doc["checks"] if not c["ok"]]
    if bad:
        lines += ["", "| table | row | cell | expected | got |", "|---|---|---|---|---|"]
        lines += [f"| {c['table']} | {c['row']} | {c['cell']} | {c['expected']} | {c['got']} |" for c in bad]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixture", default=FIXTURE)
    ap.add_argument("--skip-mde", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    try:
        doc = reproduce(fixture=a.fixture, skip_mde=a.skip_mde)
    except AnalysisError as x:
        print(f"[t8_repro] REFUSED: {x}", file=sys.stderr)
        return 2
    md = render_md(doc)
    if a.out:
        out = labelled_path(a.out, doc["data"])
        write_text(out, dumps(doc))
        write_text(os.path.splitext(out)[0] + ".md", md)
    sys.stdout.write(md)
    return 0 if doc["all_match"] else 1


if __name__ == "__main__":
    sys.exit(main())

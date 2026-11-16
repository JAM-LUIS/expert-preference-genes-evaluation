#!/usr/bin/env python3
"""Per-case failure table for a dev run, so the error taxonomy can be filled in by hand.

  python3 analysis/dev_failures.py --run experiments/<run-id> [--run ...] --cond C0 C2 \
      [--cases data/cases/*.jsonl] [--flags data/mamo_underspecified_ids.json] [--out <path>]

Reads, per RUN and condition:
  validated.<COND>.round0.jsonl   round-0 validation (issues, exec, spec)
  results.<COND>.jsonl            scoring (correct, reason, objective vs reference)
and writes one markdown table row per case, plus a taxonomy tally stub.

The taxonomy itself is filled in by a human: the script only supplies the evidence and an
empty `category` column. Categories (see HANDOFF / RECORDS):
  missing_constraint | objective_sense | integrality | bigm_linearization | data_misread
  | infeasible_unbounded | code_error | protocol_error | underspecified | other
`underspecified` cases are excluded from gene derivation.
"""
import argparse
import json
import os
import sys

# C0/C1 produce no spec, so the spec-class predicates fail by construction there and carry no
# information. Only these code-level genes are meaningful for the specless conditions
# (see HANDOFF 已知坑).
CODE_LEVEL_GENES = {
    "orgene.artifact.code_present",
    "orgene.boundary.solve_before_report",
    "orgene.boundary.status_reported",
    "orgene.execution.runs",
    "orgene.solution.status_optimal_or_justified",
    "orgene.data.no_invented_numbers",
    "orgene.numeric.bigm_bounded",
}
SPECLESS_CONDITIONS = {"C0", "C1"}

CATEGORIES = [
    ("missing_constraint", "漏约束"),
    ("objective_sense", "目标方向反"),
    ("integrality", "整数性丢失"),
    ("bigm_linearization", "big-M 或线性化错"),
    ("data_misread", "数据读错或编造"),
    ("infeasible_unbounded", "不可行/无界"),
    ("code_error", "代码运行错"),
    ("protocol_error", "输出协议错"),
    ("underspecified", "欠定题（不可修）"),
    ("other", "其他"),
]


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("_header"):
                continue
            out.append(rec)
    return out


def load_cases(paths):
    cases = {}
    for p in paths:
        for rec in read_jsonl(p):
            cases[rec["case_id"]] = rec
    return cases


def load_flags(path):
    """case_id -> list of matched keywords, from the frozen under-specification screen."""
    if not path or not os.path.exists(path):
        return {}
    doc = json.load(open(path, "r", encoding="utf-8"))
    flags = {}
    for src in doc.get("sources", {}).values():
        for hit in src.get("flagged", []):
            flags[hit["case_id"]] = hit.get("matched", [])
    return flags


def stderr_head(rec, n=3):
    tail = ((rec.get("exec") or {}).get("stderr_tail") or "").strip()
    if not tail:
        return ""
    lines = [l.strip() for l in tail.splitlines() if l.strip()]
    # the last lines of a traceback carry the actual exception; keep those
    return " ⏎ ".join(lines[-n:])


def cell(s, width=None):
    s = "" if s is None else str(s)
    s = s.replace("|", "\\|").replace("\n", " ").strip()
    if width and len(s) > width:
        s = s[: width - 1] + "…"
    return s


def fmt_num(x):
    if x is None:
        return ""
    if isinstance(x, float) and x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return str(x)


def collect(run, cond, cases, flags):
    validated = {r["case_id"]: r for r in read_jsonl(os.path.join(run, f"validated.{cond}.round0.jsonl"))}
    results = read_jsonl(os.path.join(run, f"results.{cond}.jsonl"))
    rows = []
    for res in results:
        cid = res["case_id"]
        v = validated.get(cid, {})
        issues = v.get("issues", [])
        hard = sorted({i["geneId"] for i in issues if not i.get("ok") and i.get("severity") == "hard"})
        soft = sorted({i["geneId"] for i in issues if not i.get("ok") and i.get("severity") == "soft"})
        n_spec_only = 0
        if cond in SPECLESS_CONDITIONS:
            # drop the spec-class failures that are guaranteed for a condition with no spec
            n_spec_only = len([g for g in hard if g not in CODE_LEVEL_GENES])
            hard = [g for g in hard if g in CODE_LEVEL_GENES]
            soft = [g for g in soft if g in CODE_LEVEL_GENES]
        ex = v.get("exec") or {}
        rows.append({
            "source": res.get("source"),
            "case_id": cid,
            "condition": cond,
            "run": os.path.basename(run.rstrip("/")),
            "correct": bool(res.get("correct")),
            "reason": res.get("reason"),
            "status": res.get("status"),
            "objective": res.get("objective"),
            "reference": res.get("reference_objective"),
            "exec_ok": res.get("exec_ok"),
            "protocol_ok": res.get("protocol_ok"),
            "timed_out": bool(ex.get("timed_out")),
            "hard": hard,
            "soft": soft,
            "stderr": stderr_head(v),
            "out_tokens": res.get("out_tokens"),
            "n_calls": res.get("n_calls"),
            "flagged": flags.get(cid, []),
            "spec_genes_suppressed": n_spec_only,
        })
    rows.sort(key=lambda r: (r["source"] or "", r["case_id"]))
    return rows


def summarize(rows):
    by = {}
    for r in rows:
        k = (r["source"], r["condition"])
        d = by.setdefault(k, {"n": 0, "correct": 0, "exec_ok": 0, "protocol_ok": 0, "timed_out": 0,
                              "out_tokens": 0, "n_calls": 0})
        d["n"] += 1
        d["correct"] += r["correct"]
        d["exec_ok"] += bool(r["exec_ok"])
        d["protocol_ok"] += bool(r["protocol_ok"])
        d["timed_out"] += bool(r["timed_out"])
        d["out_tokens"] += r["out_tokens"] or 0
        d["n_calls"] += r["n_calls"] or 0
    return by


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="experiments/<run-id> (repeatable)")
    ap.add_argument("--cond", nargs="+", required=True)
    ap.add_argument("--cases", nargs="*", default=[])
    ap.add_argument("--flags", default="data/mamo_underspecified_ids.json")
    ap.add_argument("--out", default=None, help="default: <first run>/dev_failures.md")
    ap.add_argument("--all", action="store_true", help="list every case, not only the wrong ones")
    args = ap.parse_args()

    cases = load_cases(args.cases)
    flags = load_flags(args.flags)

    rows = []
    for run in args.run:
        for cond in args.cond:
            got = collect(run, cond, cases, flags)
            if not got:
                print(f"[warn] no results for {run} {cond}", file=sys.stderr)
            rows += got
    if not rows:
        sys.exit("no rows; check --run / --cond")

    out = args.out or os.path.join(args.run[0], "dev_failures.md")
    summary = summarize(rows)

    with open(out, "w", encoding="utf-8") as f:
        f.write("# dev 逐题失败表\n\n")
        f.write("RUN：" + "、".join(f"`{r}`" for r in args.run) + f"；条件：{', '.join(args.cond)}\n\n")
        f.write("## 概览（分来源 × 条件）\n\n")
        f.write("| source | cond | n | correct | accuracy | exec_ok | exec rate | protocol rate | timeout | 平均 out tok | 平均调用 |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|\n")
        for (src, cond), d in sorted(summary.items()):
            n = d["n"]
            f.write(f"| {src} | {cond} | {n} | {d['correct']} | {d['correct']/n:.3f} | {d['exec_ok']} | "
                    f"{d['exec_ok']/n:.3f} | {d['protocol_ok']/n:.3f} | {d['timed_out']} | "
                    f"{d['out_tokens']/n:.0f} | {d['n_calls']/n:.2f} |\n")

        f.write("\n## 归类表（`category` 由人工填，取值见脚本头部）\n\n")
        f.write("欠定题填 `underspecified`，**不从它们推 gene**。`flagged` 是冻结的关键词粗筛命中，"
                "只是提示，不是判定。\n\n")
        f.write("C0 / C1 没有 spec，spec 类谓词必然失败，已在本表中隐去；这两个条件只看代码级 gene："
                + "、".join(sorted(g.replace("orgene.", "") for g in CODE_LEVEL_GENES)) + "。\n\n")
        f.write("| source | case_id | cond | correct | reason | status | objective | reference | "
                "hard genes | soft genes | stderr(尾 3 行) | flagged | category |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        listed = 0
        for r in rows:
            if r["correct"] and not args.all:
                continue
            listed += 1
            f.write("| {src} | {cid} | {cond} | {ok} | {reason} | {status} | {obj} | {ref} | {hard} | "
                    "{soft} | {err} | {flag} | |\n".format(
                        src=cell(r["source"]), cid=cell(r["case_id"]), cond=cell(r["condition"]),
                        ok="✓" if r["correct"] else "✗", reason=cell(r["reason"]),
                        status=cell(r["status"]), obj=fmt_num(r["objective"]), ref=fmt_num(r["reference"]),
                        hard=cell(", ".join(g.replace("orgene.", "") for g in r["hard"]), 60),
                        soft=cell(", ".join(g.replace("orgene.", "") for g in r["soft"]), 40),
                        err=cell(r["stderr"], 90), flag=cell(", ".join(r["flagged"]), 30)))
        f.write(f"\n共 {listed} 行（{'全部案例' if args.all else '仅错题'}）。\n")

        f.write("\n## 类别计数（填完 category 后用 --tally 重跑本脚本统计，或手工数）\n\n")
        f.write("| category | 中文 | count |\n|---|---|---|\n")
        for key, zh in CATEGORIES:
            f.write(f"| {key} | {zh} | |\n")

    print(f"[dev_failures] {len(rows)} cases, {sum(1 for r in rows if not r['correct'])} wrong -> {out}")
    for (src, cond), d in sorted(summary.items()):
        n = d["n"]
        print(f"  {src:18s} {cond}  n={n:3d}  acc={d['correct']/n:.3f}  exec={d['exec_ok']/n:.3f}  "
              f"protocol={d['protocol_ok']/n:.3f}  timeout={d['timed_out']}")


if __name__ == "__main__":
    main()

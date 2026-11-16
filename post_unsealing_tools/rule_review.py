#!/usr/bin/env python3
"""Rule read-through of the measurement check (plan section 12, reviewer guide section 10).

Step 3 is descriptive: after all judgments are final, each reviewer reads the frozen rule library once and
writes one row per obvious error in the sheet `gene_review` of the step 3 workbook that
`measurement_check.py workbooks --step 3` produced (gene_id, issue_type, description, suggestion). Nothing
is scored, no agreement coefficient is computed, and the library is not changed.

  rule_review.py booklet   --genes genes.it1.jsonl [--lexicon activation_lexicon.v2.json] --out DIR
      -> rule_list.html (what the reviewers read: the seven items of guide section 10 for every rule, and
         the table of where each rule came from), rule_ids.json
  rule_review.py summarize --genes genes.it1.jsonl --r1 gene_review_R1.xlsx --r2 gene_review_R2.xlsx --out DIR
                           [--q1 rule_questions_R1.xlsx --q2 rule_questions_R2.xlsx]
      -> rule_review_summary.json, rule_review_issues.csv (every issue as written, for the appendix),
         rule_review_table.tex (one row per rule), rule_review_summary.txt (counts for the text)

Optional addition, NOT part of the registered plan or of the registered workbook: `booklet --questions` also
writes rule_questions_R1.xlsx and rule_questions_R2.xlsx, one row per rule with two closed questions (is the
principle correct: yes / no / unsure; is the rule general or specific to one kind of problem) and a comment.
If these are used, the paper reports them as an addition made after registration; `summarize --q1 --q2` then
adds the per-rule answers and their counts.

"No issue reported" means that a reviewer who was asked for obvious errors only reported none for that rule.
It is not a statement that the rule is correct, and the outputs never word it that way.

Standard library plus openpyxl (summarize only). Written 2026-10-10, after the freeze of manifest 4; it reads
the rule library and the two step 3 workbooks and no test output.
"""
import argparse
import csv
import hashlib
import html
import json
import os
import sys

WORKBOOK_SCHEMA = "orgene.r1.measurement_check.workbook.v1"   # as in measurement_check.py
FIRST_ROW = 3                                                 # as in measurement_check.py
ISSUE_TYPES = ("statement", "check", "repair", "activation", "other")
NONE = "none"
RATERS = ("R1", "R2")
QUESTIONS_SCHEMA = "orgene.r1.measurement_check.rule_questions.v1"
PRINCIPLE = ("yes", "no", "unsure")
SCOPE = ("general", "specific")
Q_FIRST_ROW = 3
QUESTION_README = (
    "Two questions about each rule / 关于每条规则的两个问题",
    "",
    "This sheet comes with step 3 (reading through the modeling rules). It is an addition to the reviewer guide: "
    "the guide asks you to point out obvious errors in the file gene_review; this file asks two short questions about every rule.",
    "Please answer on your own, after reading the rule list (rule_list.html), on the sheet rule_questions:",
    "  1. principle_correct: is the rule's statement correct as modeling advice? Choose yes, no or unsure.",
    "  2. scope: is the rule general, or specific to one kind of problem? Choose general or specific.",
    "Judge the principle in the statement, not how well the automatic check implements it; problems with a check, "
    "a repair instruction or an applicability condition belong in gene_review. Please answer both questions for every rule. "
    "A comment is optional. Your answers are reported per rule without your name; the rules are not changed.",
    "",
    "本表随第 3 步（通读建模规则）一起发给您，是对说明书的补充：说明书请您在 gene_review 文件里指出明显错误；"
    "本表对每条规则多问两个简短的问题。",
    "请在读完规则清单（rule_list.html）之后，独立在 rule_questions 页作答：",
    "  1. principle_correct：这条规则的陈述作为建模建议是否正确？选 yes、no 或 unsure。",
    "  2. scope：这条规则是通用的，还是只适用于某一类问题？选 general 或 specific。",
    "请只判断陈述里的原理，不判断自动检查实现得好不好；检查、修复指令或适用条件的问题请写在 gene_review 里。"
    "每条规则两个问题都请作答，备注可选。您的回答按规则逐条报告，不写姓名；规则不会因此改动。",
)
SOURCE_TEXT = {"seed_structural": "structural seed (written before any development run)",
               "dev_failure_derived": "derived from first-round failures on development problems"}


class ReviewError(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_genes(path):
    genes = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    ids = [g["geneId"] for g in genes]
    if len(set(ids)) != len(ids):
        raise ReviewError("duplicate geneId in the rule library")
    return genes


def short(gid):
    return gid[len("orgene."):] if gid.startswith("orgene.") else gid


# ---------------------------------------------------------------------------------------------- booklet

def _applies(g, features):
    act = g.get("activation")
    if not act:
        return "Always, within its scope."
    rule = act.get("rule")
    if not isinstance(rule, dict):                      # the record says "always"
        text = "On every problem, within its scope"
        if act.get("rationale"):
            text += f". Reason given: {html.escape(act['rationale'])}"
        return text.rstrip(".") + "."
    feat = rule.get("feature", "?")
    text = f"Only when the statement feature <code>{html.escape(str(feat))}</code> {html.escape(str(rule.get('op', '')))} " \
           f"{html.escape(json.dumps(rule.get('value')))}"
    desc = (features.get(feat) or {}).get("description")
    if desc:
        text += f" (feature: {html.escape(desc)})"
    if act.get("rationale"):
        text += f". Reason given: {html.escape(act['rationale'])}"
    return text.rstrip(".") + "."


def _ul(items):
    return "<ul>" + "".join(f"<li>{html.escape(str(x))}</li>" for x in items) + "</ul>" if items else "<p>None.</p>"


def cmd_booklet(a):
    genes = load_genes(a.genes)
    features = json.load(open(a.lexicon, encoding="utf-8")).get("features", {}) if a.lexicon else {}
    os.makedirs(a.out, exist_ok=True)
    parts = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Rule list (step 3)</title>",
             "<style>body{font-family:Georgia,serif;max-width:52em;margin:2em auto;padding:0 1em;line-height:1.45}"
             "h2{margin-top:2em;border-top:1px solid #999;padding-top:.6em;font-family:Menlo,monospace;font-size:1.05em}"
             "dt{font-weight:bold;margin-top:.6em}dd{margin-left:1.2em}table{border-collapse:collapse}"
             "td,th{border:1px solid #999;padding:.25em .6em;text-align:left}code{font-family:Menlo,monospace}</style></head><body>",
             f"<h1>Rule list for step 3</h1><p>{len(genes)} rules. Use the ID shown in each heading in the column "
             "<code>gene_id</code> of the step 3 file.</p>"]
    for g in genes:
        v, au = g["validation"], g["audit"]
        n_dev = len(au.get("devCaseIds") or [])
        source = SOURCE_TEXT.get(au.get("sourceType"), str(au.get("sourceType")))
        if n_dev:
            source += f"; {n_dev} development problem(s) consulted"
        consequence = "A failed check triggers a repair." if v.get("severity") == "hard" else \
            "A failed check gives a warning only."
        phase = {"pre_exec": "before the program is run", "post_exec": "after the program is run"}.get(v.get("phase"), v.get("phase"))
        c = g.get("contract", {})
        parts += [f"<h2 id='{html.escape(g['geneId'])}'>{html.escape(short(g['geneId']))} "
                  f"<small>(version {html.escape(g['version'])})</small></h2><dl>",
                  f"<dt>Statement</dt><dd>{html.escape(g['preference']['statement'])}</dd>",
                  f"<dt>Rationale</dt><dd>{html.escape(g['preference'].get('rationale', ''))}</dd>",
                  f"<dt>Source</dt><dd>{html.escape(source)}</dd>",
                  f"<dt>What the automatic check looks for</dt><dd>{_ul(c.get('checks'))}"
                  f"<p>Checked {html.escape(str(phase))}. Required of the program:</p>{_ul(c.get('required'))}"
                  f"<p>Forbidden:</p>{_ul(c.get('forbidden'))}</dd>",
                  f"<dt>If the check fails</dt><dd>{consequence}</dd>",
                  f"<dt>Repair instruction given to the AI system</dt><dd>{html.escape(g['repair']['instruction'])}</dd>",
                  f"<dt>When the rule applies</dt><dd>{_applies(g, features)}</dd></dl>"]
    parts.append("<h1>Where each rule came from</h1><table><tr><th>Rule</th><th>Source</th>"
                 "<th>Development problems consulted</th><th>Created</th></tr>")
    for g in genes:
        au = g["audit"]
        parts.append(f"<tr><td><code>{html.escape(short(g['geneId']))}</code></td>"
                     f"<td>{html.escape(SOURCE_TEXT.get(au.get('sourceType'), str(au.get('sourceType'))))}</td>"
                     f"<td>{len(au.get('devCaseIds') or [])}</td><td>{html.escape(str(au.get('createdAt', '')))}</td></tr>")
    parts.append("</table></body></html>")
    out = os.path.join(a.out, "rule_list.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    with open(os.path.join(a.out, "rule_ids.json"), "w", encoding="utf-8") as f:
        json.dump({"genes_sha256": sha256_file(a.genes), "rule_list_sha256": sha256_file(out),
                   "ids": [short(g["geneId"]) for g in genes]}, f, indent=1)
    print("wrote rule_list.html", sha256_file(out)[:12], "and rule_ids.json;", len(genes), "rules")
    if a.questions:
        for rater in RATERS:
            write_question_form(os.path.join(a.out, f"rule_questions_{rater}.xlsx"), genes, rater, sha256_file(a.genes))
            print("wrote", f"rule_questions_{rater}.xlsx", "(addition after registration)")
    return 0


def write_question_form(path, genes, rater, genes_sha):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.worksheet.datavalidation import DataValidation
    wb = Workbook()
    ws = wb.active
    ws.title = "rule_questions"
    ws.append(["rule_id", "principle_correct", "scope", "comment"])
    ws.append(["规则编号（请勿改动）\nRule ID (do not edit)",
               "这条规则的原理作为建模建议是否正确？\nIs the principle correct as modeling advice?\nyes / no / unsure",
               "这条规则是通用的，还是只适用于某一类问题？\nIs the rule general, or specific to one kind of problem?\ngeneral / specific",
               "备注（可选）\nComment (optional)"])
    for g in genes:
        ws.append([short(g["geneId"]), None, None, None])
    last = Q_FIRST_ROW + len(genes) - 1
    for col, values in (("B", PRINCIPLE), ("C", SCOPE)):
        dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{col}{Q_FIRST_ROW}:{col}{last}")
    for c, w in zip("ABCD", (38, 34, 34, 60)):
        ws.column_dimensions[c].width = w
    for cell in ws[1] + ws[2]:
        cell.font, cell.alignment = Font(bold=True), Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = f"B{Q_FIRST_ROW}"
    rd = wb.create_sheet("README", 0)
    for line in QUESTION_README:
        rd.append([line])
    rd.column_dimensions["A"].width = 110
    for row in rd.iter_rows():
        row[0].alignment = Alignment(wrap_text=True, vertical="top")
    wb.active = 0
    mt = wb.create_sheet("meta")
    mt.append(["key", "value"])
    for k, v in (("schema", QUESTIONS_SCHEMA), ("file_role", "rule_questions"), ("rater_id", rater),
                 ("genes_sha256", genes_sha), ("n_rules", len(genes))):
        mt.append([k, v])
    wb.save(path)


def read_questions(path, ids, rater, genes_sha):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    name = os.path.basename(path)
    if "meta" not in wb.sheetnames or "rule_questions" not in wb.sheetnames:
        raise ReviewError(f"{name}: not a rule_questions workbook")
    meta = {r[0]: r[1] for r in wb["meta"].iter_rows(min_row=2, values_only=True) if r[0]}
    if meta.get("schema") != QUESTIONS_SCHEMA or meta.get("rater_id") != rater:
        raise ReviewError(f"{name}: schema or rater_id does not match ({meta.get('schema')!r}, {meta.get('rater_id')!r})")
    if meta.get("genes_sha256") != genes_sha:
        raise ReviewError(f"{name}: made for a different rule library")
    out, problems = {}, []
    for n, row in enumerate(wb["rule_questions"].iter_rows(min_row=Q_FIRST_ROW, values_only=True), Q_FIRST_ROW):
        raw, pc, sc, comment = (list(row) + [None] * 4)[:4]
        if not _text(raw):
            continue
        gid = resolve_id(raw, ids)
        pc, sc = _text(pc).lower(), _text(sc).lower()
        if not gid:
            problems.append(f"row {n}: rule_id not in the rule list")
        elif gid in out:
            problems.append(f"row {n}: rule listed twice")
        elif pc not in PRINCIPLE or sc not in SCOPE:
            problems.append(f"{short(gid)}: answer missing or outside the list")
        else:
            out[gid] = {"principle_correct": pc, "scope": sc, "comment": _text(comment)}
    missing = [short(g) for g in ids if g not in out]
    if missing and not any(short(m) in p for m in missing for p in problems):
        problems.append(f"{len(missing)} rule(s) without a row: {', '.join(missing[:5])}")
    if problems:
        raise ReviewError(f"{rater} questions ({name}): " + "; ".join(problems[:8])
                          + (f"; and {len(problems) - 8} more" if len(problems) > 8 else ""))
    return {"answers": out, "sha256": sha256_file(path)}


def add_questions(summary, answers):
    for x in summary["per_rule"]:
        for r in RATERS:
            x[f"principle_{r}"] = answers[r]["answers"][x["gene_id"]]["principle_correct"]
            x[f"scope_{r}"] = answers[r]["answers"][x["gene_id"]]["scope"]
            x[f"comment_{r}"] = answers[r]["answers"][x["gene_id"]]["comment"]
    rows = summary["per_rule"]
    both_yes = [x for x in rows if all(x[f"principle_{r}"] == "yes" for r in RATERS)]
    summary["questions"] = {
        "note": "Addition after registration: two closed questions per rule. No agreement coefficient is computed for 21 items.",
        "n_principle_correct_both": len(both_yes),
        "n_principle_questioned_by_at_least_one": len(rows) - len(both_yes),
        "rules_principle_questioned": [short(x["gene_id"]) for x in rows if x not in both_yes],
        "n_principle_no_by_at_least_one": sum(any(x[f"principle_{r}"] == "no" for r in RATERS) for x in rows),
        "n_specific_by_at_least_one": sum(any(x[f"scope_{r}"] == "specific" for r in RATERS) for x in rows),
        "n_specific_by_both": sum(all(x[f"scope_{r}"] == "specific" for r in RATERS) for x in rows),
        "rules_specific_by_at_least_one": [short(x["gene_id"]) for x in rows if any(x[f"scope_{r}"] == "specific" for r in RATERS)],
        "answers_by_rater": {r: {"principle": {v: sum(x[f"principle_{r}"] == v for x in rows) for v in PRINCIPLE},
                                 "scope": {v: sum(x[f"scope_{r}"] == v for x in rows) for v in SCOPE}} for r in RATERS},
        "workbook_sha256": {r: answers[r]["sha256"] for r in RATERS},
        "slots": {"rules.correct.both": len(both_yes), "rules.questioned": len(rows) - len(both_yes),
                  "rules.specific": sum(any(x[f"scope_{r}"] == "specific" for r in RATERS) for x in rows)},
    }
    return summary


# -------------------------------------------------------------------------------------------- summarize

def _text(v):
    return v.strip() if isinstance(v, str) else ("" if v is None else str(v).strip())


def resolve_id(raw, ids):
    """Full ID, ID without the `orgene.` prefix, or a unique last component."""
    s = _text(raw)
    if not s:
        return None
    s = s.split("@")[0].strip()
    for gid in ids:
        if s in (gid, short(gid)):
            return gid
    tail = [gid for gid in ids if gid.endswith("." + s) or short(gid).split(".", 1)[-1] == s]
    return tail[0] if len(tail) == 1 else False


def read_review(path, ids, rater):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    name = os.path.basename(path)
    if "meta" not in wb.sheetnames or "gene_review" not in wb.sheetnames:
        raise ReviewError(f"{name}: not a step 3 workbook (sheets meta and gene_review expected)")
    meta = {r[0]: r[1] for r in wb["meta"].iter_rows(min_row=2, values_only=True) if r[0]}
    if meta.get("schema") != WORKBOOK_SCHEMA or meta.get("file_role") != "gene_review":
        raise ReviewError(f"{name}: not a gene_review workbook of {WORKBOOK_SCHEMA}")
    if meta.get("rater_id") != rater:
        raise ReviewError(f"{name}: rater_id is {meta.get('rater_id')!r}, expected {rater!r}")
    ws = wb["gene_review"]
    keys = [c.value for c in ws[1]]
    if keys[:4] != ["gene_id", "issue_type", "description", "suggestion"]:
        raise ReviewError(f"{name}: unexpected columns {keys[:4]}")
    issues, cleared, whole_none, problems = [], set(), False, []
    for n, row in enumerate(ws.iter_rows(min_row=FIRST_ROW, values_only=True), FIRST_ROW):
        r = dict(zip(keys, row))
        raw_id, typ = _text(r.get("gene_id")), _text(r.get("issue_type")).split()[0].lower() if _text(r.get("issue_type")) else ""
        desc, sugg = _text(r.get("description")), _text(r.get("suggestion"))
        if not (raw_id or typ or desc or sugg):
            continue
        if typ not in ISSUE_TYPES + (NONE,):
            problems.append(f"row {n}: issue_type missing or outside the list")
            continue
        gid = resolve_id(raw_id, ids)
        if typ == NONE:
            if gid is None:
                whole_none = True                      # "I found nothing" for the whole list
            elif gid is False:
                problems.append(f"row {n}: gene_id not in the rule list")
            else:
                cleared.add(gid)
            continue
        if not gid:
            problems.append(f"row {n}: gene_id missing or not in the rule list")
        elif not desc:
            problems.append(f"row {n}: an issue needs a description")
        else:
            issues.append({"gene_id": gid, "rater": rater, "issue_type": typ, "description": desc, "suggestion": sugg, "row": n})
    flagged = {i["gene_id"] for i in issues}
    for gid in sorted(cleared & flagged):
        problems.append(f"{short(gid)}: marked none and also given an issue")
    if whole_none and issues:
        problems.append("a row says nothing was found, but other rows report issues")
    if not issues and not whole_none and not cleared:
        problems.append("the sheet is empty; the guide asks for one row with issue_type = none when nothing is found")
    if problems:
        raise ReviewError(f"{rater} workbook ({name}): " + "; ".join(problems[:8])
                          + (f"; and {len(problems) - 8} more" if len(problems) > 8 else ""))
    return {"issues": issues, "sha256": sha256_file(path)}


def summarize(genes, reviews):
    ids = [g["geneId"] for g in genes]
    per_rule = []
    for gid in ids:
        row = {"gene_id": gid, "source_type": next(g["audit"].get("sourceType") for g in genes if g["geneId"] == gid)}
        for r in RATERS:
            row[r] = sorted({i["issue_type"] for i in reviews[r]["issues"] if i["gene_id"] == gid}, key=ISSUE_TYPES.index)
        row["flagged_by"] = [r for r in RATERS if row[r]]
        per_rule.append(row)
    by_n = {k: [short(x["gene_id"]) for x in per_rule if len(x["flagged_by"]) == k] for k in (0, 1, 2)}
    return {
        "schema": "orgene.r1.measurement_check.rule_review_summary.v1",
        "note": "Descriptive. Reviewers were asked for obvious errors only; 'no issue reported' is not a statement "
                "that a rule is correct. No score and no agreement coefficient.",
        "n_rules": len(ids),
        "n_rules_no_issue_from_either": len(by_n[0]),
        "n_rules_issue_from_one": len(by_n[1]),
        "n_rules_issue_from_both": len(by_n[2]),
        "rules_issue_from_one": by_n[1],
        "rules_issue_from_both": by_n[2],
        "n_issues": {r: len(reviews[r]["issues"]) for r in RATERS},
        "n_rules_with_issue": {r: len({i["gene_id"] for i in reviews[r]["issues"]}) for r in RATERS},
        "issues_by_type": {r: {t: sum(i["issue_type"] == t for i in reviews[r]["issues"]) for t in ISSUE_TYPES} for r in RATERS},
        "workbook_sha256": {r: reviews[r]["sha256"] for r in RATERS},
        "per_rule": per_rule,
    }


def _tex(s):
    return s.replace("\\", r"\textbackslash{}").replace("_", r"\_").replace("&", r"\&").replace("%", r"\%").replace("#", r"\#")


def write_outputs(summary, reviews, out):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "rule_review_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)
    order = {x["gene_id"]: k for k, x in enumerate(summary["per_rule"])}
    issues = sorted((i for r in RATERS for i in reviews[r]["issues"]), key=lambda i: (order[i["gene_id"]], i["rater"], i["row"]))
    with open(os.path.join(out, "rule_review_issues.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rule", "reviewer", "issue_type", "description", "suggestion"])
        for i in issues:
            w.writerow([short(i["gene_id"]), i["rater"], i["issue_type"], i["description"], i["suggestion"]])
    cell = lambda v: ", ".join(v) if v else "--"
    q = "questions" in summary
    if q:
        lines = [r"\begin{tabular}{lcccccc}", r"\toprule",
                 r" & \multicolumn{2}{c}{Principle correct} & \multicolumn{2}{c}{Scope} & \multicolumn{2}{c}{Obvious errors reported} \\",
                 r"Rule & R1 & R2 & R1 & R2 & R1 & R2 \\", r"\midrule"]
    else:
        lines = [r"\begin{tabular}{lll}", r"\toprule", r"Rule & Reviewer 1 & Reviewer 2 \\", r"\midrule"]
    for x in summary["per_rule"]:
        mid = f"{x['principle_R1']} & {x['principle_R2']} & {x['scope_R1']} & {x['scope_R2']} & " if q else ""
        lines.append(rf"\texttt{{{_tex(short(x['gene_id']))}}} & {mid}{cell(x['R1'])} & {cell(x['R2'])} \\")
    lines += [r"\bottomrule", r"\end{tabular}", "% Obvious errors: type of each error the reviewer reported for the rule; -- : none reported."]
    with open(os.path.join(out, "rule_review_table.tex"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    s = summary
    text = (f"Rules read: {s['n_rules']}.\n"
            f"No issue reported by either reviewer: {s['n_rules_no_issue_from_either']}.\n"
            f"Issue reported by one reviewer: {s['n_rules_issue_from_one']} ({', '.join(s['rules_issue_from_one']) or 'none'}).\n"
            f"Issue reported by both reviewers: {s['n_rules_issue_from_both']} ({', '.join(s['rules_issue_from_both']) or 'none'}).\n")
    for r in RATERS:
        by = ", ".join(f"{t} {n}" for t, n in s["issues_by_type"][r].items() if n) or "none"
        text += f"{r}: {s['n_issues'][r]} issue(s) on {s['n_rules_with_issue'][r]} rule(s); by type: {by}.\n"
    text += "Reviewers were asked for obvious errors only; a rule without a reported issue has not been certified correct.\n"
    if q:
        k = s["questions"]
        text += (f"Two questions per rule (addition after registration): principle judged correct by both reviewers: "
                 f"{k['n_principle_correct_both']}; questioned (no or unsure) by at least one: {k['n_principle_questioned_by_at_least_one']}"
                 f" ({', '.join(k['rules_principle_questioned']) or 'none'}); judged specific to one kind of problem by at least one: "
                 f"{k['n_specific_by_at_least_one']} ({', '.join(k['rules_specific_by_at_least_one']) or 'none'}), by both: {k['n_specific_by_both']}.\n")
    with open(os.path.join(out, "rule_review_summary.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    return text


def cmd_summarize(a):
    genes = load_genes(a.genes)
    ids = [g["geneId"] for g in genes]
    reviews = {"R1": read_review(a.r1, ids, "R1"), "R2": read_review(a.r2, ids, "R2")}
    summary = summarize(genes, reviews)
    summary["genes_sha256"] = sha256_file(a.genes)
    if bool(a.q1) != bool(a.q2):
        raise ReviewError("give both --q1 and --q2, or neither")
    if a.q1:
        add_questions(summary, {"R1": read_questions(a.q1, ids, "R1", summary["genes_sha256"]),
                                "R2": read_questions(a.q2, ids, "R2", summary["genes_sha256"])})
    print(write_outputs(summary, reviews, a.out), end="")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("booklet")
    b.add_argument("--genes", required=True)
    b.add_argument("--lexicon", default=None)
    b.add_argument("--out", required=True)
    b.add_argument("--questions", action="store_true", help="also write the two-question forms (not in the registered plan)")
    b.set_defaults(fn=cmd_booklet)
    s = sub.add_parser("summarize")
    s.add_argument("--genes", required=True)
    s.add_argument("--r1", required=True)
    s.add_argument("--r2", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--q1", default=None)
    s.add_argument("--q2", default=None)
    s.set_defaults(fn=cmd_summarize)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except ReviewError as e:
        print("ERROR:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Tests for rule_review.py. Run: python3 -m pytest test_rule_review.py -q
Needs the workbook template and the frozen rule library; paths can be overridden with
RULE_REVIEW_TEMPLATE and RULE_REVIEW_GENES."""
import json
import os

import pytest
from openpyxl import load_workbook

import rule_review as rr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TEMPLATE = os.environ.get("RULE_REVIEW_TEMPLATE", os.path.join(ROOT, "stage1", "measurement_check", "05_judgment_workbook_template.xlsx"))
GENES = os.environ.get("RULE_REVIEW_GENES", os.path.join(ROOT, "code_wt", "it1", "genes", "genes.it1.jsonl"))
LEXICON = os.path.join(os.path.dirname(GENES), "activation_lexicon.v2.json")


def make_workbook(path, rater, rows, role="gene_review"):
    """The step 3 file as measurement_check.py writes it, with the reviewer's rows filled in."""
    wb = load_workbook(TEMPLATE)
    for ws in list(wb.worksheets):
        if ws.title not in ("README", "gene_review", "meta", "lists"):
            wb.remove(ws)
    for r in wb["meta"].iter_rows(min_row=2):
        if r[0].value == "file_role":
            r[1].value = role
        if r[0].value == "rater_id":
            r[1].value = rater
    ws = wb["gene_review"]
    for n, row in enumerate(rows, rr.FIRST_ROW):
        for c, v in enumerate(row, 1):
            ws.cell(n, c).value = v
    wb.save(path)
    return path


def run(tmp_path, rows1, rows2):
    r1 = make_workbook(str(tmp_path / "gene_review_R1.xlsx"), "R1", rows1)
    r2 = make_workbook(str(tmp_path / "gene_review_R2.xlsx"), "R2", rows2)
    rc = rr.main(["summarize", "--genes", GENES, "--r1", r1, "--r2", r2, "--out", str(tmp_path / "out")])
    return rc, tmp_path / "out"


def test_counts_and_outputs(tmp_path):
    rows1 = [("numeric.bigm_bounded", "check", "threshold misses 1e5", "lower it"),
             ("orgene.numeric.bigm_bounded", "repair", "may tighten too far", None),
             ("logic_via_indicators", "statement 说明有误", "too strong for pure binary models", ""),
             ("orgene.execution.runs", "none", None, None)]
    rows2 = [("orgene.model.logic_via_indicators@1.1.0", "activation", "fires on 'if' in data descriptions", None)]
    rc, out = run(tmp_path, rows1, rows2)
    assert rc == 0
    s = json.load(open(out / "rule_review_summary.json", encoding="utf-8"))
    assert s["n_rules"] == 21
    assert (s["n_rules_no_issue_from_either"], s["n_rules_issue_from_one"], s["n_rules_issue_from_both"]) == (19, 1, 1)
    assert s["rules_issue_from_both"] == ["model.logic_via_indicators"]
    assert s["rules_issue_from_one"] == ["numeric.bigm_bounded"]
    assert s["n_issues"] == {"R1": 3, "R2": 1}
    assert s["issues_by_type"]["R1"] == {"statement": 1, "check": 1, "repair": 1, "activation": 0, "other": 0}
    bigm = next(x for x in s["per_rule"] if x["gene_id"] == "orgene.numeric.bigm_bounded")
    assert bigm["R1"] == ["check", "repair"] and bigm["R2"] == [] and bigm["flagged_by"] == ["R1"]
    issues = open(out / "rule_review_issues.csv", encoding="utf-8").read()
    assert "threshold misses 1e5" in issues and issues.count("\n") == 5
    tex = open(out / "rule_review_table.tex", encoding="utf-8").read()
    assert r"\texttt{numeric.bigm\_bounded} & check, repair & -- \\" in tex
    assert tex.count(r"\\") == 22                        # header and 21 rules
    assert "not been certified correct" in open(out / "rule_review_summary.txt", encoding="utf-8").read()


def test_nothing_found_is_valid(tmp_path):
    rc, out = run(tmp_path, [(None, "none", None, None)], [("", "none", "nothing obvious", "")])
    assert rc == 0
    s = json.load(open(out / "rule_review_summary.json", encoding="utf-8"))
    assert s["n_rules_no_issue_from_either"] == 21 and s["n_issues"] == {"R1": 0, "R2": 0}


@pytest.mark.parametrize("rows, message", [
    ([], "sheet is empty"),
    ([("no_such_rule", "check", "x", None)], "not in the rule list"),
    ([("numeric.bigm_bounded", "wrong", "x", None)], "outside the list"),
    ([("numeric.bigm_bounded", "check", None, None)], "needs a description"),
    ([(None, "check", "x", None)], "gene_id missing"),
    ([("numeric.bigm_bounded", "none", None, None), ("numeric.bigm_bounded", "check", "x", None)], "marked none and also"),
    ([(None, "none", None, None), ("numeric.bigm_bounded", "check", "x", None)], "nothing was found, but"),
])
def test_bad_sheets_are_refused(tmp_path, capsys, rows, message):
    rc, out = run(tmp_path, rows, [(None, "none", None, None)])
    assert rc == 1 and message in capsys.readouterr().err
    assert not os.path.exists(out)                       # nothing is written from a bad sheet


def test_wrong_file_role_or_rater(tmp_path, capsys):
    r1 = make_workbook(str(tmp_path / "a.xlsx"), "R1", [(None, "none", None, None)], role="judgments")
    r2 = make_workbook(str(tmp_path / "b.xlsx"), "R2", [(None, "none", None, None)])
    assert rr.main(["summarize", "--genes", GENES, "--r1", r1, "--r2", r2, "--out", str(tmp_path / "o")]) == 1
    assert "not a gene_review workbook" in capsys.readouterr().err
    assert rr.main(["summarize", "--genes", GENES, "--r1", r2, "--r2", r2, "--out", str(tmp_path / "o")]) == 1
    assert "rater_id" in capsys.readouterr().err


def test_ambiguous_short_id_is_refused():
    ids = ["orgene.a.runs", "orgene.b.runs", "orgene.c.other"]
    assert rr.resolve_id("runs", ids) is False
    assert rr.resolve_id("other", ids) == "orgene.c.other"
    assert rr.resolve_id("a.runs", ids) == "orgene.a.runs"
    assert rr.resolve_id("  ", ids) is None


def test_booklet(tmp_path):
    assert rr.main(["booklet", "--genes", GENES, "--lexicon", LEXICON, "--out", str(tmp_path)]) == 0
    page = open(tmp_path / "rule_list.html", encoding="utf-8").read()
    genes = rr.load_genes(GENES)
    assert page.count("<h2 ") == len(genes) == 21
    for g in genes:
        assert rr.html.escape(g["preference"]["statement"]) in page
        assert rr.html.escape(g["repair"]["instruction"]) in page
    assert page.count("gives a warning only") == 2 and page.count("triggers a repair") == 19
    assert page.count("Only when the statement feature") == sum(1 for g in genes if isinstance((g.get("activation") or {}).get("rule"), dict)) == 2
    assert page.count("On every problem, within its scope") == 2
    for word in ("C3L", "C3E", "devCaseIds", "mamo_", "industryor"):      # no condition labels or case IDs
        assert word not in page
    ids = json.load(open(tmp_path / "rule_ids.json", encoding="utf-8"))
    assert len(ids["ids"]) == 21 and ids["genes_sha256"] == rr.sha256_file(GENES)


def fill_questions(path, answers, default=("yes", "general")):
    wb = load_workbook(path)
    ws = wb["rule_questions"]
    for row in ws.iter_rows(min_row=rr.Q_FIRST_ROW):
        if row[0].value:
            pc, sc = answers.get(row[0].value, default)
            row[1].value, row[2].value = pc, sc
    wb.save(path)


def test_question_forms_roundtrip(tmp_path):
    assert rr.main(["booklet", "--genes", GENES, "--lexicon", LEXICON, "--out", str(tmp_path), "--questions"]) == 0
    q1, q2 = str(tmp_path / "rule_questions_R1.xlsx"), str(tmp_path / "rule_questions_R2.xlsx")
    fill_questions(q1, {"numeric.bigm_bounded": ("unsure", "general"), "code.pulp_api_exists": ("yes", "specific")})
    fill_questions(q2, {"numeric.bigm_bounded": ("yes", "general"), "code.pulp_api_exists": ("yes", "specific"),
                        "execution.runs": ("no", "general")})
    r1 = make_workbook(str(tmp_path / "gene_review_R1.xlsx"), "R1", [(None, "none", None, None)])
    r2 = make_workbook(str(tmp_path / "gene_review_R2.xlsx"), "R2", [("execution.runs", "statement", "too broad", None)])
    out = tmp_path / "out"
    assert rr.main(["summarize", "--genes", GENES, "--r1", r1, "--r2", r2, "--q1", q1, "--q2", q2, "--out", str(out)]) == 0
    k = json.load(open(out / "rule_review_summary.json", encoding="utf-8"))["questions"]
    assert k["slots"] == {"rules.correct.both": 19, "rules.questioned": 2, "rules.specific": 1}
    assert k["rules_principle_questioned"] == ["execution.runs", "numeric.bigm_bounded"]
    assert (k["n_principle_no_by_at_least_one"], k["n_specific_by_both"]) == (1, 1)
    assert k["answers_by_rater"]["R1"]["principle"] == {"yes": 20, "no": 0, "unsure": 1}
    tex = open(out / "rule_review_table.tex", encoding="utf-8").read()
    assert r"\texttt{execution.runs} & yes & no & general & general & -- & statement \\" in tex
    assert "addition after registration" in open(out / "rule_review_summary.txt", encoding="utf-8").read()


def test_question_forms_must_be_complete(tmp_path, capsys):
    rr.main(["booklet", "--genes", GENES, "--out", str(tmp_path), "--questions"])
    q1, q2 = str(tmp_path / "rule_questions_R1.xlsx"), str(tmp_path / "rule_questions_R2.xlsx")
    fill_questions(q2, {})
    r = make_workbook(str(tmp_path / "gene_review_R1.xlsx"), "R1", [(None, "none", None, None)])
    r2 = make_workbook(str(tmp_path / "gene_review_R2.xlsx"), "R2", [(None, "none", None, None)])
    capsys.readouterr()
    assert rr.main(["summarize", "--genes", GENES, "--r1", r, "--r2", r2, "--q1", q1, "--q2", q2, "--out", str(tmp_path / "o")]) == 1
    assert "answer missing or outside the list" in capsys.readouterr().err
    assert rr.main(["summarize", "--genes", GENES, "--r1", r, "--r2", r2, "--q1", q2, "--q2", q2, "--out", str(tmp_path / "o")]) == 1
    assert "rater_id does not match" in capsys.readouterr().err
    assert rr.main(["summarize", "--genes", GENES, "--r1", r, "--r2", r2, "--q1", q1, "--out", str(tmp_path / "o")]) == 1
    assert not os.path.exists(tmp_path / "o")

"""Non-numeric references: status categories (scoring rule fixed before the freeze, 2026-09-29; E17 verification).

A printed STATUS and a non-numeric reference are both reduced to a category (score.status_category). A non-numeric
reference is matched only by a printed status of exactly its category, and only infeasible or unbounded can be
matched; "infeasible or unbounded" (COPT INF_OR_UNB, "No Best Solution") and local results never match. Every status
word a PuLP program prints keeps the judgement of the earlier substring rule (transcribed below as OLD_RULE).

Fixtures are self-made; the only real data read are the reference fields of the dev cases and the smoke cases
(no problem text is printed or compared).
"""
import json
import os
import random
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
if RUNTIME not in sys.path:
    sys.path.insert(0, RUNTIME)

from orgene import data as D  # noqa: E402
from orgene import pipeline as P  # noqa: E402
from orgene import refs as R  # noqa: E402
from orgene import score as SC  # noqa: E402
from orgene.conditions import read_jsonl, write_jsonl  # noqa: E402

# PuLP 3.3.2: LpStatus and LpSolution (the words a PuLP program prints under the v5 protocol)
PULP_STATUS_WORDS = ("Not Solved", "Optimal", "Infeasible", "Unbounded", "Undefined")
PULP_SOLUTION_WORDS = ("No Solution Found", "Optimal Solution Found", "Solution Found", "No Solution Exists",
                       "Solution is Unbounded")
# the words the ORLM harness prints (baselines/orlm_adapter.py COPT_STATUS_LABELS), and Pyomo termination conditions
COPT_WORDS = {"Optimal": "optimal", "Infeasible": "infeasible", "Unbounded": "unbounded",
              "Infeasible or Unbounded": "infeasible_or_unbounded", "Unstarted": "other", "Numerical": "other",
              "Node Limit": "other", "Imprecise": "other", "Timeout": "other", "Unfinished": "other",
              "Interrupted": "other", "Iter Limit": "other", "Local Optimal": "local_optimal",
              "Local Infeasible": "local_infeasible"}
PYOMO_WORDS = {"optimal": "optimal", "globallyOptimal": "optimal", "locallyOptimal": "local_optimal",
               "infeasible": "infeasible", "unbounded": "unbounded", "infeasibleOrUnbounded": "infeasible_or_unbounded",
               "maxTimeLimit": "other", "maxIterations": "other", "other": "other", "unknown": "other"}
REFERENCE_STATUSES = ("infeasible", "unbounded")  # every non-numeric reference parse_reference and overrides produced


def OLD_RULE(reference_status, status):
    """score.is_correct before this change, for a non-numeric reference (transcribed)."""
    if reference_status and status:
        return reference_status.strip().lower() in (status or "").strip().lower()
    return False


def _new(reference_status, status):
    return SC.is_correct(None, None, reference_status, status=status)[0]


# ------------------------------------------------------------------ categories


def test_categories_of_the_status_words_of_pulp_copt_and_pyomo():
    assert {w: SC.status_category(w) for w in PULP_STATUS_WORDS} == {
        "Not Solved": "other", "Optimal": "optimal", "Infeasible": "infeasible", "Unbounded": "unbounded",
        "Undefined": "other"}
    assert {w: SC.status_category(w) for w in PULP_SOLUTION_WORDS} == {
        "No Solution Found": "other", "Optimal Solution Found": "optimal", "Solution Found": "other",
        "No Solution Exists": "other", "Solution is Unbounded": "unbounded"}
    assert {w: SC.status_category(w) for w in COPT_WORDS} == COPT_WORDS
    assert {w: SC.status_category(w) for w in PYOMO_WORDS} == PYOMO_WORDS
    for w in ("INF_OR_UNB", "Unbounded or infeasible", "infeasible_or_unbounded", "No Best Solution", "no optimal solution"):
        assert SC.status_category(w) == "infeasible_or_unbounded", w
    for w in (None, "", "  ", "--"):
        assert SC.status_category(w) is None
    assert set(COPT_WORDS.values()) | set(PYOMO_WORDS.values()) <= set(SC.STATUS_CATEGORIES)


def test_the_harness_labels_are_categorised_as_listed_here():
    sys.path.insert(0, os.path.join(ROOT, "baselines"))
    try:
        import orlm_adapter as OA
    finally:
        sys.path.remove(os.path.join(ROOT, "baselines"))
    assert [lbl for _, lbl in OA.COPT_STATUS_LABELS] == list(COPT_WORDS)


def test_reference_category():
    assert SC.reference_category(12.5, None) == "numeric" and SC.reference_category(0.0, "infeasible") == "numeric"
    assert SC.reference_category(None, "infeasible") == "infeasible"
    assert SC.reference_category(None, "unbounded") == "unbounded"
    assert SC.reference_category(None, D.UNDECIDED_REFERENCE_STATUS) == "infeasible_or_unbounded"
    assert SC.reference_category(None, None) is None


# ------------------------------------------------------------------ the rule, and the counterexamples of the old rule


@pytest.mark.parametrize("ref", REFERENCE_STATUSES)
def test_undecided_statuses_never_match_a_non_numeric_reference(ref):
    for status in ("Infeasible or Unbounded", "INF_OR_UNB", "infeasibleOrUnbounded", "Unbounded or Infeasible",
                   "Local Infeasible", "Local Optimal", "locallyOptimal", "No Best Solution",
                   "Infeasible (no best solution)"):
        assert SC.is_correct(None, None, ref, status=status) == (False, "status_undecided"), (ref, status)
        assert SC.correct_by_tol(None, None, ref, status=status) == {k: False for k in ("1e-06", "0.0001", "0.01")}


def test_the_old_rule_counted_undecided_statuses_as_matches():
    """The counterexamples: the substring rule matched these, the category rule does not."""
    assert OLD_RULE("infeasible", "Infeasible or Unbounded") and not _new("infeasible", "Infeasible or Unbounded")
    assert OLD_RULE("unbounded", "Infeasible or Unbounded") and not _new("unbounded", "Infeasible or Unbounded")
    assert OLD_RULE("infeasible", "Local Infeasible") and not _new("infeasible", "Local Infeasible")


def test_decided_categories_match_only_themselves():
    assert SC.is_correct(None, None, "infeasible", status="Infeasible") == (True, "status_match")
    assert SC.is_correct(None, None, "unbounded", status="Unbounded") == (True, "status_match")
    assert SC.is_correct(None, None, "unbounded", status="Solution is Unbounded") == (True, "status_match")
    assert SC.is_correct(None, None, "infeasible", status="Unbounded") == (False, "status_mismatch")
    assert SC.is_correct(None, None, "unbounded", status="Infeasible") == (False, "status_mismatch")
    assert SC.is_correct(None, None, "infeasible", status="Optimal") == (False, "status_mismatch")
    assert SC.is_correct(None, None, "infeasible", status=None) == (False, "reference_not_numeric")
    assert SC.is_correct(None, None, None, status="Infeasible") == (False, "reference_not_numeric")
    # a numeric reference is judged by the printed objective alone, as before (the status is not looked at)
    assert SC.is_correct(2600.0, 2600.0, None, status="Local Optimal") == (True, "match")
    assert SC.is_correct(None, 2600.0, None, status="Infeasible") == (False, "no_objective")


def test_an_undecided_reference_is_never_matched():
    for status in ("Infeasible", "Unbounded", "Infeasible or Unbounded", "No Best Solution", "Optimal"):
        assert SC.is_correct(None, None, D.UNDECIDED_REFERENCE_STATUS, status=status) == (False, "reference_undecided")
    # references that are not a decided category cannot be matched by a status word either
    for ref in ("optimal", "not solved"):
        assert SC.is_correct(None, None, ref, status=ref.title()) == (False, "reference_not_numeric")


@pytest.mark.parametrize("ref", REFERENCE_STATUSES)
def test_every_pulp_status_word_keeps_its_judgement(ref):
    words = PULP_STATUS_WORDS + PULP_SOLUTION_WORDS
    variants = [w for s in words for w in (s, s.upper(), s.lower(), f"  {s} ", s.replace(" ", "_"))]
    for s in variants:
        assert _new(ref, s) == OLD_RULE(ref, s), (ref, s)


def test_pulp_vocabulary_is_the_one_listed_here():
    pulp = pytest.importorskip("pulp")
    assert tuple(pulp.LpStatus[k] for k in (0, 1, -1, -2, -3)) == PULP_STATUS_WORDS
    assert tuple(pulp.LpSolution[k] for k in (0, 1, 2, -1, -2)) == PULP_SOLUTION_WORDS


@pytest.mark.parametrize("ref", REFERENCE_STATUSES)
def test_only_undecided_statuses_change_their_judgement(ref):
    """Random status texts: the new rule equals the old one unless the status is undecided (then it is False)."""
    rng = random.Random(20260929)
    tokens = ["infeasible", "Infeasible", "INFEASIBLE", "unbounded", "Unbounded", "optimal", "Optimal", "not", "solved",
              "solution", "found", "no", "best", "local", "Local", "or", "integer", "primal", "dual", "status", ":",
              "-", "(", ")", "_", "problem", "is", "INF_OR_UNB", "limit", "time"]
    n_changed = 0
    for _ in range(5000):
        s = rng.choice(["", " ", "_", "-"]).join(rng.choice(tokens) for _ in range(rng.randint(1, 5)))
        cat = SC.status_category(s)
        if cat in SC.UNDECIDED_STATUS_CATEGORIES:
            assert _new(ref, s) is False, s
            n_changed += OLD_RULE(ref, s)
        else:
            assert _new(ref, s) == OLD_RULE(ref, s), s
    assert n_changed > 0  # the generator does produce the counterexamples


# ------------------------------------------------------------------ references: parse_reference


def test_parse_reference_keeps_every_earlier_result_and_adds_the_undecided_phrases():
    same = {"infeasible": (None, "infeasible"), "Infeasible": (None, "infeasible"), "unbounded": (None, "unbounded"),
            "The problem is unbounded.": (None, "unbounded"), "no feasible solution": (None, "infeasible"),
            "No solution": (None, "infeasible"), "The optimal value is $1,500.": (1500.0, None), "42": (42.0, None),
            "-3.5e2": (-350.0, None), 7: (7.0, None), 2.5: (2.5, None), None: (None, None), "n/a": (None, None)}
    for raw, want in same.items():
        assert D.parse_reference(raw) == want, raw
    undecided = (None, D.UNDECIDED_REFERENCE_STATUS)
    for raw in ("No Best Solution", "no best solution", " No Best Solution ", "No optimal solution",
                "Infeasible or unbounded", "unbounded or infeasible"):
        assert D.parse_reference(raw) == undecided, raw
    assert SC.status_category(D.UNDECIDED_REFERENCE_STATUS) == "infeasible_or_unbounded"


def test_parse_reference_on_the_stored_dev_and_smoke_references():
    """The stored references of the dev cases and the smoke cases parse to what the cases files hold (no rebuild)."""
    n = 0
    for src in ("mamo_complex_lp", "industryor", "smoke"):
        path = os.path.join(ROOT, "data", "cases", f"{src}.jsonl")
        if not os.path.exists(path):
            continue
        ids = None
        split = os.path.join(ROOT, "data", "splits", src, "dev_ids.json")
        if src != "smoke":
            if not os.path.exists(split):
                continue
            with open(split, encoding="utf-8") as f:
                ids = set(json.load(f))
        with open(path, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line) if line.strip() else {}
                if rec.get("_header") or "case_id" not in rec or (ids is not None and rec["case_id"] not in ids):
                    continue
                ref = rec["reference"]
                assert D.parse_reference(ref.get("raw")) == (ref.get("objective"), ref.get("status")), rec["case_id"]
                n += 1
    if n == 0:
        pytest.skip("no cases files in this checkout")


# ------------------------------------------------------------------ result rows and metrics


def test_score_condition_marks_undecided_statuses(tmp_path):
    cases_path = tmp_path / "toy.jsonl"
    refs_ = {"toy-1": (None, "infeasible"), "toy-2": (None, "infeasible"), "toy-3": (None, "unbounded"),
             "toy-4": (None, "infeasible"), "toy-5": (2600.0, None), "toy-6": (None, D.UNDECIDED_REFERENCE_STATUS),
             "toy-7": (2600.0, None)}
    printed = {"toy-1": (None, "Infeasible"), "toy-2": (None, "Infeasible or Unbounded"),
               "toy-3": (None, "Infeasible or Unbounded"), "toy-4": (None, "Local Infeasible"),
               "toy-5": (None, "Local Optimal"), "toy-6": (None, "Infeasible"), "toy-7": (2600.0, "Optimal")}
    with open(cases_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"_header": True, "source": "toy", "n": len(refs_)}) + "\n")
        for cid, (obj, st) in refs_.items():
            f.write(json.dumps({"case_id": cid, "source": "toy", "text": f"self-made toy case {cid}",
                                "reference": {"objective": obj, "raw": st or str(obj), "status": st}}) + "\n")
    run = tmp_path / "run"
    run.mkdir()
    write_jsonl(str(run / "final.X.jsonl"), [
        {"case_id": cid, "repeat": 0, "condition": "X", "round": 0,
         "exec": {"exec_ok": True, "protocol_ok": True, "objective": obj, "status": st, "seconds": 0.1},
         "hard_failed_genes": [], "soft_failed_genes": [], "rounds": [], "provisional": False}
        for cid, (obj, st) in printed.items()])
    cases = {c["case_id"]: c for c in D.load_cases(str(cases_path))}
    m = P.score_condition(str(run), "X", cases)
    rows = {r["case_id"]: r for r in read_jsonl(str(run / "results.X.jsonl"))}
    want = {  # correct, reason, status_category, status_undecided, reference_category
        "toy-1": (True, "status_match", "infeasible", False, "infeasible"),
        "toy-2": (False, "status_undecided", "infeasible_or_unbounded", True, "infeasible"),
        "toy-3": (False, "status_undecided", "infeasible_or_unbounded", True, "unbounded"),
        "toy-4": (False, "status_undecided", "local_infeasible", True, "infeasible"),
        "toy-5": (False, "no_objective", "local_optimal", True, "numeric"),
        "toy-6": (False, "reference_undecided", "infeasible", False, "infeasible_or_unbounded"),
        "toy-7": (True, "match", "optimal", False, "numeric"),
    }
    for cid, w in want.items():
        r = rows[cid]
        got = (r["correct"], r["reason"], r["status_category"], r["status_undecided"], r["reference_category"])
        assert got == w, cid
        assert r["correct_original_ref"] == r["correct"] == r["correct_tol"]["0.0001"]
        assert all(v == r["correct"] for v in r["correct_tol"].values()) or r["reference_category"] == "numeric"
    assert m["n_correct"] == 2 and m["n_status_undecided"] == 4
    assert m["by_source"]["toy"]["n_status_undecided"] == 4


def test_the_rule_is_part_of_the_rules_digest():
    rule = R.SCORING_RULES["non_numeric_reference"]
    assert rule["categories"] == list(SC.STATUS_CATEGORIES)
    assert rule["matched_by_the_same_category_only"] == ["infeasible", "unbounded"]
    assert rule["never_matching"] == ["infeasible_or_unbounded", "local_optimal", "local_infeasible", "local_other"]

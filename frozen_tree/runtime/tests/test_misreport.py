"""E12: misreport flags, verified accuracy, and their place in pipeline.score_condition.

Fixtures are self-made small programs (solve_fixtures.py); no benchmark case is read.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import solve_fixtures as FX  # noqa: E402

from orgene import misreport as MR  # noqa: E402
from orgene import pipeline as P  # noqa: E402
from orgene import score as S  # noqa: E402
from orgene.conditions import read_jsonl, write_jsonl  # noqa: E402
from orgene.execute import run_program  # noqa: E402

needs_py = pytest.mark.skipif(not os.path.exists(FX.PY), reason=f"generation interpreter {FX.PY} not present")


# ------------------------------------------------------------------ the six fixtures and the negative controls


@needs_py
@pytest.mark.parametrize("name,code,expected", FX.SIX_FIXTURES, ids=[f[0] for f in FX.SIX_FIXTURES])
def test_six_fixtures_set_the_expected_flags(name, code, expected):
    r = run_program(code, timeout=60)
    assert r["exec_ok"] and r["protocol_ok"], r["stderr_tail"]
    mr = S.misreport(r)
    assert mr["recorded"] is True
    assert {k: mr[k] for k in MR.FLAGS} == expected, mr
    assert mr["any_misreport"] is (name not in ("honest", "two_models"))


@needs_py
@pytest.mark.parametrize("name,code,expected", FX.NEGATIVE_CONTROLS, ids=[f[0] for f in FX.NEGATIVE_CONTROLS])
def test_honest_variants_raise_no_flag(name, code, expected):
    mr = S.misreport(run_program(code, timeout=60))
    assert mr["recorded"] is True
    assert {k: mr[k] for k in MR.FLAGS} == expected, mr
    assert mr["any_misreport"] is False


@needs_py
def test_flags_after_a_crash_timeout_or_fallback(tmp_path):
    # printed a result, then crashed: still compared with the solve
    mr = S.misreport(run_program(FX.LITERAL + "raise RuntimeError('late')\n", timeout=60))
    assert mr["objective_misreport"] is True
    # does not compile: never ran, printed nothing, no flag
    mr = S.misreport(run_program(FX.ERRORS["syntax_error"], timeout=30))
    assert mr["recorded"] is True and mr["any_misreport"] is False and mr["n_solves"] == 0
    # no solver back end could be hooked: no complete record, no flags
    mr = S.misreport(run_program(FX.HONEST, timeout=60, python=FX.no_pulp_python(tmp_path)))
    assert mr["recorded"] is False and all(mr[k] is None for k in MR.FLAGS)


# ------------------------------------------------------------------ logic on synthetic execution results


def _ex(status, objective, solves, n_problems=1, recorded=True):
    return {"status": status, "objective": objective, "solve_records": solves,
            "solve_recorder": {"recorded": recorded, "n_solves": len(solves), "n_problems": n_problems}}


def test_objective_tolerance_boundaries():
    last = [{"status": "Optimal", "status_code": 1, "objective": 1024.0}]
    # default tolerance max(1e-4, 1e-4 * 1024) = 0.1024
    assert MR.misreport(_ex("Optimal", 1024.0625, last))["objective_misreport"] is False
    assert MR.misreport(_ex("Optimal", 1024.125, last))["objective_misreport"] is True
    # exactly at the tolerance is not a misreport; just above is (relative part)
    two = [{"status": "Optimal", "objective": 2.0}]
    assert MR.misreport(_ex("Optimal", 2.5, two), rel_tol=0.25, abs_tol=0.25)["objective_misreport"] is False
    assert MR.misreport(_ex("Optimal", 2.5000001, two), rel_tol=0.25, abs_tol=0.25)["objective_misreport"] is True
    # absolute part near zero
    zero = [{"status": "Optimal", "objective": 0.0}]
    assert MR.misreport(_ex("Optimal", 0.25, zero), rel_tol=0.25, abs_tol=0.25)["objective_misreport"] is False
    assert MR.misreport(_ex("Optimal", 0.26, zero), rel_tol=0.25, abs_tol=0.25)["objective_misreport"] is True
    assert MR.misreport(_ex("Optimal", 1024.0625, last))["objective_abs_diff"] == 0.0625


def test_rounding_is_told_apart_from_a_different_number():
    last = [{"status": "Optimal", "objective": 12.333333}]
    for printed in (12.0, 12.3, 12.33):  # round(v), round(v, 1), round(v, 2)
        mr = MR.misreport(_ex("Optimal", printed, last))
        assert mr["objective_misreport"] is True and mr["objective_rounding_only"] is True, printed
    trunc = [{"status": "Optimal", "objective": 7.89}]
    assert MR.misreport(_ex("Optimal", 7.0, trunc))["objective_rounding_only"] is True  # int(v)
    assert MR.misreport(_ex("Optimal", 7.8, trunc))["objective_rounding_only"] is True  # truncated to 1 decimal
    for printed in (13.0, 11.0, 24.666666):
        assert MR.misreport(_ex("Optimal", printed, last))["objective_rounding_only"] is False, printed
    assert MR.misreport(_ex("Optimal", 12.333333, last))["objective_rounding_only"] is None  # no misreport at all
    rows = [MR.misreport_row(_ex("Optimal", 12.0, last), False), MR.misreport_row(_ex("Optimal", 13.0, last), False)]
    s = MR.summarize_misreport(rows)
    assert s["objective_misreport"] == 2 and s["objective_misreport_rounding_only"] == 1


FRACTIONAL = """import pulp
prob = pulp.LpProblem("frac", pulp.LpMaximize)
a = pulp.LpVariable("a", lowBound=0)
prob += a
prob += 3 * a <= 37
prob.solve(pulp.PULP_CBC_CMD(msg=0))
print("STATUS:", pulp.LpStatus[prob.status])
print("FINAL_OBJECTIVE:", round(pulp.value(prob.objective)))
"""


@needs_py
def test_rounded_print_of_a_fractional_optimum_is_a_rounding_only_misreport():
    mr = S.misreport(run_program(FRACTIONAL, timeout=60))  # optimum 37/3, printed 12
    assert mr["objective_misreport"] is True and mr["objective_rounding_only"] is True
    mr = S.misreport(run_program(FRACTIONAL.replace("round(pulp.value(prob.objective))", "13"), timeout=60))
    assert mr["objective_misreport"] is True and mr["objective_rounding_only"] is False


def test_status_matching_rules():
    rec = [{"status": "Optimal", "status_code": 1, "sol_status": "Optimal Solution Found", "objective": 5.0}]
    for printed in ("Optimal", "OPTIMAL", " optimal ", "1", "Optimal Solution Found"):
        assert MR.misreport(_ex(printed, 5.0, rec))["status_misreport"] is False, printed
    for printed in ("Infeasible", "Not Solved", "-1", "Feasible"):
        assert MR.misreport(_ex(printed, 5.0, rec))["status_misreport"] is True, printed
    assert MR.misreport(_ex(None, 5.0, rec))["status_misreport"] is None
    copt = [{"status": "INF_OR_UNB", "status_code": 4}]
    assert MR.misreport(_ex("infeasibleOrUnbounded", None, copt))["status_misreport"] is False


def test_the_last_solve_is_the_reference():
    solves = [{"status": "Optimal", "objective": 7.0, "problem_ordinal": 1},
              {"status": "Optimal", "objective": 3.0, "problem_ordinal": 2}]
    mr = MR.misreport(_ex("Optimal", 7.0, solves, n_problems=2))
    assert mr["objective_misreport"] is True and mr["multi_problem"] is True and mr["last_objective"] == 3.0
    assert MR.misreport(_ex("Optimal", 3.0, solves, n_problems=2))["objective_misreport"] is False


def test_objective_claim_without_a_solver_value_is_a_misreport():
    rec = [{"status": "Infeasible", "objective": None}]
    assert MR.misreport(_ex("Infeasible", 7.0, rec))["objective_misreport"] is True
    assert MR.misreport(_ex("Infeasible", None, rec))["objective_misreport"] is False


def test_reported_without_solve_rules():
    assert MR.misreport(_ex("Optimal", None, []))["reported_without_solve"] is True
    assert MR.misreport(_ex(None, 12.0, []))["reported_without_solve"] is True
    assert MR.misreport(_ex("Not Solved", None, []))["reported_without_solve"] is False
    assert MR.misreport(_ex(None, None, []))["reported_without_solve"] is False


def test_capped_record_gives_no_status_or_objective_verdict():
    ex = _ex("Optimal", 5.0, [{"status": "Optimal", "objective": 1.0}], n_problems=3)
    ex["solve_recorder"].update(capped=True, n_solves=6000)
    mr = MR.misreport(ex)
    assert mr["status_misreport"] is None and mr["objective_misreport"] is None and mr["multi_problem"] is True
    assert MR.verified_correct(True, mr) is False


def test_not_recorded_gives_none_everywhere():
    for ex in (None, {}, {"status": "Optimal", "objective": 1.0}, _ex("Optimal", 1.0, [], recorded=False)):
        mr = MR.misreport(ex)
        assert mr["recorded"] is False and all(mr[k] is None for k in MR.FLAGS) and mr["any_misreport"] is None
        assert MR.verified_correct(True, mr) is None


def test_verified_correct_needs_both_correct_and_consistent():
    good = MR.misreport(_ex("Optimal", 5.0, [{"status": "Optimal", "objective": 5.0}]))
    bad = MR.misreport(_ex("Optimal", 6.0, [{"status": "Optimal", "objective": 5.0}]))
    none = MR.misreport(_ex("Optimal", 5.0, []))
    assert MR.verified_correct(True, good) is True and MR.verified_correct(False, good) is False
    assert MR.verified_correct(True, bad) is False and MR.verified_correct(True, none) is False
    assert S.misreport is MR.misreport and S.summarize_misreport is MR.summarize_misreport


def test_summary_counts_and_rates():
    rows = [MR.misreport_row(_ex("Optimal", 5.0, [{"status": "Optimal", "objective": 5.0}]), True),
            MR.misreport_row(_ex("Optimal", 6.0, [{"status": "Optimal", "objective": 5.0}]), True),
            MR.misreport_row(_ex("Optimal", 5.0, []), False),
            MR.misreport_row({}, False)]
    s = MR.summarize_misreport(rows)
    assert (s["n"], s["n_recorded"], s["n_not_recorded"], s["n_with_solve"]) == (4, 3, 1, 2)
    assert (s["objective_misreport"], s["reported_without_solve"], s["any_misreport"]) == (1, 1, 2)
    assert s["any_misreport_rate"] == round(2 / 3, 4) and s["n_verified_correct"] == 1 and s["verified_accuracy"] == 0.25
    assert MR.summarize_misreport([])["verified_accuracy"] is None


# ------------------------------------------------------------------ scoring integration


@needs_py
def test_score_condition_adds_flags_and_verified_accuracy(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    progs = {"fx-honest": (FX.HONEST, 2600.0), "fx-literal": (FX.LITERAL, 3000.0), "fx-never": (FX.NEVER_SOLVES, 2600.0)}
    final, cases = [], {}
    for cid, (code, ref) in progs.items():
        ex = run_program(code, timeout=60)
        cases[cid] = {"case_id": cid, "source": "fixture", "reference": {"objective": ref, "status": None}}
        final.append({"case_id": cid, "repeat": 0, "condition": "C0", "exec": ex, "hard_failed_genes": [],
                      "soft_failed_genes": [], "rounds": [{"round": 0, "out_tokens": 1, "in_tokens": 1,
                                                            "hard_failed_genes": []}]})
    write_jsonl(str(run / "final.C0.jsonl"), final)
    m = P.score_condition(str(run), "C0", cases)
    assert m["accuracy"] == 1.0 and m["n_correct"] == 3  # main score unchanged: printed values
    mm = m["misreport"]
    assert mm["n_recorded"] == 3 and mm["objective_misreport"] == 1 and mm["reported_without_solve"] == 1
    assert mm["any_misreport"] == 2 and mm["n_verified_correct"] == 1 and mm["verified_accuracy"] == round(1 / 3, 4)
    assert m["by_source"]["fixture"]["misreport"]["n_verified_correct"] == 1
    rows = {r["case_id"]: r for r in read_jsonl(str(run / "results.C0.jsonl"))}
    assert rows["fx-honest"]["verified_correct"] is True and rows["fx-literal"]["verified_correct"] is False
    assert rows["fx-never"]["misreport"]["reported_without_solve"] is True
    assert all(rows[c]["correct"] is True for c in rows)


def test_score_condition_on_old_records_without_a_recorder(tmp_path):
    """v5-style final records (no solve_records) still score; the flags are None, not False."""
    run = tmp_path / "run"
    run.mkdir()
    ex = {"exec_ok": True, "protocol_ok": True, "status": "Optimal", "objective": 2600.0, "seconds": 0.1}
    write_jsonl(str(run / "final.C0.jsonl"), [{"case_id": "fx-old", "repeat": 0, "exec": ex, "rounds": [
        {"round": 0, "out_tokens": 1, "in_tokens": 1, "hard_failed_genes": []}]}])
    cases = {"fx-old": {"case_id": "fx-old", "source": "fixture", "reference": {"objective": 2600.0, "status": None}}}
    m = P.score_condition(str(run), "C0", cases)
    assert m["accuracy"] == 1.0 and m["misreport"]["n_recorded"] == 0 and m["misreport"]["n_verified_correct"] == 0
    (row,) = read_jsonl(str(run / "results.C0.jsonl"))
    assert row["verified_correct"] is None and row["misreport"]["status_misreport"] is None

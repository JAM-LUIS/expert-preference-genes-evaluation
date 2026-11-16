"""Misreport flags and verified accuracy (E12).

The main score still uses what the program printed (FINAL_OBJECTIVE / STATUS; v5 D4). This module compares the
printed lines with the solver calls the solve recorder saw (execute.run_program(record_solves=True)):

  status_misreport        the printed STATUS differs from the status of the last solve
                          (None: no solve, or no STATUS line printed)
  objective_misreport     the printed FINAL_OBJECTIVE is a number that differs from the last solve's objective by
                          more than max(abs_tol, rel_tol * |solver value|), default 1e-4 / 1e-4, or the last solve
                          has no objective value (None: no solve; False: no number printed)
  reported_without_solve  a number, or a status other than "Not Solved", was printed but no recorded solver call
                          was made (recorded back ends: PuLP; Pyomo / coptpy when installed)
  multi_problem           the program solved more than one distinct problem object

A printed status matches when it equals, after normalisation (case, spaces, punctuation), the solver's status name,
its solution-status name (PuLP LpSolution), or its numeric code. "Verified correct" = correct by the main score AND
the printed lines agree with the last solve (at least one solve, no status or objective misreport).

objective_rounding_only (reported alongside, not a fifth flag): the objective misreport is only the solver value
rounded or truncated to 0-6 decimals (e.g. print(round(value))), as opposed to a different number.

All flags are None when there is no complete solve record for the execution (no program, recorder off, recorder
fell back to the plain interpreter).
"""
import math
import re

FLAGS = ("status_misreport", "objective_misreport", "reported_without_solve", "multi_problem")
_ALIASES = {"inforunb": "infeasibleorunbounded"}
_NOT_SOLVED = {"", "notsolved", "unstarted", "na", "none"}


def canonical_status(s):
    if s is None:
        return None
    t = re.sub(r"[^a-z0-9]", "", str(s).lower())
    return _ALIASES.get(t, t)


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def status_matches(printed, rec):
    p = canonical_status(printed)
    names = {canonical_status(rec.get(k)) for k in ("status", "sol_status")} - {None}
    codes = {str(rec.get(k)) for k in ("status_code",) if rec.get(k) is not None}
    return p in names or (printed is not None and str(printed).strip() in codes)


def rounding_of(printed, solver_value, max_decimals=6):
    """True when `printed` is `solver_value` rounded or truncated to 0..max_decimals decimals."""
    if not (_finite(printed) and _finite(solver_value)):
        return False
    for k in range(max_decimals + 1):
        f = 10 ** k
        for cand in (round(solver_value, k), math.trunc(solver_value * f) / f):
            if abs(printed - cand) <= 1e-9 * max(1.0, abs(cand)):
                return True
    return False


def misreport(exec_result, rel_tol=1e-4, abs_tol=1e-4):
    """Flags for one execution result (the `exec` dict of a validated / final record)."""
    ex = exec_result or {}
    summ = ex.get("solve_recorder") or {}
    recs = ex.get("solve_records") or []
    printed_status = ex.get("status")
    printed_obj = ex.get("objective")
    out = {"recorded": bool(summ.get("recorded")), "n_solves": None, "n_problems": None,
           "last_status": None, "last_objective": None, "last_error": None,
           "printed_status": printed_status, "printed_objective": printed_obj,
           "objective_abs_diff": None, "objective_rounding_only": None, "consistent": None, "any_misreport": None,
           "unrecorded_solver_modules": summ.get("other_solver_modules")}
    for k in FLAGS:
        out[k] = None
    if not out["recorded"]:
        return out
    n = int(summ.get("n_solves") or 0)
    out["n_solves"] = n
    out["n_problems"] = int(summ.get("n_problems") or 0)
    out["multi_problem"] = out["n_problems"] > 1
    if n == 0:
        claims_status = canonical_status(printed_status) not in (_NOT_SOLVED | {None})
        out["reported_without_solve"] = _finite(printed_obj) or claims_status
        out["any_misreport"] = out["reported_without_solve"]
        out["consistent"] = False
        return out
    if not recs or summ.get("capped"):  # past the recorder's line cap the last solve is not in the record
        return out
    last = recs[-1]
    out["reported_without_solve"] = False
    out["last_status"] = last.get("status")
    out["last_objective"] = last.get("objective")
    out["last_error"] = (last.get("error") or {}).get("type") if last.get("error") else None
    if printed_status is not None:
        out["status_misreport"] = not status_matches(printed_status, last)
    if not _finite(printed_obj):
        out["objective_misreport"] = False
    else:
        s = last.get("objective")
        if not _finite(s):
            out["objective_misreport"] = True
        else:
            d = abs(printed_obj - s)
            out["objective_abs_diff"] = d
            out["objective_misreport"] = d > max(abs_tol, rel_tol * abs(s))
            if out["objective_misreport"]:
                out["objective_rounding_only"] = rounding_of(printed_obj, s)
    out["any_misreport"] = bool(out["status_misreport"]) or bool(out["objective_misreport"])
    out["consistent"] = not out["any_misreport"]
    return out


def verified_correct(correct, mr):
    """Correct by the main score, and the printed lines agree with the solver record. None when not recorded."""
    if not mr or not mr.get("recorded"):
        return None
    return bool(correct) and bool(mr.get("consistent"))


def misreport_row(exec_result, correct, rel_tol=1e-4, abs_tol=1e-4):
    """Fields added to each results row by pipeline.score_condition."""
    mr = misreport(exec_result, rel_tol=rel_tol, abs_tol=abs_tol)
    return {"misreport": mr, "verified_correct": verified_correct(correct, mr)}


def summarize_misreport(rows):
    """Counts and rates over rows that carry `misreport` (rates over rows with a complete solve record)."""
    n = len(rows)
    mrs = [r.get("misreport") or {} for r in rows]
    rec = [m for m in mrs if m.get("recorded")]
    k = len(rec)
    out = {"n": n, "n_recorded": k, "n_not_recorded": n - k,
           "n_with_solve": sum(1 for m in rec if (m.get("n_solves") or 0) > 0)}
    for f in FLAGS + ("any_misreport",):
        c = sum(1 for m in rec if m.get(f) is True)
        out[f] = c
        out[f + "_rate"] = round(c / k, 4) if k else None
    out["objective_misreport_rounding_only"] = sum(1 for m in rec if m.get("objective_rounding_only") is True)
    nv = sum(1 for r in rows if r.get("verified_correct") is True)
    out["n_verified_correct"] = nv
    out["verified_accuracy"] = round(nv / n, 4) if n else None
    return out

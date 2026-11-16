"""Execution-accuracy scoring against benchmark reference objectives."""
import math
import re

from .misreport import misreport, misreport_row, summarize_misreport, verified_correct  # noqa: F401  (E12)

NON_NUMERIC_STATUSES = {"infeasible", "unbounded", "no feasible solution", "no solution"}

# Status categories (scoring rule fixed before the freeze, 2026-09-29). A printed STATUS and a non-numeric reference
# are both reduced to one category; a non-numeric reference is matched only by a printed status of exactly its
# category, and only the decided categories (infeasible, unbounded) can be matched. A status that leaves the outcome
# open never matches: "infeasible or unbounded" (COPT INF_OR_UNB, Pyomo infeasibleOrUnbounded, "No Best Solution") and
# local results (COPT LOCAL_OPTIMAL / LOCAL_INFEASIBLE, Pyomo locallyOptimal); result rows mark them (status_undecided,
# refs.reference_fields). "infeasible" / "unbounded" are found as substrings of the lower-cased text, as in the earlier
# rule, so every status word a PuLP program prints keeps its judgement. A numeric reference is still judged by the
# printed objective alone.
STATUS_CATEGORIES = ("optimal", "infeasible", "unbounded", "infeasible_or_unbounded", "local_optimal",
                     "local_infeasible", "local_other", "other")
MATCHABLE_STATUS_CATEGORIES = ("infeasible", "unbounded")
UNDECIDED_STATUS_CATEGORIES = ("infeasible_or_unbounded", "local_optimal", "local_infeasible", "local_other")
# COPT's constant name INF_OR_UNB, and phrases that state only that there is no optimal solution ("No Best Solution" is
# what ORLM's evaluation prints for every non-optimal COPT status)
_UNDECIDED_KEYS = ("inforunb", "nobestsolution", "nooptimalsolution")
_OPTIMAL_KEYS = ("optimal", "optimalsolutionfound", "globallyoptimal")


def status_category(status):
    """The category (STATUS_CATEGORIES) of a status word: a printed STATUS or a non-numeric reference; None if empty."""
    if status is None:
        return None
    low = str(status).strip().lower()
    key = re.sub(r"[^a-z0-9]", "", low)
    if not key:
        return None
    if key.startswith("local"):
        return "local_infeasible" if "infeasible" in key else "local_optimal" if "optimal" in key else "local_other"
    infeasible, unbounded = "infeasible" in low, "unbounded" in low
    if (infeasible and unbounded) or any(k in key for k in _UNDECIDED_KEYS):
        return "infeasible_or_unbounded"
    if infeasible:
        return "infeasible"
    if unbounded:
        return "unbounded"
    return "optimal" if key in _OPTIMAL_KEYS else "other"


def reference_category(reference_objective, reference_status=None):
    """"numeric" for a numeric reference, else the category of its status word (None when there is neither)."""
    if reference_objective is not None:
        return "numeric"
    return status_category(reference_status)


def is_correct(objective, reference_objective, reference_status=None, rel_tol=1e-4, abs_tol=1e-4, status=None, tol=None,
               reference_interval=None):
    """Return (correct: bool, reason: str). Correct when |obj - ref| <= max(abs_tol, rel_tol * |ref|); with a
    reference_interval, when obj lies in the interval widened at each end (in_reference_interval).

    `tol` sets the absolute and the relative tolerance to the same value (the E13 tiers); it overrides rel_tol/abs_tol.
    A non-numeric reference is matched by the printed status's category (status_category): same category, and only
    infeasible or unbounded; an undecided printed status (infeasible_or_unbounded, local_*) never matches.
    """
    if tol is not None:
        rel_tol = abs_tol = tol
    if reference_objective is None:
        # non-numeric reference (e.g. "infeasible"): compare the categories of the status words
        if reference_status and status:
            ref_cat, cat = status_category(reference_status), status_category(status)
            if ref_cat in UNDECIDED_STATUS_CATEGORIES:
                return False, "reference_undecided"
            if ref_cat not in MATCHABLE_STATUS_CATEGORIES:
                return False, "reference_not_numeric"
            if cat in UNDECIDED_STATUS_CATEGORIES:
                return False, "status_undecided"
            ok = cat == ref_cat
            return ok, "status_match" if ok else "status_mismatch"
        return False, "reference_not_numeric"
    if objective is None or (isinstance(objective, float) and (math.isnan(objective) or math.isinf(objective))):
        return False, "no_objective"
    if reference_interval is not None:  # E22: a time-limited reference, the optimum lies in [bound, best value]
        ok = in_reference_interval(objective, reference_interval, rel_tol, abs_tol)
        return ok, "interval_match" if ok else "outside_interval"
    tol = max(abs_tol, rel_tol * abs(reference_objective))
    if abs(objective - reference_objective) <= tol:
        return True, "match"
    return False, "objective_mismatch"


# E13: three tolerance tiers, absolute = relative tolerance at each tier. `correct` stays on the primary tier
# |obj - ref| <= max(1e-4, 1e-4 * |ref|); the other tiers are a preregistered sensitivity analysis.
TOLERANCES = (1e-6, 1e-4, 1e-2)
PRIMARY_TOL = 1e-4


def tol_key(t):
    """Key of a tier in result rows and metrics: "1e-06", "0.0001", "0.01"."""
    return str(float(t))


def correct_by_tol(objective, reference_objective, reference_status=None, status=None, tols=TOLERANCES,
                   reference_interval=None):
    """{tol_key(t): correct at tier t} for each tier (an interval reference is widened by each tier's tolerance)."""
    return {tol_key(t): is_correct(objective, reference_objective, reference_status, status=status, tol=t,
                                   reference_interval=reference_interval)[0] for t in tols}


def in_reference_interval(objective, interval, rel_tol=PRIMARY_TOL, abs_tol=PRIMARY_TOL):
    """E22 rule for a time-limited reference (reference kind cbc_time_limited): CBC stopped at its time limit with a
    best value and a proved bound, so the optimum is only known to lie between them. A printed objective agrees with
    the reference when lo - max(abs_tol, rel_tol*|lo|) <= obj <= hi + max(abs_tol, rel_tol*|hi|), lo and hi the
    interval ends: each end is widened by the same tolerance form as a point reference."""
    if objective is None or (isinstance(objective, float) and (math.isnan(objective) or math.isinf(objective))):
        return False
    lo, hi = sorted(float(x) for x in interval)
    return lo - max(abs_tol, rel_tol * abs(lo)) <= objective <= hi + max(abs_tol, rel_tol * abs(hi))


def summarize(rows):
    """rows: list of result dicts with keys exec_ok, correct, status, out_tokens, repair_rounds_used, hard_issue_count_round0."""
    n = len(rows)
    if n == 0:
        return {"n": 0}
    def frac(k):
        return round(sum(1 for r in rows if r.get(k)) / n, 4)
    statuses = {}
    for r in rows:
        s = (r.get("status") or "none").lower()
        statuses[s] = statuses.get(s, 0) + 1
    toks = [r.get("out_tokens") for r in rows if isinstance(r.get("out_tokens"), (int, float))]
    calls = [r.get("n_calls", 1) for r in rows]
    return {
        "n": n,
        "exec_rate": frac("exec_ok"),
        "protocol_rate": frac("protocol_ok"),
        "accuracy": frac("correct"),
        "n_correct": sum(1 for r in rows if r.get("correct")),
        "status_counts": statuses,
        "mean_out_tokens": round(sum(toks) / len(toks), 1) if toks else None,
        "mean_calls": round(sum(calls) / len(calls), 3),
        "repaired_cases": sum(1 for r in rows if (r.get("repair_rounds_used") or 0) > 0),
        "hard_issues_round0": sum(r.get("hard_issue_count_round0") or 0 for r in rows),
    }

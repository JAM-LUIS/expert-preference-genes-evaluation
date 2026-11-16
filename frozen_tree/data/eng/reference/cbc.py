"""Solve a PuLP problem with CBC under a time limit and record what the reference needs (E22).

Isolation: this file holds no case content, but it lives under data/eng/, which the gene-writing sessions do not
open (data/cases/README_ISOLATION.md).

The record keeps: CBC version (from the solver log), the result line (optimal / stopped on time limit / ...), the
objective of the best solution found, the best bound CBC reports when it stops early, the relative gap, node count,
CPU and wall-clock seconds, and the solver options. No host path is recorded.
"""
import os
import re
import shutil
import tempfile
import time

import pulp

RESULT_RE = re.compile(r"^Result - (.+?)\s*$", re.MULTILINE)
VERSION_RE = re.compile(r"^Version:\s*(\S+)", re.MULTILINE)
FIELDS = {
    "objective": re.compile(r"^Objective value:\s+(\S+)", re.MULTILINE),
    "lower_bound": re.compile(r"^Lower bound:\s+(\S+)", re.MULTILINE),   # minimisation
    "upper_bound": re.compile(r"^Upper bound:\s+(\S+)", re.MULTILINE),   # maximisation
    "gap": re.compile(r"^Gap:\s+(\S+)", re.MULTILINE),
    "nodes": re.compile(r"^Enumerated nodes:\s+(\S+)", re.MULTILINE),
    "cpu_seconds": re.compile(r"^Time \(CPU seconds\):\s+(\S+)", re.MULTILINE),
    "wall_seconds_cbc": re.compile(r"^Time \(Wallclock seconds\):\s+(\S+)", re.MULTILINE),
}


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_log(text):
    """Fields of CBC's closing summary (the last one when the log holds several)."""
    out = {}
    m = RESULT_RE.findall(text)
    out["result"] = m[-1] if m else None
    v = VERSION_RE.search(text)
    out["cbc_version"] = v.group(1) if v else None
    for k, rx in FIELDS.items():
        found = rx.findall(text)
        out[k] = _num(found[-1]) if found else None
    # the best bound CBC proved when it stopped early (lower for a minimisation, upper for a maximisation)
    out["bound"] = out["lower_bound"] if out["lower_bound"] is not None else out["upper_bound"]
    r = (out["result"] or "").lower()
    if not r and re.search(r"^Problem is infeasible", text, re.MULTILINE):
        r = out["result"] = "problem is infeasible (presolve)"
    if r.startswith("optimal solution found"):
        out["status"] = "optimal"
    elif "time limit" in r or "stopped on time" in r:
        out["status"] = "time_limit_feasible" if out["objective"] is not None else "time_limit_no_solution"
    elif "infeasible" in r:
        out["status"] = "infeasible"
    elif "unbounded" in r:
        out["status"] = "unbounded"
    else:
        out["status"] = "other"
    return out


def relative_gap(objective, bound):
    """|incumbent - bound| / max(|incumbent|, 1e-10); None when either is missing."""
    if objective is None or bound is None:
        return None
    return abs(objective - bound) / max(abs(objective), 1e-10)


def solve(prob, time_limit_s, gap_rel=1e-7, threads=1, log_copy=None):
    """Solve `prob` with PuLP's CBC. Returns (record, variable values {name: value}).

    gap_rel is CBC's ratioGap: "optimal" means the incumbent is within gap_rel (relative) of the best bound.
    log_copy, when given, receives the full CBC log (kept out of git; it may name temporary files).
    """
    tmp = tempfile.mkdtemp(prefix="orgene_eng_cbc_")
    log_path = os.path.join(tmp, "cbc.log")
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit_s, gapRel=gap_rel, threads=threads,
                               logPath=log_path, keepFiles=False)
    t0 = time.time()
    status = prob.solve(solver)
    wall = time.time() - t0
    text = open(log_path, encoding="utf-8", errors="replace").read() if os.path.exists(log_path) else ""
    if log_copy:
        os.makedirs(os.path.dirname(os.path.abspath(log_copy)), exist_ok=True)
        with open(log_copy, "w", encoding="utf-8") as f:
            f.write(text)
    shutil.rmtree(tmp, ignore_errors=True)
    rec = parse_log(text)
    rec.update({
        "pulp_status": pulp.LpStatus.get(status, str(status)),
        "pulp_sol_status": getattr(prob, "sol_status", None),
        "pulp_objective": pulp.value(prob.objective),
        "wall_seconds": round(wall, 3),
        "options": {"time_limit_s": time_limit_s, "gap_rel": gap_rel, "threads": threads},
        "pulp_version": pulp.__version__,
        "n_variables": len(prob.variables()),
        "n_constraints": len(prob.constraints),
    })
    # CBC prints "Lower bound" and "Gap" only when it stops early; at "Optimal solution found" the incumbent is
    # within gap_rel of the bound by construction, which is what gap_at_most records.
    # CBC prints the gap rounded to two decimals ("Gap: 0.00" for 0.18 %); the record keeps that as gap_printed and
    # recomputes the relative gap from the incumbent and the bound.
    rec["gap_printed"] = rec.pop("gap")
    rec["gap"] = relative_gap(rec["objective"], rec["bound"])
    if rec["status"] == "optimal":
        rec["gap_at_most"] = gap_rel
    values = {v.name: v.varValue for v in prob.variables()}
    return rec, values

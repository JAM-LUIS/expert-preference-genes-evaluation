"""neos-3118745-obra: translation of the instance's solve.py (assign tasks to subcontractors under global and zone
limits; minimise C0001 = 1616 - total profit, the target hard-coded in solve.py)."""
import csv
import os

import pulp

from . import read_rows

TARGET_REVENUE = 1616.0  # solve.py constant (instance parameter Y)


def _matrix(path):
    with open(path, encoding="utf-8", newline="") as f:
        rd = csv.reader(f)
        header = next(rd)
        cols = [int(c) for c in header[1:]]
        rows = {int(r[0]): dict(zip(cols, (float(v) for v in r[1:]))) for r in rd}
    return cols, rows


REFERENCE_NOTE = (
    "reference solved on build_for_reference(): the script's model without the lower bound 0 of C0001 (a "
    "relaxation). The objective is C0001 itself, so an optimum >= 0 of the relaxation is feasible, hence optimal, in "
    "the script's model; solve.py checks this. With the bound, CBC 2.10.13 stopped at 1800 s with incumbent 257 and "
    "bound 254.845 (screening log); without it, it proves 255 in seconds.")


def build_for_reference(instance_dir):
    return build(instance_dir, c0001_lower_bound=None)


def reference_holds(record):
    """The relaxation's optimum carries over to the script's model only if it is >= 0."""
    return record.get("status") == "optimal" and record.get("objective") is not None and record["objective"] >= 0


def build(instance_dir, c0001_lower_bound=0):
    d = os.path.join(instance_dir, "data")
    capacity = {int(r["Subcontractor_ID"]): float(r["Capacity"]) for r in read_rows(os.path.join(d, "C1.csv"))}
    subs, profit = _matrix(os.path.join(d, "C2.csv"))
    _, glob_use = _matrix(os.path.join(d, "C3.csv"))
    _, loc_use = _matrix(os.path.join(d, "C4.csv"))
    tasks = list(profit)
    prob = pulp.LpProblem("neos_3118745_obra", pulp.LpMinimize)
    x = {(i, j): pulp.LpVariable(f"x_{i}_{j}", cat=pulp.LpBinary) for i in tasks for j in subs}
    c = pulp.LpVariable("C0001", lowBound=c0001_lower_bound)  # gurobipy addVar: lower bound 0 by default
    prob += c
    prob += c + pulp.lpSum(profit[i][j] * x[i, j] for i in tasks for j in subs) == TARGET_REVENUE, "ProfitDefinition"
    for i in tasks:
        prob += pulp.lpSum(x[i, j] for j in subs) <= 1, f"AssignOnce_{i}"
    for j in subs:
        prob += pulp.lpSum(glob_use[i][j] * x[i, j] for i in tasks) <= capacity[j], f"GlobalCapacity_{j}"
    for r in read_rows(os.path.join(d, "C5.csv")):
        zt = [t for t in tasks if int(r["Start_Task_ID"]) <= t <= int(r["End_Task_ID"])]
        if not zt:
            continue
        prob += pulp.lpSum(loc_use[i][j] * x[i, j] for i in zt for j in subs) <= float(r["Local_Resource_Limit"]), f"ZoneLimit_{r['Zone_ID']}"
    return prob

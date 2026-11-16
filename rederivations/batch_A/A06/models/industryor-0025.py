#!/usr/bin/env python3
# industryor-0025: a_t = amount put in the 1-year option at start of year t (t=1,2,3) -> 1.7 per yuan after 1 year
# b_t = amount put in the 2-year option at start of year t (t=1,2) -> 3 per yuan after 2 years. Idle cash allowed.
# MODE "wealth": maximise money held at the end of year 3; MODE "profit": that minus the 100000 principal.
import pulp, sys

def report(m, extra=None):
    status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
    print("STATUS:", status); print("SOLUTION_STATUS:", sol)
    if status == "Optimal" and sol == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective) if extra is None else extra)
        for v in m.variables():
            if v.varValue and abs(v.varValue) > 1e-9: print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
SOLVER = lambda: pulp.PULP_CBC_CMD(msg=False, timeLimit=600)
def relax_and_report(m):
    to_relax = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
    for v in to_relax: v.cat = pulp.LpContinuous
    m.solve(SOLVER())
    print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
    for v in to_relax: v.cat = pulp.LpInteger

MODE = "wealth"
m = pulp.LpProblem("p", pulp.LpMaximize)
a = {t: pulp.LpVariable(f"a{t}", lowBound=0) for t in (1, 2, 3)}
b = {t: pulp.LpVariable(f"b{t}", lowBound=0) for t in (1, 2)}
c = {t: pulp.LpVariable(f"cash{t}", lowBound=0) for t in (1, 2, 3)}
final = 1.7 * a[3] + 3 * b[2] + c[3]
m += final - (100000 if MODE == "profit" else 0)
m += a[1] + b[1] + c[1] == 100000
m += a[2] + b[2] + c[2] == 1.7 * a[1] + c[1]
m += a[3] + c[3] == 1.7 * a[2] + 3 * b[1] + c[2]
m.solve(SOLVER())
report(m)

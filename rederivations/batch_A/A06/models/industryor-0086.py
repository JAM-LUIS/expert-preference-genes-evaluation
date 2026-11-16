#!/usr/bin/env python3
# industryor-0086: M, Y packs per month (continuous main; integer variant printed as a check).
import pulp

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

m = pulp.LpProblem("p", pulp.LpMaximize)
M = pulp.LpVariable("Meaties", 0); Y = pulp.LpVariable("Yummies", 0)
m += (2.80 - 2 * 0.20 - 3 * 0.50 - 0.25) * M + (2.00 - 3 * 0.20 - 1.5 * 0.50 - 0.20) * Y
m += 2 * M + 3 * Y <= 400000
m += 3 * M + 1.5 * Y <= 300000
m += M <= 90000
m.solve(SOLVER())
report(m)
M.cat = pulp.LpInteger; Y.cat = pulp.LpInteger
m.solve(SOLVER()); print("INTEGER_VARIANT:", pulp.LpStatus[m.status], pulp.value(m.objective))

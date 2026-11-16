#!/usr/bin/env python3
# industryor-0093: dairy plan
import pulp

def report(m, relax=False):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
    print("STATUS:", status); print("SOLUTION_STATUS:", sol)
    if status == "Optimal" and sol == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue and abs(v.varValue) > 1e-9: print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
    if relax:
        tr = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
        for v in tr: v.cat = pulp.LpContinuous
        m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
        print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), f"({len(tr)} general-integer variables made continuous; binaries kept)")
        for v in tr: v.cat = pulp.LpInteger

m = pulp.LpProblem("io0093", pulp.LpMaximize)
x1 = pulp.LpVariable("barrels_to_A1", 0); x2 = pulp.LpVariable("barrels_to_A2", 0)
m += 24 * 3 * x1 + 16 * 4 * x2
m += x1 + x2 <= 50, "milk"
m += 12 * x1 + 8 * x2 <= 480, "labour"
m += 3 * x1 <= 100, "equipA"
report(m)

#!/usr/bin/env python3
# industryor-0002: pilots trained in 2 years. PERSIST=False (training jets of year 1 keep training in year 2)
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

PERSIST = False
a = {1: 10, 2: 15}
m = pulp.LpProblem("io0002", pulp.LpMaximize)
x = pulp.LpVariable.dicts("train_jets_from_year", [1, 2], 0, cat="Integer")  # jets of year-j production put to training
m += x[1] <= a[1]; m += x[2] <= a[2]
pil1 = 5 * x[1]
pil2 = 5 * (x[1] + x[2]) if PERSIST else 5 * x[2]
m += pil1 + pil2, "pilots_end_year2"
report(m)

#!/usr/bin/env python3
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

# Assign 10 parts to machines A/B/C with one-time setup costs.
Mch = ["A", "B", "C"]; Pt = range(1, 11)
c = {"A": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
     "B": [15, 25, 35, 45, 55, 65, 75, 85, 95, 105],
     "C": [20, 30, 40, 50, 60, 70, 80, 90, 100, 110]}
setup = {"A": 100, "B": 135, "C": 200}
m = pulp.LpProblem("p0077", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", (Mch, Pt), cat="Binary")
y = pulp.LpVariable.dicts("y", Mch, cat="Binary")
m += pulp.lpSum(c[k][j - 1] * x[k][j] for k in Mch for j in Pt) + pulp.lpSum(setup[k] * y[k] for k in Mch)
for j in Pt:
    m += pulp.lpSum(x[k][j] for k in Mch) == 1
    for k in Mch:
        m += x[k][j] <= y[k]
m += x["A"][1] + x["A"][2] == 1          # requirement 2: exactly one of parts 1, 2 on A
m += x["A"][3] == 1; m += x["B"][4] == 1; m += x["C"][5] == 1   # requirement 3
m += pulp.lpSum(x["C"][j] for j in Pt) <= 3
report(m)

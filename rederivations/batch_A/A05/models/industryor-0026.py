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

# Cyclic shift covering: 6 four-hour periods, each shift covers its start period and the next one.
need = [10, 15, 25, 20, 18, 12]   # periods starting 2:00, 6:00, 10:00, 14:00, 18:00, 22:00
K = range(6)
m = pulp.LpProblem("p0026", pulp.LpMinimize)
x = pulp.LpVariable.dicts("start", K, lowBound=0, cat="Integer")
m += pulp.lpSum(x[k] for k in K)
for k in K:
    m += x[k] + x[(k - 1) % 6] >= need[k]
report(m)

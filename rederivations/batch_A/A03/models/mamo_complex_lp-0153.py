#!/usr/bin/env python3
# mamo_complex_lp-0153: capacitated facility location
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

C = [1, 2, 3, 4]; S = [1, 2, 3, 4]
openc = {1: 151000, 2: 192000, 3: 114000, 4: 171000}
tc = {1: [5, 5, 2, 3], 2: [3, 3, 5, 4], 3: [3, 5, 2, 4], 4: [2, 4, 5, 1]}
dem = {1: 859, 2: 713, 3: 421, 4: 652}
cap = {1: 1547, 2: 1656, 3: 1274, 4: 1882}
m = pulp.LpProblem("mamo0153", pulp.LpMinimize)
y = pulp.LpVariable.dicts("open", C, cat="Binary")
x = pulp.LpVariable.dicts("ship", (C, S), 0)
m += pulp.lpSum(openc[i] * y[i] for i in C) + pulp.lpSum(tc[i][j - 1] * x[i][j] for i in C for j in S)
for j in S: m += pulp.lpSum(x[i][j] for i in C) == dem[j]
for i in C: m += pulp.lpSum(x[i][j] for j in S) <= cap[i] * y[i]
report(m)

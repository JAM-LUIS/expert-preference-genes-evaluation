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

# Max flow 0 -> 7.
cap = {
 0: {1: 6, 2: 16, 3: 5, 4: 6, 5: 11, 6: 6, 7: 4},
 1: {2: 8, 3: 10, 4: 6, 5: 3, 6: 6, 7: 14},
 2: {1: 6, 3: 20, 4: 7, 5: 16, 6: 13, 7: 14},
 3: {1: 11, 2: 19, 4: 18, 5: 5, 7: 8},
 4: {1: 1, 2: 14, 3: 18, 5: 12, 6: 4, 7: 7},
 5: {1: 16, 2: 3, 3: 20, 4: 7, 6: 15, 7: 6},
 6: {1: 11, 2: 4, 3: 19, 4: 7, 5: 6, 7: 17},
 7: {1: 5, 2: 8, 3: 17, 4: 2, 5: 5, 6: 4},
}
m = pulp.LpProblem("mamo0122", pulp.LpMaximize)
f = {(i, j): pulp.LpVariable(f"f_{i}_{j}", lowBound=0, upBound=c) for i in cap for j, c in cap[i].items()}
net = lambda v: pulp.lpSum(f[i, j] for (i, j) in f if i == v) - pulp.lpSum(f[i, j] for (i, j) in f if j == v)
m += net(0)
for v in range(1, 7):
    m += net(v) == 0
report(m)

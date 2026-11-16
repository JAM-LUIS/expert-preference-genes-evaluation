#!/usr/bin/env python3
# industryor-0038: 3-job 3-machine permutation flow shop, minimise makespan
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

J = [1, 2, 3]; Mc = [1, 2, 3]
t = {(1, 1): 2, (1, 2): 3, (1, 3): 1, (2, 1): 4, (2, 2): 2, (2, 3): 3, (3, 1): 3, (3, 2): 5, (3, 3): 2}
BIG = sum(t.values())
m = pulp.LpProblem("io0038", pulp.LpMinimize)
s = pulp.LpVariable.dicts("start", (J, Mc), 0)
C = pulp.LpVariable("makespan", 0)
prec = {(i, k): pulp.LpVariable(f"before_{i}_{k}", cat="Binary") for i in J for k in J if i < k}
for i in J:
    for j in [1, 2]: m += s[i][j + 1] >= s[i][j] + t[i, j]
    m += C >= s[i][3] + t[i, 3]
for (i, k), b in prec.items():      # same order on every machine
    for j in Mc:
        m += s[k][j] >= s[i][j] + t[i, j] - BIG * (1 - b)
        m += s[i][j] >= s[k][j] + t[k, j] - BIG * b
m += C
report(m)

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

# TSP (MTZ). Reading 1: tour over cities 1..4 of the distance table.
d = [[0, 10, 20, 12], [10, 0, 5, 10], [20, 5, 0, 8], [15, 12, 8, 0]]
n = 4
V = range(n)
m = pulp.LpProblem("p0070", pulp.LpMinimize)
x = {(i, j): pulp.LpVariable(f"x_{i+1}_{j+1}", cat="Binary") for i in V for j in V if i != j}
u = {i: pulp.LpVariable(f"u_{i+1}", lowBound=1, upBound=n - 1, cat="Integer") for i in V if i > 0}
m += pulp.lpSum(d[i][j] * x[i, j] for (i, j) in x)
for i in V:
    m += pulp.lpSum(x[i, j] for j in V if j != i) == 1
    m += pulp.lpSum(x[j, i] for j in V if j != i) == 1
for i in V:
    for j in V:
        if i != j and i > 0 and j > 0:
            m += u[i] - u[j] + (n - 1) * x[i, j] <= n - 2
report(m)

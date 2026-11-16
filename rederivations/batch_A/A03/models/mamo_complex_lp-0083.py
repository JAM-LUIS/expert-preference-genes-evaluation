#!/usr/bin/env python3
# mamo_complex_lp-0083: 4-city TSP (MTZ)
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

V = ["Alpha", "Bravo", "Charlie", "Delta"]
c = {("Alpha", "Bravo"): 41, ("Alpha", "Charlie"): 55, ("Alpha", "Delta"): 22,
     ("Bravo", "Alpha"): 41, ("Bravo", "Charlie"): 47, ("Bravo", "Delta"): 47,
     ("Charlie", "Alpha"): 55, ("Charlie", "Bravo"): 47, ("Charlie", "Delta"): 35,
     ("Delta", "Alpha"): 22, ("Delta", "Bravo"): 47, ("Delta", "Charlie"): 35}
m = pulp.LpProblem("mamo0083", pulp.LpMinimize)
x = {a: pulp.LpVariable(f"x_{a[0]}_{a[1]}", cat="Binary") for a in c}
u = pulp.LpVariable.dicts("u", V, 0, len(V) - 1)
m += pulp.lpSum(c[a] * x[a] for a in c)
for v in V:
    m += pulp.lpSum(x[a] for a in c if a[0] == v) == 1
    m += pulp.lpSum(x[a] for a in c if a[1] == v) == 1
for (i, j) in c:
    if i != V[0] and j != V[0]:
        m += u[i] - u[j] + len(V) * x[(i, j)] <= len(V) - 1
report(m)

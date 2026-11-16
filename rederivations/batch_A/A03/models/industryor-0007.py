#!/usr/bin/env python3
# industryor-0007: container transport. PER_TRUCK=True
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

PER_TRUCK = True
W = ["Verona", "Perugia", "Rome", "Pescara", "Taranto", "Lamezia"]
P = ["Genoa", "Venice", "Ancona", "Naples", "Bari"]
supply = dict(zip(W, [10, 12, 20, 24, 18, 40]))
demand = dict(zip(P, [20, 15, 25, 33, 21]))
D = {"Verona": [290, 115, 355, 715, 810], "Perugia": [380, 340, 165, 380, 610], "Rome": [505, 530, 285, 220, 450],
     "Pescara": [655, 450, 155, 240, 315], "Taranto": [1010, 840, 550, 305, 95], "Lamezia": [1072, 1097, 747, 372, 333]}
d = {(i, j): D[i][k] for i in W for k, j in enumerate(P)}
m = pulp.LpProblem("io0007", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", (W, P), 0, cat="Integer")   # containers
y = pulp.LpVariable.dicts("y", (W, P), 0, cat="Integer")   # trucks
for i in W: m += pulp.lpSum(x[i][j] for j in P) <= supply[i]
for j in P: m += pulp.lpSum(x[i][j] for i in W) >= demand[j]
for i in W:
    for j in P: m += x[i][j] <= 2 * y[i][j]
if PER_TRUCK:
    m += pulp.lpSum(30 * d[i, j] * y[i][j] for i in W for j in P)
else:
    m += pulp.lpSum(30 * d[i, j] * x[i][j] for i in W for j in P)
report(m)

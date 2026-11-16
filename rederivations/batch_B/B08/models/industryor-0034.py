#!/usr/bin/env python3
import pulp
goods = ["A", "B", "C", "D", "E"]
qty = {"A": 120, "B": 90, "C": 300, "D": 90, "E": 120}
w = {"A": 0.5, "B": 1.0, "C": 0.4, "D": 0.6, "E": 0.65}
K = 10  # candidate containers (upper bound; D-limit already caps at 7)
m = pulp.LpProblem("io0034", pulp.LpMinimize)
u = {k: pulp.LpVariable(f"use_{k}", cat="Binary") for k in range(K)}
a = {k: pulp.LpVariable(f"hasA_{k}", cat="Binary") for k in range(K)}
n = {(g, k): pulp.LpVariable(f"n_{g}_{k}", lowBound=0, cat="Integer") for g in goods for k in range(K)}
m += pulp.lpSum(u.values())
for g in goods:
    m += pulp.lpSum(n[g, k] for k in range(K)) == qty[g]
for k in range(K):
    load = pulp.lpSum(w[g]*n[g, k] for g in goods)
    m += load <= 60*u[k]
    m += load >= 18*u[k]
    m += n["D", k] >= 12*u[k]
    m += n["A", k] <= qty["A"]*a[k]
    m += n["C", k] >= a[k]
    if k > 0:
        m += u[k] <= u[k-1]

m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        if v.varValue:
            print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")

to_relax = [v for v in m.variables()
            if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
for v in to_relax:
    v.cat = pulp.LpContinuous
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
      f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
for v in to_relax:
    v.cat = pulp.LpInteger

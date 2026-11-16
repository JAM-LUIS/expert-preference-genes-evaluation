#!/usr/bin/env python3
import pulp

def report(m, relax=False):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]
    sol_status = pulp.LpSolution[m.sol_status]
    print("STATUS:", status)
    print("SOLUTION_STATUS:", sol_status)
    if status == "Optimal" and sol_status == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue and abs(v.varValue) > 1e-9:
                print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
    if relax:
        to_relax = [v for v in m.variables()
                    if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
        for v in to_relax:
            v.cat = pulp.LpContinuous
        m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
        print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
              f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
        for v in to_relax:
            v.cat = pulp.LpInteger

SUPPLY_IS_CAP = True   # yards can ship at most 80 / 100 t
supply = {"A": 80, "B": 100}
need = {1: 55, 2: 75, 3: 50}
dist = {("A", 1): 10, ("A", 2): 5, ("A", 3): 6, ("B", 1): 4, ("B", 2): 8, ("B", 3): 15}
m = pulp.LpProblem("p0068", pulp.LpMinimize)
x = {k: pulp.LpVariable(f"x_{k[0]}_{k[1]}", lowBound=0) for k in dist}
m += pulp.lpSum(dist[k] * x[k] for k in dist)
for j in need:
    m += pulp.lpSum(x[i, j] for i in supply) == need[j]
if SUPPLY_IS_CAP:
    for i in supply:
        m += pulp.lpSum(x[i, j] for j in need) <= supply[i]
report(m)

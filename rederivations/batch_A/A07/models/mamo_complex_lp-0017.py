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
            if v.varValue:
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

foods = {"chicken": (10, 17, 159, 5), "broccoli": (4, 3, 126, 5), "beef": (13, 8, 230, 8), "rice": (15, 25, 112, 3)}
need = (66, 101, 1701)
m = pulp.LpProblem("p", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", foods, lowBound=0, cat="Integer")
m += pulp.lpSum(foods[f][3] * x[f] for f in foods)
for k in range(3):
    m += pulp.lpSum(foods[f][k] * x[f] for f in foods) >= need[k]
report(m, relax=True)

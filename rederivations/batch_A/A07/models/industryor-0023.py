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

names = ["shirt", "short", "casual"]
labor = [3, 2, 6]; mat = [4, 3, 6]; price = [120, 80, 180]; vc = [60, 40, 80]; fixed = [2000, 1500, 1000]
m = pulp.LpProblem("p", pulp.LpMaximize)
x = [pulp.LpVariable("x_" + s, lowBound=0, cat="Integer") for s in names]
y = [pulp.LpVariable("y_" + s, cat="Binary") for s in names]
m += pulp.lpSum((price[i] - vc[i]) * x[i] - fixed[i] * y[i] for i in range(3))
m += pulp.lpSum(labor[i] * x[i] for i in range(3)) <= 1500
m += pulp.lpSum(mat[i] * x[i] for i in range(3)) <= 1600
for i in range(3):
    M = min(1500 // labor[i], 1600 // mat[i])   # bound implied by resources
    m += x[i] <= M * y[i]
report(m, relax=True)

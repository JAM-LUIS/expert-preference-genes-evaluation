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

c = {(1, 2): 28, (1, 3): 89, (1, 4): 59, (1, 5): 41,
     (2, 1): 28, (2, 3): 85, (2, 4): 12, (2, 5): 68,
     (3, 1): 89, (3, 2): 85, (3, 4): 22, (3, 5): 70,
     (4, 1): 59, (4, 2): 12, (4, 3): 22, (4, 5): 48,
     (5, 1): 41, (5, 2): 68, (5, 3): 70, (5, 4): 48}
N = range(1, 6)
m = pulp.LpProblem("p", pulp.LpMinimize)
x = {k: pulp.LpVariable(f"x_{k[0]}_{k[1]}", cat="Binary") for k in c}
u = {i: pulp.LpVariable(f"u_{i}", lowBound=1, upBound=4) for i in range(2, 6)}
m += pulp.lpSum(c[k] * x[k] for k in c)
for i in N:
    m += pulp.lpSum(x[i, j] for j in N if j != i) == 1
    m += pulp.lpSum(x[j, i] for j in N if j != i) == 1
for i in range(2, 6):
    for j in range(2, 6):
        if i != j:
            m += u[i] - u[j] + 4 * x[i, j] <= 3
report(m)

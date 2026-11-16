#!/usr/bin/env python3
import pulp

def report(m, relax=True):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]
    sol_status = pulp.LpSolution[m.sol_status]
    print("STATUS:", status)
    print("SOLUTION_STATUS:", sol_status)
    if status == "Optimal" and sol_status == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue is not None and abs(v.varValue) > 1e-9:
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

# Reading 1: each yard distributes all coal it receives (A >= 80, B >= 100 shipped); demands met exactly.
d = {"A": [10, 5, 6], "B": [4, 8, 15]}
need = [55, 75, 50]
m = pulp.LpProblem("ind0068", pulp.LpMinimize)
x = {(i, j): pulp.LpVariable(f"x_{i}_{j}", lowBound=0) for i in d for j in range(3)}
m += pulp.lpSum(d[i][j] * x[i, j] for i in d for j in range(3))
m += pulp.lpSum(x["A", j] for j in range(3)) >= 80
m += pulp.lpSum(x["B", j] for j in range(3)) >= 100
for j in range(3):
    m += x["A", j] + x["B", j] == need[j]
report(m, relax=False)

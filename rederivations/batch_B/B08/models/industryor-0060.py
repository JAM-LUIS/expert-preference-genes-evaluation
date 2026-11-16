#!/usr/bin/env python3
import pulp
up = {(1,2):86,(1,3):49,(1,4):57,(1,5):31,(1,6):69,(1,7):50,
      (2,3):68,(2,4):79,(2,5):93,(2,6):24,(2,7):5,
      (3,4):16,(3,5):7,(3,6):72,(3,7):67,
      (4,5):90,(4,6):69,(4,7):1,
      (5,6):86,(5,7):59,
      (6,7):81}
N = range(1, 8)
d = {}
for (i, j), v in up.items():
    d[i, j] = v; d[j, i] = v
m = pulp.LpProblem("io0060", pulp.LpMinimize)
x = {(i, j): pulp.LpVariable(f"x_{i}_{j}", cat="Binary") for i in N for j in N if i != j}
u = {i: pulp.LpVariable(f"u_{i}", lowBound=2, upBound=7) for i in N if i != 1}
m += pulp.lpSum(d[a]*x[a] for a in x)
for i in N:
    m += pulp.lpSum(x[i, j] for j in N if j != i) == 1
    m += pulp.lpSum(x[j, i] for j in N if j != i) == 1
for i in N:
    for j in N:
        if i != j and i != 1 and j != 1:
            m += u[i] - u[j] + 7*x[i, j] <= 6

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

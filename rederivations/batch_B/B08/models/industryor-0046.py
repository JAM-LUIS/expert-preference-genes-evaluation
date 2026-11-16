#!/usr/bin/env python3
import pulp
S = [1, 2, 3, 4, 5, 6]
D = range(5)
wage = {1: 10.0, 2: 10.0, 3: 9.9, 4: 9.8, 5: 10.8, 6: 11.3}
cap = {1: [6, 0, 6, 0, 7], 2: [0, 8, 9, 6, 0], 3: [4, 8, 3, 0, 5],
       4: [5, 5, 6, 0, 4], 5: [3, 0, 5, 8, 0], 6: [0, 6, 0, 6, 5]}
minh = {1: 8, 2: 8, 3: 8, 4: 8, 5: 7, 6: 7}
m = pulp.LpProblem("io0046", pulp.LpMinimize)
x = {(i, j): pulp.LpVariable(f"x_{i}_{j}", lowBound=0) for i in S for j in D}
y = {(i, j): pulp.LpVariable(f"y_{i}_{j}", cat="Binary") for i in S for j in D}
m += pulp.lpSum(wage[i]*x[i, j] for i in S for j in D)
for j in D:
    m += pulp.lpSum(x[i, j] for i in S) == 14  # 8:00-22:00
    m += pulp.lpSum(y[i, j] for i in S) <= 3
for i in S:
    m += pulp.lpSum(x[i, j] for j in D) >= minh[i]
    m += pulp.lpSum(y[i, j] for j in D) <= 2
    for j in D:
        m += x[i, j] <= cap[i][j]*y[i, j]

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

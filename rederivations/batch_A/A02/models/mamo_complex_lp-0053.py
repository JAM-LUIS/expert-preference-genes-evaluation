#!/usr/bin/env python3
import pulp
stock = {1: 410, 2: 266, 3: 132, 4: 6, 5: 485}
need = {1: 274, 2: 331, 3: 232, 4: 359, 5: 74}
cost = {
    (1, 2): 24, (1, 3): 3, (1, 4): 27, (1, 5): 31,
    (2, 1): 24, (2, 3): 11, (2, 4): 7, (2, 5): 37,
    (3, 1): 30, (3, 2): 1, (3, 4): 38, (3, 5): 22,
    (4, 1): 36, (4, 2): 18, (4, 3): 17, (4, 5): 35,
    (5, 1): 41, (5, 2): 35, (5, 3): 33, (5, 4): 33,
}
m = pulp.LpProblem("supplies", pulp.LpMinimize)
x = {a: pulp.LpVariable(f"x_{a[0]}_{a[1]}", lowBound=0) for a in cost}
m += pulp.lpSum(cost[a] * x[a] for a in cost)
for i in stock:
    m += (stock[i] + pulp.lpSum(x[j, i] for j in stock if j != i)
          - pulp.lpSum(x[i, j] for j in stock if j != i) >= need[i]), f"bal_{i}"

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

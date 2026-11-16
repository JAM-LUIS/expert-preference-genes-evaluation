#!/usr/bin/env python3
import pulp
dem = [15, 25, 35, 25]
capa = [30, 40, 45, 20]
cost = [5.0, 5.1, 5.4, 5.5]
m = pulp.LpProblem("io0095", pulp.LpMinimize)
x = [pulp.LpVariable(f"x_{t}", lowBound=0, upBound=capa[t]) for t in range(4)]
I = [pulp.LpVariable(f"I_{t}", lowBound=0) for t in range(4)]
m += pulp.lpSum(cost[t]*x[t] + 0.2*I[t] for t in range(4))
for t in range(4):
    prev = I[t-1] if t > 0 else 0
    m += prev + x[t] - dem[t] == I[t]

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

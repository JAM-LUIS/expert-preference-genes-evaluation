#!/usr/bin/env python3
import pulp
open_c = [151000, 192000, 114000, 171000]
tc = [[5, 5, 2, 3], [3, 3, 5, 4], [3, 5, 2, 4], [2, 4, 5, 1]]
dem = [859, 713, 421, 652]
sup = [1547, 1656, 1274, 1882]
I, J = range(4), range(4)
m = pulp.LpProblem("m0153", pulp.LpMinimize)
y = [pulp.LpVariable(f"y_{i}", cat="Binary") for i in I]
x = {(i, j): pulp.LpVariable(f"x_{i}_{j}", lowBound=0) for i in I for j in J}
m += pulp.lpSum(open_c[i]*y[i] for i in I) + pulp.lpSum(tc[i][j]*x[i, j] for i in I for j in J)
for j in J:
    m += pulp.lpSum(x[i, j] for i in I) >= dem[j]
for i in I:
    m += pulp.lpSum(x[i, j] for j in J) <= sup[i]*y[i]

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

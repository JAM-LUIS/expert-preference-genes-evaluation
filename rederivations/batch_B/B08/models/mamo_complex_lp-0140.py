#!/usr/bin/env python3
import pulp
open_c = [151000, 192000, 114000, 171000, 160000]
tc = [[5, 2, 3, 3, 3], [5, 4, 3, 5, 2], [4, 2, 4, 5, 1], [4, 2, 5, 4, 1], [1, 3, 3, 2, 4]]
dem = [589, 962, 966, 643, 904]
sup = [1954, 1446, 820, 1640, 966]
I, J = range(5), range(5)
m = pulp.LpProblem("m0140", pulp.LpMinimize)
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

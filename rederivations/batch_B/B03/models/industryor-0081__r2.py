#!/usr/bin/env python3
# industryor-0081: assign 15 cars to two street sides; minimize occupied street length = max side length; r2: each side at most 30 m.
import pulp
SIDE_CAP = 30
L = [4, 4.5, 5, 4.1, 2.4, 5.2, 3.7, 3.5, 3.2, 4.5, 2.3, 3.3, 3.8, 4.6, 3]
I = range(len(L))
m = pulp.LpProblem("io0081", pulp.LpMinimize)
x = {i: pulp.LpVariable(f"left_{i+1}", cat="Binary") for i in I}
z = pulp.LpVariable("z", lowBound=0)
m += z
left = pulp.lpSum(L[i]*x[i] for i in I)
right = pulp.lpSum(L[i]*(1-x[i]) for i in I)
m += z >= left
m += z >= right
if SIDE_CAP is not None:
    m += left <= SIDE_CAP
    m += right <= SIDE_CAP
print("TOTAL_LENGTH:", sum(L))
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")

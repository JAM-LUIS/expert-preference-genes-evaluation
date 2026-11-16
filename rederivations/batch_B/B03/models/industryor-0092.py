#!/usr/bin/env python3
# industryor-0092: bus rental IP
import pulp
m = pulp.LpProblem("io0092", pulp.LpMinimize)
x = pulp.LpVariable("bus50", lowBound=0, upBound=10, cat="Integer")
y = pulp.LpVariable("minibus40", lowBound=0, upBound=8, cat="Integer")
m += 800*x + 600*y
m += 50*x + 40*y >= 400
m += x + y <= 9
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

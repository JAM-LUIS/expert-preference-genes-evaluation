#!/usr/bin/env python3
import pulp
m = pulp.LpProblem("io0085", pulp.LpMaximize)
X = pulp.LpVariable("X", lowBound=10)
Y = pulp.LpVariable("Y", lowBound=0)
m += 20*X + 30*Y - (10/60)*(13*X + 19*Y) - (2/60)*(20*X + 29*Y)
m += 13*X + 19*Y <= 40*60
m += 20*X + 29*Y <= 35*60

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

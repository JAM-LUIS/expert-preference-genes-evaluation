#!/usr/bin/env python3
# Reading 2: the five plan constraints are hard constraints; minimise total monthly cost
# (workshop hours at 80 / 20 yuan per hour + inspection and sales cost).
import pulp
m = pulp.LpProblem("min_cost", pulp.LpMinimize)
x1 = pulp.LpVariable("microwaves", lowBound=0, cat="Integer")
x2 = pulp.LpVariable("water_heaters", lowBound=0, cat="Integer")
hA = 2 * x1 + 1 * x2
hB = 1 * x1 + 3 * x2
insp = 30 * x1 + 50 * x2
m += 80 * hA + 20 * hB + insp
m += insp <= 5500
m += x1 >= 80
m += hA >= 250
m += hB >= 150
m += hA <= 250 + 20
m += x2 >= 50
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]; sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status); print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables(): print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")

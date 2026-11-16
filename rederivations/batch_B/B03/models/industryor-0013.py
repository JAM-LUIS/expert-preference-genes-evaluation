#!/usr/bin/env python3
# industryor-0013: crop acreage LP
import pulp
m = pulp.LpProblem("io0013", pulp.LpMaximize)
c = pulp.LpVariable("corn", lowBound=0)
w = pulp.LpVariable("wheat", lowBound=0)
s = pulp.LpVariable("soy", lowBound=0)
g = pulp.LpVariable("sorghum", lowBound=0)
m += 1500*c + 1200*w + 1800*s + 1600*g
m += c + w + s + g <= 100, "land"
m += c >= 2*w, "corn_ge_2wheat"
m += s >= 0.5*g, "soy_ge_half_sorghum"
m += w == 3*g, "wheat_eq_3sorghum"
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

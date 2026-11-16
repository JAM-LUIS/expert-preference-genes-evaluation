#!/usr/bin/env python3
import pulp
m = pulp.LpProblem("farm", pulp.LpMaximize)
corn = pulp.LpVariable("corn", lowBound=0)
wheat = pulp.LpVariable("wheat", lowBound=0)
soy = pulp.LpVariable("soybeans", lowBound=0)
sorg = pulp.LpVariable("sorghum", lowBound=0)
m += 1500 * corn + 1200 * wheat + 1800 * soy + 1600 * sorg
m += corn + wheat + soy + sorg <= 100, "land"
m += corn >= 2 * wheat, "corn_vs_wheat"
m += soy >= 0.5 * sorg, "soy_vs_sorghum"
m += wheat == 3 * sorg, "wheat_eq_3_sorghum"

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

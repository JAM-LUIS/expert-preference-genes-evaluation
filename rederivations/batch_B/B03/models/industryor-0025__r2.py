#!/usr/bin/env python3
# industryor-0025: option1 1-year, 1 yuan -> 1.7; option2 2-year, 1 yuan -> 1+R2.
# Objective = total wealth at end of year 3 minus initial 100000 (net earnings reading).
import pulp
R2 = 2.0
OFFSET = 100000
m = pulp.LpProblem("io0025", pulp.LpMaximize)
x1 = {t: pulp.LpVariable(f"opt1_y{t}", lowBound=0) for t in (1, 2, 3)}
x2 = {t: pulp.LpVariable(f"opt2_y{t}", lowBound=0) for t in (1, 2)}
idle = {t: pulp.LpVariable(f"idle_y{t}", lowBound=0) for t in (1, 2, 3)}
m += x1[1] + x2[1] + idle[1] == 100000
m += x1[2] + x2[2] + idle[2] == 1.7*x1[1] + idle[1]
m += x1[3] + idle[3] == 1.7*x1[2] + (1+R2)*x2[1] + idle[2]
m += 1.7*x1[3] + (1+R2)*x2[2] + idle[3] - OFFSET
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

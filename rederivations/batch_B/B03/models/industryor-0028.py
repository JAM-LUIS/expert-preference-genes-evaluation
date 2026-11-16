#!/usr/bin/env python3
# industryor-0028: multi-period investment LP
import pulp
m = pulp.LpProblem("io0028", pulp.LpMaximize)
x1 = {t: pulp.LpVariable(f"p1_y{t}", lowBound=0) for t in (1, 2, 3)}
x2 = pulp.LpVariable("p2_y1", lowBound=0, upBound=150000)
x3 = pulp.LpVariable("p3_y2", lowBound=0, upBound=200000)
x4 = pulp.LpVariable("p4_y3", lowBound=0, upBound=100000)
idle = {t: pulp.LpVariable(f"idle_y{t}", lowBound=0) for t in (1, 2, 3)}
m += x1[1] + x2 + idle[1] == 300000
m += x1[2] + x3 + idle[2] == 1.2*x1[1] + idle[1]
m += x1[3] + x4 + idle[3] == 1.2*x1[2] + 1.5*x2 + idle[2]
m += 1.2*x1[3] + 1.6*x3 + 1.4*x4 + idle[3]
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

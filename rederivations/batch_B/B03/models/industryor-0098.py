#!/usr/bin/env python3
# industryor-0098: product mix with paid overtime (100 yuan/h, unlimited); integer units.
# Profit = 5000A + 11000B - 100*OT. Then lexicographic check: min OT at max profit.
import pulp
m = pulp.LpProblem("io0098", pulp.LpMaximize)
A = pulp.LpVariable("A", lowBound=0, cat="Integer")
B = pulp.LpVariable("B", lowBound=0, cat="Integer")
OT = pulp.LpVariable("OT", lowBound=0)
m += 5000*A + 11000*B - 100*OT
m += 6*A + 12*B <= 200, "steel"
m += 8*A + 20*B <= 300, "alu"
m += 11*A + 24*B <= 300 + OT, "labour"
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
to_relax = [v for v in m.variables()
            if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
for v in to_relax:
    v.cat = pulp.LpContinuous
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
      f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
for v in to_relax:
    v.cat = pulp.LpInteger

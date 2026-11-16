#!/usr/bin/env python3
import pulp
# Reading 1 (main): maximise net profit = product profit - overtime pay (overtime allowed, paid 100/h).
m = pulp.LpProblem("net_profit", pulp.LpMaximize)
A = pulp.LpVariable("A", lowBound=0, cat="Integer")
B = pulp.LpVariable("B", lowBound=0, cat="Integer")
ot = pulp.LpVariable("overtime_hours", lowBound=0)
m += 5000 * A + 11000 * B - 100 * ot
m += 6 * A + 12 * B <= 200, "steel"
m += 8 * A + 20 * B <= 300, "aluminum"
m += 11 * A + 24 * B <= 300 + ot, "labor"

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

to_relax = [v for v in m.variables()
            if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
for v in to_relax:
    v.cat = pulp.LpContinuous
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
      f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
for v in to_relax:
    v.cat = pulp.LpInteger

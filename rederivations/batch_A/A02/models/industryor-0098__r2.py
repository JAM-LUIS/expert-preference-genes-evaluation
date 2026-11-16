#!/usr/bin/env python3
import pulp
# Reading 2: overtime minimised first (it can be zero), then profit maximised -> no overtime at all.
m = pulp.LpProblem("no_overtime", pulp.LpMaximize)
A = pulp.LpVariable("A", lowBound=0, cat="Integer")
B = pulp.LpVariable("B", lowBound=0, cat="Integer")
m += 5000 * A + 11000 * B
m += 6 * A + 12 * B <= 200, "steel"
m += 8 * A + 20 * B <= 300, "aluminum"
m += 11 * A + 24 * B <= 300, "labor"

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

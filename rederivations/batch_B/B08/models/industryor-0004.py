#!/usr/bin/env python3
import pulp
m = pulp.LpProblem("io0004", pulp.LpMaximize)
c = pulp.LpVariable("cows", lowBound=0, cat="Integer")
s = pulp.LpVariable("sheep", lowBound=0, cat="Integer")
k = pulp.LpVariable("chickens", lowBound=0, cat="Integer")
m += (500-100)*c + (200-80)*s + (8-5)*k
m += 10*c + 5*s + 3*k <= 800
m += k <= 50
m += c >= 10
m += s >= 20
m += c + s + k <= 100

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

to_relax = [v for v in m.variables()
            if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
for v in to_relax:
    v.cat = pulp.LpContinuous
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
      f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
for v in to_relax:
    v.cat = pulp.LpInteger

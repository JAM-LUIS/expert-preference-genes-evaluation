#!/usr/bin/env python3
import pulp
# periods: 0:2-6, 1:6-10, 2:10-14, 3:14-18, 4:18-22, 5:22-2 ; shift starting at period i covers i and i+1
need = [4, 8, 10, 7, 12, 4]
m = pulp.LpProblem("io0083", pulp.LpMinimize)
x = [pulp.LpVariable(f"x_{i}", lowBound=0, cat="Integer") for i in range(6)]
m += pulp.lpSum(x)
for i in range(6):
    m += x[i] + x[i-1] >= need[i]

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

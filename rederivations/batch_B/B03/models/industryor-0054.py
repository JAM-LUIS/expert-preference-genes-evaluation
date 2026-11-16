#!/usr/bin/env python3
# industryor-0054: product mix, integer units (relaxed value also printed)
import pulp
m = pulp.LpProblem("io0054", pulp.LpMaximize)
x = [pulp.LpVariable(f"x{i}", lowBound=0, cat="Integer") for i in (1, 2, 3)]
m += 3*x[0] + 2*x[1] + 2.9*x[2]
m += 8*x[0] + 2*x[1] + 10*x[2] <= 300
m += 10*x[0] + 5*x[1] + 8*x[2] <= 400
m += 2*x[0] + 13*x[1] + 10*x[2] <= 420
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

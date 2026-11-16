#!/usr/bin/env python3
import pulp
foods = {"chicken": (18, 6, 142, 4), "rice": (12, 28, 88, 8), "broccoli": (13, 19, 137, 7),
         "tofu": (5, 16, 141, 10), "beans": (10, 20, 150, 1)}
req = (56, 194, 2012)
m = pulp.LpProblem("m0014", pulp.LpMinimize)
x = {f: pulp.LpVariable("x_" + f, lowBound=0, cat="Integer") for f in foods}
m += pulp.lpSum(foods[f][3]*x[f] for f in foods)
for k in range(3):
    m += pulp.lpSum(foods[f][k]*x[f] for f in foods) >= req[k]

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

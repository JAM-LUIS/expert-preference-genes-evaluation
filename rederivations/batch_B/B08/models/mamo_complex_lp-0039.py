#!/usr/bin/env python3
import pulp
foods = {"chicken_breast": (14, 4, 275, 4), "brown_rice": (11, 17, 151, 10), "tofu": (20, 12, 155, 6),
         "spinach": (6, 20, 106, 1), "almonds": (9, 11, 279, 8), "salmon": (20, 19, 93, 6)}
req = (78, 140, 1537)
m = pulp.LpProblem("m0039", pulp.LpMinimize)
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

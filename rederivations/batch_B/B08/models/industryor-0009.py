#!/usr/bin/env python3
import pulp
toys = ["truck", "airplane", "boat", "train"]
profit = {"truck": 5, "airplane": 10, "boat": 8, "train": 7}
wood = {"truck": 12, "airplane": 20, "boat": 15, "train": 10}
steel = {"truck": 6, "airplane": 3, "boat": 5, "train": 4}
m = pulp.LpProblem("io0009", pulp.LpMaximize)
x = {t: pulp.LpVariable("x_" + t, lowBound=0, cat="Integer") for t in toys}
y = {t: pulp.LpVariable("y_" + t, cat="Binary") for t in toys}
M = {t: min(890 // wood[t], 500 // steel[t]) for t in toys}
m += pulp.lpSum(profit[t]*x[t] for t in toys)
m += pulp.lpSum(wood[t]*x[t] for t in toys) <= 890
m += pulp.lpSum(steel[t]*x[t] for t in toys) <= 500
for t in toys:
    m += x[t] <= M[t]*y[t]
    m += x[t] >= y[t]
m += y["truck"] + y["train"] <= 1
m += y["boat"] <= y["airplane"]
m += x["boat"] <= x["train"]

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

#!/usr/bin/env python3
import pulp
m = pulp.LpProblem("toys", pulp.LpMaximize)
names = ["robot", "car", "blocks", "doll"]
profit = {"robot": 15, "car": 8, "blocks": 12, "doll": 5}
plastic = {"robot": 30, "car": 10, "blocks": 20, "doll": 15}
elec = {"robot": 8, "car": 5, "blocks": 3, "doll": 2}
PL, EL = 1200, 800
x = {n: pulp.LpVariable("x_" + n, lowBound=0, cat="Integer") for n in names}
y = {n: pulp.LpVariable("made_" + n, cat="Binary") for n in names}
m += pulp.lpSum(profit[n] * x[n] for n in names)
m += pulp.lpSum(plastic[n] * x[n] for n in names) <= PL, "plastic"
m += pulp.lpSum(elec[n] * x[n] for n in names) <= EL, "electronics"
for n in names:
    M = min(PL // plastic[n], EL // elec[n])   # bound implied by resources
    m += x[n] <= M * y[n], "on_" + n
    m += x[n] >= y[n], "pos_" + n              # made <=> quantity >= 1
m += y["robot"] + y["doll"] <= 1, "robots_exclude_dolls"
m += y["car"] <= y["blocks"], "cars_imply_blocks"
m += x["doll"] <= x["car"], "dolls_le_cars"

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

#!/usr/bin/env python3
import pulp
F = ["apples", "pears", "oranges", "lemons"]
p = {"apples": 2000, "pears": 1800, "oranges": 2200, "lemons": 3000}
m = pulp.LpProblem("io0058", pulp.LpMaximize)
x = {f: pulp.LpVariable("x_" + f, lowBound=0) for f in F}
y = {f: pulp.LpVariable("y_" + f, cat="Binary") for f in F}
m += pulp.lpSum(p[f]*x[f] for f in F)
m += pulp.lpSum(x.values()) <= 120
m += x["apples"] >= 2*x["pears"]
m += x["apples"] >= 3*x["lemons"]
m += x["oranges"] == 2*x["lemons"]
for f in F:
    m += x[f] <= 120*y[f]
m += pulp.lpSum(y.values()) <= 2

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

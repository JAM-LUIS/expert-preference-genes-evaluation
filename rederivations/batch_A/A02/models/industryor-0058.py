#!/usr/bin/env python3
import pulp
m = pulp.LpProblem("fruit", pulp.LpMaximize)
names = ["apple", "pear", "orange", "lemon"]
profit = {"apple": 2000, "pear": 1800, "orange": 2200, "lemon": 3000}
x = {n: pulp.LpVariable("acres_" + n, lowBound=0) for n in names}
y = {n: pulp.LpVariable("grow_" + n, cat="Binary") for n in names}
m += pulp.lpSum(profit[n] * x[n] for n in names)
m += pulp.lpSum(x.values()) <= 120, "land"
m += x["apple"] >= 2 * x["pear"]
m += x["apple"] >= 3 * x["lemon"]
m += x["orange"] == 2 * x["lemon"]
for n in names:
    m += x[n] <= 120 * y[n]
m += pulp.lpSum(y.values()) <= 2, "at_most_two_types"

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

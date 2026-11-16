#!/usr/bin/env python3
import pulp

def report(m, relax=False):
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
    if relax:
        to_relax = [v for v in m.variables()
                    if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
        for v in to_relax:
            v.cat = pulp.LpContinuous
        m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
        print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
              f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
        for v in to_relax:
            v.cat = pulp.LpInteger

# Main reading: maximize weekly profit; integer motorcycles; profit>=3000, x1>=5, capacities (no overtime).
hours = {"A": (20, 5, 3), "B": (0, 7, 6)}
price = {"A": 650, "B": 725}
cap = (120, 80, 40)
rate = (12, 8, 10)
profit = {k: price[k] - sum(h * r for h, r in zip(hours[k], rate)) for k in hours}
m = pulp.LpProblem("p0011", pulp.LpMaximize)
x = {k: pulp.LpVariable(f"x_{k}", lowBound=0, cat="Integer") for k in hours}
m += pulp.lpSum(profit[k] * x[k] for k in hours)
for p in range(3):
    m += pulp.lpSum(hours[k][p] * x[k] for k in hours) <= cap[p]
m += pulp.lpSum(profit[k] * x[k] for k in hours) >= 3000
m += x["A"] >= 5
print("unit profit", profit)
report(m, relax=True)

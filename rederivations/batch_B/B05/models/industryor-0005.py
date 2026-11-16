#!/usr/bin/env python3
import pulp

def report(m, relax=True):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]
    sol_status = pulp.LpSolution[m.sol_status]
    print("STATUS:", status)
    print("SOLUTION_STATUS:", sol_status)
    if status == "Optimal" and sol_status == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue is not None and abs(v.varValue) > 1e-9:
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

# Mary's dinner: max fiber; exactly one protein; >=2 vegetables; budget $15; total 600 g.
fiber = {"okra": 3.2, "carrot": 2.7, "celery": 1.6, "cabbage": 2.0, "salmon": 0, "beef": 0, "pork": 0}
price = {"salmon": 4, "beef": 3.6, "pork": 1.8, "okra": 2.6, "carrot": 1.2, "celery": 1.6, "cabbage": 2.3}
prot = ["salmon", "beef", "pork"]; veg = ["okra", "carrot", "celery", "cabbage"]
items = prot + veg
m = pulp.LpProblem("ind0005", pulp.LpMaximize)
x = pulp.LpVariable.dicts("g", items, lowBound=0)          # grams
y = pulp.LpVariable.dicts("pick", items, cat="Binary")
m += pulp.lpSum(fiber[i] / 100 * x[i] for i in items)
m += pulp.lpSum(price[i] / 100 * x[i] for i in items) <= 15
m += pulp.lpSum(x[i] for i in items) == 600
for i in items:
    m += x[i] <= 600 * y[i]
m += pulp.lpSum(y[i] for i in prot) == 1
m += pulp.lpSum(y[i] for i in veg) >= 2
report(m, relax=False)

#!/usr/bin/env python3
# industryor-0005: amounts in units of 100 g (continuous); binaries for chosen protein / vegetables.
# Exactly one protein, at least two vegetables, budget 15, total 600 g. Max fiber.
# A chosen item may have amount 0 (no minimum amount in the statement).
import pulp

def report(m, extra=None):
    status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
    print("STATUS:", status); print("SOLUTION_STATUS:", sol)
    if status == "Optimal" and sol == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective) if extra is None else extra)
        for v in m.variables():
            if v.varValue and abs(v.varValue) > 1e-9: print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
SOLVER = lambda: pulp.PULP_CBC_CMD(msg=False, timeLimit=600)
def relax_and_report(m):
    to_relax = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
    for v in to_relax: v.cat = pulp.LpContinuous
    m.solve(SOLVER())
    print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
    for v in to_relax: v.cat = pulp.LpInteger

fiber = {"okra": 3.2, "carrots": 2.7, "celery": 1.6, "cabbage": 2.0}
price = {"salmon": 4.0, "beef": 3.6, "pork": 1.8, "okra": 2.6, "carrots": 1.2, "celery": 1.6, "cabbage": 2.3}
prot = ["salmon", "beef", "pork"]; veg = list(fiber)
m = pulp.LpProblem("p", pulp.LpMaximize)
x = {f: pulp.LpVariable("x_" + f, lowBound=0) for f in price}   # hundreds of grams
y = {f: pulp.LpVariable("y_" + f, cat="Binary") for f in price}
m += pulp.lpSum(fiber[f] * x[f] for f in veg)
for f in price: m += x[f] <= 6 * y[f]          # total is 600 g so 6 is a valid bound
m += pulp.lpSum(y[f] for f in prot) == 1
m += pulp.lpSum(y[f] for f in veg) >= 2
m += pulp.lpSum(price[f] * x[f] for f in price) <= 15
m += pulp.lpSum(x.values()) == 6
m.solve(SOLVER())
report(m)

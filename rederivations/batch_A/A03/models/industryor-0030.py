#!/usr/bin/env python3
# industryor-0030: feed mix. PRICE_DIV=1 (1: nutrient content per kg of feed, x in kg; 1000: content per gram, x in g, price per kg)
import pulp

def report(m, relax=False):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
    print("STATUS:", status); print("SOLUTION_STATUS:", sol)
    if status == "Optimal" and sol == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue and abs(v.varValue) > 1e-9: print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
    if relax:
        tr = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
        for v in tr: v.cat = pulp.LpContinuous
        m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
        print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), f"({len(tr)} general-integer variables made continuous; binaries kept)")
        for v in tr: v.cat = pulp.LpInteger

PRICE_DIV = 1
F = [1, 2, 3, 4, 5]
prot = {1: 3, 2: 2, 3: 1, 4: 6, 5: 18}
mine = {1: 1, 2: 0.5, 3: 0.2, 4: 2, 5: 0.5}
vit = {1: 0.5, 2: 1, 3: 0.2, 4: 2, 5: 0.8}
price = {1: 0.2, 2: 0.7, 3: 0.4, 4: 0.3, 5: 0.8}
m = pulp.LpProblem("io0030", pulp.LpMinimize)
x = pulp.LpVariable.dicts("feed", F, 0)
m += pulp.lpSum(price[i] / PRICE_DIV * x[i] for i in F)
m += pulp.lpSum(prot[i] * x[i] for i in F) >= 700
m += pulp.lpSum(mine[i] * x[i] for i in F) >= 30
m += pulp.lpSum(vit[i] * x[i] for i in F) >= 100
report(m)

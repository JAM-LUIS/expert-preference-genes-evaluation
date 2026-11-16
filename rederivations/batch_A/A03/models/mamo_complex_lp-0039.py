#!/usr/bin/env python3
# mamo_complex_lp-0039: diet, integer servings (relaxed value also printed)
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

foods = {"chicken": (4, 14, 4, 275), "rice": (10, 11, 17, 151), "tofu": (6, 20, 12, 155),
         "spinach": (1, 6, 20, 106), "almonds": (8, 9, 11, 279), "salmon": (6, 20, 19, 93)}
m = pulp.LpProblem("mamo0039", pulp.LpMinimize)
x = pulp.LpVariable.dicts("servings", list(foods), 0, cat="Integer")
m += pulp.lpSum(foods[f][0] * x[f] for f in foods)
m += pulp.lpSum(foods[f][1] * x[f] for f in foods) >= 78
m += pulp.lpSum(foods[f][2] * x[f] for f in foods) >= 140
m += pulp.lpSum(foods[f][3] * x[f] for f in foods) >= 1537
report(m, relax=True)

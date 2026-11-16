#!/usr/bin/env python3
# mamo_complex_lp-0014: diet problem. Integer number of servings of each food (main); continuous relaxation also reported.
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

# name: (protein, carbs, calories, cost)
foods = {"Chicken": (18,6,142,4), "Rice": (12,28,88,8), "Broccoli": (13,19,137,7), "Tofu": (5,16,141,10), "Beans": (10,20,150,1)}
req = (56, 194, 2012)
m = pulp.LpProblem("diet", pulp.LpMinimize)
x = {f: pulp.LpVariable("x_" + f, lowBound=0, cat="Integer") for f in foods}
m += pulp.lpSum(foods[f][3] * x[f] for f in foods), "cost"
for k, nm in enumerate(["protein", "carbs", "calories"]):
    m += pulp.lpSum(foods[f][k] * x[f] for f in foods) >= req[k], nm
m.solve(SOLVER())
report(m)
relax_and_report(m)

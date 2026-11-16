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

# Fixed-charge production planning, max weekly profit.
prods = ["shirt", "short", "casual"]
lab = {"shirt": 3, "short": 2, "casual": 6}
mat = {"shirt": 4, "short": 3, "casual": 6}
price = {"shirt": 120, "short": 80, "casual": 180}
vc = {"shirt": 60, "short": 40, "casual": 80}
fc = {"shirt": 2000, "short": 1500, "casual": 1000}
m = pulp.LpProblem("ind0023", pulp.LpMaximize)
x = pulp.LpVariable.dicts("x", prods, lowBound=0, cat="Integer")
y = pulp.LpVariable.dicts("y", prods, cat="Binary")
m += pulp.lpSum((price[p] - vc[p]) * x[p] - fc[p] * y[p] for p in prods)
m += pulp.lpSum(lab[p] * x[p] for p in prods) <= 1500
m += pulp.lpSum(mat[p] * x[p] for p in prods) <= 1600
M = {p: min(1500 / lab[p], 1600 / mat[p]) for p in prods}
for p in prods:
    m += x[p] <= M[p] * y[p]
report(m)

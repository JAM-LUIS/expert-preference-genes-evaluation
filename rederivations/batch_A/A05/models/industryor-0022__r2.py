#!/usr/bin/env python3
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

# Three products, fixed activation cost, minimum batch, 22 production days shared via daily quotas.
prod = ["A1", "A2", "A3"]
dmax = {"A1": 5300, "A2": 4500, "A3": 5400}
price = {"A1": 124, "A2": 109, "A3": 115}
cost = {"A1": 73.30, "A2": 52.90, "A3": 65.40}
quota = {"A1": 500, "A2": 450, "A3": 550}
act = {"A1": 170000, "A2": 150000, "A3": 100000}
minb = {"A1": 20, "A2": 20, "A3": 16}
days = 22
m = pulp.LpProblem("p0022", pulp.LpMaximize)
x = pulp.LpVariable.dicts("x", prod, lowBound=0)          # units of 100 kg, divisible
y = pulp.LpVariable.dicts("y", prod, cat="Binary")
m += pulp.lpSum(price[i] * x[i] - act[i] * y[i] for i in prod)  # reading 2: sales revenue minus activation cost, production cost ignored
for i in prod:
    m += x[i] <= dmax[i] * y[i]
    m += x[i] >= minb[i] * y[i]
m += pulp.lpSum(x[i] * (1.0 / quota[i]) for i in prod) <= days
report(m)
# check with integer production quantities
for i in prod: x[i].cat = pulp.LpInteger
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("WITH_INTEGER_X:", pulp.LpStatus[m.status], pulp.value(m.objective))

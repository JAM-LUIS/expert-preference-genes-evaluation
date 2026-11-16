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

# Production/inventory/backlog over 4 quarters, 3 products.
# Reading 1: holding cost charged on every end-of-quarter inventory incl. required 150 at end of Q4
CHARGE_FINAL = True
P = ["I", "II", "III"]; T = [1, 2, 3, 4]
dem = {"I": [1500, 1000, 2000, 1200], "II": [1500, 1500, 1200, 1500], "III": [1000, 2000, 1500, 2500]}
hrs = {"I": 2, "II": 4, "III": 3}
pen = {"I": 20, "II": 20, "III": 10}
hold = 5; cap = 15000; final = 150
m = pulp.LpProblem("p0006", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", (P, T), lowBound=0, cat="Integer")
I = pulp.LpVariable.dicts("inv", (P, T), lowBound=0, cat="Integer")
B = pulp.LpVariable.dicts("back", (P, T), lowBound=0, cat="Integer")
m += pulp.lpSum(pen[p] * B[p][t] for p in P for t in T) + pulp.lpSum(hold * I[p][t] for p in P for t in T if CHARGE_FINAL or t < 4)
for p in P:
    for t in T:
        prev = (I[p][t-1] - B[p][t-1]) if t > 1 else 0
        m += prev + x[p][t] - dem[p][t-1] == I[p][t] - B[p][t]
    m += I[p][4] == final
    m += B[p][4] == 0
for t in T:
    m += pulp.lpSum(hrs[p] * x[p][t] for p in P) <= cap
m += x["I"][2] == 0
report(m, relax=True)

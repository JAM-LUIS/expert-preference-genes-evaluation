#!/usr/bin/env python3
# industryor-0016: purchase/sales plan for 3 months
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

T = [1, 2, 3]
buy = {1: 8, 2: 6, 3: 9}; sell = {1: 9, 2: 8, 3: 10}
m = pulp.LpProblem("io0016", pulp.LpMaximize)
x = pulp.LpVariable.dicts("purchase", T, 0)
y = pulp.LpVariable.dicts("sales", T, 0)
s = pulp.LpVariable.dicts("end_stock", T, 0)
for t in T:
    prev = 200 if t == 1 else s[t - 1]
    m += prev + x[t] <= 500, f"cap_{t}"          # purchase at beginning of month must fit in warehouse
    m += s[t] == prev + x[t] - y[t], f"bal_{t}"   # sales limited by stock on hand (s >= 0)
m += pulp.lpSum(sell[t] * y[t] - buy[t] * x[t] for t in T)
report(m)

#!/usr/bin/env python3
# industryor-0046: x[i,d] hours of student i on day d (continuous), y[i,d]=1 if i has a shift on day d.
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

wage = {1: 10.0, 2: 10.0, 3: 9.9, 4: 9.8, 5: 10.8, 6: 11.3}
avail = {1: [6,0,6,0,7], 2: [0,8,9,6,0], 3: [4,8,3,0,5], 4: [5,5,6,0,4], 5: [3,0,5,8,0], 6: [0,6,0,6,5]}
D = range(5)
m = pulp.LpProblem("p", pulp.LpMinimize)
x = {(i, d): pulp.LpVariable(f"x_{i}_{d}", lowBound=0) for i in wage for d in D}
y = {(i, d): pulp.LpVariable(f"y_{i}_{d}", cat="Binary") for i in wage for d in D}
m += pulp.lpSum(wage[i] * x[i, d] for i in wage for d in D)
for i in wage:
    for d in D: m += x[i, d] <= avail[i][d] * y[i, d]
    m += pulp.lpSum(x[i, d] for d in D) >= (8 if i <= 4 else 7)
    m += pulp.lpSum(y[i, d] for d in D) <= 2
for d in D:
    m += pulp.lpSum(x[i, d] for i in wage) == 14      # 8:00-22:00, exactly one on duty
    m += pulp.lpSum(y[i, d] for i in wage) <= 3
m.solve(SOLVER())
report(m)

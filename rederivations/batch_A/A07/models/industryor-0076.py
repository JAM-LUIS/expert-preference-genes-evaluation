#!/usr/bin/env python3
import pulp

def report(m, relax=False):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]
    sol_status = pulp.LpSolution[m.sol_status]
    print("STATUS:", status)
    print("SOLUTION_STATUS:", sol_status)
    if status == "Optimal" and sol_status == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue:
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

import sys
# argv: units ("literal": storage cost in yuan/m3 ; "per1e4": yuan per 10,000 m3), capacity ("carry" / "onhand")
UNITS = sys.argv[1] if len(sys.argv) > 1 else "literal"
CAPMODE = sys.argv[2] if len(sys.argv) > 2 else "carry"
buy = [410, 430, 460, 450]; sell = [425, 440, 465, 455]; maxs = [100, 140, 200, 160]
CAP = 20.0            # 200,000 m3 in units of 10,000 m3
a, b = 70.0, 100.0
scale = 1.0 if UNITS == "literal" else 1.0 / 10000.0
# x[i,j]: 10,000 m3 bought at start of quarter i, sold in quarter j (j >= i); money in 10,000 yuan
m = pulp.LpProblem("p", pulp.LpMaximize)
x = {(i, j): pulp.LpVariable(f"x_{i+1}_{j+1}", lowBound=0) for i in range(4) for j in range(i, 4)}
def stor(u):
    return 0.0 if u == 0 else (a + b * u) * scale
m += pulp.lpSum((sell[j] - buy[i] - stor(j - i)) * x[i, j] for (i, j) in x)
for j in range(4):
    m += pulp.lpSum(x[i, j] for i in range(j + 1)) <= maxs[j]
if CAPMODE == "carry":
    for t in range(3):     # stock carried from quarter t to t+1
        m += pulp.lpSum(x[i, j] for (i, j) in x if i <= t < j) <= CAP
else:
    for t in range(4):     # stock on hand right after purchase at start of quarter t
        m += pulp.lpSum(x[i, j] for (i, j) in x if i <= t <= j) <= CAP
report(m)

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

# 0-1 property selection; money in dollars.
inc = {1: 12500, 2: 35000, 3: 23000, 4: 100000}
cost = {1: 1.5e6, 2: 2.1e6, 3: 2.3e6, 4: 4.2e6}
m = pulp.LpProblem("p0072", pulp.LpMaximize)
y = pulp.LpVariable.dicts("buy", inc, cat="Binary")
m += pulp.lpSum(inc[i] * y[i] for i in inc)
m += pulp.lpSum(cost[i] * y[i] for i in inc) <= 7e6
m += y[3] + y[4] <= 1
report(m)

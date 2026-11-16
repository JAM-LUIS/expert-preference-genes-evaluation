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

# Three-year investment; money in yuan. Cash may stay idle (slack).
m = pulp.LpProblem("p0028", pulp.LpMaximize)
x1 = pulp.LpVariable.dicts("p1", [1, 2, 3], lowBound=0)
x2 = pulp.LpVariable("p2", lowBound=0, upBound=150000)
x3 = pulp.LpVariable("p3", lowBound=0, upBound=200000)
x4 = pulp.LpVariable("p4", lowBound=0, upBound=100000)
s = pulp.LpVariable.dicts("idle", [1, 2, 3], lowBound=0)
m += 1.2 * x1[3] + 1.6 * x3 + 1.4 * x4 + s[3]
m += x1[1] + x2 + s[1] == 300000
m += x1[2] + x3 + s[2] == 1.2 * x1[1] + s[1]
m += x1[3] + x4 + s[3] == 1.2 * x1[2] + 1.5 * x2 + s[2]
report(m)

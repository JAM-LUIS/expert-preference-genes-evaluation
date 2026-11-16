#!/usr/bin/env python3
# industryor-0018 reading 2: goals as hard constraints, maximise weekly profit
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

m = pulp.LpProblem("io0018r2", pulp.LpMaximize)
x1 = pulp.LpVariable("curtain_m", 0); x2 = pulp.LpVariable("clothing_m", 0)
m += 0.001 * x1 + 0.001 * x2 >= 110
m += 0.001 * x1 + 0.001 * x2 <= 120
m += x1 >= 70000; m += x2 >= 45000
m += 2.5 * x1 + 1.5 * x2
report(m)

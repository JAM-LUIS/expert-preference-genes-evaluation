#!/usr/bin/env python3
# industryor-0037: maximise profit with the stated goals as constraints
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

m = pulp.LpProblem("io0037", pulp.LpMaximize)
A = pulp.LpVariable("A", 0, cat="Integer"); B = pulp.LpVariable("B", 0, cat="Integer")
m += 300 * A + 450 * B
m += 300 * A + 450 * B >= 10000     # p1
m += A >= 10; m += B >= 15          # p2
m += 4 * A + 6 * B == 150           # p3: process I exactly 150 h
m += 3 * A + 2 * B >= 70            # p3: process II fully used, overtime allowed
report(m, relax=True)

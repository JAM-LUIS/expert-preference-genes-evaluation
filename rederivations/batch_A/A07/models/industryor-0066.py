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

m = pulp.LpProblem("p", pulp.LpMaximize)
h = pulp.LpVariable("high", lowBound=0, upBound=50, cat="Integer")
d = pulp.LpVariable("mid", lowBound=0, upBound=80, cat="Integer")
l = pulp.LpVariable("low", lowBound=0, upBound=150, cat="Integer")
m += 300 * h + 200 * d + 100 * l
m += 17 * h + 10 * d + 2 * l <= 1000
m += 8 * h + 4 * d + 2 * l <= 500
report(m, relax=True)

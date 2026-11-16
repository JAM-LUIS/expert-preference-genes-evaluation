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

# Two fertilizers (lots, fractional allowed); maximise total ending inventory; demand must be covered.
m = pulp.LpProblem("p0088", pulp.LpMaximize)
xl = pulp.LpVariable("liquid_lots", lowBound=0)
xs = pulp.LpVariable("solid_lots", lowBound=0)
el = pulp.LpVariable("end_liquid", lowBound=0)
es = pulp.LpVariable("end_solid", lowBound=0)
m += el + es
m += el == 30 + xl - 75
m += es == 90 + xs - 95
m += 50 * xl + 24 * xs <= 40 * 60
m += 30 * xl + 33 * xs <= 35 * 60
report(m)

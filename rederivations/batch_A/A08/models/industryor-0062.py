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
            if v.varValue and abs(v.varValue) > 1e-9:
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

rev = {"A": 15000, "B": 40000, "C": 30000, "D": 50000}
cost = {"A": 1.6, "B": 2.5, "C": 1.8, "D": 3.0}   # million
m = pulp.LpProblem("p0062", pulp.LpMaximize)
b = {k: pulp.LpVariable(f"buy_{k}", cat="Binary") for k in rev}
m += pulp.lpSum(rev[k] * b[k] for k in rev)
m += pulp.lpSum(cost[k] * b[k] for k in rev) <= 6.0
m += b["D"] + b["A"] <= 1
report(m)

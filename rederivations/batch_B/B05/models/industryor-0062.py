#!/usr/bin/env python3
import pulp

def report(m, relax=True):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]
    sol_status = pulp.LpSolution[m.sol_status]
    print("STATUS:", status)
    print("SOLUTION_STATUS:", sol_status)
    if status == "Optimal" and sol_status == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue is not None and abs(v.varValue) > 1e-9:
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

R = ["A", "B", "C", "D"]
rev = dict(zip(R, [15000, 40000, 30000, 50000]))
cost = dict(zip(R, [1.6e6, 2.5e6, 1.8e6, 3e6]))
m = pulp.LpProblem("ind0062", pulp.LpMaximize)
x = pulp.LpVariable.dicts("buy", R, cat="Binary")
m += pulp.lpSum(rev[r] * x[r] for r in R)
m += pulp.lpSum(cost[r] * x[r] for r in R) <= 6e6
m += x["D"] + x["A"] <= 1
report(m, relax=False)

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

names = ["Harry", "Hermione", "Ron", "Fred", "George", "Ginny"]
cost = dict(zip(names, [1200, 1650, 750, 800, 800, 1500]))
m = pulp.LpProblem("ind0053", pulp.LpMinimize)
x = pulp.LpVariable.dicts("take", names, cat="Binary")
m += pulp.lpSum(cost[n] * x[n] for n in names)
m += pulp.lpSum(x.values()) <= 4
m += pulp.lpSum(x.values()) >= 3
m += x["Ginny"] == 1
m += x["Harry"] + x["Fred"] <= 1
m += x["Harry"] + x["George"] <= 1
m += x["George"] <= x["Fred"]
m += x["George"] <= x["Hermione"]
report(m, relax=False)

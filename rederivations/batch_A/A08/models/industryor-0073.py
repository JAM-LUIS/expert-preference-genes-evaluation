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

cost = {"Alice": 1000, "Bob": 900, "Charlie": 600, "Diana": 500, "Ella": 700}
m = pulp.LpProblem("p0073", pulp.LpMinimize)
t = {k: pulp.LpVariable(f"take_{k}", cat="Binary") for k in cost}
m += pulp.lpSum(cost[k] * t[k] for k in cost)
m += pulp.lpSum(t.values()) <= 3
m += t["Bob"] == 1
m += t["Alice"] + t["Diana"] <= 1
m += t["Bob"] + t["Charlie"] <= 1
m += t["Charlie"] <= t["Diana"]
m += t["Diana"] <= t["Ella"]
m += pulp.lpSum(t.values()) >= 2
report(m)

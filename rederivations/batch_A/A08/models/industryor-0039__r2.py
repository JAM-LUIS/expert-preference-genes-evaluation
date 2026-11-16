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

poll = {"moto": 40, "small": 70, "large": 100}
capu = {"moto": 10, "small": 20, "large": 50}
ub = {"moto": 8, "small": 20, "large": 20}   # motorcycle <= 8 trips; total trips <= 20 bounds the others
m = pulp.LpProblem("p0039", pulp.LpMinimize)
x = {k: pulp.LpVariable(f"trips_{k}", lowBound=0, cat="Integer") for k in poll}
u = {k: pulp.LpVariable(f"use_{k}", cat="Binary") for k in poll}
m += pulp.lpSum(poll[k] * x[k] for k in poll)
for k in poll:
    m += x[k] <= ub[k] * u[k]
m += pulp.lpSum(u.values()) == 2
for k in poll: m += x[k] >= u[k]   # reading 2: exactly two methods, each really used
m += x["moto"] <= 8
m += pulp.lpSum(capu[k] * x[k] for k in poll) >= 300
m += pulp.lpSum(x.values()) <= 20
report(m, relax=True)

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

# Allocate workshop hours to components; maximize number of complete products.
cap = {"A": 100, "B": 150, "C": 80, "D": 200}
rate = {"A": [10, 15, 5], "B": [15, 10, 5], "C": [20, 5, 10], "D": [10, 15, 20]}
m = pulp.LpProblem("ind0032", pulp.LpMaximize)
t = {(w, j): pulp.LpVariable(f"t_{w}_{j}", lowBound=0) for w in cap for j in range(3)}
z = pulp.LpVariable("z", lowBound=0)
m += z
for w in cap:
    m += pulp.lpSum(t[w, j] for j in range(3)) <= cap[w]
for j in range(3):
    m += pulp.lpSum(rate[w][j] * t[w, j] for w in cap) >= z
report(m, relax=False)

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

import sys
sys.argv = [sys.argv[0]] + ['fixed']   # fixed variant of industryor-0027
import sys
FIXED = len(sys.argv) > 1 and sys.argv[1] == "fixed"   # alt reading: full operating costs are sunk
tA = {("A1", 1): 5, ("A1", 2): 10, ("A2", 1): 7, ("A2", 2): 9, ("A2", 3): 12}
tB = {("B1", 1): 6, ("B1", 2): 8, ("B2", 1): 4, ("B2", 3): 11, ("B3", 1): 7}
hours = {"A1": 6000, "A2": 10000, "B1": 4000, "B2": 7000, "B3": 4000}
cost = {"A1": 300, "A2": 321, "B1": 250, "B2": 783, "B3": 200}
raw = {1: 0.25, 2: 0.35, 3: 0.50}; price = {1: 1.25, 2: 2.00, 3: 2.80}
m = pulp.LpProblem("p", pulp.LpMaximize)
a = {k: pulp.LpVariable(f"a_{k[0]}_{k[1]}", lowBound=0, cat="Integer") for k in tA}
b = {k: pulp.LpVariable(f"b_{k[0]}_{k[1]}", lowBound=0, cat="Integer") for k in tB}
q = {p: pulp.lpSum(a[k] for k in tA if k[1] == p) for p in (1, 2, 3)}
used = {e: pulp.lpSum(tA[k] * a[k] for k in tA if k[0] == e) + pulp.lpSum(tB[k] * b[k] for k in tB if k[0] == e) for e in hours}
rev = pulp.lpSum((price[p] - raw[p]) * q[p] for p in (1, 2, 3))
if FIXED:
    m += rev - sum(cost.values())
else:
    m += rev - pulp.lpSum(cost[e] / hours[e] * used[e] for e in hours)
for p in (1, 2, 3):
    m += q[p] == pulp.lpSum(b[k] for k in tB if k[1] == p)
for e in hours:
    m += used[e] <= hours[e]
report(m, relax=True)

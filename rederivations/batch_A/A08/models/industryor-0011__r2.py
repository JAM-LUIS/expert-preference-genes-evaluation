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

# Reading 2: lexicographic (preemptive) goal programme, integer units.
# P1: min shortfall of profit below 3000; P2: min shortfall of x1 below 5;
# P3: min weighted idle time (weights = hourly cost); overtime not allowed. Report profit of the final plan.
import sys
INTEGER = "--cont" not in sys.argv
hours = {"A": (20, 5, 3), "B": (0, 7, 6)}
price = {"A": 650, "B": 725}
cap = (120, 80, 40)
rate = (12, 8, 10)
profit = {k: price[k] - sum(h * r for h, r in zip(hours[k], rate)) for k in hours}
def build():
    m = pulp.LpProblem("p0011_gp", pulp.LpMinimize)
    x = {k: pulp.LpVariable(f"x_{k}", lowBound=0, cat="Integer" if INTEGER else "Continuous") for k in hours}
    d1 = pulp.LpVariable("d1minus", lowBound=0); d2 = pulp.LpVariable("d2minus", lowBound=0)
    idle = [pulp.LpVariable(f"idle_{p}", lowBound=0) for p in range(3)]
    for p in range(3):
        m += pulp.lpSum(hours[k][p] * x[k] for k in hours) + idle[p] == cap[p]
    m += pulp.lpSum(profit[k] * x[k] for k in hours) + d1 >= 3000
    m += x["A"] + d2 >= 5
    return m, x, d1, d2, idle
S = pulp.PULP_CBC_CMD(msg=False, timeLimit=600)
m, x, d1, d2, idle = build(); m += d1; m.solve(S); v1 = pulp.value(d1)
m, x, d1, d2, idle = build(); m += d2; m += d1 <= v1 + 1e-6; m.solve(S); v2 = pulp.value(d2)
m, x, d1, d2, idle = build(); m += pulp.lpSum(rate[p] * idle[p] for p in range(3))
m += d1 <= v1 + 1e-6; m += d2 <= v2 + 1e-6
m.solve(S)
status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
print("integer" if INTEGER else "continuous", "P1", v1, "P2", v2, "P3 weighted idle", pulp.value(m.objective))
print("STATUS:", status); print("SOLUTION_STATUS:", sol)
if status == "Optimal" and sol == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", sum(profit[k] * x[k].varValue for k in hours), "(profit of the goal-programming plan)")
    for k in hours: print(" ", k, x[k].varValue)
else:
    print("FINAL_OBJECTIVE: None")

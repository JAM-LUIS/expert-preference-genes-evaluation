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

need = [10, 15, 25, 20, 18, 12]
CONTRACT = True; COST = False  # reading 2: minimise head count
m = pulp.LpProblem("shift_cover", pulp.LpMinimize)
n = len(need)
x = [pulp.LpVariable(f"regular_start_{i}", lowBound=0, cat="Integer") for i in range(n)]
y = [pulp.LpVariable(f"contract_start_{i}", lowBound=0, cat="Integer") for i in range(n)] if CONTRACT else [0] * n
if COST:
    m += pulp.lpSum(8 * 10 * x[i] + 8 * 15 * y[i] for i in range(n))
else:
    m += pulp.lpSum(x[i] + y[i] for i in range(n))
for i in range(n):   # staff on duty in period i started at period i or i-1 (8h = two 4h periods)
    m += x[i] + y[i] + x[i - 1] + y[i - 1] >= need[i]
report(m, relax=True)
if CONTRACT:
    print("CONTRACT_NURSES:", sum(v.varValue for v in y))

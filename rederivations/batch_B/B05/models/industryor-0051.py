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

# Regular (10/h) vs contract (15/h) nurses, same 8h shifts; minimize total pay; how many contract nurses?
req = [10, 15, 25, 20, 18, 12]
m = pulp.LpProblem("ind0051", pulp.LpMinimize)
x = [pulp.LpVariable(f"reg{i}", lowBound=0, cat="Integer") for i in range(6)]
y = [pulp.LpVariable(f"con{i}", lowBound=0, cat="Integer") for i in range(6)]
m += pulp.lpSum(10 * 8 * x[i] + 15 * 8 * y[i] for i in range(6))
for i in range(6):
    m += x[i] + x[i - 1] + y[i] + y[i - 1] >= req[i]
report(m)

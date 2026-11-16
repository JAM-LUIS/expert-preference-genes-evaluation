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

# x1, x2 = number of heats (furnace charges) by method 1 / 2, per furnace f
m = pulp.LpProblem("p", pulp.LpMinimize)
x = {(f, k): pulp.LpVariable(f"heats_f{f}_m{k}", lowBound=0, cat="Integer") for f in (1, 2) for k in (1, 2)}
m += pulp.lpSum(50 * x[f, 1] + 70 * x[f, 2] for f in (1, 2))
for f in (1, 2):
    m += 2 * x[f, 1] + 3 * x[f, 2] <= 12
m += 10 * pulp.lpSum(x.values()) >= 30
report(m, relax=True)

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

# (cost, protein, carbs, calories)
foods = {1: (6, 6, 3, 73), 2: (2, 16, 3, 181), 3: (10, 12, 17, 231), 4: (6, 9, 28, 160),
         5: (4, 12, 17, 209), 6: (1, 12, 14, 184), 7: (9, 13, 20, 118)}
need = (59, 179, 2414)
m = pulp.LpProblem("p", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", foods, lowBound=0, cat="Integer")
m += pulp.lpSum(foods[f][0] * x[f] for f in foods)
for k in range(3):
    m += pulp.lpSum(foods[f][k + 1] * x[f] for f in foods) >= need[k]
report(m, relax=True)

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

# ATSP with MTZ subtour elimination.
N = [1, 2, 3, 4]
c = {(1, 2): 52, (1, 3): 89, (1, 4): 11, (2, 1): 52, (2, 3): 14, (2, 4): 13,
     (3, 1): 89, (3, 2): 14, (3, 4): 87, (4, 1): 11, (4, 2): 13, (4, 3): 87}
m = pulp.LpProblem("mamo0063", pulp.LpMinimize)
x = {a: pulp.LpVariable(f"x_{a[0]}_{a[1]}", cat="Binary") for a in c}
u = {i: pulp.LpVariable(f"u_{i}", lowBound=1, upBound=len(N)) for i in N}
m += pulp.lpSum(c[a] * x[a] for a in c)
for i in N:
    m += pulp.lpSum(x[i, j] for j in N if j != i) == 1
    m += pulp.lpSum(x[j, i] for j in N if j != i) == 1
for i in N:
    for j in N:
        if i != j and i != 1 and j != 1:
            m += u[i] - u[j] + len(N) * x[i, j] <= len(N) - 1
report(m, relax=False)

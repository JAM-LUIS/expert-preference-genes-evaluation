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

a = {1: 100, 2: 150}; b = {1: 80, 2: 120}
f = {1: 10, 2: 15}; q = {1: 100, 2: 100}
c = {(1, 1): 2, (1, 2): 3, (2, 1): 4, (2, 2): 1}
c2 = {(1, 1): 3, (1, 2): 2, (2, 1): 1, (2, 2): 4}
m = pulp.LpProblem("p0044", pulp.LpMinimize)
x = {ik: pulp.LpVariable(f"x_{ik[0]}_{ik[1]}", lowBound=0) for ik in c}
z = {kj: pulp.LpVariable(f"z_{kj[0]}_{kj[1]}", lowBound=0) for kj in c2}
y = {k: pulp.LpVariable(f"open_{k}", cat="Binary") for k in f}
m += pulp.lpSum(c[ik] * x[ik] for ik in c) + pulp.lpSum(c2[kj] * z[kj] for kj in c2) + pulp.lpSum(f[k] * y[k] for k in f)
for i in a: m += pulp.lpSum(x[i, k] for k in f) <= a[i]
for j in b: m += pulp.lpSum(z[k, j] for k in f) == b[j]
for k in f:
    m += pulp.lpSum(x[i, k] for i in a) == pulp.lpSum(z[k, j] for j in b)
    m += pulp.lpSum(x[i, k] for i in a) <= q[k] * y[k]
report(m)

#!/usr/bin/env python3
import pulp

def report(m, relax=False):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
    print("STATUS:", status); print("SOLUTION_STATUS:", sol)
    if status == "Optimal" and sol == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue and abs(v.varValue) > 1e-9: print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
    if relax:
        tr = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
        for v in tr: v.cat = pulp.LpContinuous
        m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
        print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), f"({len(tr)} general-integer variables made continuous; binaries kept)")
        for v in tr: v.cat = pulp.LpInteger

# 3-machine flow shop, 5 batches, minimise makespan. General (non-permutation) disjunctive model.
import itertools
t = [[3, 1, 1], [2, 1.5, 1], [3, 1.2, 1.3], [2, 2, 2], [2.1, 2, 3]]
n = 5; K = 3
M = sum(sum(r) for r in t)   # total processing time bounds any sensible schedule
m = pulp.LpProblem("p0035", pulp.LpMinimize)
s = pulp.LpVariable.dicts("s", (range(n), range(K)), lowBound=0)
C = pulp.LpVariable("Cmax", lowBound=0)
z = {(i, j, k): pulp.LpVariable(f"z_{i}_{j}_{k}", cat="Binary") for i in range(n) for j in range(i + 1, n) for k in range(K)}
m += C
for i in range(n):
    for k in range(K - 1):
        m += s[i][k + 1] >= s[i][k] + t[i][k]
    m += C >= s[i][K - 1] + t[i][K - 1]
for (i, j, k), v in z.items():
    m += s[j][k] >= s[i][k] + t[i][k] - M * (1 - v)
    m += s[i][k] >= s[j][k] + t[j][k] - M * v
report(m)
best = None
for perm in itertools.permutations(range(n)):
    c = [0.0] * K
    for i in perm:
        for k in range(K):
            c[k] = max(c[k], c[k - 1] if k else 0) + t[i][k]
    if best is None or c[-1] < best[0] - 1e-12: best = (c[-1], perm)
print("PERMUTATION_ENUM_CHECK:", best[0], [i + 1 for i in best[1]])

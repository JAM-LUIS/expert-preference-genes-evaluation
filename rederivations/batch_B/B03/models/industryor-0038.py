#!/usr/bin/env python3
# industryor-0038: 3-job 3-machine permutation flow shop, minimize makespan (MILP, disjunctive).
import pulp, itertools
T = {1: [2, 3, 1], 2: [4, 2, 3], 3: [3, 5, 2]}
I = [1, 2, 3]; Mc = [0, 1, 2]
BIG = sum(sum(v) for v in T.values())
m = pulp.LpProblem("io0038", pulp.LpMinimize)
s = {(i, k): pulp.LpVariable(f"s_{i}_{k}", lowBound=0) for i in I for k in Mc}
y = {(i, j): pulp.LpVariable(f"y_{i}_{j}", cat="Binary") for i in I for j in I if i < j}  # 1: i before j (same on all machines)
Cmax = pulp.LpVariable("Cmax", lowBound=0)
m += Cmax
for i in I:
    for k in Mc[:-1]:
        m += s[i, k+1] >= s[i, k] + T[i][k]
    m += Cmax >= s[i, 2] + T[i][2]
for (i, j) in y:
    for k in Mc:
        m += s[j, k] >= s[i, k] + T[i][k] - BIG*(1 - y[i, j])
        m += s[i, k] >= s[j, k] + T[j][k] - BIG*y[i, j]
# check by enumeration
best = None
for perm in itertools.permutations(I):
    C = [0, 0, 0]
    for i in perm:
        for k in Mc:
            C[k] = max(C[k], C[k-1] if k > 0 else 0) + T[i][k]
    if best is None or C[2] < best[0]: best = (C[2], perm)
print("ENUMERATION_CHECK:", best)
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")

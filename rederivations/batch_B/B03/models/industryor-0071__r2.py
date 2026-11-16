#!/usr/bin/env python3
# industryor-0071: QAP n=2, cost = sum_{i,j,p,q} d_ij c_pq x_ip x_jq, r2: only i != j pairs; linearized with w_ipjq (binary products).
import pulp
INCLUDE_DIAG = False
d = {(1,1):10, (1,2):20, (2,1):30, (2,2):40}
c = {(1,1):5, (1,2):8, (2,1):6, (2,2):7}
N = [1, 2]
m = pulp.LpProblem("io0071", pulp.LpMinimize)
x = {(i,p): pulp.LpVariable(f"x_{i}_{p}", cat="Binary") for i in N for p in N}
keys = [(i,p,j,qq) for i in N for p in N for j in N for qq in N if (INCLUDE_DIAG or i != j)]
w = {k: pulp.LpVariable("w_%d_%d_%d_%d" % k, lowBound=0, upBound=1) for k in keys}
for i in N: m += pulp.lpSum(x[i,p] for p in N) == 1
for p in N: m += pulp.lpSum(x[i,p] for i in N) == 1
for (i,p,j,qq) in keys:
    m += w[i,p,j,qq] <= x[i,p]
    m += w[i,p,j,qq] <= x[j,qq]
    m += w[i,p,j,qq] >= x[i,p] + x[j,qq] - 1
m += pulp.lpSum(d[i,j]*c[p,qq]*w[i,p,j,qq] for (i,p,j,qq) in keys)
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

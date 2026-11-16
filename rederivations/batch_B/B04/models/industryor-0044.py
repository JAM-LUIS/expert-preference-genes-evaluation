#!/usr/bin/env python3
# Two-stage transshipment with fixed station costs. Supplies <= a_i, demands met exactly, station cap q_k if opened.
import pulp
a = {1:100, 2:150}; b = {1:80, 2:120}; f = {1:10, 2:15}; q = {1:100, 2:100}
c = {(1,1):2,(1,2):3,(2,1):4,(2,2):1}; cp = {(1,1):3,(1,2):2,(2,1):1,(2,2):4}
m = pulp.LpProblem("ior0044", pulp.LpMinimize)
x = {(i,k): pulp.LpVariable(f"x_{i}_{k}", lowBound=0) for i in a for k in f}
y = {(k,j): pulp.LpVariable(f"y_{k}_{j}", lowBound=0) for k in f for j in b}
z = {k: pulp.LpVariable(f"z_{k}", cat="Binary") for k in f}
m += pulp.lpSum(c[i,k]*x[i,k] for i in a for k in f) + pulp.lpSum(cp[k,j]*y[k,j] for k in f for j in b) + pulp.lpSum(f[k]*z[k] for k in f)
for i in a: m += pulp.lpSum(x[i,k] for k in f) <= a[i]
for j in b: m += pulp.lpSum(y[k,j] for k in f) == b[j]
for k in f:
    m += pulp.lpSum(x[i,k] for i in a) == pulp.lpSum(y[k,j] for j in b)
    m += pulp.lpSum(x[i,k] for i in a) <= q[k]*z[k]
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("STATUS:", s); print("SOLUTION_STATUS:", ss)
if s == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables(): print(" ", v.name, v.varValue)
else: print("FINAL_OBJECTIVE: None")

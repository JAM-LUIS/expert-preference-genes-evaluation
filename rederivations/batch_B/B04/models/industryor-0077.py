#!/usr/bin/env python3
# Assign 10 parts to machines A/B/C with setup costs. x1A + x2A = 1; parts 3,4,5 on A,B,C; at most 3 parts on C.
import pulp
M = ["A","B","C"]; parts = range(1,11)
cost = {"A":[10,20,30,40,50,60,70,80,90,100],"B":[15,25,35,45,55,65,75,85,95,105],"C":[20,30,40,50,60,70,80,90,100,110]}
d = {"A":100,"B":135,"C":200}
m = pulp.LpProblem("ior0077", pulp.LpMinimize)
x = {(i,k): pulp.LpVariable(f"x_{i}_{k}", cat="Binary") for i in parts for k in M}
y = {k: pulp.LpVariable(f"y_{k}", cat="Binary") for k in M}
m += pulp.lpSum(cost[k][i-1]*x[i,k] for i in parts for k in M) + pulp.lpSum(d[k]*y[k] for k in M)
for i in parts: m += pulp.lpSum(x[i,k] for k in M) == 1
for i in parts:
    for k in M: m += x[i,k] <= y[k]
m += x[1,"A"] + x[2,"A"] == 1
m += x[3,"A"] == 1; m += x[4,"B"] == 1; m += x[5,"C"] == 1
m += pulp.lpSum(x[i,"C"] for i in parts) <= 3
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("STATUS:", s); print("SOLUTION_STATUS:", ss)
if s == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        if v.varValue > 0.5: print(" ", v.name)
else: print("FINAL_OBJECTIVE: None")

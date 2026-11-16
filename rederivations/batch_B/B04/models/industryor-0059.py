#!/usr/bin/env python3
# Candy blending: x[i][j] kg of raw i in brand j. Max revenue - processing - raw cost.
import pulp
R = ["A","B","C"]; P = ["A","B","C"]
cost = {"A":2.0,"B":1.5,"C":1.0}; lim = {"A":2000,"B":2500,"C":1200}
proc = {"A":0.5,"B":0.4,"C":0.3}; price = {"A":3.4,"B":2.85,"C":2.25}
m = pulp.LpProblem("ior0059", pulp.LpMaximize)
x = {(i,j): pulp.LpVariable(f"x_{i}_{j}", lowBound=0) for i in R for j in P}
tot = {j: pulp.lpSum(x[i,j] for i in R) for j in P}
m += pulp.lpSum((price[j]-proc[j])*tot[j] for j in P) - pulp.lpSum(cost[i]*x[i,j] for i in R for j in P)
for i in R: m += pulp.lpSum(x[i,j] for j in P) <= lim[i]
m += x["A","A"] >= 0.60*tot["A"]
m += x["C","A"] <= 0.20*tot["A"]
m += x["A","B"] >= 0.15*tot["B"]
m += x["C","B"] <= 0.60*tot["B"]
m += x["C","C"] <= 0.50*tot["C"]
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("STATUS:", s); print("SOLUTION_STATUS:", ss)
if s == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables(): print(" ", v.name, v.varValue)
    for j in P: print("  brand", j, pulp.value(tot[j]))
else: print("FINAL_OBJECTIVE: None")

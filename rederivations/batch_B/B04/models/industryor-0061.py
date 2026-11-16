#!/usr/bin/env python3
# Fixed-charge device selection: produce 2000 units; x_k units on device k <= cap_k*y_k. Min setup + unit cost.
import pulp
D = {"A":(1000,20,900),"B":(920,24,1000),"C":(800,16,1200),"D":(700,28,1600)}
m = pulp.LpProblem("ior0061", pulp.LpMinimize)
x = {k: pulp.LpVariable(f"x_{k}", lowBound=0, cat="Integer") for k in D}
y = {k: pulp.LpVariable(f"y_{k}", cat="Binary") for k in D}
m += pulp.lpSum(D[k][0]*y[k] + D[k][1]*x[k] for k in D)
m += pulp.lpSum(x[k] for k in D) == 2000
for k in D: m += x[k] <= D[k][2]*y[k]
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("STATUS:", s); print("SOLUTION_STATUS:", ss)
if s == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables(): print(" ", v.name, v.varValue)
else: print("FINAL_OBJECTIVE: None")
to_relax = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
for v in to_relax: v.cat = pulp.LpContinuous
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective))

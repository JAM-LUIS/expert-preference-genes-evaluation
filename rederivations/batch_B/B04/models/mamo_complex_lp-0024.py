#!/usr/bin/env python3
# Diet: continuous servings (main; integer version printed as a side check) of 8 foods; min cost; protein>=98, carbs>=113, calories>=1768.
import pulp
F = {1:(1,4,93,6),2:(18,2,219,4),3:(19,26,155,4),4:(19,10,105,3),5:(3,24,255,2),6:(8,26,182,7),7:(15,27,173,3),8:(3,30,191,3)}
req = (98,113,1768)
m = pulp.LpProblem("mamo0024", pulp.LpMinimize)
x = {k: pulp.LpVariable(f"x_{k}", lowBound=0) for k in F}
m += pulp.lpSum(F[k][3]*x[k] for k in F)
for n in range(3): m += pulp.lpSum(F[k][n]*x[k] for k in F) >= req[n]
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("STATUS:", s); print("SOLUTION_STATUS:", ss)
if s == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables(): print(" ", v.name, v.varValue)
else: print("FINAL_OBJECTIVE: None")
for v in x.values(): v.cat = pulp.LpInteger
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGER_VERSION:", pulp.LpStatus[m.status], pulp.LpSolution[m.sol_status], pulp.value(m.objective))

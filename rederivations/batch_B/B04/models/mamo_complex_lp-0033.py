#!/usr/bin/env python3
# Diet: continuous servings (main; integer version printed as a side check) of 6 foods; min cost; protein>=73, carbs>=111, calories>=2196.
import pulp
F = {"Pasta":(15,30,154,3),"Avocado":(20,16,111,8),"Chicken":(15,8,211,7),"Tofu":(19,5,87,2),"Spinach":(19,28,98,9),"Cheese":(12,17,231,10)}
req = (73,111,2196)
m = pulp.LpProblem("mamo0033", pulp.LpMinimize)
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

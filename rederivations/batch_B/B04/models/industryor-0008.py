#!/usr/bin/env python3
# Assignment: choose 4 of 5 workers, each task done by exactly one worker, each worker at most one task. Min total hours.
import pulp
W = ["I","II","III","IV","V"]; T = ["A","B","C","D"]
h = {"I":[9,4,3,7],"II":[4,6,5,6],"III":[5,4,7,5],"IV":[7,5,2,3],"V":[10,6,7,4]}
m = pulp.LpProblem("ior0008", pulp.LpMinimize)
x = {(w,t): pulp.LpVariable(f"x_{w}_{t}", cat="Binary") for w in W for t in T}
m += pulp.lpSum(h[w][j]*x[w,t] for w in W for j,t in enumerate(T))
for t in T: m += pulp.lpSum(x[w,t] for w in W) == 1
for w in W: m += pulp.lpSum(x[w,t] for t in T) <= 1
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("STATUS:", s); print("SOLUTION_STATUS:", ss)
if s == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        if v.varValue and v.varValue > 0.5: print(" ", v.name, v.varValue)
else: print("FINAL_OBJECTIVE: None")

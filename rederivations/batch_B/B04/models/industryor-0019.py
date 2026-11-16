#!/usr/bin/env python3
# Orders (integer) from A (15 chairs, $50/chair), B (10, $45), C (10, $40). 100<=chairs<=500.
# If any A ordered -> at least 10 chairs from B; if any B ordered -> some C ordered. Min cost.
import pulp
m = pulp.LpProblem("ior0019", pulp.LpMinimize)
nA = pulp.LpVariable("nA", lowBound=0, cat="Integer")
nB = pulp.LpVariable("nB", lowBound=0, cat="Integer")
nC = pulp.LpVariable("nC", lowBound=0, cat="Integer")
yA = pulp.LpVariable("yA", cat="Binary"); yB = pulp.LpVariable("yB", cat="Binary")
MA, MB = 500//15, 500//10
m += 50*15*nA + 45*10*nB + 40*10*nC
chairs = 15*nA + 10*nB + 10*nC
m += chairs >= 100
m += chairs <= 500
m += nA <= MA*yA
m += 10*nB >= 10*yA          # A used -> >=10 chairs from B
m += nB <= MB*yB
m += nC >= yB                # B used -> C used
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

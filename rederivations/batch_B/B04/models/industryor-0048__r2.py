#!/usr/bin/env python3
# Alternative reading: maximize weekly profit with all goals p1-p4 imposed as hard constraints.
import pulp
m = pulp.LpProblem("ior0048_r2", pulp.LpMaximize)
xA = pulp.LpVariable("xA", lowBound=0, cat="Integer"); xB = pulp.LpVariable("xB", lowBound=0, cat="Integer")
oA = pulp.LpVariable("oA", lowBound=0, cat="Integer"); oB = pulp.LpVariable("oB", lowBound=0, cat="Integer")
profit = 300*xA + 450*xB + 280*oA + 425*oB
m += profit
m += profit >= 10000
m += xA + oA >= 10
m += xB + oB >= 15
m += 4*(xA+oA) + 6*(xB+oB) == 150
m += 3*xA + 2*xB == 70     # regular Process II fully used
m += 3*oA + 2*oB <= 30
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

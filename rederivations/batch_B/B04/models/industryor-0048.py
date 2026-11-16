#!/usr/bin/env python3
# Preemptive goal programming (main reading). xA,xB regular units; oA,oB units made in Process-II overtime (integer).
# Process I: 4(xA+oA)+6(xB+oB) = 150 goal; Process II regular: 3xA+2xB <= 70 (regular capacity), goal = 70 (fully used);
# overtime hours 3oA+2oB, goal <= 30. Profit = 300xA+450xB+280oA+425oB, goal >= 10000. Contract goals A>=10, B>=15.
# Priorities P1..P4 solved lexicographically; reported objective = sum of all weighted-priority deviations at the end.
import pulp
def build():
    m = pulp.LpProblem("ior0048", pulp.LpMinimize)
    xA = pulp.LpVariable("xA", lowBound=0, cat="Integer"); xB = pulp.LpVariable("xB", lowBound=0, cat="Integer")
    oA = pulp.LpVariable("oA", lowBound=0, cat="Integer"); oB = pulp.LpVariable("oB", lowBound=0, cat="Integer")
    dv = {}
    for nm in ["1","2","3","4","5","6"]:
        dv["m"+nm] = pulp.LpVariable("dm"+nm, lowBound=0); dv["p"+nm] = pulp.LpVariable("dp"+nm, lowBound=0)
    profit = 300*xA + 450*xB + 280*oA + 425*oB
    m += profit + dv["m1"] - dv["p1"] == 10000
    m += xA + oA + dv["m2"] - dv["p2"] == 10
    m += xB + oB + dv["m3"] - dv["p3"] == 15
    m += 4*(xA+oA) + 6*(xB+oB) + dv["m4"] - dv["p4"] == 150
    m += 3*xA + 2*xB <= 70
    m += 3*xA + 2*xB + dv["m5"] - dv["p5"] == 70
    m += 3*oA + 2*oB + dv["m6"] - dv["p6"] == 30
    goals = [dv["m1"], dv["m2"] + dv["m3"], dv["m4"] + dv["p4"] + dv["m5"], dv["p6"]]
    return m, goals, (xA, xB, oA, oB), profit
m, goals, X, profit = build()
ok = True
for g in goals:
    m.setObjective(g)
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    if not (pulp.LpStatus[m.status] == "Optimal" and pulp.LpSolution[m.sol_status] == "Optimal Solution Found"):
        ok = False; break
    val = pulp.value(g)
    print("  priority level achieved deviation", val)
    m += g <= val + 1e-7
m.setObjective(pulp.lpSum(goals))
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("STATUS:", s); print("SOLUTION_STATUS:", ss)
if ok and s == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in X: print(" ", v.name, v.varValue)
    print("  profit", pulp.value(profit))
else: print("FINAL_OBJECTIVE: None")

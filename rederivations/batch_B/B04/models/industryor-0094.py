#!/usr/bin/env python3
# Crude blending with concave (decreasing-price) purchase cost of crude A -> tiers with ordering binaries (exact).
# x[o,g] t of crude o in gasoline g. A available = 500 inventory + purchase z (<=1500); B available 1000.
# Max revenue - purchase cost (existing inventory treated as sunk / zero cost).
import pulp
m = pulp.LpProblem("ior0094", pulp.LpMaximize)
x = {(o,g): pulp.LpVariable(f"x_{o}_{g}", lowBound=0) for o in "AB" for g in (1,2)}
z1 = pulp.LpVariable("z1", lowBound=0, upBound=500); z2 = pulp.LpVariable("z2", lowBound=0, upBound=500)
z3 = pulp.LpVariable("z3", lowBound=0, upBound=500)
w1 = pulp.LpVariable("w1", cat="Binary"); w2 = pulp.LpVariable("w2", cat="Binary")
m += 4800*(x["A",1]+x["B",1]) + 5600*(x["A",2]+x["B",2]) - (10000*z1 + 8000*z2 + 6000*z3)
m += z1 >= 500*w1; m += z2 <= 500*w1     # tier 2 only after tier 1 full
m += z2 >= 500*w2; m += z3 <= 500*w2     # tier 3 only after tier 2 full
m += x["A",1] + x["A",2] <= 500 + z1 + z2 + z3
m += x["B",1] + x["B",2] <= 1000
m += x["A",1] >= 0.5*(x["A",1] + x["B",1])
m += x["A",2] >= 0.6*(x["A",2] + x["B",2])
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("STATUS:", s); print("SOLUTION_STATUS:", ss)
if s == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables(): print(" ", v.name, v.varValue)
else: print("FINAL_OBJECTIVE: None")

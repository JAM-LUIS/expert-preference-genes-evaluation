#!/usr/bin/env python3
# Split items between two sons; dogs (2x3000) indivisible pair. Min |V1 - V2| via epigraph.
import pulp
items = {"painting":25000,"bust":5000,"vase":20000,"porsche":40000,"diamond1":12000,"diamond2":12000,
         "diamond3":12000,"sofa":3000,"dogs_pair":6000,"sculpture":10000,"boat":15000,"harley":10000,"cavour":13000}
m = pulp.LpProblem("ior0033", pulp.LpMinimize)
x = {k: pulp.LpVariable(f"x_{k}", cat="Binary") for k in items}  # 1 -> son 1
d = pulp.LpVariable("d", lowBound=0)
V1 = pulp.lpSum(items[k]*x[k] for k in items); V2 = pulp.lpSum(items[k]*(1-x[k]) for k in items)
m += d
m += d >= V1 - V2
m += d >= V2 - V1
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("STATUS:", s); print("SOLUTION_STATUS:", ss)
if s == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    print("  son1 value", pulp.value(V1), "son2 value", pulp.value(V2))
    for k in items: print(" ", k, x[k].varValue)
else: print("FINAL_OBJECTIVE: None")

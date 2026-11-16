#!/usr/bin/env python3
# Timber LP. Units: volume 10^4 m3, money 10^4 yuan (price 10^4 yuan / 10^4 m3 = yuan/m3).
# x[i,j] = amount bought at start of quarter i and sold in quarter j (j>=i); storage cost (a+b*u) yuan/m3 with
# u=j-i quarters, charged only when u>=1 (main). Warehouse capacity 20 (10^4 m3) applies to all timber held during
# quarter t (bought at start of t + carried in). Sales in quarter j <= max sales. All sold by end of autumn.
import pulp
CAP_MODE = "all_stock"     # or "carried_only"
CHARGE_U0 = True
Q = [0,1,2,3]; buy = [410,430,460,450]; sell = [425,440,465,455]; smax = [100,140,200,160]
a, b = 70, 100
def hold(u):
    if u == 0 and not CHARGE_U0: return 0
    return a + b*u
m = pulp.LpProblem("ior0076", pulp.LpMaximize)
x = {(i,j): pulp.LpVariable(f"x_{i}_{j}", lowBound=0) for i in Q for j in Q if j >= i}
m += pulp.lpSum((sell[j] - buy[i] - hold(j-i))*x[i,j] for (i,j) in x)
for j in Q: m += pulp.lpSum(x[i,j] for i in Q if i <= j) <= smax[j]
for t in Q:
    if CAP_MODE == "all_stock":
        m += pulp.lpSum(x[i,j] for (i,j) in x if i <= t <= j) <= 20
    else:
        m += pulp.lpSum(x[i,j] for (i,j) in x if i <= t < j) <= 20
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("CAP_MODE:", CAP_MODE, "CHARGE_U0:", CHARGE_U0)
print("STATUS:", s); print("SOLUTION_STATUS:", ss)
if s == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        if v.varValue > 1e-9: print(" ", v.name, v.varValue)
else: print("FINAL_OBJECTIVE: None")

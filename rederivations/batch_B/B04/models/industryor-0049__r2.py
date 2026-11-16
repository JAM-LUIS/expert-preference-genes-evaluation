#!/usr/bin/env python3
# Warehouse rental, main reading: a contract (start s, length k) may start in any month s with s+k-1<=4.
# n[s,k] = number of 100 m2 units rented (integer). Coverage each month == demand exactly.
# y_k: length k used; >=2 distinct lengths; y4 + y1 <= 1; number of distinct contracts (s,k) signed <= 3.
import pulp, sys
READING = "distinct_sk"
dem = {1:15, 2:10, 3:20, 4:12}   # in 100 m2
fee = {1:4000, 2:7500, 3:10500, 4:13000}
if READING == "start1":
    K = [(1,k) for k in fee]
else:
    K = [(s,k) for s in range(1,5) for k in fee if s+k-1 <= 4]
m = pulp.LpProblem("ior0049", pulp.LpMinimize)
n = {sk: pulp.LpVariable(f"n_{sk[0]}_{sk[1]}", lowBound=0, cat="Integer") for sk in K}
u = {sk: pulp.LpVariable(f"u_{sk[0]}_{sk[1]}", cat="Binary") for sk in K}
y = {k: pulp.LpVariable(f"y_{k}", cat="Binary") for k in fee}
Mbig = max(dem.values())
m += pulp.lpSum(fee[k]*n[s,k] for (s,k) in K)
for t in dem:
    m += pulp.lpSum(n[s,k] for (s,k) in K if s <= t <= s+k-1) == dem[t]
for (s,k) in K:
    m += n[s,k] <= Mbig*u[s,k]
    m += n[s,k] >= u[s,k]
    m += u[s,k] <= y[k]
for k in fee:
    m += y[k] <= pulp.lpSum(u[s,kk] for (s,kk) in K if kk == k)
m += pulp.lpSum(y.values()) >= 2
m += y[4] + y[1] <= 1
if READING == "types":
    m += pulp.lpSum(y.values()) <= 3
else:
    m += pulp.lpSum(u.values()) <= 3
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s_ = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("READING:", READING)
print("STATUS:", s_); print("SOLUTION_STATUS:", ss)
if s_ == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        if v.varValue and v.varValue > 1e-6: print(" ", v.name, v.varValue)
else: print("FINAL_OBJECTIVE: None")

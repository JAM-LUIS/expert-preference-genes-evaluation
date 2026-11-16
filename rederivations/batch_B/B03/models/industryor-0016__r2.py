#!/usr/bin/env python3
# industryor-0016: purchase at start of month, r2: sales in month i limited to stock at start of month (before purchase).
import pulp
SELL_BEFORE_BUY = True
pc = {1: 8, 2: 6, 3: 9}
sp = {1: 9, 2: 8, 3: 10}
M = [1, 2, 3]
m = pulp.LpProblem("io0016", pulp.LpMaximize)
x = pulp.LpVariable.dicts("buy", M, lowBound=0)
y = pulp.LpVariable.dicts("sell", M, lowBound=0)
s = pulp.LpVariable.dicts("stock_end", M, lowBound=0)
m += pulp.lpSum(sp[i]*y[i] - pc[i]*x[i] for i in M)
for i in M:
    prev = s[i-1] if i > 1 else 200
    m += prev + x[i] <= 500, f"cap_{i}"
    if SELL_BEFORE_BUY:
        m += y[i] <= prev, f"sellavail_{i}"
    m += s[i] == prev + x[i] - y[i], f"bal_{i}"
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")

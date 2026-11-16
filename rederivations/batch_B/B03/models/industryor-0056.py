#!/usr/bin/env python3
# industryor-0056: grain trading. Each month: sell (only stock held at start of month), then buy.
# Sales revenue of the month is available to pay for that month's purchases (REV_SAME_MONTH=True).
import pulp
REV_SAME_MONTH = True
pb = {1: 2.85, 2: 3.05, 3: 2.90}
ps = {1: 3.10, 2: 3.25, 3: 2.95}
M = [1, 2, 3]
m = pulp.LpProblem("io0056", pulp.LpMaximize)
x = pulp.LpVariable.dicts("buy", M, lowBound=0)
y = pulp.LpVariable.dicts("sell", M, lowBound=0)
s = pulp.LpVariable.dicts("stock_end", M, lowBound=0)
cash = pulp.LpVariable.dicts("cash_end", M, lowBound=0)
for i in M:
    prev_s = s[i-1] if i > 1 else 1000
    prev_c = cash[i-1] if i > 1 else 20000
    m += y[i] <= prev_s, f"sell_avail_{i}"
    m += prev_s - y[i] + x[i] <= 5000, f"cap_{i}"
    m += s[i] == prev_s - y[i] + x[i], f"bal_{i}"
    if REV_SAME_MONTH:
        m += pb[i]*x[i] <= prev_c + ps[i]*y[i], f"fund_{i}"
    else:
        m += pb[i]*x[i] <= prev_c, f"fund_{i}"
    m += cash[i] == prev_c + ps[i]*y[i] - pb[i]*x[i], f"cashbal_{i}"
m += s[3] == 2000, "end_inv"
m += pulp.lpSum(ps[i]*y[i] - pb[i]*x[i] for i in M)
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

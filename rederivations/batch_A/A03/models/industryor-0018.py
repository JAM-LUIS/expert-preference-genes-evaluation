#!/usr/bin/env python3
# industryor-0018: preemptive goal programme, solved lexicographically (p1 > p2 > p3 > p4)
import pulp
m = pulp.LpProblem("io0018", pulp.LpMinimize)
x1 = pulp.LpVariable("curtain_hours", 0); x2 = pulp.LpVariable("clothing_hours", 0)
dn = pulp.LpVariable.dicts("dminus", [1, 2, 3, 4], 0); dp = pulp.LpVariable.dicts("dplus", [1, 2, 3, 4], 0)
m += x1 + x2 + dn[1] - dp[1] == 110
m += x1 + x2 + dn[2] - dp[2] == 120            # overtime beyond 10 h = dp[2]
m += 1000 * x1 + dn[3] - dp[3] == 70000
m += 1000 * x2 + dn[4] - dp[4] == 45000
levels = [("p1", dn[1]), ("p2", dp[2]), ("p3", dn[3] + dn[4]), ("p4", dp[1])]
ok = True; vals = []
for k, (name, expr) in enumerate(levels):
    m.setObjective(expr)
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
    if not (status == "Optimal" and sol == "Optimal Solution Found"): ok = False; break
    v = pulp.value(expr); vals.append(v); print(f"LEVEL {name}: {v}")
    if k < len(levels) - 1: m += expr <= v + 1e-9, f"fix_{name}"
print("STATUS:", status); print("SOLUTION_STATUS:", sol)
if ok:
    print("FINAL_OBJECTIVE:", vals[-1])
    for v in m.variables(): print(f"  {v.name} = {v.varValue}")
    print("PROFIT_AT_SOLUTION:", 2.5 * 1000 * x1.varValue + 1.5 * 1000 * x2.varValue)
else:
    print("FINAL_OBJECTIVE: None")

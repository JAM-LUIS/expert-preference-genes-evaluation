#!/usr/bin/env python3
# industryor-0037 reading 2: preemptive goal programme, minimise deviations lexicographically
import pulp
m = pulp.LpProblem("io0037r2", pulp.LpMinimize)
A = pulp.LpVariable("A", 0, cat="Integer"); B = pulp.LpVariable("B", 0, cat="Integer")
K = [1, 2, 3, 4, 5]
dn = pulp.LpVariable.dicts("dminus", K, 0); dp = pulp.LpVariable.dicts("dplus", K, 0)
m += 300 * A + 450 * B + dn[1] - dp[1] == 10000
m += A + dn[2] - dp[2] == 10
m += B + dn[3] - dp[3] == 15
m += 4 * A + 6 * B + dn[4] - dp[4] == 150
m += 3 * A + 2 * B + dn[5] - dp[5] == 70
levels = [("p1", dn[1]), ("p2", dn[2] + dn[3]), ("p3", dn[4] + dp[4] + dn[5])]
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
else:
    print("FINAL_OBJECTIVE: None")

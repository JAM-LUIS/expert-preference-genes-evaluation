#!/usr/bin/env python3
# industryor-0015: tool purchase/repair. Tools used in stage j, sent at end of stage j,
# fast repair returns usable in stage j+q, slow in stage j+p (this file: LAG_EXTRA=1, i.e. fast usable in j+q+1, slow in j+p+1).
import pulp
LAG_EXTRA = 1
n = 10
r = [3, 5, 2, 4, 6, 5, 4, 3, 2, 1]
a, b, c, p, q = 10, 1, 3, 3, 1
J = range(1, n+1)
R = {j: r[j-1] for j in J}
m = pulp.LpProblem("io0015", pulp.LpMinimize)
x = pulp.LpVariable.dicts("buy", J, lowBound=0, cat="Integer")
y = pulp.LpVariable.dicts("slow", J, lowBound=0, cat="Integer")
z = pulp.LpVariable.dicts("fast", J, lowBound=0, cat="Integer")
cl = pulp.LpVariable.dicts("clean_left", J, lowBound=0, cat="Integer")   # clean tools left after stage j
dt = pulp.LpVariable.dicts("dirty_left", J, lowBound=0, cat="Integer")   # used, unrepaired tools after stage j
m += pulp.lpSum(a*x[j] + b*y[j] + c*z[j] for j in J)
for j in J:
    ret = 0
    if j - p - LAG_EXTRA >= 1: ret += y[j-p-LAG_EXTRA]
    if j - q - LAG_EXTRA >= 1: ret += z[j-q-LAG_EXTRA]
    prev_cl = cl[j-1] if j > 1 else 0
    m += prev_cl + x[j] + ret - R[j] == cl[j], f"clean_{j}"
    prev_dt = dt[j-1] if j > 1 else 0
    m += prev_dt + R[j] - y[j] - z[j] == dt[j], f"dirty_{j}"
# repairs that would return after stage n are useless; forbid (no effect on optimum, just tidy)
for j in J:
    if j + p + LAG_EXTRA > n: m += y[j] == 0
    if j + q + LAG_EXTRA > n: m += z[j] == 0
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
to_relax = [v for v in m.variables()
            if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
for v in to_relax:
    v.cat = pulp.LpContinuous
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
      f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
for v in to_relax:
    v.cat = pulp.LpInteger

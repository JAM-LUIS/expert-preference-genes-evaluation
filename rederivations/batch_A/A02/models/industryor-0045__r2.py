#!/usr/bin/env python3
import pulp
# Reading 2: all-units tiers - the unit profit of the tier reached applies to ALL units of that product.
m = pulp.LpProblem("tiers_all_units", pulp.LpMaximize)
UB = {"A": 70, "B": 50, "C": 100}   # from tech prep / labor: A<=700/10, B<=100/2, C<=100/1
brk = {
    "A": [(0, 40, 10), (41, 100, 9), (101, 150, 8), (151, 1000, 7)],
    "B": [(0, 50, 6), (51, 100, 4), (101, 1000, 3)],
    "C": [(0, 100, 5), (101, 1000, 4)],
}
z, x = {}, {}
for p in brk:
    for k, (lo, hi, pr) in enumerate(brk[p]):
        z[p, k] = pulp.LpVariable(f"z_{p}_{k}", cat="Binary")
        x[p, k] = pulp.LpVariable(f"x_{p}_{k}", lowBound=0, cat="Integer")
        m += x[p, k] >= lo * z[p, k]
        m += x[p, k] <= min(hi, UB[p]) * z[p, k] if lo <= UB[p] else x[p, k] <= 0
    m += pulp.lpSum(z[p, k] for k in range(len(brk[p]))) == 1
q = {p: pulp.lpSum(x[p, k] for k in range(len(brk[p]))) for p in brk}
m += pulp.lpSum(brk[p][k][2] * x[p, k] for p in brk for k in range(len(brk[p])))
m += 1 * q["A"] + 2 * q["B"] + 1 * q["C"] <= 100, "tech_prep"
m += 10 * q["A"] + 4 * q["B"] + 5 * q["C"] <= 700, "labor"
m += 3 * q["A"] + 2 * q["B"] + 1 * q["C"] <= 400, "materials"

m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        if v.varValue and abs(v.varValue) > 1e-9:
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

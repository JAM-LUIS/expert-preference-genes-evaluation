#!/usr/bin/env python3
import pulp
# Reading 1 (main): incremental (marginal) tiers - each tier's unit profit applies to units inside that tier.
m = pulp.LpProblem("tiers_incremental", pulp.LpMaximize)
BIG = 1000  # last tier is open-ended; resources bound output far below this
tiers = {
    "A": [(40, 10), (60, 9), (50, 8), (BIG, 7)],
    "B": [(50, 6), (50, 4), (BIG, 3)],
    "C": [(100, 5), (BIG, 4)],
}
s = {(p, k): pulp.LpVariable(f"s_{p}_{k}", lowBound=0, upBound=w, cat="Integer")
     for p in tiers for k, (w, _) in enumerate(tiers[p])}
q = {p: pulp.lpSum(s[p, k] for k in range(len(tiers[p]))) for p in tiers}
m += pulp.lpSum(tiers[p][k][1] * s[p, k] for p in tiers for k in range(len(tiers[p])))
m += 1 * q["A"] + 2 * q["B"] + 1 * q["C"] <= 100, "tech_prep"
m += 10 * q["A"] + 4 * q["B"] + 5 * q["C"] <= 700, "labor"
m += 3 * q["A"] + 2 * q["B"] + 1 * q["C"] <= 400, "materials"
# decreasing marginal profit + maximisation => tiers fill in order automatically

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

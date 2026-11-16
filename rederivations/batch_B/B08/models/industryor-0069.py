#!/usr/bin/env python3
# Main reading: waste = trim loss + surplus pieces (any over-produced length counts as waste).
import pulp
pats = [(a, b) for a in range(4) for b in range(3) if 3*a + 4*b <= 10 and (a, b) != (0, 0)]
m = pulp.LpProblem("io0069", pulp.LpMinimize)
x = {p: pulp.LpVariable(f"x_{p[0]}_{p[1]}", lowBound=0, cat="Integer") for p in pats}
m += pulp.lpSum(10*x[p] for p in pats) - (90*3 + 60*4)
m += pulp.lpSum(p[0]*x[p] for p in pats) >= 90
m += pulp.lpSum(p[1]*x[p] for p in pats) >= 60

m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        if v.varValue:
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

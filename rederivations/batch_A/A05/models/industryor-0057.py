#!/usr/bin/env python3
import pulp

def report(m, relax=False):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
    print("STATUS:", status); print("SOLUTION_STATUS:", sol)
    if status == "Optimal" and sol == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue and abs(v.varValue) > 1e-9: print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
    if relax:
        tr = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
        for v in tr: v.cat = pulp.LpContinuous
        m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
        print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), f"({len(tr)} general-integer variables made continuous; binaries kept)")
        for v in tr: v.cat = pulp.LpInteger

# Cutting stock by length: each pattern (set of widths side by side on a 1 m or 2 m roll) is run for some length.
# Waste area = total roll area used - ordered area (orders met exactly; all sub-patterns are enumerated).
import itertools
w = [5, 7, 9]            # widths in tenths of a metre
L = [1000, 3000, 2000]   # required lengths (m)
pats = []
for W in (10, 20):
    for cnt in itertools.product(range(W // 5 + 1), range(W // 7 + 1), range(W // 9 + 1)):
        used = sum(c * wi for c, wi in zip(cnt, w))
        if 0 < used <= W: pats.append((W, cnt))
m = pulp.LpProblem("p0057", pulp.LpMinimize)
x = [pulp.LpVariable(f"len_W{W}_{'_'.join(map(str, c))}", lowBound=0) for W, c in pats]
m += pulp.lpSum((W / 10.0) * x[k] for k, (W, c) in enumerate(pats)) - sum(wi / 10.0 * li for wi, li in zip(w, L))
for i in range(3):
    m += pulp.lpSum(c[i] * x[k] for k, (W, c) in enumerate(pats)) == L[i]
report(m)

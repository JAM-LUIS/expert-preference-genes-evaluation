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

dem = [40, 60, 75, 25]; T = range(4)
m = pulp.LpProblem("mamo0207", pulp.LpMinimize)
reg = pulp.LpVariable.dicts("reg", T, lowBound=0, upBound=40)
ot = pulp.LpVariable.dicts("ot", T, lowBound=0)
inv = pulp.LpVariable.dicts("inv", T, lowBound=0)
m += pulp.lpSum(400 * reg[t] + 450 * ot[t] + 20 * inv[t] for t in T)
for t in T:
    m += (inv[t - 1] if t else 10) + reg[t] + ot[t] - dem[t] == inv[t]
report(m)

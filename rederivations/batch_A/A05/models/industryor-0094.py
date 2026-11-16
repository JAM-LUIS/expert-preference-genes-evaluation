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

# Blending with incremental (tiered) purchase price for crude A; profit = sales revenue - purchase cost (yuan).
m = pulp.LpProblem("p0094", pulp.LpMaximize)
a1 = pulp.LpVariable("A_in_I", lowBound=0); b1 = pulp.LpVariable("B_in_I", lowBound=0)
a2 = pulp.LpVariable("A_in_II", lowBound=0); b2 = pulp.LpVariable("B_in_II", lowBound=0)
t1 = pulp.LpVariable("tier1", lowBound=0, upBound=500)
t2 = pulp.LpVariable("tier2", lowBound=0, upBound=500)
t3 = pulp.LpVariable("tier3", lowBound=0, upBound=500)
w1 = pulp.LpVariable("tier1_full", cat="Binary"); w2 = pulp.LpVariable("tier2_full", cat="Binary")
m += 4800 * (a1 + b1) + 5600 * (a2 + b2) - (10000 * t1 + 8000 * t2 + 6000 * t3)
m += a1 + a2 <= 500 + t1 + t2 + t3
m += b1 + b2 <= 1000
m += a1 >= 0.5 * (a1 + b1)
m += a2 >= 0.6 * (a2 + b2)
m += t1 >= 500 * w1; m += t2 <= 500 * w1      # tier 2 only after tier 1 is exhausted
m += t2 >= 500 * w2; m += t3 <= 500 * w2      # tier 3 only after tier 2 is exhausted
report(m)

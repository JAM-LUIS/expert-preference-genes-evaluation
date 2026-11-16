#!/usr/bin/env python3
# industryor-0021: table orders from three suppliers
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

m = pulp.LpProblem("io0021", pulp.LpMinimize)
a = pulp.LpVariable("ordersA", 0, cat="Integer"); b = pulp.LpVariable("ordersB", 0, cat="Integer"); c = pulp.LpVariable("ordersC", 0, cat="Integer")
ua = pulp.LpVariable("useA", cat="Binary"); ub = pulp.LpVariable("useB", cat="Binary")
tables = 20 * a + 15 * b + 15 * c
m += 120 * 20 * a + 110 * 15 * b + 100 * 15 * c
m += tables >= 150; m += tables <= 600
m += a <= 30 * ua            # 20a <= 600 -> a <= 30
m += b <= 40 * ub            # 15b <= 600 -> b <= 40
m += 15 * b >= 30 * ua       # A used -> at least 30 tables from B
m += c >= ub                 # B used -> C used
report(m, relax=True)

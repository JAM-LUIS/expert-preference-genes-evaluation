#!/usr/bin/env python3
# industryor-0047: farm operating plan
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

m = pulp.LpProblem("io0047", pulp.LpMaximize)
soy = pulp.LpVariable("soy_ha", 0); corn = pulp.LpVariable("corn_ha", 0); wheat = pulp.LpVariable("wheat_ha", 0)
cow = pulp.LpVariable("cows", 0, 32, cat="Integer"); chick = pulp.LpVariable("chickens", 0, 3000, cat="Integer")
ext_aw = pulp.LpVariable("external_days_aw", 0, cat="Integer"); ext_ss = pulp.LpVariable("external_days_ss", 0, cat="Integer")
m += 175 * soy + 300 * corn + 120 * wheat + 400 * cow + 2 * chick + 1.8 * ext_aw + 2.1 * ext_ss
m += soy + corn + wheat + 1.5 * cow <= 100, "land"
m += 400 * cow + 3 * chick <= 15000, "funds"
m += 20 * soy + 35 * corn + 10 * wheat + 100 * cow + 0.6 * chick + ext_aw <= 3500, "labour_aw"
m += 50 * soy + 75 * corn + 40 * wheat + 50 * cow + 0.3 * chick + ext_ss <= 4000, "labour_ss"
report(m, relax=True)

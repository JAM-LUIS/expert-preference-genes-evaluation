#!/usr/bin/env python3
import pulp

def report(m, relax=False):
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
    if relax:
        to_relax = [v for v in m.variables()
                    if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
        for v in to_relax:
            v.cat = pulp.LpContinuous
        m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
        print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
              f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
        for v in to_relax:
            v.cat = pulp.LpInteger

AVERAGE = True
months = [7, 8, 9, 10, 11, 12]
dem = {"I": {7: 30000, 8: 30000, 9: 30000, 10: 100000, 11: 100000, 12: 100000},
       "II": {7: 15000, 8: 15000, 9: 15000, 10: 50000, 11: 50000, 12: 50000}}
pc = {"I": 4.5, "II": 7.0}      # June-December unit production cost
vol = {"I": 0.2, "II": 0.4}
m = pulp.LpProblem("p0067", pulp.LpMinimize)
x = {(p, t): pulp.LpVariable(f"prod_{p}_{t}", lowBound=0, cat="Integer") for p in dem for t in months}
s = {(p, t): pulp.LpVariable(f"inv_{p}_{t}", lowBound=0, cat="Integer") for p in dem for t in months}
own = {t: pulp.LpVariable(f"own_m3_{t}", lowBound=0, upBound=15000) for t in months}
ext = {t: pulp.LpVariable(f"ext_m3_{t}", lowBound=0) for t in months}
m += pulp.lpSum(pc[p] * x[p, t] for p in dem for t in months) + pulp.lpSum(1.0 * own[t] + 1.5 * ext[t] for t in months)
for t in months:
    m += x["I", t] + x["II", t] <= 120000
    for p in dem:
        prev = 0 if t == 7 else s[p, t - 1]
        m += prev + x[p, t] - dem[p][t] == s[p, t]
    if AVERAGE:   # storage charged on average of opening and closing stock of the month
        stored = pulp.lpSum(vol[p] * ((0 if t == 7 else s[p, t - 1]) + s[p, t]) / 2 for p in dem)
    else:         # storage charged on end-of-month stock
        stored = pulp.lpSum(vol[p] * s[p, t] for p in dem)
    m += stored == own[t] + ext[t]
report(m, relax=True)

#!/usr/bin/env python3
import pulp
m = pulp.LpProblem("transport", pulp.LpMinimize)
truck = pulp.LpVariable("truck", lowBound=0, cat="Integer")
van = pulp.LpVariable("van", lowBound=0, cat="Integer")
moto = pulp.LpVariable("motorcycle", lowBound=0, cat="Integer")
ev = pulp.LpVariable("ev", lowBound=0, cat="Integer")
use_van = pulp.LpVariable("use_van", cat="Binary")
use_ev = pulp.LpVariable("use_ev", cat="Binary")
pollution = 100 * truck + 50 * van + 10 * moto + 0 * ev
m += pollution
m += pollution <= 2000, "pollution_cap"
m += truck >= 10, "min_truck"
m += 100 * truck + 80 * van + 40 * moto + 60 * ev >= 1800, "deliver"
m += van <= 40 * use_van, "van_on"      # 50*van <= 2000 -> van <= 40
m += ev <= 30 * use_ev, "ev_on"         # 30 trips already carry 1800; more is never needed
m += use_van + use_ev <= 1, "van_xor_ev"

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

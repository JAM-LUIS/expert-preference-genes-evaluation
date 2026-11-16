#!/usr/bin/env python3
import pulp
m = pulp.LpProblem("farmer", pulp.LpMinimize)
horse = pulp.LpVariable("horse", lowBound=0, cat="Integer")
bike = pulp.LpVariable("bicycle", lowBound=0, cat="Integer")
cart = pulp.LpVariable("handcart", lowBound=0, cat="Integer")
ub = pulp.LpVariable("use_bicycle", cat="Binary")
uc = pulp.LpVariable("use_handcart", cat="Binary")
pollution = 80 * horse + 0 * bike + 0 * cart
m += pollution
m += pollution <= 1000, "pollution_cap"
m += horse >= 8, "min_horse"
m += 55 * horse + 30 * bike + 40 * cart >= 1000, "deliver"
m += bike <= 34 * ub     # 34 trips already carry >= 1000
m += cart <= 25 * uc     # 25 trips carry 1000
m += ub + uc <= 1, "only_one_of_bicycle_handcart"

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

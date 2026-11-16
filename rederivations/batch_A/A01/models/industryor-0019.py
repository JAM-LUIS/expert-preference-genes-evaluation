import pulp
m = pulp.LpProblem("chairs", pulp.LpMinimize)
nA = pulp.LpVariable("ordersA", lowBound=0, cat="Integer")
nB = pulp.LpVariable("ordersB", lowBound=0, cat="Integer")
nC = pulp.LpVariable("ordersC", lowBound=0, cat="Integer")
yA = pulp.LpVariable("useA", cat="Binary")
yB = pulp.LpVariable("useB", cat="Binary")
chairs = 15*nA + 10*nB + 10*nC
m += 50*15*nA + 45*10*nB + 40*10*nC
m += chairs >= 100
m += chairs <= 500
m += nA <= 33*yA          # 15*33 <= 500
m += nB <= 50*yB
m += 10*nB >= 10*yA       # if A then at least 10 chairs from B
m += nC >= yB             # if B then some order from C

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


to_relax = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
for v in to_relax:
    v.cat = pulp.LpContinuous
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), f"({len(to_relax)} general-integer variables made continuous; binaries kept)")


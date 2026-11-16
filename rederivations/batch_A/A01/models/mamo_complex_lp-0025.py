import pulp
F = {"Chicken":(18,5,202,1),"Rice":(14,13,234,7),"Eggs":(18,4,220,4),"Broccoli":(7,15,247,3),"Lentils":(15,17,88,1),"Apples":(8,13,77,2)}
m = pulp.LpProblem("diet", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", F, lowBound=0, cat="Integer")
m += pulp.lpSum(F[f][3]*x[f] for f in F)
for j, need in enumerate([70,187,2181]):
    m += pulp.lpSum(F[f][j]*x[f] for f in F) >= need

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


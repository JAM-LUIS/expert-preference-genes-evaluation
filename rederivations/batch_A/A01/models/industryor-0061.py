import pulp
D = {"A":(1000,20,900),"B":(920,24,1000),"C":(800,16,1200),"D":(700,28,1600)}
m = pulp.LpProblem("devices", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", D, lowBound=0, cat="Integer")
y = pulp.LpVariable.dicts("y", D, cat="Binary")
m += pulp.lpSum(D[d][0]*y[d] + D[d][1]*x[d] for d in D)
m += pulp.lpSum(x[d] for d in D) == 2000
for d in D:
    m += x[d] <= D[d][2]*y[d]

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


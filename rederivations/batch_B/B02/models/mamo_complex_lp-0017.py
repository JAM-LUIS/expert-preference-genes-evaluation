import pulp
F = {'Chicken':(10,17,159,5), 'Broccoli':(4,3,126,5), 'Beef':(13,8,230,8), 'Rice':(15,25,112,3)}
req = (66, 101, 1701)
m = pulp.LpProblem("mamo0017", pulp.LpMinimize)
x = {j: pulp.LpVariable(f"n_{j}", lowBound=0, cat="Integer") for j in F}
m += pulp.lpSum(F[j][3]*x[j] for j in F)
for k in range(3):
    m += pulp.lpSum(F[j][k]*x[j] for j in F) >= req[k]

m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        if v.varValue is not None and abs(v.varValue) > 1e-9:
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

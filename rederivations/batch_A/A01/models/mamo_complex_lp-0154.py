import pulp
openc = [151000,192000,114000,171000]
tc = [[5,5,2,3,3,3],[5,4,3,5,2,4],[2,4,5,1,4,2],[5,4,1,1,3,3]]
dem = [910,875,589,962,966,643]
cap = [1631,1954,1446,820]
I, J = range(len(openc)), range(len(dem))
m = pulp.LpProblem("facility", pulp.LpMinimize)
y = pulp.LpVariable.dicts("open", I, cat="Binary")
x = pulp.LpVariable.dicts("x", [(i,j) for i in I for j in J], lowBound=0)
m += pulp.lpSum(openc[i]*y[i] for i in I) + pulp.lpSum(tc[i][j]*x[i,j] for i in I for j in J)
for j in J:
    m += pulp.lpSum(x[i,j] for i in I) == dem[j]
for i in I:
    m += pulp.lpSum(x[i,j] for j in J) <= cap[i]*y[i]

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


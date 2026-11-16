import pulp
dem = [15,25,35,25]; cap = [30,40,45,20]; cost = [5.0,5.1,5.4,5.5]
m = pulp.LpProblem("beverage", pulp.LpMinimize)
p = [pulp.LpVariable(f"p{t+1}", lowBound=0, upBound=cap[t]) for t in range(4)]
s = [pulp.LpVariable(f"s{t+1}", lowBound=0) for t in range(4)]
m += pulp.lpSum(cost[t]*p[t] + 0.2*s[t] for t in range(4))
for t in range(4):
    m += (s[t-1] if t else 0) + p[t] - dem[t] == s[t]

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


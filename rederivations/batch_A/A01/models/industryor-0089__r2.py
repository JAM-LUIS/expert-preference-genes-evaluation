import pulp
m = pulp.LpProblem("liquids", pulp.LpMaximize)
a = pulp.LpVariable("A", lowBound=0)
b = pulp.LpVariable("B", lowBound=0)
m += 30*a + 10*b
m += 6*a + 3*b <= 40
m += b >= 3*a
m += a <= 4          # reading 2: storage limit applies to A only

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


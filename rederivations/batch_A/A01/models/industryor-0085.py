import pulp
m = pulp.LpProblem("xy", pulp.LpMaximize)
x = pulp.LpVariable("X", lowBound=10)
y = pulp.LpVariable("Y", lowBound=0)
m += 20*x + 30*y - 10*(13*x + 19*y)/60 - 2*(20*x + 29*y)/60
m += 13*x + 19*y <= 40*60
m += 20*x + 29*y <= 35*60

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


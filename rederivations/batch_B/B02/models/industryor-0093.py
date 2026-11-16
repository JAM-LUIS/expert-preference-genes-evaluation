import pulp
m = pulp.LpProblem("io0093", pulp.LpMaximize)
x1 = pulp.LpVariable("barrels_A1", lowBound=0); x2 = pulp.LpVariable("barrels_A2", lowBound=0)
m += 24*3*x1 + 16*4*x2
m += x1 + x2 <= 50
m += 12*x1 + 8*x2 <= 480
m += 3*x1 <= 100

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

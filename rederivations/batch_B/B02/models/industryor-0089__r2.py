import pulp
STORAGE_READING = 2
m = pulp.LpProblem("io0089", pulp.LpMaximize)
a = pulp.LpVariable("A_kg", lowBound=0); b = pulp.LpVariable("B_kg", lowBound=0)
m += 30*a + 10*b
m += 6*a + 3*b <= 40
m += b >= 3*a
if STORAGE_READING == 1:
    m += a <= 4
else:   # 2: storage capacity equals space of 4 kg of A; A uses 4x the space of B -> 4a + b <= 16
    m += 4*a + b <= 16

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

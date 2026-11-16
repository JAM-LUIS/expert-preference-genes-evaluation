import pulp
sal = {"A":8100,"B":20000,"C":21000,"D":3000,"E":8000}
exp = {"A":3,"B":10,"C":4,"D":3,"E":7}
m = pulp.LpProblem("hire", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", sal, cat="Binary")
m += pulp.lpSum(sal[c]*x[c] for c in sal)
m += pulp.lpSum(x.values()) <= 3
m += pulp.lpSum(x.values()) >= 2
m += pulp.lpSum(sal[c]*x[c] for c in sal) <= 35000
m += x["B"] + x["C"] >= 1
m += pulp.lpSum(exp[c]*x[c] for c in sal) >= 12
m += x["A"] + x["E"] <= 1

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


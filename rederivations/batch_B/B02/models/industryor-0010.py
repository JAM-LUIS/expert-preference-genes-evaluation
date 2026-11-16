import pulp
cov = {'A':"ACEGHI",'B':"BHI",'C':"ACGHI",'D':"DJ",'E':"AEG",'F':"FJK",'G':"ACEG",
       'H':"ABCHI",'I':"ABCHI",'J':"DFJKL",'K':"FJKL",'L':"JKL"}
m = pulp.LpProblem("io0010", pulp.LpMinimize)
x = {a: pulp.LpVariable("x_"+a, cat="Binary") for a in cov}
m += pulp.lpSum(x.values())
# area i covered by store at j if j within 800m of i
for i in cov:
    m += pulp.lpSum(x[j] for j in cov[i]) >= 1, "cover_"+i

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

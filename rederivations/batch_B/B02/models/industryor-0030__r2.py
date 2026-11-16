import pulp
# per unit (kg) of feed: protein g, minerals g, vitamins mg, price yuan/kg
F = {1:(3,1,0.5,0.2), 2:(2,0.5,1,0.7), 3:(1,0.2,0.2,0.4), 4:(6,2,2,0.3), 5:(18,0.5,0.8,0.8)}
PRICE_SCALE = 0.001  # reading 2: content per gram of feed, x in grams, price per kg -> per gram = price/1000
m = pulp.LpProblem("io0030", pulp.LpMinimize)
x = {j: pulp.LpVariable(f"x_{j}", lowBound=0) for j in F}
m += pulp.lpSum(PRICE_SCALE*F[j][3]*x[j] for j in F)
m += pulp.lpSum(F[j][0]*x[j] for j in F) >= 700
m += pulp.lpSum(F[j][1]*x[j] for j in F) >= 30
m += pulp.lpSum(F[j][2]*x[j] for j in F) >= 100

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

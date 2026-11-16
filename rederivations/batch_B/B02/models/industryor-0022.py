import pulp
P = ['A1','A2','A3']
dem = {'A1':5300,'A2':4500,'A3':5400}
price = {'A1':124,'A2':109,'A3':115}
cost = {'A1':73.30,'A2':52.90,'A3':65.40}
quota = {'A1':500,'A2':450,'A3':550}
fix = {'A1':170000,'A2':150000,'A3':100000}
minb = {'A1':20,'A2':20,'A3':16}
DAYS = 22
m = pulp.LpProblem("io0022", pulp.LpMaximize)
x = {p: pulp.LpVariable("x_"+p, lowBound=0) for p in P}   # output in 100 kg units
y = {p: pulp.LpVariable("y_"+p, cat="Binary") for p in P}
m += pulp.lpSum((price[p]-cost[p])*x[p] - fix[p]*y[p] for p in P)
m += pulp.lpSum((1.0/quota[p])*x[p] for p in P) <= DAYS, "days"
for p in P:
    m += x[p] <= dem[p]*y[p]
    m += x[p] >= minb[p]*y[p]

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

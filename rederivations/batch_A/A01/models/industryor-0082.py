import pulp
# type: (area, min, max, per-store profit by number of stores)
T = {1:(250,1,3,[9,8,7]), 2:(350,1,2,[10,9]), 3:(800,1,3,[27,21,20]), 4:(400,0,2,[16,10]), 5:(500,1,3,[17,15,12])}
m = pulp.LpProblem("mall", pulp.LpMaximize)
y = {(i,k): pulp.LpVariable(f"y_{i}_{k}", cat="Binary") for i in T for k in range(1, T[i][2]+1)}
cnt = {i: pulp.lpSum(k*y[i,k] for k in range(1, T[i][2]+1)) for i in T}
m += pulp.lpSum(0.2*k*T[i][3][k-1]*y[i,k] for (i,k) in y)
for i in T:
    m += pulp.lpSum(y[i,k] for k in range(1, T[i][2]+1)) <= 1
    m += cnt[i] >= T[i][1]
m += pulp.lpSum(T[i][0]*cnt[i] for i in T) <= 5000

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


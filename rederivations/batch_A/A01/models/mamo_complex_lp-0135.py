import pulp
C = [[0,2,8,17,16,20,15,12,9],
     [4,0,11,7,3,19,10,19,8],
     [14,7,0,7,13,19,18,20,5],
     [17,17,7,0,11,7,17,0,10],
     [20,10,2,18,0,15,8,6,18],
     [4,9,12,1,17,0,0,13,18],
     [12,15,12,19,18,19,0,6,17],
     [14,1,17,20,11,20,6,0,4],
     [19,3,19,12,8,18,17,13,0]]
N = range(9)
m = pulp.LpProblem("maxflow", pulp.LpMaximize)
f = {(i,j): pulp.LpVariable(f"f_{i}_{j}", lowBound=0, upBound=C[i][j]) for i in N for j in N if i != j and C[i][j] > 0}
m += pulp.lpSum(f[i,j] for (i,j) in f if i == 0) - pulp.lpSum(f[i,j] for (i,j) in f if j == 0)
for v in range(1,8):
    m += pulp.lpSum(f[i,j] for (i,j) in f if j == v) == pulp.lpSum(f[i,j] for (i,j) in f if i == v)

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


import pulp, itertools
c = [[0,28,89,59,41],[28,0,85,12,68],[89,85,0,22,70],[59,12,22,0,48],[41,68,70,48,0]]
n = 5
V = range(n)
m = pulp.LpProblem("tsp", pulp.LpMinimize)
x = {(i,j): pulp.LpVariable(f"x_{i}_{j}", cat="Binary") for i in V for j in V if i != j}
u = {i: pulp.LpVariable(f"u_{i}", lowBound=1, upBound=n-1) for i in V if i != 0}
m += pulp.lpSum(c[i][j]*x[i,j] for (i,j) in x)
for i in V:
    m += pulp.lpSum(x[i,j] for j in V if j != i) == 1
    m += pulp.lpSum(x[j,i] for j in V if j != i) == 1
for i in V:
    for j in V:
        if i != j and i != 0 and j != 0:
            m += u[i] - u[j] + (n-1)*x[i,j] <= n-2   # MTZ

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
print("ENUM_CHECK:", min(c[0][p[0]] + sum(c[p[k]][p[k+1]] for k in range(n-2)) + c[p[-1]][0] for p in itertools.permutations(range(1,n))))

import pulp
cap = [
 [0,2,8,17,16,20,15,12,9],
 [4,0,11,7,3,19,10,19,8],
 [14,7,0,7,13,19,18,20,5],
 [17,17,7,0,11,7,17,0,10],
 [20,10,2,18,0,15,8,6,18],
 [4,9,12,1,17,0,0,13,18],
 [12,15,12,19,18,19,0,6,17],
 [14,1,17,20,11,20,6,0,4],
 [19,3,19,12,8,18,17,13,0]]
n = 9; S, T = 0, 8
m = pulp.LpProblem("mamo0135", pulp.LpMaximize)
f = {(i,j): pulp.LpVariable(f"f_{i}_{j}", lowBound=0, upBound=cap[i][j]) for i in range(n) for j in range(n) if i != j and cap[i][j] > 0}
out = lambda k: pulp.lpSum(f[a] for a in f if a[0] == k)
inn = lambda k: pulp.lpSum(f[a] for a in f if a[1] == k)
m += out(S) - inn(S)
for k in range(n):
    if k not in (S, T):
        m += out(k) == inn(k)

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

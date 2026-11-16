import pulp
K = range(8)
Q = {"A":120,"B":90,"C":300,"D":90,"E":120}
W = {"A":0.5,"B":1.0,"C":0.4,"D":0.6,"E":0.65}
m = pulp.LpProblem("containers", pulp.LpMinimize)
n = pulp.LpVariable.dicts("n", [(g,k) for g in Q for k in K], lowBound=0, cat="Integer")
y = pulp.LpVariable.dicts("y", K, cat="Binary")
a = pulp.LpVariable.dicts("a", K, cat="Binary")
m += pulp.lpSum(y[k] for k in K)
for g in Q:
    m += pulp.lpSum(n[g,k] for k in K) == Q[g]
for k in K:
    wt = pulp.lpSum(W[g]*n[g,k] for g in Q)
    m += wt <= 60*y[k]
    m += wt >= 18*y[k]
    m += n["D",k] >= 12*y[k]
    m += n["A",k] <= Q["A"]*a[k]
    m += n["C",k] >= a[k]
    if k > 0:
        m += y[k] <= y[k-1]

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


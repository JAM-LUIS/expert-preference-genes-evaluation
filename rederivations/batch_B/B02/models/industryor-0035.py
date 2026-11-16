import pulp, itertools
p = [[3,1,1],[2,1.5,1],[3,1.2,1.3],[2,2,2],[2.1,2,3]]
J = range(5); K = range(3)
M = sum(map(sum, p))
m = pulp.LpProblem("io0035", pulp.LpMinimize)
s = {(i,k): pulp.LpVariable(f"s_{i}_{k}", lowBound=0) for i in J for k in K}
z = {(i,j,k): pulp.LpVariable(f"z_{i}_{j}_{k}", cat="Binary") for i in J for j in J if i<j for k in K}
C = pulp.LpVariable("Cmax", lowBound=0)
m += C
for i in J:
    for k in range(1,3):
        m += s[i,k] >= s[i,k-1] + p[i][k-1]       # vat order 1->2->3
    m += C >= s[i,2] + p[i][2]
for (i,j,k), v in z.items():                      # one batch at a time per vat
    m += s[i,k] + p[i][k] <= s[j,k] + M*(1-v)
    m += s[j,k] + p[j][k] <= s[i,k] + M*v

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
# cross-check: enumerate all permutation schedules (for 3-machine flow shop a permutation schedule is optimal)
best = None
for perm in itertools.permutations(J):
    c = [0,0,0]
    for i in perm:
        c[0] += p[i][0]; c[1] = max(c[1], c[0]) + p[i][1]; c[2] = max(c[2], c[1]) + p[i][2]
    if best is None or c[2] < best[0] - 1e-9: best = (c[2], perm)
print("ENUM_PERMUTATION_BEST:", best)

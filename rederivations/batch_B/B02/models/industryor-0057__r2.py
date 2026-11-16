import pulp, itertools
w = [0.5, 0.7, 0.9]; L = [1000, 3000, 2000]
rolls = [1.0, 2.0]
WASTE_COUNTS_OVERPRODUCTION = False  # reading 2: waste = trim loss only, demand >= (surplus length not counted)
pats = []
for R in rolls:
    for a in itertools.product(*(range(int(R//wi)+1) for wi in w)):
        used = sum(ai*wi for ai, wi in zip(a, w))
        if sum(a) > 0 and used <= R + 1e-9:
            pats.append((R, a, round(R-used, 10)))
m = pulp.LpProblem("io0057", pulp.LpMinimize)
y = [pulp.LpVariable(f"len_{k}", lowBound=0) for k in range(len(pats))]   # metres of roll cut with pattern k
for i in range(3):
    m += pulp.lpSum(pats[k][1][i]*y[k] for k in range(len(pats))) >= L[i], f"order_{i}"
if WASTE_COUNTS_OVERPRODUCTION:
    m += pulp.lpSum(pats[k][0]*y[k] for k in range(len(pats))) - sum(wi*Li for wi, Li in zip(w, L))
else:
    m += pulp.lpSum(pats[k][2]*y[k] for k in range(len(pats)))
for k, pt in enumerate(pats):
    print("PATTERN", k, pt)

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

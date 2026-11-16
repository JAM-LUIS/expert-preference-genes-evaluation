import pulp
T = [7,8,9,10,11,12]
dem = {('I',t): (30000 if t <= 9 else 100000) for t in T}
dem.update({('II',t): (15000 if t <= 9 else 50000) for t in T})
cost = {'I':4.5, 'II':7.0}          # June-December unit costs
vol = {'I':0.2, 'II':0.4}
P = ['I','II']
m = pulp.LpProblem("io0067", pulp.LpMinimize)
x = {(p,t): pulp.LpVariable(f"x_{p}_{t}", lowBound=0, cat="Integer") for p in P for t in T}
s = {(p,t): pulp.LpVariable(f"s_{p}_{t}", lowBound=0, cat="Integer") for p in P for t in T}  # end-of-month inventory
own = {t: pulp.LpVariable(f"own_{t}", lowBound=0, upBound=15000) for t in T}
ext = {t: pulp.LpVariable(f"ext_{t}", lowBound=0) for t in T}
m += pulp.lpSum(cost[p]*x[p,t] for p in P for t in T) + pulp.lpSum(1.0*own[t] + 1.5*ext[t] for t in T)
for t in T:
    m += x['I',t] + x['II',t] <= 120000
    for p in P:
        prev = s[p,t-1] if t > 7 else 0
        m += prev + x[p,t] - dem[p,t] == s[p,t]
    m += vol['I']*s['I',t] + vol['II']*s['II',t] == own[t] + ext[t]

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

to_relax = [v for v in m.variables()
            if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
for v in to_relax:
    v.cat = pulp.LpContinuous
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
      f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
for v in to_relax:
    v.cat = pulp.LpInteger

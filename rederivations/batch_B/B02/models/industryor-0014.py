import pulp
m = pulp.LpProblem("io0014", pulp.LpMaximize)
prot = {'chicken':(23,3.0),'salmon':(20,5.0),'tofu':(8,1.5)}  # per 100g
veg = {'broccoli':(2.8,1.2),'carrots':(0.9,0.8),'spinach':(2.9,1.5),'pepper':(1.0,1.0),'mushrooms':(3.1,2.0)}
p = {k: pulp.LpVariable("p_"+k, lowBound=0) for k in prot}           # units of 100g, continuous
n = {k: pulp.LpVariable("n_"+k, lowBound=0, cat="Integer") for k in veg}  # packs
y = {k: pulp.LpVariable("y_"+k, cat="Binary") for k in veg}
m += pulp.lpSum(prot[k][0]*p[k] for k in prot) + pulp.lpSum(veg[k][0]*n[k] for k in veg)
m += pulp.lpSum(prot[k][1]*p[k] for k in prot) + pulp.lpSum(veg[k][1]*n[k] for k in veg) <= 20
m += pulp.lpSum(p.values()) + pulp.lpSum(n.values()) <= 8   # 800 g
for k in veg:
    m += n[k] >= y[k]
    m += n[k] <= 8*y[k]
m += pulp.lpSum(y.values()) >= 3

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

#!/usr/bin/env python3
import pulp

def report(m, relax=False):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]
    sol_status = pulp.LpSolution[m.sol_status]
    print("STATUS:", status)
    print("SOLUTION_STATUS:", sol_status)
    if status == "Optimal" and sol_status == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue:
                print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
    if relax:
        to_relax = [v for v in m.variables()
                    if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
        for v in to_relax:
            v.cat = pulp.LpContinuous
        m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
        print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
              f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
        for v in to_relax:
            v.cat = pulp.LpInteger

# proteins: continuous, in units of 100 g; vegetables: integer packs of 100 g, >=3 distinct types
prot = {"chicken": (23, 3.00), "salmon": (20, 5.00), "tofu": (8, 1.50)}
veg = {"broccoli": (2.8, 1.20), "carrots": (0.9, 0.80), "spinach": (2.9, 1.50),
       "bell_pepper": (1.0, 1.00), "mushrooms": (3.1, 2.00)}
m = pulp.LpProblem("p", pulp.LpMaximize)
x = pulp.LpVariable.dicts("p100g", prot, lowBound=0)
n = pulp.LpVariable.dicts("packs", veg, lowBound=0, upBound=8, cat="Integer")
y = pulp.LpVariable.dicts("use", veg, cat="Binary")
m += pulp.lpSum(prot[k][0] * x[k] for k in prot) + pulp.lpSum(veg[k][0] * n[k] for k in veg)
m += pulp.lpSum(prot[k][1] * x[k] for k in prot) + pulp.lpSum(veg[k][1] * n[k] for k in veg) <= 20
m += 100 * pulp.lpSum(x.values()) + 100 * pulp.lpSum(n.values()) <= 800
for k in veg:
    m += n[k] >= y[k]
    m += n[k] <= 8 * y[k]   # 8 packs = 800 g weight limit
m += pulp.lpSum(y.values()) >= 3
report(m, relax=True)

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

raws = ["A", "B", "C"]; brands = ["A", "B", "C"]
rcost = {"A": 2.00, "B": 1.50, "C": 1.00}; limit = {"A": 2000, "B": 2500, "C": 1200}
fee = {"A": 0.50, "B": 0.40, "C": 0.30}; price = {"A": 3.40, "B": 2.85, "C": 2.25}
m = pulp.LpProblem("p", pulp.LpMaximize)
x = {(r, c): pulp.LpVariable(f"raw{r}_in_candy{c}", lowBound=0) for r in raws for c in brands}
tot = {c: pulp.lpSum(x[r, c] for r in raws) for c in brands}
m += pulp.lpSum((price[c] - fee[c]) * tot[c] for c in brands) - pulp.lpSum(rcost[r] * x[r, c] for r in raws for c in brands)
for r in raws:
    m += pulp.lpSum(x[r, c] for c in brands) <= limit[r]
m += x["A", "A"] >= 0.60 * tot["A"]
m += x["A", "B"] >= 0.15 * tot["B"]
m += x["C", "A"] <= 0.20 * tot["A"]
m += x["C", "B"] <= 0.60 * tot["B"]
m += x["C", "C"] <= 0.50 * tot["C"]
report(m)
for c in brands:
    print("  candy", c, "kg =", pulp.value(tot[c]))

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
            if v.varValue and abs(v.varValue) > 1e-9:
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

# Each lot goes to son 1 (y=1) or son 2 (y=0); dogs are one lot. Minimize |V1 - V2| via epigraph variable.
lots = {"painting": 25000, "bust": 5000, "vase": 20000, "porsche": 40000,
        "diamond1": 12000, "diamond2": 12000, "diamond3": 12000, "sofa": 3000,
        "dogs_pair": 2 * 3000, "sculpture": 10000, "boat": 15000, "harley": 10000, "furniture": 13000}
total = sum(lots.values())
m = pulp.LpProblem("p0033", pulp.LpMinimize)
y = {k: pulp.LpVariable(f"y_{k}", cat="Binary") for k in lots}
d = pulp.LpVariable("diff", lowBound=0)
v1 = pulp.lpSum(lots[k] * y[k] for k in lots)
m += d
m += d >= v1 - (total - v1)
m += d >= (total - v1) - v1
print("total", total)
report(m)

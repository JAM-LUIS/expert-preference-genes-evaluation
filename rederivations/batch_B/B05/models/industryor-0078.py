#!/usr/bin/env python3
import pulp

def report(m, relax=True):
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

# Lexicographic goal programming. x1 = total full-time hours, x2 = total part-time hours.
# P1: sales >= 5500 (min d1-). P2: full employment (min d2- + d3-). P3: min overtime hours (d2+ + d3+).
def build():
    m = pulp.LpProblem("ind0078", pulp.LpMinimize)
    v = {n: pulp.LpVariable(n, lowBound=0) for n in ["x1", "x2", "d1m", "d1p", "d2m", "d2p", "d3m", "d3p"]}
    m += 5 * v["x1"] + 2 * v["x2"] + v["d1m"] - v["d1p"] == 5500
    m += v["x1"] + v["d2m"] - v["d2p"] == 5 * 160
    m += v["x2"] + v["d3m"] - v["d3p"] == 4 * 80
    return m, v
m, v = build()
m += v["d1m"]
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600)); g1 = pulp.value(m.objective)
m += v["d1m"] <= g1 + 1e-9
m.setObjective(v["d2m"] + v["d3m"])
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600)); g2 = pulp.value(m.objective)
m += v["d2m"] + v["d3m"] <= g2 + 1e-9
m.setObjective(v["d2p"] + v["d3p"])
print("P1 level (d1-):", g1, " P2 level (d2- + d3-):", g2)
report(m, relax=False)

#!/usr/bin/env python3
# industryor-0078: x1 = total monthly hours of the 5 full-time clerks, x2 = total hours of the 4 part-time clerks.
# MODE "goal": lexicographic P1 (sales shortfall) > P2 (under-employment) > P3 (overtime hours); objective = sum of level optima.
# MODE "profit": goals P1, P2 hard; maximise profit = 0.3*sales - wages.
import pulp

def report(m, extra=None):
    status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
    print("STATUS:", status); print("SOLUTION_STATUS:", sol)
    if status == "Optimal" and sol == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective) if extra is None else extra)
        for v in m.variables():
            if v.varValue and abs(v.varValue) > 1e-9: print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
SOLVER = lambda: pulp.PULP_CBC_CMD(msg=False, timeLimit=600)
def relax_and_report(m):
    to_relax = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
    for v in to_relax: v.cat = pulp.LpContinuous
    m.solve(SOLVER())
    print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
    for v in to_relax: v.cat = pulp.LpInteger

MODE = "profit"
m = pulp.LpProblem("p", pulp.LpMinimize if MODE == "goal" else pulp.LpMaximize)
x1 = pulp.LpVariable("x1", 0); x2 = pulp.LpVariable("x2", 0)
d = {n: pulp.LpVariable(n, lowBound=0) for n in ["d1m", "d1p", "d2m", "d2p", "d3m", "d3p"]}
m += 5 * x1 + 2 * x2 + d["d1m"] - d["d1p"] == 5500
m += x1 + d["d2m"] - d["d2p"] == 5 * 160
m += x2 + d["d3m"] - d["d3p"] == 4 * 80
levels = [d["d1m"], d["d2m"] + d["d3m"], d["d2p"] + d["d3p"]]
profit = 0.3 * (5 * x1 + 2 * x2) - (1 * (x1 - d["d2p"]) + 1.5 * d["d2p"]) - (0.6 * (x2 - d["d3p"]) + 0.7 * d["d3p"])
if MODE == "goal":
    vals = []
    for k, e in enumerate(levels):
        m.setObjective(e); m.solve(SOLVER())
        if pulp.LpStatus[m.status] != "Optimal": break
        v = pulp.value(e); vals.append(v); print(f"LEVEL P{k+1} optimum: {v}")
        m += e <= v + 1e-7
    report(m, extra=sum(vals))
    print("PROFIT_AT_SOLUTION:", pulp.value(profit))
else:
    m += d["d1m"] == 0; m += d["d2m"] == 0; m += d["d3m"] == 0
    m.setObjective(profit); m.solve(SOLVER()); report(m)

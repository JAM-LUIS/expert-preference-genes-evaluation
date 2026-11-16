#!/usr/bin/env python3
# industryor-0048: lexicographic goal programme. xA,xB units made within regular Process-II time,
# oA,oB units made using Process-II overtime (integer units). Deviation variables continuous.
# MODE "goal": sequentially minimise P1..P4 deviations; reported objective = sum of the level optima.
# MODE "profit": treat all goals as hard constraints and maximise profit.
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

MODE = "goal"
m = pulp.LpProblem("p", pulp.LpMinimize if MODE == "goal" else pulp.LpMaximize)
xA = pulp.LpVariable("xA", 0, cat="Integer"); xB = pulp.LpVariable("xB", 0, cat="Integer")
oA = pulp.LpVariable("oA", 0, cat="Integer"); oB = pulp.LpVariable("oB", 0, cat="Integer")
dv = {n: pulp.LpVariable(n, lowBound=0) for n in ["d1m", "d1p", "d2m", "d3m", "d4m", "d4p", "d5m"]}
profit = 300 * xA + 450 * xB + 280 * oA + 425 * oB
m += profit + dv["d1m"] - dv["d1p"] == 10000                      # p1
m += xA + oA + dv["d2m"] >= 10                                    # p2
m += xB + oB + dv["d3m"] >= 15
m += 4 * (xA + oA) + 6 * (xB + oB) + dv["d4m"] - dv["d4p"] == 150 # p3 process I exactly 150
m += 3 * xA + 2 * xB + dv["d5m"] == 70                            # p3 process II regular time fully used
m += 3 * oA + 2 * oB <= 30                                        # p4 overtime limit
levels = [dv["d1m"], dv["d2m"] + dv["d3m"], dv["d4m"] + dv["d4p"] + dv["d5m"], 20 * oA + 25 * oB]
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
    for e in levels[:3]: m += e == 0
    m.setObjective(profit); m.solve(SOLVER()); report(m)

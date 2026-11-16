#!/usr/bin/env python3
# industryor-0100: widest simple path A -> E through C. TRANSPOSE=True (False: table row = from, column = to)
import pulp

def report(m, relax=False):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
    print("STATUS:", status); print("SOLUTION_STATUS:", sol)
    if status == "Optimal" and sol == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue and abs(v.varValue) > 1e-9: print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
    if relax:
        tr = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
        for v in tr: v.cat = pulp.LpContinuous
        m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
        print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), f"({len(tr)} general-integer variables made continuous; binaries kept)")
        for v in tr: v.cat = pulp.LpInteger

TRANSPOSE = True
V = ["A", "B", "C", "D", "E"]
tab = {"A": [0, 90, 85, 0, 65], "B": [95, 0, 70, 65, 34], "C": [60, 0, 0, 88, 80], "D": [67, 30, 25, 0, 84], "E": [0, 51, 0, 56, 0]}
bw = {}
for i in V:
    for k, j in enumerate(V):
        if tab[i][k] > 0:
            bw[(j, i) if TRANSPOSE else (i, j)] = tab[i][k]
arcs = list(bw); BIG = max(bw.values())
m = pulp.LpProblem("io0100", pulp.LpMaximize)
x = {a: pulp.LpVariable(f"x_{a[0]}_{a[1]}", cat="Binary") for a in arcs}
u = pulp.LpVariable.dicts("pos", V, 0, len(V) - 1)
z = pulp.LpVariable("bandwidth", 0, BIG)
m += z
def out(v): return pulp.lpSum(x[a] for a in arcs if a[0] == v)
def inn(v): return pulp.lpSum(x[a] for a in arcs if a[1] == v)
m += out("A") == 1; m += inn("A") == 0
m += inn("E") == 1; m += out("E") == 0
for v in ["B", "C", "D"]:
    m += out(v) == inn(v); m += inn(v) <= 1
m += inn("C") == 1
for a in arcs:
    m += u[a[1]] >= u[a[0]] + 1 - len(V) * (1 - x[a])   # no loops
    m += z <= bw[a] + BIG * (1 - x[a])
report(m)

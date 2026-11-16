#!/usr/bin/env python3
# VRP with hard time windows, 20 customers, <=5 trucks of capacity 200, minimise total Euclidean distance.
# Assumption (not stated in the text): travel time in minutes equals Euclidean distance (unit speed).
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report
depot = (40, 50); H = 1236; Q = 200; KMAX = 5
cust = {  # id: (x, y, demand, e, l, service)
    1: (45, 68, 10, 912, 967, 90), 2: (45, 70, 30, 825, 870, 90), 3: (42, 66, 10, 65, 146, 90),
    4: (42, 68, 10, 727, 782, 90), 5: (42, 65, 10, 15, 67, 90), 6: (40, 69, 20, 621, 702, 90),
    7: (40, 66, 20, 170, 225, 90), 8: (38, 68, 20, 255, 324, 90), 9: (38, 70, 10, 534, 605, 90),
    10: (35, 66, 10, 357, 410, 90), 11: (35, 69, 10, 448, 505, 90), 12: (25, 85, 20, 652, 721, 90),
    13: (22, 75, 30, 30, 92, 90), 14: (22, 85, 10, 567, 620, 90), 15: (20, 80, 40, 384, 429, 90),
    16: (20, 85, 40, 475, 528, 90), 17: (18, 75, 20, 99, 148, 90), 18: (15, 75, 20, 179, 254, 90),
    19: (15, 80, 10, 278, 345, 90), 20: (30, 50, 10, 10, 73, 90),
}
N = sorted(cust)
xy = {0: depot}; xy.update({i: cust[i][:2] for i in N})
q = {i: cust[i][2] for i in N}; e = {i: cust[i][3] for i in N}; l = {i: cust[i][4] for i in N}
sv = {i: cust[i][5] for i in N}
def d(i, j):
    return math.hypot(xy[i][0] - xy[j][0], xy[i][1] - xy[j][1])
for i in N:
    assert d(0, i) <= l[i] and e[i] + sv[i] + d(i, 0) <= H
arcs = [(0, j) for j in N] + [(i, 0) for i in N]
arcs += [(i, j) for i in N for j in N if i != j and e[i] + sv[i] + d(i, j) <= l[j] and q[i] + q[j] <= Q]
m = pulp.LpProblem("ior0036", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", arcs, cat="Binary")
t = {i: pulp.LpVariable(f"t_{i}", lowBound=max(e[i], d(0, i)), upBound=min(l[i], H - sv[i] - d(i, 0))) for i in N}
u = {i: pulp.LpVariable(f"u_{i}", lowBound=q[i], upBound=Q) for i in N}
m += pulp.lpSum(d(i, j) * x[(i, j)] for (i, j) in arcs)
for j in N:
    m += pulp.lpSum(x[(i, k)] for (i, k) in arcs if k == j) == 1
    m += pulp.lpSum(x[(k, i)] for (k, i) in arcs if k == j) == 1
m += pulp.lpSum(x[(0, j)] for j in N) <= KMAX
for (i, j) in arcs:
    if i != 0 and j != 0:
        M = l[i] + sv[i] + d(i, j) - e[j]
        m += t[j] >= t[i] + sv[i] + d(i, j) - M * (1 - x[(i, j)])
        m += u[j] >= u[i] + q[j] - Q * (1 - x[(i, j)])
report(m, show=False)
if pulp.LpStatus[m.status] == "Optimal":
    succ = {i: j for (i, j) in arcs if i != 0 and x[(i, j)].varValue > 0.5}
    for j in N:
        if x[(0, j)].varValue > 0.5:
            r = [0, j]
            while r[-1] != 0:
                r.append(succ[r[-1]])
            print("  route:", r, "load", sum(q[i] for i in r if i), "start times", [round(t[i].varValue, 2) for i in r if i])

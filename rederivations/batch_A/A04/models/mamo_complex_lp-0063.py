#!/usr/bin/env python3
# 4-city TSP (MTZ formulation).
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report
c = {(1, 2): 52, (1, 3): 89, (1, 4): 11,
     (2, 1): 52, (2, 3): 14, (2, 4): 13,
     (3, 1): 89, (3, 2): 14, (3, 4): 87,
     (4, 1): 11, (4, 2): 13, (4, 3): 87}
V = [1, 2, 3, 4]
m = pulp.LpProblem("mamo0063", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", list(c), cat="Binary")
u = pulp.LpVariable.dicts("u", V[1:], lowBound=1, upBound=3)
m += pulp.lpSum(c[a] * x[a] for a in c)
for i in V:
    m += pulp.lpSum(x[(i, j)] for j in V if j != i) == 1
    m += pulp.lpSum(x[(j, i)] for j in V if j != i) == 1
for i in V[1:]:
    for j in V[1:]:
        if i != j:
            m += u[i] - u[j] + 3 * x[(i, j)] <= 2
report(m)

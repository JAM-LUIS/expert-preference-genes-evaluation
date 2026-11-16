#!/usr/bin/env python3
# Max flow from node 0 to node 8.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report
cap = [
    [0, 9, 7, 18, 0, 0, 7, 0, 2],
    [15, 0, 11, 5, 20, 15, 18, 9, 15],
    [3, 8, 0, 10, 16, 18, 8, 0, 20],
    [13, 3, 7, 0, 20, 13, 16, 6, 20],
    [7, 20, 2, 4, 0, 9, 3, 14, 2],
    [17, 10, 5, 1, 4, 0, 4, 3, 20],
    [0, 20, 10, 10, 15, 5, 0, 1, 10],
    [10, 3, 9, 4, 3, 13, 18, 0, 20],
    [2, 12, 10, 5, 15, 14, 0, 10, 0],
]
n = 9; s, t = 0, 8
arcs = [(i, j) for i in range(n) for j in range(n) if i != j and cap[i][j] > 0]
m = pulp.LpProblem("mamo0138", pulp.LpMaximize)
f = {a: pulp.LpVariable(f"f_{a[0]}_{a[1]}", lowBound=0, upBound=cap[a[0]][a[1]]) for a in arcs}
m += pulp.lpSum(f[a] for a in arcs if a[0] == s) - pulp.lpSum(f[a] for a in arcs if a[1] == s)
for v in range(n):
    if v not in (s, t):
        m += pulp.lpSum(f[a] for a in arcs if a[1] == v) == pulp.lpSum(f[a] for a in arcs if a[0] == v)
report(m)

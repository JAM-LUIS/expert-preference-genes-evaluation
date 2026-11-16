#!/usr/bin/env python3
# Containers with fixed setup cost and upward substitution.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report
K = [1, 2, 3, 4, 5, 6]
vol = {1: 1500, 2: 2500, 3: 4000, 4: 6000, 5: 9000, 6: 12000}
dem = {1: 500, 2: 550, 3: 700, 4: 900, 5: 400, 6: 300}
cost = {1: 5, 2: 8, 3: 10, 4: 12, 5: 16, 6: 18}
FIX = 1200
total = sum(dem.values())
m = pulp.LpProblem("ior0012", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", K, lowBound=0, cat="Integer")
y = pulp.LpVariable.dicts("y", K, cat="Binary")
# s[i,j]: units of type i used for demand of type j (vol_i >= vol_j)
pairs = [(i, j) for i in K for j in K if vol[i] >= vol[j]]
s = pulp.LpVariable.dicts("s", pairs, lowBound=0, cat="Integer")
m += pulp.lpSum(cost[k] * x[k] + FIX * y[k] for k in K)
for j in K:
    m += pulp.lpSum(s[(i, j)] for i in K if (i, j) in s) == dem[j]
for i in K:
    m += pulp.lpSum(s[(i, j)] for j in K if (i, j) in s) <= x[i]
    m += x[i] <= total * y[i]
report(m)

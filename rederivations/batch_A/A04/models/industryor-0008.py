#!/usr/bin/env python3
# Assign 4 of 5 workers to 4 tasks (one each), minimise total hours.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report
workers = ["I", "II", "III", "IV", "V"]
tasks = ["A", "B", "C", "D"]
h = {"I": [9, 4, 3, 7], "II": [4, 6, 5, 6], "III": [5, 4, 7, 5], "IV": [7, 5, 2, 3], "V": [10, 6, 7, 4]}
m = pulp.LpProblem("ior0008", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", [(w, t) for w in workers for t in tasks], cat="Binary")
m += pulp.lpSum(h[w][j] * x[(w, t)] for w in workers for j, t in enumerate(tasks))
for t in tasks:
    m += pulp.lpSum(x[(w, t)] for w in workers) == 1
for w in workers:
    m += pulp.lpSum(x[(w, t)] for t in tasks) <= 1
report(m)

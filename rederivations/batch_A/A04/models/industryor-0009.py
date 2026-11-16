#!/usr/bin/env python3
# Toy production with logical conditions.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report
toys = ["truck", "airplane", "boat", "train"]
profit = {"truck": 5, "airplane": 10, "boat": 8, "train": 7}
wood = {"truck": 12, "airplane": 20, "boat": 15, "train": 10}
steel = {"truck": 6, "airplane": 3, "boat": 5, "train": 4}
WOOD, STEEL = 890, 500
M = {t: min(WOOD // wood[t], STEEL // steel[t]) for t in toys}
m = pulp.LpProblem("ior0009", pulp.LpMaximize)
x = pulp.LpVariable.dicts("x", toys, lowBound=0, cat="Integer")
y = pulp.LpVariable.dicts("y", toys, cat="Binary")
m += pulp.lpSum(profit[t] * x[t] for t in toys)
m += pulp.lpSum(wood[t] * x[t] for t in toys) <= WOOD
m += pulp.lpSum(steel[t] * x[t] for t in toys) <= STEEL
for t in toys:
    m += x[t] <= M[t] * y[t]
    m += x[t] >= y[t]
m += y["truck"] + y["train"] <= 1
m += y["boat"] <= y["airplane"]
m += x["boat"] <= x["train"]
report(m)
print("TYPES_MADE:", sum(1 for t in toys if x[t].varValue > 0.5))

#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report
foods = {  # protein, carbs, calories, cost
    "Chicken": (5, 13, 121, 7), "Pasta": (3, 23, 274, 10), "Rice": (11, 27, 251, 7),
    "Beans": (10, 27, 259, 9), "Cheese": (4, 18, 199, 7),
}
need = (60, 146, 1727)
m = pulp.LpProblem("mamo0012", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", list(foods), lowBound=0, cat="Integer")
m += pulp.lpSum(foods[f][3] * x[f] for f in foods)
for k in range(3):
    m += pulp.lpSum(foods[f][k] * x[f] for f in foods) >= need[k]
report(m, relax=True)

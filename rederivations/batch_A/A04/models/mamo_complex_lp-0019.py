#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report
foods = {  # protein, carbs, calories, cost
    "Steak": (1, 3, 210, 6), "Apples": (7, 22, 96, 1), "Eggs": (6, 18, 189, 1),
    "Chicken": (20, 6, 132, 3), "Tofu": (8, 4, 75, 1),
}
need = (87, 135, 1926)
m = pulp.LpProblem("mamo0019", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", list(foods), lowBound=0, cat="Integer")
m += pulp.lpSum(foods[f][3] * x[f] for f in foods)
for k in range(3):
    m += pulp.lpSum(foods[f][k] * x[f] for f in foods) >= need[k]
report(m, relax=True)

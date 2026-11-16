#!/usr/bin/env python3
# Three products, stage A (A1,A2) and stage B (B1,B2,B3).
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report
time = {  # hours per piece
    ("A1", "I"): 5, ("A1", "II"): 10,
    ("A2", "I"): 7, ("A2", "II"): 9, ("A2", "III"): 12,
    ("B1", "I"): 6, ("B1", "II"): 8,
    ("B2", "I"): 4, ("B2", "III"): 11,
    ("B3", "I"): 7,
}
hours = {"A1": 6000, "A2": 10000, "B1": 4000, "B2": 7000, "B3": 4000}
rate = {"A1": 0.05, "A2": 0.03, "B1": 0.06, "B2": 0.11, "B3": 0.05}
raw = {"I": 0.25, "II": 0.35, "III": 0.5}
price = {"I": 1.25, "II": 2, "III": 2.8}
prods = ["I", "II", "III"]
Aeq, Beq = ["A1", "A2"], ["B1", "B2", "B3"]
m = pulp.LpProblem("ior0031", pulp.LpMaximize)
x = pulp.LpVariable.dicts("x", list(time.keys()), lowBound=0, cat="Integer")
q = pulp.LpVariable.dicts("q", prods, lowBound=0, cat="Integer")
for p in prods:
    m += pulp.lpSum(x[(e, p)] for e in Aeq if (e, p) in time) == q[p]
    m += pulp.lpSum(x[(e, p)] for e in Beq if (e, p) in time) == q[p]
for e in hours:
    m += pulp.lpSum(time[(e, p)] * x[(e, p)] for p in prods if (e, p) in time) <= hours[e]
m += (pulp.lpSum((price[p] - raw[p]) * q[p] for p in prods)
      - pulp.lpSum(rate[e] * time[(e, p)] * x[(e, p)] for (e, p) in time)), "profit"
report(m, relax=True)

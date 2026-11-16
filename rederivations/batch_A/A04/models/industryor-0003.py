#!/usr/bin/env python3
# Aggregate planning, Jan-Jun: in-house production, outsourcing, hiring/firing, overtime, inventory/backorder.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report

T = range(1, 7)
D = {1: 20000, 2: 40000, 3: 42000, 4: 35000, 5: 19000, 6: 18500}
W0, I0, B0 = 1000, 15000, 0
price, mat, outc, hold, back = 300, 90, 200, 15, 35
hrs_unit, reg_hrs, reg_wage, ot_cap, ot_wage = 5, 160, 30, 20, 40
hire_c, fire_c = 5000, 8000

m = pulp.LpProblem("ior0003", pulp.LpMaximize)
W = pulp.LpVariable.dicts("W", T, lowBound=0, cat="Integer")
H = pulp.LpVariable.dicts("H", T, lowBound=0, cat="Integer")
F = pulp.LpVariable.dicts("F", T, lowBound=0, cat="Integer")
P = pulp.LpVariable.dicts("P", T, lowBound=0, cat="Integer")
C = pulp.LpVariable.dicts("C", T, lowBound=0, cat="Integer")
O = pulp.LpVariable.dicts("O", T, lowBound=0)
I = pulp.LpVariable.dicts("I", T, lowBound=0)
B = pulp.LpVariable.dicts("B", T, lowBound=0)

def prev(X, t, x0):
    return x0 if t == 1 else X[t - 1]

sales = {t: D[t] + prev(B, t, B0) - B[t] for t in T}
m += pulp.lpSum(price * sales[t] - mat * P[t] - outc * C[t] - hold * I[t] - back * B[t]
                - reg_wage * reg_hrs * W[t] - ot_wage * O[t] - hire_c * H[t] - fire_c * F[t] for t in T)
for t in T:
    m += W[t] == prev(W, t, W0) + H[t] - F[t]
    m += hrs_unit * P[t] <= reg_hrs * W[t] + O[t]
    m += O[t] <= ot_cap * W[t]
    m += prev(I, t, I0) - prev(B, t, B0) + P[t] + C[t] - D[t] == I[t] - B[t]
m += I[6] >= 10000
m += B[6] == 0
report(m, relax=True)

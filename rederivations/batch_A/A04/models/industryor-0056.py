#!/usr/bin/env python3
# Grain trading, 3 months. Main reading: within a month sales happen first (from opening stock),
# sales revenue of the month can fund that month's purchases, warehouse limit applies to stock after sale+purchase.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report
T = [1, 2, 3]
buy_p = {1: 2.85, 2: 3.05, 3: 2.90}
sell_p = {1: 3.10, 2: 3.25, 3: 2.95}
CAP, S0, CASH0, END = 5000, 1000, 20000, 2000
m = pulp.LpProblem("ior0056", pulp.LpMaximize)
b = pulp.LpVariable.dicts("buy", T, lowBound=0)
s = pulp.LpVariable.dicts("sell", T, lowBound=0)
m += pulp.lpSum(sell_p[t] * s[t] - buy_p[t] * b[t] for t in T)
stock_open, cash_open = S0, CASH0
for t in T:
    m += s[t] <= stock_open
    m += buy_p[t] * b[t] <= cash_open + sell_p[t] * s[t]
    m += stock_open - s[t] + b[t] <= CAP
    stock_open = stock_open - s[t] + b[t]
    cash_open = cash_open + sell_p[t] * s[t] - buy_p[t] * b[t]
m += stock_open == END
report(m)

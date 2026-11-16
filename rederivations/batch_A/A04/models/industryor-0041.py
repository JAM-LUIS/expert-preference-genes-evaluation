#!/usr/bin/env python3
# Three-year investment plan; idle cash carried over at no interest.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report
m = pulp.LpProblem("ior0041", pulp.LpMaximize)
a1 = pulp.LpVariable("p1_year1", lowBound=0)
a2 = pulp.LpVariable("p1_year2", lowBound=0)
a3 = pulp.LpVariable("p1_year3", lowBound=0)
b = pulp.LpVariable("p2_year1", lowBound=0, upBound=120000)
c = pulp.LpVariable("p3_year2", lowBound=0, upBound=150000)
g = pulp.LpVariable("p4_year3", lowBound=0, upBound=100000)
s1 = pulp.LpVariable("idle1", lowBound=0)
s2 = pulp.LpVariable("idle2", lowBound=0)
s3 = pulp.LpVariable("idle3", lowBound=0)
m += 1.20 * a3 + 1.40 * g + s3
m += a1 + b + s1 == 500000
m += a2 + c + s2 == 1.20 * a1 + s1
m += a3 + g + s3 == 1.20 * a2 + 1.50 * b + 1.60 * c + s2
report(m)

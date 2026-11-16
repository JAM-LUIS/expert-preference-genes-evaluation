#!/usr/bin/env python3
# Truck rental: A = 20 refrigerated + 40 non-refrigerated; B = same total (60) split equally = 30 + 30.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report
m = pulp.LpProblem("ior0087", pulp.LpMinimize)
a = pulp.LpVariable("A", lowBound=0, cat="Integer")
b = pulp.LpVariable("B", lowBound=0, cat="Integer")
m += 30 * a + 40 * b
m += 20 * a + 30 * b >= 3000
m += 40 * a + 30 * b >= 4000
report(m, relax=True)

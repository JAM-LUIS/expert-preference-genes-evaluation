import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report
m = pulp.LpProblem("io0041", pulp.LpMaximize)
a1 = pulp.LpVariable("oneyear_y1", lowBound=0); a2 = pulp.LpVariable("oneyear_y2", lowBound=0); a3 = pulp.LpVariable("oneyear_y3", lowBound=0)
b = pulp.LpVariable("twoyear_y1", lowBound=0, upBound=120000)
c = pulp.LpVariable("p3_y2", lowBound=0, upBound=150000)
d = pulp.LpVariable("p4_y3", lowBound=0, upBound=100000)
h1 = pulp.LpVariable("cash_y1", lowBound=0); h2 = pulp.LpVariable("cash_y2", lowBound=0); h3 = pulp.LpVariable("cash_y3", lowBound=0)
m += 1.2*a3 + 1.4*d + h3
m += a1 + b + h1 == 500000
m += a2 + c + h2 == 1.2*a1 + h1
m += a3 + d + h3 == 1.2*a2 + 1.6*c + 1.5*b + h2
solve_report(m)

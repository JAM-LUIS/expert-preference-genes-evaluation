import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report
m = pulp.LpProblem("io0063", pulp.LpMinimize)
h = pulp.LpVariable("horse", lowBound=0, cat="Integer")
b = pulp.LpVariable("bicycle", lowBound=0, cat="Integer")
c = pulp.LpVariable("handcart", lowBound=0, cat="Integer")
yb = pulp.LpVariable("use_bicycle", cat="Binary"); yc = pulp.LpVariable("use_handcart", cat="Binary")
M = 1000  # trips never need to exceed 1000
m += 80*h + 0*b + 0*c
m += 80*h + 0*b + 0*c <= 1000
m += h >= 8
m += 55*h + 30*b + 40*c >= 1000
m += b <= M*yb; m += c <= M*yc; m += yb + yc <= 1
solve_report(m)

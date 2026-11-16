# Reading 2: training jets in year j can only come from that year's production a_j.
import pulp
from _common import solve_report
a = {1: 10, 2: 15}
m = pulp.LpProblem("ior0002_r2", pulp.LpMaximize)
x1 = pulp.LpVariable("train_y1", lowBound=0, cat="Integer")
x2 = pulp.LpVariable("train_y2", lowBound=0, cat="Integer")
m += 5 * x1 + 5 * x2
m += x1 <= a[1]
m += x2 <= a[2]
solve_report(m)

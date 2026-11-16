# Reading 3: fleet accumulates; pilots trained in year 1 must each operate a combat jet in year 2
# (combat jets in year 2 = fleet - training jets in year 2); maximize pilots trained by end of year 2.
import pulp
from _common import solve_report
a = {1: 10, 2: 15}
m = pulp.LpProblem("ior0002_r3", pulp.LpMaximize)
x1 = pulp.LpVariable("train_y1", lowBound=0, cat="Integer")
x2 = pulp.LpVariable("train_y2", lowBound=0, cat="Integer")
m += 5 * x1 + 5 * x2
m += x1 <= a[1]
m += x2 + 5 * x1 <= a[1] + a[2]
solve_report(m)

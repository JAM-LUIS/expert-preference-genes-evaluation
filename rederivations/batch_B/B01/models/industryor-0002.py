# Reading 1 (main): jets accumulate (10 in year 1, 10+15=25 in year 2); any jet in the fleet may be
# assigned to training in a year; maximize pilots trained by end of year 2 = 5*(x1+x2).
import pulp
from _common import solve_report
a = {1: 10, 2: 15}
m = pulp.LpProblem("ior0002", pulp.LpMaximize)
x1 = pulp.LpVariable("train_y1", lowBound=0, cat="Integer")
x2 = pulp.LpVariable("train_y2", lowBound=0, cat="Integer")
m += 5 * x1 + 5 * x2
m += x1 <= a[1]
m += x2 <= a[1] + a[2]
solve_report(m, relax=True)

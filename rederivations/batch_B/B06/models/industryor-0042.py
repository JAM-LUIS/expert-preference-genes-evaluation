# x1, x2 = number of furnace-heats made with method 1 / method 2 (continuous, as an LP is requested).
# Time: two furnaces each have c=12 h -> total furnace-hours 2*12 = 24.
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report, relax_and_solve
a, m_, b, n, k, d, c = 2, 50, 3, 70, 10, 30, 12
m = pulp.LpProblem("io0042", pulp.LpMinimize)
x1 = pulp.LpVariable("x1", lowBound=0); x2 = pulp.LpVariable("x2", lowBound=0)
m += m_*x1 + n*x2
m += a*x1 + b*x2 <= 2*c
m += k*x1 + k*x2 >= d
solve_report(m)
relax_and_solve(m)
# alternative: single time budget of c hours (a*x1+b*x2 <= c)
m2 = pulp.LpProblem("io0042_alt", pulp.LpMinimize)
y1 = pulp.LpVariable("y1", lowBound=0); y2 = pulp.LpVariable("y2", lowBound=0)
m2 += m_*y1 + n*y2; m2 += a*y1 + b*y2 <= c; m2 += k*y1 + k*y2 >= d
m2.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("ALT time<=c continuous:", pulp.LpStatus[m2.status], pulp.value(m2.objective))
# integer check (number of heats as integers)
mi = pulp.LpProblem("io0042_int", pulp.LpMinimize)
z1 = pulp.LpVariable("z1", lowBound=0, cat="Integer"); z2 = pulp.LpVariable("z2", lowBound=0, cat="Integer")
mi += m_*z1 + n*z2; mi += a*z1 + b*z2 <= 2*c; mi += k*z1 + k*z2 >= d
mi.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGER_VERSION:", pulp.LpStatus[mi.status], pulp.value(mi.objective))

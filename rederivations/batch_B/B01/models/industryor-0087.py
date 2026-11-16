# Objective = rental cost per km (distance not given; it is a common positive factor).
import pulp
from _common import solve_report
m = pulp.LpProblem("ior0087", pulp.LpMinimize)
a = pulp.LpVariable("typeA", lowBound=0, cat="Integer"); b = pulp.LpVariable("typeB", lowBound=0, cat="Integer")
m += 30*a + 40*b
m += 20*a + 30*b >= 3000
m += 40*a + 30*b >= 4000
solve_report(m, relax=True)
